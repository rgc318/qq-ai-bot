# 当前部署：Docker Compose + Ubuntu WSL2

## 部署约定

- Windows 工作区：`E:\AI\ai\qq-ai-bot`。
- WSL 路径：`/mnt/e/AI/ai/qq-ai-bot`。
- Docker Engine：复用 Ubuntu WSL2 中已有的 Docker。
- Compose 项目名：`qq-ai-bot`，使用独立网络和数据卷。
- AstrBot：官方 `soulter/astrbot:v4.29.1`，固定镜像摘要。
- SnowLuma：官方 `motricseven7/snowluma:v2.1.1`，固定镜像摘要。
- LiteLLM：`http://192.168.31.229:4000/v1`，Chat Completions。
- 初始验收模型：`siliconflow/deepseek-ai/DeepSeek-V4.1-Flash`。

没有安装新的 Docker Desktop，也没有修改已有其他项目的 Compose 或 Docker daemon 配置。SnowLuma 使用官方预构建镜像，没有重新打包其原生组件。

## 容器网络与端口

只有 `6185`、`5099`、`6081` 绑定到宿主的 `127.0.0.1`。OneBot `6199` 不发布到宿主机。

- SnowLuma 连接 `ws://astrbot:6199/ws`。
- AstrBot 容器内监听 `0.0.0.0:6199`。
- 不能在 SnowLuma 容器中使用 `127.0.0.1:6199` 连接另一个容器。
- 两端使用相同的随机 OneBot Token。
- 所有服务设置 `restart: unless-stopped`。Docker Engine 必须先运行；Windows 重启后仍需确保 Ubuntu WSL 与 Docker 已启动。本次没有创建 Windows 自启动任务。

## 凭据

本部署生成的凭据放在 `secrets/credentials.local.json`，直接在本机编辑器打开，不要把它的内容贴进聊天、截图或公开日志。

- AstrBot 用户名和密码：`astrbot_username` / `astrbot_password`。
- SnowLuma 默认管理员登录入口：密码为 `snowluma_password`，用户名按该版本登录界面填写（若要求用户名，一般为 `admin`）。
- noVNC 密码：`novnc_password`；连接后用手机 QQ 扫码，不需要把 QQ 密码交给部署者。
- LiteLLM Key：`secrets/model-api.env` 中的 `QQ_BOT_API_KEY`。

`secrets/snowluma.env` 只为首次初始化提供后台密码。后续若在后台更改密码，不要再把文件里的旧密码当作当前密码。引导脚本保留已存在的本地凭据，不会每次重新生成。

## 首次登录后要完成的事项

1. 在 SnowLuma 界面按实际要求完成 EULA 和隐私政策确认。
2. 打开 noVNC，输入本地保存的 VNC 密码，在容器里的 QQ 界面扫码登录。
3. 确认 SnowLuma 检测到正确 QQ 账号。
4. 检查 QQ 账号对应的 OneBot 配置是否继承了 `ws://astrbot:6199/ws`。如果已经存在账号专用配置，需要在后台确认它未覆盖全局连接。
5. 当前管理员已设为 `2354912009`、测试群已设为 `347440128`。需要更改范围时，更新 `config/deployment.local.json` 的 `access` 字段并应用配置。
6. 按验收清单测试实际 QQ 收发。基础服务健康不等于 QQ 链路已通过验收。

## 应用部署记录到 AstrBot

只更新管理员和白名单时，使用下面的窄范围操作；它保留模型、人格等其他应用设置，并备份原配置：

```powershell
.\scripts\compose.ps1 stop astrbot
.\scripts\compose.ps1 run --rm --no-deps --volume /mnt/e/AI/ai/qq-ai-bot/scripts:/deployment-scripts:ro --volume /mnt/e/AI/ai/qq-ai-bot/config:/deployment-config:ro --entrypoint python astrbot /deployment-scripts/configure-access.py
.\scripts\compose.ps1 up -d astrbot
```

管理员和允许的私聊用户会转换为完整私聊会话 ID，群号直接加入群白名单，以免把私聊用户 QQ 号当作允许的群号。

需要重新应用整个部署约定时，使用下面的完整配置引导。仅修改 `deployment.local.json` 不会让运行中的 AstrBot 自动更新：

```powershell
.\scripts\compose.ps1 stop astrbot
.\scripts\compose.ps1 run --rm --no-deps --volume /mnt/e/AI/ai/qq-ai-bot/scripts:/deployment-scripts:ro --volume /mnt/e/AI/ai/qq-ai-bot/config:/deployment-config:ro --volume /mnt/e/AI/ai/qq-ai-bot/secrets:/deployment-secrets:ro --entrypoint python astrbot /deployment-scripts/bootstrap-astrbot.py
.\scripts\compose.ps1 up -d astrbot
```

挂载路径针对当前 Ubuntu WSL Docker；如果以后换到 Docker Desktop，要随引擎调整路径。引导脚本更新本部署的模型、QQ 适配器和访问范围，并在命名卷内保存旧配置备份；它会重设本部署约定的 Agent 与访问设置，后台做过自定义调整时应先核对差异。

## 更新临时 API Key

在本机编辑 `secrets/model-api.env`，保持 `QQ_BOT_API_KEY=...` 单行格式，然后：

```powershell
.\scripts\compose.ps1 up -d --force-recreate astrbot
# 等待 AstrBot 后台启动后，同步本地 Key 到已有模型源并验证：
.\scripts\repair-model-source.ps1 -ReplaceExistingKey
```

只执行 `restart` 不会重新加载 Compose 环境变量。只重建容器也不会替换模型源中已经保存的 Key，因此还需运行同步脚本，或在后台更新 `litellm-lan` 的 API Key。同步脚本仅更新该模型源，保留已配置模型和其他设置；`-ReplaceExistingKey` 明确允许替换当前源的 Key。

v4.29.1 的模型列表路径直接实例化提供商，不展开 `$QQ_BOT_API_KEY`，会造成 LiteLLM 401，而前端显示 Internal server error。本部署因此在原生模型源中保存解析后的 Key；该文件位于 AstrBot 数据卷内，备份数据卷时也需按凭据保管。2026-10-23 已验证直连 LiteLLM 与 AstrBot 后台均返回 125 个模型，默认聊天模型检查通过。

## 数据持久化与备份

数据卷：

- `qq-ai-bot_astrbot-data`：AstrBot 配置、数据库与插件数据。
- `qq-ai-bot_snowluma-data`：SnowLuma 配置与状态。
- `qq-ai-bot_qq-client-config`：QQ 配置、登录状态。
- `qq-ai-bot_qq-client-data`：QQ 用户数据。

升级前停止本项目服务，再导出这些卷并保管本地 `secrets/`。备份 E 盘部署文件夹不会自动备份命名卷。禁止用 `down -v` 做普通停止，它会删除上述持久化卷。日常停机用 `stop`；只重建容器时保留卷。

## 资料

- [AstrBot 官方 Compose](https://github.com/AstrBotDevs/AstrBot/blob/master/compose.yml)
- [AstrBot Docker 部署](https://docs.astrbot.app/deploy/astrbot/docker.html)
- [SnowLuma 官方 Compose](https://github.com/SnowLuma/SnowLuma.Docker.Framework/blob/main/docker-compose.yml)
- [SnowLuma 官方 Windows Docker / WSL 说明](https://snowluma.github.io/zh/docs/guide/deploy/windows-docker)

本次按官方文档运行其官方镜像。原生 Windows 安装路线保留在 `setup-windows.md`，不再作为当前操作入口。
