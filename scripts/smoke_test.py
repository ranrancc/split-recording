#!/usr/bin/env python3
import json, pathlib, subprocess, sys
import tempfile
root=pathlib.Path(tempfile.mkdtemp(prefix='split-recording-test-'))
script=pathlib.Path(__file__).with_name('recording.py')
source=root/'测试 录制.mp4'
with (root/'fixture.log').open('w') as log:
 subprocess.run(['ffmpeg','-hide_banner','-nostats','-v','warning','-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=12','-f','lavfi','-i','aevalsrc=if(lt(t\\,2)\\,0\\,0.1*sin(2*PI*440*t)):s=48000:d=12','-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=12','-map','0:v:0','-map','1:a:0','-map','2:a:0','-c:v','libx265','-x265-params','pools=1:frame-threads=1:keyint=96:min-keyint=96:scenecut=0:log-level=error','-c:a','aac','-output_ts_offset','0.044',str(source)],stdout=log,stderr=log,check=True)
def run(*args,ok=True):
 result=subprocess.run([sys.executable,str(script),*map(str,args)],capture_output=True,text=True)
 (root/'commands.log').open('a').write(str(args)+'\n'+result.stdout+result.stderr+'\n')
 assert (result.returncode==0)==ok,(args,result.returncode,result.stderr)
 return result
work=root/'analysis'
run('inspect',source,'--work',work)
keys=json.loads((work/'keyframes.json').read_text())
assert len(keys)>=3,keys
run('scan',source,'--work',work)
silences=json.loads((work/'silences.json').read_text())
assert silences and silences[0]['duration']>=1.9,silences
run('sheets',source,'--work',work,'--times','0,4,8','--columns','2')
assert (work/'overview_01.jpg').is_file()
plan={'source':source.name,'output':'成功输出','title':'合成夹具验证','segments':[{'start':0,'kind':'报告01','speaker':'甲','title':'中文路径与双音轨','evidence_time':1},{'start':keys[1],'kind':'讨论','title':'交接后内容','evidence_time':5},{'start':keys[2],'kind':'休息','title':'附加片段','extra':True}]}
p=root/'plan.json';p.write_text(json.dumps(plan,ensure_ascii=False))
run('export',p)
verification=json.loads((root/'成功输出'/'验证记录.json').read_text())
assert verification['passed']
assert len(verification['rows'])==3
assert len(verification['expected_packet_counts'])==3
assert verification['actual_packet_counts']==verification['expected_packet_counts']
assert (root/'成功输出'/'附加片段').is_dir()
assert max(abs(v) for v in verification['boundary_deviations'])<0.15
run('export',p,ok=False)
plan['output']='错误切点不应创建';plan['segments'][1]['start']=keys[1]+0.5;p.write_text(json.dumps(plan))
run('export',p,ok=False)
assert not (root/'错误切点不应创建').exists()
plan['output']='过小容差';plan['segments'][1]['start']=keys[1];plan['boundary_tolerance']=0.0001;p.write_text(json.dumps(plan))
run('export',p,ok=False)
assert not (root/'过小容差').exists()
assert any(root.glob('.过小容差.partial-*/boundary-errors.json'))
result={'passed':True,'fixture':str(source),'source_keyframes':keys,'audio_tracks':2,'boundary_deviations':verification['boundary_deviations'],'checks':['single video and two audio tracks conserved','first/last decode','Chinese paths','contact sheet','silence detected','source unchanged','existing output refused','non-keyframe refused','boundary mismatch blocks completion']}
(root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))
