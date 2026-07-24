# 言幕 YanMu

一个本地优先的视频字幕生成工具：自动判断视频语种，中文视频统一生成简体中文字幕；外语视频生成“上方外文原文、下方简体中文翻译”的双语字幕。支持下载 SRT，也可将字幕压制到 MP4 视频。

## 功能

- Whisper 自动语音识别与语种检测
- NVIDIA CUDA 加速语音识别，自动选择 FP16 / CPU INT8
- NVENC、Quick Sync、AMF、VideoToolbox 加速字幕视频编码
- 中文视频繁体内容自动转换为简体，输出单语简体中文字幕
- 外语视频输出“上方原文 + 下方简体中文”双语字幕
- 支持 OpenAI 兼容接口、Ollama、LM Studio 和 LibreTranslate
- 任务进度、历史记录、视频预览与文件下载
- 可选导出硬字幕 MP4
- Windows 脚本与 Docker 部署

## 快速启动

Windows PowerShell：

```powershell
.\setup.ps1
# 编辑 .env；外语视频需要配置翻译服务
.\start.ps1
```

Docker：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

浏览器打开 <http://localhost:8000>。

完整安装、配置、模型选择和故障排查请阅读 [使用说明.md](./使用说明.md)。

## 技术结构

```text
app/
├── main.py          # FastAPI 与文件接口
├── pipeline.py      # 字幕任务流水线
├── transcriber.py   # faster-whisper 识别
├── translator.py   # 中文翻译提供方
├── subtitles.py    # SRT / ASS 生成
├── media.py        # FFmpeg 音频提取与压制
└── static/          # 无构建依赖的网页工作台
```

任务文件默认保存在 `data/jobs/<任务 ID>/`。首次使用某个 Whisper 模型时会自动下载模型，请预留时间和磁盘空间。
