# 本机脚本用法

`scripts/recording.py` 使用 Python 标准库、`ffmpeg`、`ffprobe`；只有 `sheets` 使用 Pillow。先运行 `--help`。路径作为参数传递，含中文或空格时用 shell 单引号；不要把标题拼成 shell 命令。

```bash
python3 /path/to/skill/scripts/recording.py inspect '/path/录制.mp4' --work '/path/.切分分析'
python3 /path/to/skill/scripts/recording.py scan '/path/录制.mp4' --work '/path/.切分分析'
python3 /path/to/skill/scripts/recording.py sheets '/path/录制.mp4' --work '/path/.切分分析' --step 300
python3 /path/to/skill/scripts/recording.py sheets '/path/录制.mp4' --work '/path/.切分分析' --times 190,200,210,220 --prefix handoff --columns 2
python3 /path/to/skill/scripts/recording.py export '/path/plan.json'
```

`inspect` 保存元数据与关键帧列表，屏幕仅返回时长、轨道与关键帧间隔摘要。`scan` 默认 `noise=-38dB:d=2`，保存完整日志和时间区间，只返回最长候选静音；噪声水平不同可用 `--noise`、`--minimum` 调整。扫描参数不是交接判据。

`sheets` 缓存 640 像素宽截图，默认一张拼图 16 帧；先看一张再决定加密范围。全局 `--step` 和局部 `--times` 二选一。原分辨率证据截图在导出时按计划提取。拼图不代表已经核实标题。

## JSON 计划

`source`、`output` 可以是绝对路径；相对路径按计划文件所在目录解析。`output` 必须尚不存在。每段 `start` 是原视频秒数，起点严格递增，首段为 0，最后一段自动延伸至源文件末尾。

下面展示字段形式，切点必须替换成实际视频已核对的关键帧：

```json
{
  "source": "录制.mp4",
  "output": "按报告切分",
  "title": "会议上午录像",
  "segment_time_delta": 0.05,
  "boundary_tolerance": 0.15,
  "notes": ["题目依议程命名，原视频相对时间记录于清单。"],
  "segments": [
    {"start": 0, "kind": "报告01", "speaker": "讲者甲", "title": "报告题目", "status": "开头缺失", "evidence_time": 60, "evidence": "议程与片段内课件核对"},
    {"start": 200.044, "kind": "集中讨论01", "title": "报告01集中讨论", "evidence_time": 230},
    {"start": 600.044, "kind": "休息", "title": "中场休息", "extra": true}
  ]
}
```

`kind`、`title` 必填；`speaker`、`status`、`evidence_time`、`evidence` 可省略。`extra: true` 移入“附加片段”。文件名由序号与字段生成，移除目录分隔符等非法字符；长文件名按 UTF-8 字节限长，完整题目保留在 CSV 与计划中。

`boundary_tolerance` 比较导出 segment CSV 中的实际起点与计划起点。默认 0.15 秒容纳小封装偏移；它不能用于掩盖错过关键帧。脚本会同时保存实际起点、偏差与首段偏移，遇到更大时间偏移要检查原轨道 PTS 与 FFmpeg 日志。

脚本覆盖整个源文件，包含附加片段，以逐轨数据包数量守恒验证覆盖；适合单一视频轨、零个或多个音频轨的本地 MP4。多视频轨、字幕或数据轨、非 MP4 容器、跨文件拼接与精确重编码需另选实现；脚本会对不支持的轨道结构明确报错。

导出先写入输出目录旁的隐藏暂存目录；出错返回非零退出码并保留暂存成果与错误记录，正式目录不会出现。成功后保存：视频、核对截图、`切分计划.json`、`切分清单.csv`、`切分说明.txt`、`验证记录.json`、`segments.csv` 与 `ffmpeg-export.log`。原文件不改动。

验证覆盖实际切点、片段数、轨道结构、编码、分辨率、逐轨数据包总数、每段首尾解码，以及处理期间源文件大小/修改时间是否变化。它不检查讲者身份、题目准确性或会议环节语义。
