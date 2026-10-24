# Windows 同机部署步骤

> 当前已经切换到 Docker Compose 部署；请优先阅读 `docker-compose.md`。本页仅保留为原生安装备用路线，不代表已执行这些步骤。

这里记录操作顺序；当前没有执行安装。工作区根目录为 `E:\AI\ai\qq-ai-bot`。

## 1. 补齐部署信息

编辑 `config/deployment.local.json`，记录机器人 QQ、主人 QQ、允许的群、API Base URL、接口类型和模型 ID。QQ 号使用字符串。

- `provider_type`：按服务实际协议填写 `OpenAI Compatible` 或 `OpenAI Responses`。
- 空的允许列表表示本阶段尚未决定放行对象，不表示放行全部。实际访问限制需要在 AstrBot 中配置。
- `supports_tool_calling`、`supports_image_input` 先保留 `null`，验证后再填写。
- 表中的端口是本次部署约定；最终以应用实际启动日志和配置为准。

## 2. 手动安装 SnowLuma

从官方 Releases 下载 Windows x64 完整发行包，保存到 `downloads/`，手动解压到 `apps/snowluma/`。初始参考版本是已核对的 `v2.1.1`；实际安装前再次确认发行说明与 QQ 兼容要求，并记录所安装版本。

保留完整发行包内的文件布局，从其实际解压目录运行 `launcher.bat`。按界面要求完成协议确认与 QQ 接入。WebUI 约定地址为 `http://127.0.0.1:5099`，初始密码以启动日志为准。

发行包目录多一层时，以实际包含 `launcher.bat` 的目录为程序目录，不要随意移动内部文件。SnowLuma 自行生成的配置、账号状态和日志保留在它自己的目录布局中。

## 3. 安装 AstrBot 独立实例

按官方 uv 包管理器方式安装。需要先具备 `uv`，以下命令在你决定开始安装时再执行：

```powershell
uv tool install astrbot --python 3.12
Set-Location -LiteralPath 'E:\AI\ai\qq-ai-bot\apps\astrbot'
astrbot init
astrbot run
```

`astrbot init` 只在首次初始化时执行。后续仍从同一工作目录启动，避免把实例数据分散到其他位置。uv 管理的程序和 Python 环境可能位于其全局工具目录，`apps/astrbot/` 预留的是本实例工作目录，不代表所有依赖都安装在这里；初始化后确认实际数据路径并记录。

uv 安装需要联网，可能下载 Python。使用该方式的 AstrBot 版本升级通过命令行管理。后台初始凭据以本次安装提示为准，不预设默认密码。

## 4. 连接 OneBot v11

在 AstrBot 创建 OneBot v11 机器人，设置本机监听 `127.0.0.1:6199`。生成一个随机 Token，在 AstrBot 和 SnowLuma 两边填写相同的值。

在 SnowLuma 启用反向 WebSocket，连接到：

```text
ws://127.0.0.1:6199/ws
```

观察两边日志，确认连接成功后，再检查 QQ 的实际收发。此处是 SnowLuma 主动连接 AstrBot；不要把 WebUI 端口填进这个地址。本次反向连接链路无需另开 OneBot HTTP 服务。

这些回环地址只适用于 Windows 同机原生运行。以后改为 Docker 或分机部署时，需要重新设置监听地址、连接主机名和网络边界，不能直接照搬 `127.0.0.1`。

## 5. 接入模型 API

在 AstrBot「模型提供商 → 对话」中添加与实际 API 协议一致的提供商，设置 Base URL、API Key 和模型 ID。Base URL 的路径以服务提供方的接口说明为准，不手动重复拼接 `/v1`。

v4.29.1 的正常模型加载支持环境变量 Key，但后台获取模型列表的路径未展开变量。若需要在后台获取模型列表，请在模型源的 API Key 栏保存实际 Key，并妥善保管包含它的应用配置备份。当前 Docker 部署通过配置引导和修复脚本同步 `secrets/model-api.env` 中的 Key，详见 `docker-compose.md`。

先测试模型，再在机器人所用配置文件中选择这个对话模型，使用内置 Agent 执行方式。首次仅配置聊天；工具和图片能力分别验证后再开启。

## 6. 设置访问范围并验收

在 AstrBot 中设置管理员、允许的 QQ 会话、群聊触发方式和人格。第一轮只放行主人私聊和一个测试群。按 `docs/acceptance.md` 验收，结果填写到 `STATUS.md`。

升级前停止相应服务并备份配置和持久化数据到 `backups/`。后台与 OneBot 服务保持本机访问，排障共享日志前先脱敏。
