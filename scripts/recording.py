#!/usr/bin/env python3
"""Inspect, scan, review frames, and execute evidence-backed lossless split plans."""
import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def stamp(t):
    return f'{int(t)//3600:02d}:{int(t)%3600//60:02d}:{t%60:06.3f}'


def fingerprint(source):
    s = source.stat()
    return {'path': str(source), 'size': s.st_size, 'mtime_ns': s.st_mtime_ns}


def probe(source, count=False):
    command = ['ffprobe', '-v', 'error']
    if count:
        command += ['-count_packets']
    command += ['-show_entries', 'format=duration,size,start_time:stream=index,codec_type,codec_name,width,height,r_frame_rate,start_time,duration,nb_read_packets', '-of', 'json', str(source)]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def duration(meta):
    t = float(meta['format']['duration'])
    if not math.isfinite(t) or t <= 0:
        raise ValueError('Source has no positive finite duration')
    return t


def bind_work(work, source):
    work.mkdir(parents=True, exist_ok=True)
    marker = work / 'source.json'
    current = fingerprint(source)
    if marker.exists() and json.loads(marker.read_text()) != current:
        raise ValueError('Work directory belongs to a different or changed source; use a new directory')
    save(marker, current)


def keyframes(source, work):
    # Keep only keyframe PTS; never put the full packet inventory into the chat.
    cache = work / 'keyframes.json'
    if cache.exists():
        return json.loads(cache.read_text())
    keys = []
    with (work / 'ffprobe-keyframes.log').open('w') as log:
        p = subprocess.Popen(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_packets', '-show_entries', 'packet=pts_time,flags', '-of', 'csv=p=0', str(source)], stdout=subprocess.PIPE, stderr=log, text=True)
        for row in csv.reader(p.stdout):
            if len(row) >= 2 and 'K' in row[1]:
                keys.append(float(row[0]))
        p.stdout.close()
        code = p.wait()
    if code:
        raise RuntimeError(f'ffprobe exited {code}; inspect {work / "ffprobe-keyframes.log"}')
    keys.sort()
    save(cache, keys)
    return keys


def inspect(args):
    bind_work(args.work, args.source)
    meta = probe(args.source)
    save(args.work / 'metadata.json', meta)
    keys = keyframes(args.source, args.work)
    print(json.dumps({'duration': duration(meta), 'streams': meta['streams'], 'keyframe_count': len(keys), 'max_keyframe_gap': max((b-a for a, b in zip(keys, keys[1:])), default=None), 'work': str(args.work)}, ensure_ascii=False))


def scan(args):
    bind_work(args.work, args.source)
    with (args.work / 'silence.log').open('w') as log:
        subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-threads', '2', '-i', str(args.source), '-map', '0:a:0', '-vn', '-af', f'silencedetect=noise={args.noise}dB:d={args.minimum}', '-f', 'null', '-'], stdout=subprocess.DEVNULL, stderr=log, check=True)
    text = (args.work / 'silence.log').read_text()
    intervals = [{'start': float(e)-float(d), 'end': float(e), 'duration': float(d)} for e, d in re.findall(r'silence_end: ([\d.]+) \| silence_duration: ([\d.]+)', text)]
    save(args.work / 'silences.json', intervals)
    print(json.dumps({'audio_track': 'a:0', 'count': len(intervals), 'longest_candidates': sorted(intervals, key=lambda r: r['duration'], reverse=True)[:20], 'work': str(args.work)}, ensure_ascii=False))


def extract(source, second, output, width=None):
    command = ['ffmpeg', '-v', 'error', '-threads', '2', '-ss', str(second), '-i', str(source), '-frames:v', '1']
    if width:
        command += ['-vf', f'scale={width}:-2']
    subprocess.run(command + ['-n', str(output)], check=True, capture_output=True)


def sheets(args):
    from PIL import Image, ImageDraw, ImageFont
    bind_work(args.work, args.source)
    t = duration(probe(args.source))
    times = [float(v) for v in args.times.split(',')] if args.times else [float(v) for v in range(0, math.ceil(t), args.step)] + [max(0, t-2)]
    if any(not math.isfinite(v) or v < 0 or v >= t for v in times):
        raise ValueError('Frame times must be within source duration')
    font_path = next((p for p in ['/System/Library/Fonts/Monaco.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'] if Path(p).exists()), None)
    font = ImageFont.truetype(font_path, 20) if font_path else ImageFont.load_default()
    paths = []
    for second in times:
        p = args.work / f'frame_{second:.6f}.jpg'
        if not p.exists():
            extract(args.source, second, p, 640)
        paths.append(p)
    for offset in range(0, len(times), args.per_sheet):
        batch = paths[offset:offset+args.per_sheet]
        opened = [Image.open(p) for p in batch]
        cell_height = max(im.height for im in opened)+32
        canvas = Image.new('RGB', (640*args.columns, math.ceil(len(batch)/args.columns)*cell_height), '#151515')
        draw = ImageDraw.Draw(canvas)
        for i, im in enumerate(opened):
            x, y = (i % args.columns)*640, (i // args.columns)*cell_height
            canvas.paste(im, (x, y)); draw.text((x+8, y+cell_height-28), stamp(times[offset+i]), font=font, fill='white'); im.close()
        target = args.work / f'{args.prefix}_{offset//args.per_sheet+1:02d}.jpg'
        canvas.save(target, quality=92)
        print(target)


def clean_name(value):
    return re.sub(r'[\x00-\x1f/\\:*?"<>|]', '_', str(value)).strip(' .')


def filename(i, segment):
    name = '_'.join(clean_name(v) for v in [f'{i+1:02d}', segment['kind'], segment.get('speaker'), segment['title'], segment.get('status')] if v)
    while len(name.encode('utf-8')) > 230:
        name = name[:-1]
    return name + '.mp4'


def stream_signature(meta):
    return [(s['codec_type'], s['codec_name'], s.get('width'), s.get('height')) for s in meta['streams']]


def export(args):
    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text())
    resolve = lambda key: (plan_path.parent / plan[key]).resolve()
    source, output = resolve('source'), resolve('output')
    if not source.is_file() or source.suffix.lower() != '.mp4':
        raise ValueError('This exporter requires a local MP4 file')
    if output.exists():
        raise ValueError(f'Output already exists; refusing to overwrite: {output}')
    meta = probe(source)
    total = duration(meta)
    types = [s['codec_type'] for s in meta['streams']]
    if types.count('video') != 1 or any(v not in ['video', 'audio'] for v in types):
        raise ValueError('Exporter supports one video track and audio tracks only')
    segments = plan['segments']
    starts = [float(s['start']) for s in segments]
    if not starts or starts[0] != 0 or any(not math.isfinite(v) or v < 0 or v >= total for v in starts) or any(a >= b for a, b in zip(starts, starts[1:])):
        raise ValueError('Segments must start at 0, be strictly increasing, and stay within duration')
    for s in segments:
        if not s.get('kind') or not s.get('title'):
            raise ValueError('Every segment needs kind and title')
        if s.get('evidence_time') is not None:
            v = float(s['evidence_time'])
            if not math.isfinite(v) or not 0 <= v < total:
                raise ValueError('Evidence time lies outside source duration')
    tolerance = float(plan.get('boundary_tolerance', 0.15))
    delta = float(plan.get('segment_time_delta', 0.05))
    if not math.isfinite(tolerance) or not math.isfinite(delta) or tolerance <= 0 or delta < 0:
        raise ValueError('Invalid boundary tolerance or segment_time_delta')
    before = fingerprint(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f'.{output.name}.partial-', dir=output.parent))
    try:
        save(stage / '切分计划.json', {**plan, 'source': str(source), 'output': str(output)})
        keys = keyframes(source, stage)
        for start in starts[1:]:
            if not keys or min(abs(k-start) for k in keys) > 0.002:
                raise ValueError(f'{start} is not a reviewed source keyframe; consult keyframes.json')
        command = ['ffmpeg', '-hide_banner', '-nostats', '-v', 'warning', '-n', '-i', str(source), '-map', '0', '-c', 'copy', '-f', 'segment']
        if len(starts) > 1:
            command += ['-segment_times', ','.join(f'{v:.6f}' for v in starts[1:])]
        else:
            command += ['-segment_time', str(total+60)]
        command += ['-segment_time_delta', str(delta), '-reset_timestamps', '1', '-segment_list', str(stage / 'segments.csv'), '-segment_list_type', 'csv', str(stage / 'part_%04d.mp4')]
        with (stage / 'ffmpeg-export.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=log, check=True)
        actual = list(csv.reader((stage / 'segments.csv').open()))
        if len(actual) != len(segments) or len(list(stage.glob('part_*.mp4'))) != len(segments):
            raise RuntimeError('Exported segment count differs from plan')
        deviations = [float(a[1])-s for a, s in zip(actual, starts)]
        if any(abs(v) > tolerance for v in deviations):
            save(stage / 'boundary-errors.json', {'planned': starts, 'actual': actual, 'deviations': deviations})
            raise RuntimeError('Actual boundaries exceed tolerance; inspect boundary-errors.json, do not hide keyframe drift')
        source_meta = probe(source, count=True)
        expected = [int(s['nb_read_packets']) for s in source_meta['streams']]
        totals = [0]*len(expected)
        rows = []
        for i, (segment, start, times) in enumerate(zip(segments, starts, actual)):
            relative = Path('附加片段') / filename(i, segment) if segment.get('extra') else Path(filename(i, segment))
            target = stage / relative
            target.parent.mkdir(exist_ok=True)
            (stage / f'part_{i:04d}.mp4').rename(target)
            m = probe(target, count=True)
            if stream_signature(m) != stream_signature(source_meta):
                raise RuntimeError(f'Track structure or codec changed: {relative}')
            for j, s in enumerate(m['streams']):
                totals[j] += int(s['nb_read_packets'])
            errors = []
            for seek in [0, max(0, duration(m)-2)]:
                result = subprocess.run(['ffmpeg', '-v', 'error', '-threads', '2', '-ss', str(seek), '-i', str(target), '-t', '2', '-f', 'null', '-'], capture_output=True, text=True)
                if result.returncode or result.stderr.strip():
                    errors.append({'seek': seek, 'exit_code': result.returncode, 'stderr': result.stderr})
            shot = ''
            if segment.get('evidence_time') is not None:
                (stage / '核对截图').mkdir(exist_ok=True)
                shot = f'核对截图/{i+1:02d}.jpg'
                extract(source, segment['evidence_time'], stage / shot)
            rows.append({**segment, 'sequence': i+1, 'source_end': starts[i+1] if i+1 < len(starts) else total, 'filename': str(relative), 'screenshot': shot, 'container_start': float(times[1]), 'boundary_deviation': deviations[i], 'probe': m, 'decode_errors': errors})
        checks = {'boundary_deviations': deviations, 'expected_packet_counts': expected, 'actual_packet_counts': totals, 'source_before': before, 'source_after': fingerprint(source), 'source_metadata': source_meta, 'rows': rows}
        checks['passed'] = totals == expected and checks['source_before'] == checks['source_after'] and not any(r['decode_errors'] for r in rows)
        save(stage / '验证记录.json', checks)
        if not checks['passed']:
            raise RuntimeError('Packet counts, source fingerprint, or decode check failed; inspect 验证记录.json')
        with (stage / '切分清单.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['序号', '环节', '讲者', '题目', '状态', '原视频起点', '原视频终点', '起点秒', '终点秒', 'segment起点', '偏差秒', '文件', '截图', '依据'])
            for r in rows:
                writer.writerow([r['sequence'], r['kind'], r.get('speaker', ''), r['title'], r.get('status', ''), stamp(float(r['start'])), stamp(r['source_end']), r['start'], r['source_end'], r['container_start'], r['boundary_deviation'], r['filename'], r['screenshot'], r.get('evidence', '')])
        lines = [plan.get('title', '录像切分'), '', f'原视频：{source}', '无损分段，保留原视频。序号依实际录像顺序；环节编号按计划。', '时间为原视频相对秒数，segment CSV 保留封装时间偏移。', f'验证通过：{len(rows)} 段，实际切点最大偏差 {max(abs(v) for v in deviations):.6f} 秒；逐轨数据包总数一致；各段首尾约 2 秒解码通过。', '数据包与解码验证不替代讲者、题目和交接位置的人工核实。', *plan.get('notes', []), '']
        lines += [f'{r["sequence"]:02d} {stamp(float(r["start"]))} — {stamp(r["source_end"])}  {r["filename"]}' for r in rows]
        (stage / '切分说明.txt').write_text('\n'.join(lines), encoding='utf-8')
        if output.exists():
            raise RuntimeError('Output appeared during export; refusing to replace it')
        stage.rename(output)
        print(json.dumps({'output': str(output), 'segments': len(rows), 'passed': True, 'max_boundary_deviation': max(abs(v) for v in deviations)}, ensure_ascii=False))
    except Exception as e:
        save(stage / 'error.json', {'error': str(e), 'stage': str(stage), 'output_created': False})
        print(f'Partial results retained at {stage}', file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['inspect', 'scan', 'sheets']:
        p = sub.add_parser(name)
        p.add_argument('source', type=lambda s: Path(s).resolve())
        p.add_argument('--work', required=True, type=lambda s: Path(s).resolve())
        if name == 'scan':
            p.add_argument('--noise', type=float, default=-38)
            p.add_argument('--minimum', type=float, default=2)
        if name == 'sheets':
            group = p.add_mutually_exclusive_group()
            group.add_argument('--times')
            group.add_argument('--step', type=int, default=300)
            p.add_argument('--prefix', default='overview')
            p.add_argument('--columns', type=int, default=4)
            p.add_argument('--per-sheet', type=int, default=16)
    p = sub.add_parser('export')
    p.add_argument('plan', type=Path)
    args = parser.parse_args()
    for name in ['step', 'columns', 'per_sheet', 'minimum']:
        if hasattr(args, name) and getattr(args, name) <= 0:
            parser.error(f'{name} must be positive')
    if args.command == 'sheets' and (clean_name(args.prefix) != args.prefix or not args.prefix):
        parser.error('prefix must be a nonempty filename component')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('ffmpeg and ffprobe are required on PATH')
    globals()[args.command](args)


if __name__ == '__main__':
    main()
