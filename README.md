# YKI-video-generator

面向 **Windows 11 + NVIDIA GPU** 的本地短视频生成软件。原始目标为 RTX 5090，现提供 **RTX 4070 Super 12GB 显存 / 32GB 系统内存实验配置**。在 macOS 开发和演示，在 Windows 由启动脚本安装运行环境和模型；输入一句故事梗概，生成分镜、中文旁白、竖屏视频与字幕。

**当前版本为 0.1.0 测试版。macOS 的 34 项自动测试和 DEMO 流程已通过，Windows 安装及 4070S/5090 上的真实 Qwen → Kokoro → H3 链路尚未完成实机验收。** DEMO 使用标注色块和静音，不能证明真实模型的画质、速度或成功率。

仓库：[kuguya-AI-app-develop/YKI-video-generator](https://github.com/kuguya-AI-app-develop/YKI-video-generator)。当前为公开仓库，可直接克隆。逐个模型的运行条件、官方依据和 4070S 试跑步骤见 [硬件核查与实验配置](docs/HARDWARE.md)。安装器已撤销约 32GB 显存硬门槛；128GB 系统内存也不是统一最低要求。

## 在另一台设备接手开发

先安装 Git，然后执行；读取公开源码不需要登录 GitHub：

```bash
git clone https://github.com/kuguya-AI-app-develop/YKI-video-generator.git
cd YKI-video-generator
```

推送贡献时再使用有权限的账号配置 Git 凭据，不要把 token 写进 URL 或源码。

接手顺序：先按下文启动 DEMO，运行测试，再阅读 [开发交接](docs/HANDOFF.md)、[架构](docs/ARCHITECTURE.md) 和 [领域说明](CONTEXT.md)。AI 编程代理还应阅读 [AGENTS.md](AGENTS.md)。下一阶段的主要工作是完成 [Windows 实机验收](docs/WINDOWS_ACCEPTANCE.md)。

### macOS 开发与演示

需要 Python 3.12、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和 FFmpeg。Python 可由 uv 下载；使用 Homebrew 的机器可这样开始：

```bash
brew install uv ffmpeg
chmod +x Start-Mac-Demo.command
./Start-Mac-Demo.command
```

脚本创建 `.venv`，安装 `Pillow==12.3.0`，启动演示服务并打开 [本地创作台](http://127.0.0.1:8765)。保持终端打开，按 Ctrl+C 退出。Mac 演示不下载或运行 Windows CUDA 模型。

也可以手动运行，便于调试：

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python Pillow==12.3.0
.venv/bin/python -m app serve --mode demo --open
```

应用使用 Python 标准库 HTTP 服务，前端为原生 HTML/CSS/JavaScript，**不需要 npm install 或前端构建**。修改前端后刷新网页，修改 Python 后重启服务。Node.js 仅用于可选的 JavaScript 语法检查和 CodeGraph 开发工具。

`requirements.txt` 还包含真实配音及解压所需的 sherpa-onnx、py7zr；最小 Mac DEMO 环境只需 Pillow 与 FFmpeg。`requirements-windows.lock` 是 Windows x64 / Python 3.12 的完整哈希锁文件，不用于安装 Mac 环境。

### Windows 部署与开发

1. 克隆仓库到可写本地磁盘，例如 `D:\YKI-video-generator`；也可解压 `YKI-video-generator-0.1.0-windows.zip`。不要从 ZIP 预览窗口内启动。
2. 准备 Windows 11 x64 和 NVIDIA GPU。4070S / 32GB 内存先按 [实验步骤](docs/HARDWARE.md)复制 `config/experimental-4070s-32gb.json` 到个人配置，再启动安装。低于约 32GB 显存时安装器会提示实验风险，允许继续。运行 `nvidia-smi`，其 `CUDA Version` 必须至少为 **13.3**。驱动不足时从 [NVIDIA 官方网站](https://www.nvidia.com/en-us/drivers/)更新并重启，无需额外安装 CUDA Toolkit。
3. 首次安装至少预留 **100 GiB** 磁盘空间。系统内存没有经本项目实测确认的统一最低值；32GB 需配合卸载与磁盘读取进行实验，不能保证只降低速度而不会内存不足。视频、历史版本和换页会继续占用磁盘。
4. 双击 `Start-Windows.bat`，首次自动进入安装器；也可先双击 `Install-Windows.bat` 单独安装。
5. 安装完成后打开 [本地创作台](http://127.0.0.1:8765)。先完成「流程演示」「3 镜头」，再新建「真实生成」项目。

固定资产清单的模型和运行时压缩包约 **57.63 GiB**，另需 Python、依赖及解压空间。下载需要访问 GitHub、Hugging Face 和 PyPI。没有内置收费 API，无需模型 API Key。源码仓库和 ZIP 均不含模型，首次克隆不等于模型已经安装。

安装器将 uv、Python、应用环境、llama.cpp、FFmpeg、ComfyUI 和缓存放在项目目录，不注册全局 Python。当前固定组件包括 Python 3.12.14、uv 0.12.13、llama.cpp b10919、ComfyUI v0.35.0，实际版本、大小与 SHA256 见安装脚本和 `config/models.lock.json`。

若缺少 VC++ DLL，安装器从 [Microsoft 官方入口](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)获取 x64 运行库，验证 Microsoft 数字签名后补装共享系统组件，可能触发 UAC。需要重启时，重启 Windows 后再次运行启动脚本；已校验的下载可复用。显卡驱动需自行预先安装。安装或修复前先退出创作台。

首次 Windows 启动会先完成完整部署；网页中的「流程演示」选项不会跳过安装。部署后可用以下命令开发、诊断和测试：

```powershell
# 只查看安装计划，不下载模型
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Plan
# 已完成安装后
.\runtime\app-env\Scripts\python.exe -m app doctor --json
.\runtime\app-env\Scripts\python.exe -m app serve --mode demo
.\runtime\app-env\Scripts\python.exe -m unittest discover -s tests -v
```

模型服务与素材生成问题优先保留日志，按 [Windows 验收与排障](docs/WINDOWS_ACCEPTANCE.md) 排查。`doctor` 检查基础环境，不能代替真实推理测试。

## 从一句话到成片

1. Qwen3.8-27B GGUF 编写 3 或 6 个镜头，输出英文画面提示词、中文旁白和角色描述。
2. Qwen 服务退出释放显存。Kokoro 在 CPU 生成中文 WAV，短旁白补尾部静音；超过 14.5 秒的旁白会报错并要求缩短。
3. ComfyUI 使用量化 H3-Base 按镜头顺序生成画面，默认生成分辨率为 768×1344，4070S 实验配置为 384×672。
4. FFmpeg 合成 **720×1280、24 fps、H.264/AAC MP4**，烧录中文字幕和「AI 生成」标识，另存 SRT。音轨使用中文旁白，当前不混入 H3 原始声音。

首条可以输入：`雨后的街角，一只穿黄色雨衣的小猫发现了一颗发光的种子，并把它带回家。`

完成后在「成片预览」播放或下载 MP4；SRT 位于项目输出目录。实际时长取决于旁白，没有已验证的固定生成耗时。上方模式选项只影响新项目，不能把已有 DEMO 项目改成真实项目。

### 编辑、重做和恢复

- 修改镜头提示词或旁白并「保存」后，点击「继续生成」处理待生成镜头。只保存不会立即生成；修改旁白也会重新生成该镜头画面。
- 「重做镜头」使用新种子产生新版本，并自动合成成片。已完成的其他镜头复用；其他待生成镜头也会在该任务中处理。
- 选择历史版本会恢复对应提示词、旁白、种子和素材，并自动更新成片；旧文件保留。
- 锁定镜头后不能直接编辑或重做，须解锁并保存；锁定仍允许选择历史版本，也不代表人物外观被模型锁定。
- 「停止任务」保留完整素材。重启后中断项目可继续，恢复以完整镜头为单位，不恢复扩散采样中间步骤。CPU 配音可能需等待当前合成调用返回。

## 目录与配置

```text
app/                       HTTP API、项目存储、串行任务与媒体管线
app/providers/             Qwen、Kokoro、ComfyUI 适配
web/                       无构建前端
scripts/                   Windows 安装与启动、CUDA 检查、源码打包
config/defaults.json       默认配置
config/models.lock.json    资产版本、下载地址、大小、SHA256
workflows/                 H3 原生工作流
requirements-windows.lock  Windows 应用依赖哈希锁
tests/                     自动回归测试
docs/                      使用说明、架构、交接、验证与实机验收
```

默认端口：界面 `8765`、llama.cpp `8189`、ComfyUI `8188`，均绑定本机。不要直接暴露为公网或多人服务。程序只管理自己启动的子进程，不接管其他已有模型服务。

个人覆盖配置写入根目录 `settings.local.json`，不进入 Git 或源码 ZIP。例如：

```json
{
  "port": 8766,
  "tts": {"speaker_id": 3, "speed": 1.0, "threads": 4}
}
```

退出服务后修改并重启；端口改为 8766 后访问 `http://127.0.0.1:8766`。完整配置字段见 `config/defaults.json`。中文字体可通过环境变量 `AIGC_FONT` 指向 TTF/TTC 文件，此兼容变量在更名后保留。

### 换设备时迁移什么

| 内容 | 是否进入 Git | 迁移方式 |
| --- | --- | --- |
| 源码、脚本、配置清单、文档 | 是 | 在新机器 clone / pull |
| `projects/<id>/` | 否 | 停止任务并退出后，单独复制完整目录 |
| `settings.local.json` | 否 | 单独备份，按新机器路径合并配置 |
| `models/` | 否 | 新安装器下载；已有资产按固定清单校验后复用 |
| `runtime/` | 否 | 在目标机器重建，勿直接搬运 Python 环境 |
| `.venv/`、`.codegraph/` | 否 | 每台设备独立创建 |
| `logs/`、`runtime/logs/`、`dist/` | 否 | 按需留存验收或故障证据 |

**H3 权重在 `runtime/comfy-portable/ComfyUI_windows_portable/ComfyUI/models/` 内**，只备份根目录 `models/` 不会包含所有模型。若要节省重下载，只迁移清单中对应的模型/归档文件，保持相对路径并由安装器重新校验；不要把旧 `install-state.json` 当成新机器的安装证明。

每个创作项目包含 `project.json`、`renders/` 下各版本 WAV/MP4/参数、`output/` 下递增的 `final-001.mp4` 和 `.srt`。只带走 MP4 可播放，但不能恢复镜头编辑与历史。Git 不同步这些创作数据，也没有多机冲突合并功能。

## 测试与打包

在项目根目录运行：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q app scripts tests
node --check web/app.js
.venv/bin/python scripts/package.py
```

Windows 已安装环境使用 `.\runtime\app-env\Scripts\python.exe` 替换上述 Python 路径。若系统 PATH 没有 FFmpeg/FFprobe，媒体测试会被跳过；请检查 skipped 数为 0，以覆盖媒体测试；2026-09-16 的基线为 28 项，新增硬件配置测试后的实际计数见验证记录。在 Windows 可把安装生成的 FFmpeg `bin` 目录加入当前终端 PATH 再测，详见 `config/models.lock.json` 的运行时路径。

打包输出 `dist/YKI-video-generator-0.1.0-windows.zip` 及 `.zip.sha256`。包内 `PACKAGE_MANIFEST.json` 记录逐文件哈希；只包含白名单源码、启动脚本、配置、工作流、测试和文档，排除模型、项目视频、运行环境、日志、本机设置与 Git 数据。ZIP 是源码启动包，并非已编译 EXE。

```powershell
Get-FileHash .\dist\YKI-video-generator-0.1.0-windows.zip -Algorithm SHA256
```

仓库当前未配置 CI；本地验证记录见 [VALIDATION.md](docs/VALIDATION.md)。不要用演示测试代替 Windows 安装、CUDA、真实语音和视频验收。

## CodeGraph 与协作

CodeGraph 是可选的开发工具，不影响应用运行。本机已初始化并重新索引。新设备需重新建立本机索引，不要复制或提交 `.codegraph/`。

本次使用 `@colbymchenry/codegraph` 0.7.12；其 Node 版本范围为 18 至 24。已安装 CLI 时可跳过第一条：

```bash
npm install -g @colbymchenry/codegraph@0.7.12
codegraph init -i
codegraph status
# 修改代码后重建
codegraph index
```

在项目根目录运行；若提示已经初始化，使用 `codegraph index` 更新。编辑器中的 CodeGraph MCP 接入依各设备客户端配置，CLI 初始化不会替你同步其他机器的编辑器设置。

开发前拉取更新，使用 `codex/<功能名>` 分支。提交前运行相关测试并检查 `git diff`，更新行为对应文档；不要提交 `.env`、模型、视频、日志或个人配置。模型版本变更必须同时检查固定下载清单、哈希、工作流兼容和 Windows 验收，不要只替换一个下载 URL。

## 已知限制与接手优先级

- 当前重点是 Windows 4070S / 32GB 内存首轮实验与后续 5090 验收；还没有已验证的速度、峰值显存/内存、成功率或完整离线运行结论。
- 角色一致性依赖文本条件，没有参考图、人物身份锁定或角色资产库。
- 当前为 H3-Base，不含官方完整 2K 增强流程；无自动降画质应对显存不足的策略。
- 没有音乐库、口型同步、自动审片、自动投稿或多用户服务。发布前人工检查画面、旁白与字幕。
- 接手后依次完成：Windows 安装 → 3 镜头 DEMO → 3 镜头真实生成 → 重做/历史/停止恢复 → 6 镜头和断网验收。

详细用户操作见 [使用说明书 Word](docs/YKI-video-generator_使用说明书_v0.1.0.docx)。该手册为 2026-09-16 版本，其中硬件建议以更新的 [硬件核查](docs/HARDWARE.md) 为准。模型与依赖各有独立许可，来源和使用条件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；H3 有地域、用途及商业许可条件。本仓库尚未为原创源码指定开源许可证。
