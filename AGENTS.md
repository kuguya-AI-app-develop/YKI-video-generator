# YKI-video-generator 开发约定

先读 `README.md`、`CONTEXT.md` 和 `docs/HANDOFF.md`。当前为 0.1.0 Windows NVIDIA 测试版（含 4070S / 32GB RAM 实验配置），真实 GPU 链路尚未验收，不得把 DEMO 当作真实生成成功。

## 修改范围与验证

- 应用是 Python 标准库 HTTP + 无构建前端，不为简单需求引入新框架。
- 保持 localhost 绑定、单任务队列、进程所有权、安装运行互斥和资产哈希校验。
- 保留用户素材和镜头历史；恢复以完整镜头为单位。真实生成失败不得悄悄回退为 DEMO。
- 不提交模型、项目视频、运行环境、日志、个人设置或凭据；不要读取或上传无关项目数据。
- 修改下载、安装或工作流时同步检查 `config/models.lock.json`、Windows 依赖锁和验收说明。
- 运行相关测试；完整回归为 `python -m unittest discover -s tests -v`。媒体测试要求 FFmpeg/FFprobe，否则会跳过。
- UI 修改后用浏览器验证桌面和窄屏。打包用 `python scripts/package.py`，检查 ZIP 与哈希。
- 没有 Windows GPU 验证结果时明确写“未测试”，保留 `docs/VALIDATION.md` 的历史日期与验证范围。
- 新功能分支用 `codex/` 前缀。提交/推送遵循当前用户授权，不自动发布 release。

## CodeGraph

结构查询优先用 CodeGraph：`codegraph_explore` 追踪流程，`codegraph_search` 查符号，`codegraph_impact` 查改动影响。字面文本检索使用 `rg`。委派探索时也传递这一约定，避免重复全仓阅读。

在有 CodeGraph CLI 的新设备，按 README 于项目根运行 `codegraph init -i`；已有索引用 `codegraph index` 更新，`codegraph status` 检查状态。`.codegraph/` 是机器本地缓存，不提交。尚未具备工具时说明情况，必要的源码阅读可以继续。
