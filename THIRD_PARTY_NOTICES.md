# 第三方来源与许可

核查日期：2026-09-12。此项目的源码 ZIP 不捆绑第三方模型或推理程序；Windows 安装器根据 `config/models.lock.json` 从上游下载。下面是主要直接依赖的来源索引，不替代上游完整许可，也不替所有传递依赖统一授予许可。安装归档及 Python 包中的许可证和版权声明应保留。

## 模型

| 内容 | 许可与来源 |
| --- | --- |
| Qwen3.8-27B | Apache-2.0。[原始模型及许可](https://huggingface.co/Qwen/Qwen3.8-27B)、[本项目使用的 Unsloth GGUF](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF)。安装 `UD-Q4_K_M` 量化版本，固定 revision 与哈希见清单。 |
| MiniMax H3-Base 及适配权重 | MiniMax H3 Community License。[官方许可](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)、[官方仓库](https://github.com/MiniMax-AI/MiniMax-H3)、[Comfy-Org 适配权重](https://huggingface.co/Comfy-Org/MiniMax-H3)。本项目使用剪枝 int8 主模型、量化文本编码器以及视频/音频 VAE。 |
| H3 所用 Qwen3-VL 编码器基础模型 | H3 官方许可额外注明基础 Qwen3-VL-32B 采用 Apache-2.0，参见 [Qwen3-VL LICENSE](https://github.com/QwenLM/Qwen3-VL/blob/main/LICENSE)；H3 适配权重仍应结合其上游提供的条款判断。 |
| Kokoro-82M v1.1 中文/英文 | Apache-2.0。[原作者模型卡](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)说明中文数据由 LongMaoData 授权提供。[sherpa-onnx 模型包与使用说明](https://k2-fsa.github.io/sherpa/onnx/tts/all/Chinese-English/kokoro-multi-lang-v1_1.html)、[转换包 LICENSE](https://huggingface.co/csukuangfj/kokoro-multi-lang-v1_1/blob/main/LICENSE)。 |

H3 采用有条件的社区许可，不能简单理解为无地域限制的开源授权。当前许可排除欧盟、英国、韩国和美国，相关限制也涉及模型输出；商业授权、标识、可接受用途和对外提供服务的要求见官方完整文本。真实成片默认烧录「AI 生成」，发布时仍须遵守适用平台规则。此个人本机工具尚未实现面向公众服务所需的内容审核体系。

## 软件与运行时

| 软件 | 许可与上游 |
| --- | --- |
| llama.cpp | MIT。[源码与 LICENSE](https://github.com/ggml-org/llama.cpp)、[本项目固定 b10919 下载](https://github.com/ggml-org/llama.cpp/releases/tag/b10919)。配套 CUDA 二进制也包含 NVIDIA 组件，须保留归档中的相应声明。 |
| ComfyUI | GNU GPL v3。[LICENSE](https://github.com/Comfy-Org/ComfyUI/blob/master/LICENSE)、[固定 v0.35.0 portable](https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.35.0)。其 Python、PyTorch、前端和其他组件各有自己的许可。 |
| sherpa-onnx 1.13.8 | Apache-2.0。[源码与 LICENSE](https://github.com/k2-fsa/sherpa-onnx)、[PyPI](https://pypi.org/project/sherpa-onnx/1.13.8/)。内含/依赖的 ONNX Runtime、语音前端等组件按各自声明分发。 |
| Pillow 12.3.0 | MIT-CMU，参见 [LICENSE](https://github.com/python-pillow/Pillow/blob/main/LICENSE)、[PyPI](https://pypi.org/project/Pillow/12.3.0/)。用于将本机字体渲染为字幕图层。 |
| py7zr 1.1.0 | GNU LGPL v2.1，参见 [LICENSE](https://github.com/miurahr/py7zr/blob/master/LICENSE)、[PyPI](https://pypi.org/project/py7zr/1.1.0/)。用于解压 ComfyUI portable。 |
| uv | MIT / Apache-2.0 双许可。[上游](https://github.com/astral-sh/uv)、[固定 0.12.13 下载](https://github.com/astral-sh/uv/releases/tag/0.12.13)。其托管 Python 发行包另带 Python 及所含库的许可。 |
| Python | Python Software Foundation 许可及随附第三方许可。[Python 许可说明](https://docs.python.org/3/license.html)、[uv 管理 Python 的说明](https://docs.astral.sh/uv/concepts/python-versions/)。 |
| Microsoft Visual C++ v14 x64 Runtime | Microsoft 专有许可，以官方安装器随附条款为准。[官方来源及许可入口](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)、[官方安装参数](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)。仅缺少所需 DLL 时从官方最新 x64 链接下载，验证有效 Microsoft 签名后安装；实际版本和 SHA256 留存于安装日志，不包含在固定模型清单中。 |
| FFmpeg / FFprobe | FFmpeg 的 LGPL/GPL 条件随编译选项和外部库变化，不能对所有构建作同一许可保证。[FFmpeg 法律与许可说明](https://ffmpeg.org/legal.html)、[Gyan Windows 构建来源](https://www.gyan.dev/ffmpeg/builds/)、[本项目固定 9.0.1 essentials 下载](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.1)。应以该下载包内许可、构建配置和相应源码为准。 |

本项目读取 Windows 自带微软雅黑/黑体或 macOS 自带宋体绘制字幕，不把这些字体文件复制进交付包。自定义 `AIGC_FONT` 时由使用者选择有适用许可的字体。

精确下载 URL、文件大小、SHA256 在 `config/models.lock.json`；应用 Python 依赖见 `requirements.txt` 与 Windows 哈希锁文件。此处所列许可证不改变各上游条款，也不说明原始素材或生成视频必然满足发布条件。
