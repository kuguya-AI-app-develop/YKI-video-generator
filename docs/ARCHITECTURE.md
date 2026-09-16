# YKI-video-generator 架构与实现边界

本项目用 Python 标准库提供本机 HTTP 界面和串行任务队列；前端是无需构建的 HTML/CSS/JavaScript。模型权重与运行环境由 Windows PowerShell 安装器下载，源码分发包不包含模型或用户项目。

## 数据流

```mermaid
flowchart LR
    UI[一句话 + 3或6镜头] --> Plan[llama.cpp / Qwen规划]
    Plan --> Stop[退出编剧模型]
    Stop --> TTS[CPU Kokoro中文旁白]
    TTS --> H3[ComfyUI / H3-Base逐镜头]
    H3 --> Merge[FFmpeg + Pillow字幕]
    Merge --> Output[MP4 + SRT + 镜头版本]
```

GPU 按阶段使用：规划模型退出后才启动视频服务。CPU 配音先确定单镜头时间；H3-Base 负责画面生成，FFmpeg 按旁白时长裁切或冻结末帧，使每段对齐 24 fps 的帧边界。真实成片音轨当前只使用 TTS，不混入 H3 原始声音。

## 模块

| 文件/目录 | 责任 |
| --- | --- |
| `scripts/bootstrap.ps1` | 前置条件检查、隔离 Python、运行时与模型安装、校验和安装状态。 |
| `config/models.lock.json` | 固定资产版本、不可变下载地址、大小与 SHA256；约 57.63 GiB 下载。 |
| `app/assets.py` | 续传下载、哈希验证和限制目标路径的归档解压。 |
| `app/server.py` / `web/` | 本机 HTTP API、静态界面、媒体 Range 请求和 2 秒轮询。 |
| `app/jobs.py` | 单工作队列、取消信号、错误转为项目状态。 |
| `app/storage.py` | 原子 JSON 持久化、镜头编辑、锁定、启动后中断恢复。 |
| `app/pipeline.py` | 规划、配音、视频、合成阶段编排与素材复用。 |
| `app/processes.py` | 仅管理自己启动的推理服务、健康检查与退出。 |
| `app/providers/llama.py` | 请求结构化镜头，校验规划输出。 |
| `app/providers/tts.py` | CPU sherpa-onnx/Kokoro 合成单声道 PCM WAV。 |
| `app/providers/comfy.py` / `workflows/` | H3 工作流参数、节点兼容性校验、提交与下载输出。 |
| `app/media.py` | 中文字幕栅格化、视频编排、音轨合并、SRT 和可取消 FFmpeg。 |
| `app/diagnostics.py` | 安装文件、基础依赖、驱动与本机运行前检查。 |

## 状态与复用

项目通常经历 `draft → queued → running → completed`。错误进入 `failed`，主动停止进入 `cancelled`；服务重启将遗留的 `queued/running` 项目标记为 `interrupted`。继续运行会复用已完成且素材存在的镜头；失败或未完成的镜头重新处理。

每个镜头保留 `versions`，内容包含视频、音频、提示词、旁白和种子。重做生成新版本，旧文件保留；选择历史版本恢复整套对应内容并自动重新合成。编辑提示词或旁白会清除当前成片引用并将该镜头改为待处理，不删除旧成片和旧镜头版本。锁定主要保护内容编辑及重做，不等于生成画面的人物一致性锁定。

存储以整个 `projects/<id>/` 为恢复单位。JSON 使用临时文件加替换写入；不提供数据库事务、跨机器同步或多人并发编辑。

## 网络与运行方式

界面、llama.cpp、ComfyUI 分别使用本机 `8765`、`8189`、`8188` 端口，绑定 `127.0.0.1`。应用检查 Host 与写请求 Origin，媒体路径限制在项目目录中。首次部署联网下载，生成接口使用本机服务；断网使用仍需在 Windows 验收时确认依赖完整。

Windows 安装器不安装显卡驱动、不注册全局 Python。缺少必需的 VC++ DLL 时，验证 Microsoft 官方安装器的数字签名后安装共享系统运行库，可能触发 UAC 或要求重启。安装器和创作台持有同一个运行环境文件锁，避免安装或修复覆盖正在使用的程序。`settings.local.json` 用于覆盖默认端口、路径和配音参数；该文件不进入源码 ZIP。

## 已知边界与验证分层

- 实机目标是 Windows 11、32GB NVIDIA Blackwell GPU；macOS 只运行 DEMO 管线。
- DEMO 是明确标记的卡片与静音，不调用语言、语音或视频模型；真实模式报错时不会回退成 DEMO。
- H3-Base 的文本条件维持人物描述，但没有参考图、身份锁定、角色资产库或完整 2K 增强链。
- 每镜头旁白过长会停止并要求修改；不自动删减用户台词。
- 停止能中断 HTTP 等待与本程序启动的推理/FFmpeg 进程；CPU TTS 的单次原生合成调用需返回后才能继续处理取消。
- 恢复以完成镜头为单位，不恢复扩散采样中间状态；重新合成会创建新的成片文件。
- `doctor` 检查文件存在/大小和基础依赖，安装时执行完整 SHA256 校验；它不等于真实模型推理验收。
- 合格率、人物一致性、长任务速度和峰值内存仍需目标 5090 测试。发布前需要人工审片。

运行 `python -m unittest discover -s tests -v` 做本地回归；真实模型验收按 [WINDOWS_ACCEPTANCE.md](WINDOWS_ACCEPTANCE.md) 记录。
