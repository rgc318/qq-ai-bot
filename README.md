# QQ AI 机器人部署工作区

方案：**SnowLuma + AstrBot 官方版 + 自有模型 API**。

当前已通过 **Ubuntu WSL2 的 Docker Compose** 部署，本地扩展为 **1.11.4**。实际状态与验收范围见 [STATUS.md](STATUS.md)；操作入口是 [compose.yaml](compose.yaml) 和 [Compose 部署说明](docs/docker-compose.md)，原生 Windows 安装说明保留为备用。

```text
QQ ↔ SnowLuma ↔ OneBot v11 反向 WebSocket ↔ AstrBot ↔ 模型 API
```

## 当前部署入口

人格切换、模型绑定、自动接话与生图用法见 [人格与工具说明](docs/personas-and-tools.md)。当前默认“大肥鱼 + DeepSeek 1017”，可切换为“ChatGPT龙娘 + 6.1 sol / low”。

点名、跨成员追问、普通群聊如何区别处理，见 [回复条件](docs/reply-conditions.md)。

配置完善事项、社区功能对照及本次搜索兼容修复、实际改图验证见 [2026-10-23 配置审计](docs/configuration-audit-2026-10-23.md)。

长期记忆与表情包已经启用，配置入口、人格隔离和用法见 [长期记忆和表情包](docs/memory-and-memes.md)。

较旧的对话可跨新会话按需检索原文，日常聊天继续使用近期上下文，用法和设置见 [按需找回旧对话](docs/history-recall.md)。

测试群已接入可切换的 ContextAware 上下文后端，共用持久化消息与附件档案；历史图片可按来源重新读取并用于改图。后端切换、权限和已实现边界见 [上下文运行层](docs/context-runtime-2026-10-25.md)。

一句话可生成最多 4 张独立图片，支持逐张不同描述和共用参考图；用法与部分失败处理见 [多图方案](docs/multi-image-plan-2026-10-26.md)。最新真实双参考图任务已完成原图恢复、改图、发送及文字收尾，耗时与仍需改进的收尾描述见 [真实流程与时延复核](docs/runtime-latency-review-2026-10-26.md)。

服务启动后，在 Windows 浏览器访问：

- AstrBot 后台：`http://127.0.0.1:6185/`。
- SnowLuma 后台：`http://127.0.0.1:5099/`。
- QQ 远程桌面：`http://127.0.0.1:6081/`，用于手机扫码登录容器中的 Linux QQ。

运行数据存储在独立 Docker 命名卷。`apps/` 和 `downloads/` 是原生安装备用目录，当前 Compose 不从这些目录运行应用。

本次生成的后台密码与 OneBot Token 在 `secrets/credentials.local.json`；临时 API Key 在 `secrets/model-api.env`。不要把凭据文件内容贴进聊天或公开日志。

在本目录打开 PowerShell，通过 `scripts/compose.ps1 ps` 查看状态，`scripts/compose.ps1 up -d` 启动，`scripts/compose.ps1 stop` 停止。当前容器间反向连接为 `ws://astrbot:6199/ws`，不再使用原生同机部署的回环地址。

## 目录

| 路径 | 用途 |
| --- | --- |
| `apps/snowluma/` | 原生安装备用目录；当前应用使用官方 Docker 镜像 |
| `apps/astrbot/` | 原生安装备用目录；当前实例数据使用 Docker 命名卷 |
| `config/` | 部署参数记录、无密钥示例；不是应用原生配置 |
| `secrets/` | 本地后台凭据、模型 Key、OneBot 原生配置 |
| `scripts/` | Compose 包装器、配置引导和模型检查工具 |
| `logs/` | 脱敏后的部署、排障日志 |
| `backups/` | 升级前的应用配置和数据备份 |
| `downloads/` | 官方发行包下载目录 |
| `docs/` | 部署步骤、验收项目及资料来源 |

## 从这里开始

1. 阅读 [Compose 部署步骤](docs/docker-compose.md)。
2. 在 `config/deployment.local.json` 记录 QQ 号、允许的群、模型接口地址和模型 ID。
3. 安装应用后，通过各自 WebUI 保存原生配置。
4. 按 [验收清单](docs/acceptance.md) 检查实际链路。

`deployment.local.json` **不会被 SnowLuma 或 AstrBot 自动读取**，引导脚本将其中的部署约定转换为 AstrBot 原生配置。API Key、OneBot Token 和后台密码不写进示例、日志或资料文档。为兼容 v4.29.1 的模型列表接口，模型源保存实际 API Key，位于 AstrBot 数据卷中。更换 Key 时需同时同步模型源与 Compose 环境，操作见 Compose 部署说明。

标准模型 API 接入不需要 DSH、qq-bridge 或 Codex 桥接。后续需要业务操作时，再为 AstrBot 添加相应插件或 MCP 工具。

注意：`.gitignore` 只避免 Git 误提交，不会加密或限制本地文件访问。两个项目均有非商业使用限制；本次使用 SnowLuma 官方文档公布的预构建 Docker 镜像，没有重新打包原生组件。具体资料见 [资料来源](docs/sources.md)。
