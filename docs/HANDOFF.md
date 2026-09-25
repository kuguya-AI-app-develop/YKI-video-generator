# YKI-video-generator 开发交接

交接日期：2026-09-16。版本：0.1.0 测试版。仓库为 `kuguya-AI-app-develop/YKI-video-generator`；正式产品名称、网页、CLI、安装器提示、源码包和使用说明书已统一。

## 新设备先做什么

1. 按 [README](../README.md) 直接 clone 公开仓库；不要从旧设备直接搬运虚拟环境。
2. Mac 安装 uv 与 FFmpeg，运行 `Start-Mac-Demo.command`；Windows 实机按安装与验收章节执行。
3. 运行完整回归，确认 0 skipped，再开始修改；最新计数见验证记录。若媒体测试跳过，补齐 FFmpeg/FFprobe。
4. 阅读 [架构](ARCHITECTURE.md)、[领域说明](../CONTEXT.md) 和 [代理约定](../AGENTS.md)。安装 CodeGraph CLI 后运行 `codegraph init -i`。
5. 需要旧故事时，退出两端应用后单独复制完整 `projects/`；Git 中没有视频、模型或本机设置。

## 已有实现

- 本机中文 Web 创作台、3/6 镜头项目、串行队列、进度和错误显示。
- Qwen / Kokoro / ComfyUI H3 适配及 FFmpeg/Pillow 合成，真实失败不回退 DEMO。
- 镜头编辑、重做、历史选择、锁定、停止、中断恢复和递增成片版本。
- Windows 安装/启动脚本，固定清单和哈希、下载续传、安全解压、运行环境锁与 CUDA 检查。
- 源码 ZIP 打包、逐文件 manifest、Word 使用说明、Windows 实机验收清单。

## 验证状态与下一阶段

本轮 Mac 回归为 28 项通过、0 skipped；Python 编译与 JavaScript 语法检查通过。更名后桌面和 390px 界面检查通过，7 页 Word 已渲染检查。CodeGraph 已索引 23 个源码文件、376 个节点。历史验证和未测范围见 [VALIDATION.md](VALIDATION.md)。

**尚未在 Windows 5090 完成真实安装或推理验收。** 下一阶段按 [WINDOWS_ACCEPTANCE.md](WINDOWS_ACCEPTANCE.md) 顺序处理：

1. 在干净 Windows 11 环境验证下载、依赖安装、驱动/CUDA 和 VC++ 修复分支，保留日志。
2. 完成 3 镜头 DEMO，确认中文、播放、下载和媒体编码。
3. 完成 3 镜头真实生成，分别确认 Qwen 输出、Kokoro 有声 WAV、H3 动态画面和最终同步；记录耗时、显存和内存。
4. 验证只重做 S02 时 S01/S03 素材保持不变，历史恢复、停止与重启能继续。
5. 再做 6 镜头、角色一致性观察和断网新项目测试。根据证据决定是否需要内存/性能优化。

不要预先将这些项目勾为通过。失败时保留安装日志、模型日志、项目状态和相关素材；分享前检查故事内容和个人路径。先定位最小故障，避免反复整套重新下载。

## 修改入口与注意点

流程编排在 `app/pipeline.py`；模型适配在 `app/providers/`；前端在 `web/`；持久化/队列在 `app/storage.py` 与 `app/jobs.py`；Windows 部署在 `scripts/bootstrap.ps1`、`scripts/start.ps1`。

更改模型需要联动固定资产清单与工作流。安装器内容哈希变化可能触发已安装用户重新检查部署，已校验资产可复用。保留兼容环境变量 `AIGC_FONT` 和现有项目结构，不因更名迁移用户数据。

用户素材与源码分开备份；出现回归时先备份整个 `projects/`，在独立 checkout 中验证旧提交。不要用删除项目数据、强制重置或绕过哈希校验的方式回退。

## 2026-09-25 硬件条件修订

仓库已公开。当前试跑目标改为 Windows 11、RTX4070 Super 12GB、32GB RAM。修订依据和逐模型说明见 [HARDWARE.md](HARDWARE.md)：撤销安装器约32GB显存硬拦截；Qwen允许自动CPU/GPU分层；新增低分辨率、磁盘辅助加载、禁用锁页内存的实验配置。模型清单、哈希和推理后端版本保持不变，真实GPU生成仍待用户机器验收。

新实验配置位于 `config/experimental-4070s-32gb.json`，合并到 `settings.local.json` 后生效。不要将旧Word手册中的5090/128GB建议视为当前最低条件，也不要把社区报告当成本项目实测。
