# 会议与赛课录像切分

一个 Codex 技能：根据会议议程、讲者或选手交接，把本地长录像切成可独立播放的片段，并加序号、讲者与题目命名。

方法是“稀疏抽帧定位结构 → 停顿检测辅助定位 → 交接画面核实 → 关键帧无损导出 → 实际切点与音视频验证”。静音、计划钟点和换机位都只是线索，不能直接当成分界。讲者与题目仍需结合议程和画面判断，脚本不自动认人。

## 安装与调用

将仓库放入 Codex 的技能目录；若该目录已有同名技能，先检查现有版本，避免覆盖。

```bash
git clone https://github.com/ranrancc/split-recording.git ~/.codex/skills/split-recording
```

在 Codex 中可以明确调用：

> 用 $split-recording 根据这张议程切分同目录里的录像，按“序号＋讲者＋题目”命名。

也适用于“按不同参赛老师切分赛课视频”“用同样的方法处理剩下的录像”。

## 依赖

- Python 3.10 或更新版本。
- PATH 中可运行 `ffmpeg` 和 `ffprobe`。
- 只有拼图子命令需要 Pillow：`python3 -m pip install Pillow`。
- 自检使用 FFmpeg 的 `libx265` 编码器生成合成夹具，不需要真实会议素材。

## 脚本用法

```bash
python3 scripts/recording.py inspect '/path/录制.mp4' --work '/path/.切分分析'
python3 scripts/recording.py scan '/path/录制.mp4' --work '/path/.切分分析'
python3 scripts/recording.py sheets '/path/录制.mp4' --work '/path/.切分分析' --step 300
python3 scripts/recording.py export '/path/plan.json'
```

计划格式、局部抽帧命令和支持范围见 [references/commands.md](references/commands.md)。

导出器支持单视频轨、零个或多个音频轨的本地 MP4。每个切点应选在已核实的源关键帧上，默认覆盖整个原文件；休息和末尾黑屏可作为附加片段保留。需要逐帧精确切割、重新编码、多视频轨或跨文件拼接时，应另选实现。

## 交付和验证

导出先写暂存目录，验证通过才生成正式目录；已有输出不会被覆盖。交付包含视频、原分辨率核对截图、JSON 计划、CSV 时间清单、说明、验证记录、分段时间记录和完整日志。

检查实际切点、轨道结构、逐轨数据包数量、每段首尾解码及源文件是否变化。数量一致和可播放不能证明报告边界切对了，所以画面核实与实际切点比对都保留。

[复盘案例](references/case-20261009.md) 记录了一次关键帧分段整体延后 10 秒的现象及修正。案例不包含录像、截图或本机素材路径；其参数只能作为起点，不能当作所有视频的固定答案。

## 自检

```bash
python3 scripts/smoke_test.py
```

自检在临时目录生成一段 12 秒的 HEVC 录像与两条音轨，验证中文路径、静音检测、拼图、关键帧分段、音视频包守恒、首尾解码，以及已有输出、错误切点、切点偏差的拒绝行为。它不验证人物识别或会议环节语义。

技能入口为 [SKILL.md](SKILL.md)。
