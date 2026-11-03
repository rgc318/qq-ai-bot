# 部署状态

核对日期：2026-11-03（Asia/Shanghai）。旧状态页完整保存在[部署历史](docs/deployment-history-through-2026-11-02.md)，其中旧模型、白名单和“尚未验收”不代表现状。

## 服务与入口

Ubuntu WSL2 Docker Compose：**容器内 Linux QQ → SnowLuma → OneBot v11 反向 WebSocket → AstrBot → 模型 API**。不依赖 Windows QQ；关闭浏览器页面不停止容器。

| 服务 | 版本 / 配置 | Windows 本机入口 |
| --- | --- | --- |
| AstrBot | Compose 固定 v4.29.1 | http://127.0.0.1:6185/ |
| SnowLuma | Compose 固定 v2.1.1 | http://127.0.0.1:5099/ |
| Linux QQ 远程桌面 | 用于观察、扫码登录 | http://127.0.0.1:6081/ |
| 本地扩展 | 1.14.0，已启用 | AstrBot → 插件 → QQ 人格模型与回复条件 |

OneBot 连接为容器内 `ws://astrbot:6199/ws`；6199 未发布到 Windows。应用数据在 Docker 命名卷，密钥在忽略的 `secrets/` 及应用原生配置中，Git 仓库不包含这些数据。

`restart: unless-stopped` 依赖 Docker 引擎运行，不等于 Windows 启动后必定自动启动 WSL / Docker。`scripts/compose.ps1 ps` 查看状态，部署和备份见 [Compose 说明](docs/docker-compose.md)。

## 当前模型与插件

以下由本机 AstrBot API 只读核对，不调用模型。

| 用途 | 当前 Provider / 模型 | 说明 |
| --- | --- | --- |
| 大肥鱼 | `deepseek-official/deepseek-flash` / `deepseek-flash` | 官方 API，关闭思考，输出上限 4096 token |
| ChatGPT龙娘 | `litellm-lan/cliproxyapi/gpt-6.1-terra` / `cliproxyapi/gpt-6.1-terra` | 现有 LiteLLM 路线；旧 Sol / low 不代表当前 Terra 参数 |
| 接话判断 | `qq-reply-judge-fast` / 官方 `deepseek-v4-pro` | 与业镜共用；非思考 JSON，8 秒超时，0.88 阈值 |
| 生图 / 改图 | 万象画卷 `litellm-image25` / `gpt-image-2.5` | 沿用已部署路线；本次不发起生图验收 |

两条人格绑定验证均通过；原硅基路线保留。实际选择以后台绑定为准，操作见[人格、模型与工具](docs/personas-and-tools.md)。

已启用：万象画卷 3.3.23、多人格管理 v3.5.6、业镜 1.5.1、LivingMemory 2.7.1、表情包管理器 5.2.5、本地扩展 1.14.0。ContextAware 为受管集成，来源固定提交 `f026c5635f49b43b18f2f4e53eefbc7a0180cd94`，不是另装的独立接话器。

尚未安装 AI 群管理插件；禁言、撤回只是 SnowLuma 可提供的接口能力。微信接入是独立后续事项，不算已完成。

## 群范围与上下文

- 原生群白名单包含 `347440128`、`476547826`，管理员不绕过群白名单。人的后台管理权限、群策略管理员与 QQ 真实群权限分别配置，不能互相替代。
- 当前后端 `contextaware`，启动等待、切换中和失败状态均为 false；本地后端也可用。切换入口在本地插件“上下文后端”页面，需等待在途请求结束。
- 统一近期输入：最多 16 条消息 / 6000 字符、4 张历史预览、最长边 1024 像素、总 JPEG 1 MiB。候选最长 86400 秒，仍受保存期、容量和消息窗口限制。
- 较早图片、原消息和文字文档按需读取；改图使用模型选择的来源原图。不保证模型必然理解正确或选全相关资料。
- `task_completion.enabled=true`：非流式原生 Agent 的明确证据矛盾最多纠正一次；漏报状态记为未知，不固定增加独立审核模型。
- 原生分段已启用，仅 LLM 结果，随机间隔 0.3–0.8 秒，字数阈值 150；插件首段立即发送已开启，只跳过首段人为停顿，后续间隔保留。这不是流式生成。

新群需要核对原生访问控制、本地插件生效群、业镜范围及多人格策略，见[新群配置](docs/personas-and-tools.md#添加新群)。

## 验证与时延边界

真实群聊已验证历史双图恢复、改图、QQ 投递及文字收尾，见[流程复核](docs/runtime-latency-review-2026-10-26.md)。这不等于全部功能和 24 小时稳定性均验收。本次只读核对状态并运行禁网合成回归，不重放真实聊天、不调用付费模型、不发送 QQ。

首段优化后 3 次样本，从 AstrBot 收到消息到首段平台发送返回为 **3.998 / 3.808 / 4.703 秒**。旧日志没有首段埋点，不能实测逐条前后对照；同条件下直接移除 **0.3–0.8 秒**等待，均匀随机配置的期望约 0.55 秒。全部气泡完成时间不能当首段时间，见[计时说明](docs/first-segment-delivery-2026-11-02.md)。

本地准备、模型接口等待、工具执行和分段投递应分开看。合成毫秒基准不是线上总延迟；预览增加输入量，工具回看、纠正和多张生图均可能增加等待。

## 维护索引

- [1.14.0 发布整理与本次检查](docs/release-1.14.0-2026-11-03.md)
- [统一多模态架构](docs/shared-context-architecture-2026-11-01.md)、[资料证据与一次纠正](docs/task-evidence-and-correction-2026-11-01.md)
- [官方主聊天试用](docs/deepseek-official-trial-2026-11-01.md)、[官方判断模型试用](docs/official-judge-trial-2026-11-01.md)
- [验收清单](docs/acceptance.md)、[历史部署记录](docs/deployment-history-through-2026-11-02.md)

本地源码、GitHub 和容器数据卷是不同状态。推送源码不会自动部署，也不会备份 QQ 登录态、人格数据库、历史图片和 API Key；应用卷需单独备份。
