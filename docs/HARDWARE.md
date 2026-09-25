# 模型运行条件与 4070 Super 试跑

核查日期：2026-09-25。适用当前固定资产清单、llama.cpp b10919 和 ComfyUI v0.35.0。**RTX 4070 Super 12GB 显存、32GB 系统内存、Windows 11 可以作为实验配置；本项目尚未在这台机器完成真实推理测试。** 此前 32GB 显存安装阻断和 128GB 系统内存推荐过于保守，不是这些模型共同的官方最低要求。

## 逐个模型核查

下表大小来自 `config/models.lock.json`，单位为 GiB（1024³ 字节），表示文件体积，**不等于运行时峰值 RAM 或 VRAM**。

| 组件 | 当前资产大小 | 运行条件与 4070S 判断 |
| --- | --- | --- |
| Qwen3.8-27B UD-Q4_K_M | 15.334 GiB GGUF | 文件大于 12GB 显存，需部分权重留在系统内存。llama.cpp 支持 CPU/GPU 混合执行；本项目用自动选择 GPU 层数，并保留 8192 context。还需 KV/状态缓存、计算缓冲和系统余量。 |
| H3 pruned INT8 ConvRot 主模型 | 19.530 GiB | 依赖 ComfyUI 动态卸载，不能全部常驻 12GB 显存。官方优化路径明确涵盖 RTX 3060，但未给通用 RAM 最低或本项目耗时保证。 |
| H3 Qwen3-VL-32B NVFP4 AWQ 编码器 | 14.610 GiB | 模型维护者明确说不要求 Blackwell。4070S 可走反量化回退路径；读取压缩权重与原生 FP4 加速是不同能力。反量化仍需临时内存。 |
| H3 视频 VAE FP16 | 4.850 GiB | 用于解码，除了权重还需中间张量；解码仍可能内存不足。降低画面面积可减小部分工作负载，不能保证消除全部峰值。 |
| H3 音频 VAE FP32 | 0.564 GiB | 原生 H3 工作流所需，不能因为最终使用旁白就直接删掉。它与视频 VAE 一并受工作流和内存管理影响。 |
| Kokoro-82M v1.1 中英配音 | 0.340 GiB 压缩包 | 项目使用 sherpa-onnx CPU provider；无需 CUDA 显卡。模型卡和运行示例没有给统一的最低 RAM，压缩包体积不是运行内存。 |

Qwen 规划结束后进程退出，随后 CPU 配音，再运行 H3。不能把 Qwen 和全部 H3 文件相加后当作必须同时驻留的内存。四个 H3 资产共约 39.554 GiB（42.471 GB），也不能直接据此宣称必须有同等显存，或宣称 32GB 内存一定够。

证据与适用范围：

- [llama.cpp b10919 README](https://github.com/ggml-org/llama.cpp/blob/b10919/README.md)明确支持 CPU/GPU 混合推理；该版本的[参数实现](https://github.com/ggml-org/llama.cpp/blob/b10919/common/arg.cpp)和[自动适配实现](https://github.com/ggml-org/llama.cpp/blob/b10919/common/fit.cpp)支持 `--n-gpu-layers auto --fit on`。固定 `99` 会妨碍自动调整层数。
- [Unsloth Qwen3.8 运行说明](https://unsloth.ai/docs/models/qwen3.8)把 27B 四位量化的大致内存预算列为 16–19GB RAM+VRAM/统一内存。这是发布方的一般指导，不是当前 8192 context、Windows 和完整流水线的实测峰值。
- [Comfy 官方 H3 发布说明](https://blog.comfy.org/p/minimax-h3-day-0-support-in-comfyui)明确提到 RTX 3060 和动态卸载，没有把 128GB RAM 列为通用最低条件。
- [固定版本的 H3 权重说明](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/a98869194787969724c7425d95d0ed73ce9202af/README.md#L23)说明 NVFP4 编码器无需 Blackwell。ComfyUI 固定版本的[硬件判断](https://github.com/Comfy-Org/ComfyUI/blob/40c4fcdf513a4523e39d54a9d391908af8df8171/comfy/model_management.py#L1995)与[反量化前向路径](https://github.com/Comfy-Org/ComfyUI/blob/40c4fcdf513a4523e39d54a9d391908af8df8171/comfy/ops.py#L1355)解释了旧架构上的回退行为。
- [sherpa-onnx Kokoro v1.1 示例](https://k2-fsa.github.io/sherpa/onnx/tts/all/Chinese-English/kokoro-multi-lang-v1_1.html)及[默认 CPU 配置](https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/csrc/offline-tts-model-config.h)支持无需 GPU 的运行方式。

此外，[上游模型讨论 #16](https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/16)有 RTX3060 12GB、32GB RAM、960×544、20 步的第一手成功报告，但使用 Ref2VA，且没有完整版本、片长和峰值日志。它支持“值得试”，不能当成本项目验收结果。上游也有 [RTX4070 12GB 动态加载挂起报告](https://github.com/Comfy-Org/ComfyUI/issues/15628)，软件版本和加载路径仍可能影响成功率。

## 为什么不一定只是慢一点

显存不足时，部分权重可放在系统内存或通过磁盘映射读取，但正在执行的算子、反量化结果、视频中间张量和解码缓冲仍需要实际可分配的内存。32GB 还要留给 Windows、配音、文件缓存和其他程序。可能出现的结果包括成功但较慢、频繁换页、分配失败或特定加载路径挂起。

本项目没有测得这台配置每个镜头需要多少分钟。不要用权重文件大小当运行峰值，也不要用“RAM+VRAM 总和大于文件大小”保证成功。先关闭其他 GPU 应用，把项目放在本地 SSD，保留足够磁盘空间；Windows 页面文件可保持系统管理，并检查其所在盘剩余空间，避免为试跑盲目指定很大的固定值。

安装器仍要求的 CUDA 13.3 驱动兼容性来自锁定的 llama.cpp 二进制包，**不是所有模型的通用最低 CUDA 版本，也不是要求 RTX50 系显卡**。更新 NVIDIA 官方驱动后用 `nvidia-smi` 检查，安装时会另用 ComfyUI 的 Python 做 CUDA 运算检查。

`nvidia-smi` 可能显示 `CUDA Version` 或 `CUDA UMD Version`；两种标题均受支持。若显示 `CUDA UMD Version: 13.4`，已满足 13.3 版本门槛。旧代码只识别前一种标题，可能误报 `Cannot determine driver CUDA compatibility from nvidia-smi.`；按下文更新项目后重试，无需因此重装驱动。版本检查通过仍不等于 CUDA 运算或真实生成已验收。

## 为 4070S 32GB 开始试跑

仓库公开，无需 GitHub 登录即可克隆。尚未克隆时，在 CMD 或 PowerShell 执行：

```text
git clone https://github.com/kuguya-AI-app-develop/YKI-video-generator.git
cd YKI-video-generator
```

已有仓库无需重新克隆。先退出应用，在项目根目录（例如 `D:\YKI-video-generator`）检查本地改动并更新；若更新失败，先处理报错，不要继续启动：

```text
git status
git pull --ff-only
```

再按当前终端选择一组命令。提示符形如 `D:\YKI-video-generator>` 是 **CMD**，不能运行 PowerShell 的 `Copy-Item`：

```bat
if exist settings.local.json (
    echo settings.local.json already exists; merge the preset before running Start-Windows.bat.
) else (
    copy /-Y config\experimental-4070s-32gb.json settings.local.json && Start-Windows.bat
)
```

提示符形如 `PS D:\YKI-video-generator>` 是 **PowerShell**：

```powershell
if (Test-Path .\settings.local.json) {
    throw 'settings.local.json already exists; merge the experimental preset into it first.'
} else {
    Copy-Item .\config\experimental-4070s-32gb.json .\settings.local.json -ErrorAction Stop
    .\Start-Windows.bat
}
```

两组命令均保留已有 `settings.local.json`。如果它已存在，手动合并实验配置，保留自己的路径和其他设置，再双击 `Start-Windows.bat`。若个人配置仍指定 `llama.gpu_layers: 99`，应改为 `auto`。

实验配置做了这些调整：

- Qwen 使用 `gpu_layers: "auto"`，允许 CPU/GPU 分层；保留 8192 context 和单并发。若 Qwen 单独报显存分配错误，可尝试设置 `gpu_layers: 0` 验证 CPU 路径，这也需要足够系统内存且通常更慢。
- H3 生成尺寸从 768×1344 降为 **384×672**，仍用 20 步；最终 MP4 仍为 720×1280，由较低分辨率素材缩放，不代表原生 720p 细节。
- ComfyUI 启用 `--fast-disk` 和 `--disable-pinned-memory`，尝试降低权重驻留与锁页内存压力；吞吐可能下降。这些开关不是 32GB RAM 的成功保证。
- 延长模型启动等待至 1800 秒、规划请求至 3600 秒、单镜头视频等待至 28800 秒；这是避免提前超时的上限，不是预计耗时，仍可手动停止。

[ComfyUI v0.35.0 参数说明](https://github.com/Comfy-Org/ComfyUI/blob/40c4fcdf513a4523e39d54a9d391908af8df8171/comfy/cli_args.py#L167)表明动态模式下 `--lowvram` 不生效，因此本配置保留默认 DynamicVRAM 路径，没有叠加 `--lowvram`、`--novram` 或强制整个文本编码器上 CPU。[默认启用条件](https://github.com/Comfy-Org/ComfyUI/blob/40c4fcdf513a4523e39d54a9d391908af8df8171/main.py#L264)仍需 NVIDIA/PyTorch/aimdo 满足要求，需查看实际启动日志。

首次安装仍按完整固定清单下载约 57.63 GiB，不会自动改成小模型。先运行 3 镜头 DEMO，再创建 3 镜头真实项目；旁白保持简短，观察每个阶段日志。只想验证 H3 执行时可暂把 `comfy.steps` 调为 1；这种输出只验证执行，不能评价画质，随后恢复 20。

如果目前只想验证安装环境而不下载模型，可直接运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -SkipModels
.\runtime\app-env\Scripts\python.exe -m app serve --mode demo --open
```

`-SkipModels` 仍下载运行时、安装 Python 依赖和检查 CUDA，需要联网及磁盘空间。此时不要用 `Start-Windows.bat` 启动，它会发现模型未齐并补全安装。完整真实管线仍需要全部清单资产；单独下载某个模型不会让完整 `doctor` 或流水线就绪。

## 记录与回退

记录 GPU、系统 RAM、驱动、可用磁盘、Git 提交、配置、各阶段耗时和任务管理器中的内存峰值。失败时保留 `runtime/logs/`、`logs/llama.log`、`logs/comfy.log` 与对应项目 `project.json`，区别 CUDA OOM、系统内存提交失败和加载挂起，按 [Windows 验收清单](WINDOWS_ACCEPTANCE.md) 处理。

要回到默认生成参数，退出应用后删除个人配置中本次增加的覆盖项，或先备份再重命名 `settings.local.json`；不要删除项目素材或模型。旧版 Word 手册修订于 2026-09-16，其中 5090/128GB 建议已被本文取代，操作流程仍可参考。
