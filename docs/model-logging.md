# 模型调用日志

2026-10-24，本地插件 1.5.0。日志在 AstrBot 原有日志页面及 Docker 容器日志中显示，统一前缀 `[AI调用]`。

1.6.1 补充：新增“绘图参考图检查”，记录 available_reference_count、attached_reference_count 与 selected_previous_reference，不打印路径或图片。routing_done 的 normal_pipeline_eligible 只代表允许进入后续流程，命令等可能提前处理，真正的模型开始以 start 为准。修复一个旧参考图自检事件缺少 qq_diagnostic 标记的问题，新增回调完成和不改生产图片任务的断言，避免钩子异常被框架捕获后检查仍显示通过。最近实际问题和计时口径见 [运行审计](runtime-audit-2026-10-24.md)。

1.5.1 修复：实际事件出现 `ContextVar ... was created in a different Context`，来自 1.5.0 包装在异步 yield 期间保留追踪 token；消费者提前结束、Python 在另一任务清理生成器时会重置失败，并可能让后台记忆继承 main_reply 用途。现在每次读取和关闭单独设置/还原作用域，yield 时不保留 token，记忆来源的用途优先于继承标签。新增跨任务关闭、上下文不泄漏、记忆用途覆盖检查，总计 26 项通过。使用真实龙娘和原生执行器提前读取、另一任务关闭的路径复测通过（约 12.34 秒），返回 generate_image 并捕获开工对白；不实际生图或发 QQ 消息。报告：`logs/model-logging-cross-context-fix.json`、`logs/model-logging-early-close-native-check.json`。这一修复针对新增日志缺陷，不能把现场没有图片工具调用自动解释为它阻断了生图。

## 看哪里卡住

下例为字段简化示意，不是某次实际请求的完整记录：

```text
[AI调用] 开始请求 {"purpose":"reply_judge","model":"siliconflow/Qwen/Qwen3-30B-A3B-Instruct-2507","trace":"...","call":"..."}
[AI调用] 调用取消或超时中断 {"model":"...","seconds":8.0,"error_type":"CancelledError","trace":"..."}
[AI调用] 判断超时，未进入正文生成 {"model":"...","error_type":"TimeoutError","next":"main_reply_not_started","trace":"..."}
```

这意味着判断接口超时，不能解释成模型判断“用户不是在问 AI”；这条消息没有进入正文生成，也没有启动图片任务。判断超时仍为原来的 8 秒，日志不会自动重试或更改回复条件。

普通主模型/绘图请求会看到如下阶段：

| 日志阶段 | 含义 |
| --- | --- |
| 正文请求已准备 | 最终人格、历史、附件和工具已构造；随后是否真正调用看下一条 |
| 开始请求 | 已进入对应 Provider 的模型调用方法 |
| 仍在等待模型接口 | 该调用尚未返回，不代表已确认远端服务器开始推理 |
| 收到首个输出 | 流式接口首次产出一个片段；不是所有请求都有此日志，也不保证片段含可见文字 |
| 调用完成 / tool_calls_returned | 模型返回了工具调用；查看 tool_calls 是否包含 generate_image |
| 调用完成 / text_returned | 模型只返回文字，不能据此认为已启动图片任务 |
| 图片节点开始请求 | kind=image、purpose=image_generation，包含 node、model；此时才进入图片 Provider |
| 本轮模型回复结束 | Agent 已结束，image_tool_calls 表示尝试调用图片工具的次数，不是成功发图数 |
| 消息发送完成 | 正常回复发送后回调已执行，耗时从本条事件进入路由时起计 |

工具返回调用、图片节点成功和 QQ 图片送达是不同事件，不能互相替代。新增日志不会执行或补做缺失的工具调用。

## 公共字段与范围

- `trace`：同一条消息的关联标识；`call`：每次模型调用标识。一轮工具往返可有多次 call。
- `group`、`message`、`persona`：可取得消息上下文时记录；没有消息来源的后台调用使用独立 bg trace，不猜测其属于某个群。
- `purpose`：reply_judge 本地接话判断，background_reply_judge 业镜后台判断，main_reply 正文，image_notice 补写开工对白，image_generation 绘图，memory_processing 记忆模型处理，memory_embedding 向量处理。未能确认用途时按 text/embedding 等类别记录。
- `provider`、`model`：本次实际调用对象的节点 ID 与请求模型 ID；LiteLLM 内部路由到哪个后端不在本地日志的可见范围。
- `seconds`：Provider 公共调用方法开始至返回/异常的耗时，包含其准备数据、网络、上游处理及内部重试，不能直接当作纯服务端推理耗时。
- `context_messages`、`image_count`、`tool_count`：可取得的输入消息、图片片段、可用工具数；不展开其内容。request_ready 的 input_chars 只统计系统提示与当前正文字符，不是完整 token 数。
- `tool_calls`、`input_tokens`、`output_tokens`：结果提供这些信息时记录；未提供 usage 不填假零。
- `error_type`、`http_status`：异常类别及能提取到的 HTTP 数字状态，不打印原始异常正文。外层超时取消 Provider 时先记录 cancelled，再由路由日志明确 TimeoutError 与后续阶段。
- `parent`：万象画卷同一链路的标识，多个备用节点的调用可按它关联；每个节点分别记录真实 model、node 和结果。
- `diagnostic=true`：可识别的隔离诊断事件，不作为群内实际收发记录。

当前 AstrBot 注册的文本、Embedding、重排、STT/TTS Provider 公开方法均接入统一包装；当前万象画卷的四类图片 Provider 也接入。Provider 热加载后自动补装。新插件若直接用自己的 HTTP 客户端调用其他模型，不经过这些入口，需要另行接入，不能保证任意第三方请求都被自动识别。

实现为可恢复包装，不改 AstrBot 或社区插件源文件。取消、异常、返回值及流式逐段输出保留；同一 Provider 内部嵌套调用不重复记账。日志及等待计时不发起模型请求、不延后正文或图片任务。此处“开始请求”只能确认进入客户端调用，无法从本机确认远端具体何时开始推理。

## 配置与状态

AstrBot 后台 → 插件 → QQ 人格模型与回复条件 → **模型调用与消息处理日志**：

```json
{"model_logging":{"enabled":true,"heartbeat_seconds":10,"heartbeat_repeat_seconds":30}}
```

长请求默认在 10 秒显示第一条等待日志，以后每隔 30 秒显示一次；8 秒接话判断通常会在首个等待提示之前完成或超时。heartbeat_seconds=0 可停止等待心跳，enabled=false 停止新增模型日志包装。保存后插件重载生效。后台始终可以看到现有原生日志，新增开关不会关闭第三方自身日志。

已认证管理接口 `GET /api/plug/qq_persona_models/model_activity/status` 返回当前 active 调用、最近 50 次完成记录，以及按模型和用途分组的样本数、平均值、P50/P95、失败和取消数。统计保存在内存，插件重载/进程重启后清零；小样本分位数仅用于排查，不能视为长期性能保证。

新增日志只输出白名单元数据，不记录 API Key、请求头、URL、提示词、对话正文、工具参数、图片字节或模型回复。AstrBot 和第三方原本的消息/提示词日志没有在本次统一改写，不能声称整个服务所有日志都不含原文。现有 Docker 日志轮转仍为每容器 10 MB × 3 份。

## 验证

- 21 项本地与运行时替身检查：稳定 trace 与最终人格、开始/等待/完成、取消、异常/HTTP 状态脱敏、流式输出、并发 trace 隔离、向量嵌套去重、Embedding 模型字段兼容、图片节点/改图模式、继承包装去重、敏感内容过滤、耗时摘要、卸载恢复与关闭日志。
- 真实 Qwen3-30B-A3B-Instruct-2507 与 Qwen3-Embedding-0.6B 各一次专用诊断，正确显示模型和完成状态，不写入生产会话。
- 真实龙娘 Sol 主模型经过原生请求构造和工具前置流程，耗时约 10.913 秒；出现等待心跳并返回 generate_image，日志含相同 trace、消息 ID、模型和工具名。图片执行器为替身，没有生成或发送图片。
- 37 项路由规则、原有 12 项回复回调、10 项参考图和 13 项多人上下文/隔离检查通过。模型绑定、记忆与历史能力仍保留。

测试期间首次日志诊断分支挂错到了历史检查入口，误调用了原有可清理的合成记忆检查两次；结果显示测试记忆已清理、无 QQ 发送。该入口已纠正，并增加返回 model_calls=0 等断言，最终日志检查结果来自正确专用入口。该情况不应被说成整个测试过程完全无记忆存储访问。

本地报告（不公开）：`logs/model-logging-native-checks.json`、`logs/model-logging-live-checks.json`、`logs/model-logging-main-tool-checks.json`、`logs/model-logging-runtime-status.json`、`logs/model-logging-regression-checks.json`。测试脚本：`scripts/test-model-logging.py`。
