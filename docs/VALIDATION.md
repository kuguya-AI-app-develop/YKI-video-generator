# 0.1.0 开发机验证记录

日期：2026-09-12。环境：macOS、Python 3.12、Pillow 12.3.0、本机 FFmpeg。真实模型没有在开发机下载或运行。

## 已执行

`.venv/bin/python -m unittest discover -s tests -v`：28 项测试通过，包含实际 FFmpeg 合成、下载续传与校验失败保护、HTTP 来源与文件范围读取、项目恢复和镜头锁定、ComfyUI 模拟服务协议、单队列、取消后回收媒体子进程，以及安装器运行锁阻止应用启动。

自动端到端测试在演示模式创建三个镜头，只修改 S02 后继续生成，核对 S01/S03 的素材哈希和版本保持不变。成片编号按已存在的最大编号递增，验证旧成片不会被覆盖。

在本地浏览器实际操作：

- 输入「雨夜里，邮递员收到一封写给明天的信。」生成三个 DEMO 镜头。
- 修改 S02 旁白，保存并继续；仅 S02 新增版本。
- 锁定、保存、解锁、保存；输入控件和重做按钮状态符合操作。
- 选择 S02 历史版本，恢复原旁白并自动输出新成片。
- 点击重新合成，生成另一个成片版本。
- 重启服务后读取已有项目，历史素材仍可访问。
- 浏览器读取成片达到 readyState 4，720×1280，无媒体解码错误。

演示画面为标注 DEMO 的色块，音轨静音；这只证明应用与媒体流程可运行。

## 尚未执行

- Windows PowerShell 5.1 上的实际安装、跨 PowerShell/Python 文件锁互斥和系统运行库修复。
- 5090 上的 CUDA 检查、Qwen 规划、Kokoro 中文发声、H3 加载和采样。
- 真实模型的峰值显存、系统内存、速度、画质和六镜头角色一致性。
- 目标 Windows 机器完整安装后的断网生成。

这些项目按 [Windows 实机验收](WINDOWS_ACCEPTANCE.md) 逐项记录。不要把开发机演示结果当成真实模型验收结果。

## 2026-09-16 更名与开发交接验证

产品名称统一为 `YKI-video-generator`。本轮在 macOS 实际执行：

- 单元测试 28 项通过，0 skipped；包含实际 FFmpeg 媒体测试。
- `python -m compileall -q app scripts tests` 通过。
- `node --check web/app.js` 通过。
- 浏览器检查桌面与 390px 窄屏，新品牌页头清晰，窄屏无横向溢出。
- 新名称使用说明书渲染为 7 页并逐页检查，修订日期为 2026-09-16。
- 源码 ZIP 的 47 个文件完成逐文件 SHA256、排除目录和文档链接检查，解压后 CLI 启动帮助检查通过。
- CodeGraph 初始化确认和重新索引完成，23 个源码文件、376 个节点，状态正常。索引缓存不进入 Git。

本轮未重新执行 Windows 安装或真实模型推理，上述“尚未执行”项目仍待目标设备验收。

## 2026-09-25 4070S 实验配置验证

在 macOS 执行新增硬件配置测试 6 项、完整 unittest 34 项，全部通过且 0 skipped（完整回归耗时 10.734 秒）；`compileall -q app scripts tests` 通过。新增测试验证 llama 自动/手动 GPU 层数、配置校验、Comfy 磁盘辅助开关、localhost/单并发约束、个人配置合并与 384×672 工作流参数，不启动真实模型。

官方运行条件核查及社区报告见 [HARDWARE.md](HARDWARE.md)。本机没有 PowerShell 或 NVIDIA GPU，未运行 Windows 安装器、CUDA、真实 Qwen/Kokoro/H3 或峰值内存/速度测试。4070S / 32GB RAM 配置仍为实验性，测试通过不表示目标机器已经成片。

## 2026-09-25 CUDA UMD 标题兼容修复

用户在 Windows 11 / RTX 4070 Super 上提供的 `nvidia-smi` 标题为 `NVIDIA-SMI 616.92 / KMD Version: 616.92 / CUDA UMD Version: 13.4`。旧安装器与 doctor 仅识别 `CUDA Version:`，因此错误阻止安装；13.4 已满足锁定运行时要求的 13.3。保留此版本门槛，兼容两种标题和空白变体，补充 CMD 配置复制说明。

在 macOS 使用 Python 3.12、FFmpeg 和校验过官方 SHA256 的便携 PowerShell 7.6.6 执行：

- 修改前，用上述原始标题在安装器真实检测代码和 doctor 中分别复现失败；测试仅保留标题，不包含用户进程列表或个人路径。
- 修改后完整 unittest **36 项通过，0 skipped，11.222 秒**。两项新回归使用同一组 12 个样例，覆盖 UMD / 旧标题、13.3 边界、低版本、空值、N/A 和命令失败。安装器测试从 PowerShell AST 提取实际检测代码，模拟 `nvidia-smi` 输出，不运行安装、下载或 GPU。
- `compileall -q app scripts tests`、`node --check web/app.js`、`git diff --check` 通过。
- `pwsh -NoProfile -File scripts/bootstrap.ps1 -Plan` 通过；CodeGraph 更新至 25 个源码文件、409 个节点。

复现命令：将 PowerShell 加入当前终端 PATH 后运行 `python -m unittest discover -s tests -p test_nvidia_driver.py -v`；完整回归去掉 `-p`。没有 `powershell.exe` 或 `pwsh` 时安装器回归会明确跳过。本地便携测试运行时位于忽略的 `dist/`，不进入 Git 或源码包。

**未测试**：Windows PowerShell 5.1 上的完整安装、Windows CMD 指令实机执行、GPU CUDA 运算与真实模型生成。本次修复通过只证明已知标题能被正确识别；目标设备需拉取更新后继续安装验收。
