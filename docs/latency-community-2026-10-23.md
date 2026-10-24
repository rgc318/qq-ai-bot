# 群聊延迟复查与社区方案

## 真实等待发生在哪里

- 21:20:31 空 @ 到 21:20:56 准备发送约 25.46 秒。数据库中的模型请求用时 25.32 秒，输入 188+9600=9788 tokens，输出 27 tokens；本地路由与请求准备约 0.1 秒。这次主要等待在上游模型调用。
- 21:21:24 画菜追问先经过本地判断，10 秒超时后又转业镜；随后等待静默 5 秒，再判断 14.05 秒，正文尚未开始就已耗费约 29 秒。这是之前优化遗漏的串行回退路径。
- 截图中的 NotADirectoryError 为归档失败保留原上下文的主动诊断，不是真实聊天故障。后续诊断日志已单独标注。

## 参考的社区方案

业镜作者明确区分点名回复与主动回复，并建议单独使用轻量判断模型、关闭判断识图，正文按需识图。我们保留该划分：[业镜 README](https://github.com/chengzhi-c/astrbot_plugin_self_initiated_reply/blob/main/README.md)。

智能提及社区实现包含避免多套主动回复重复触发、只在灰区判断、判断失败后熔断、默认不额外调用模型做分段或润色等策略。我们借鉴其减少串行请求和失败退避的思路，没有安装第三套接话插件：[小昭智能提及 README](https://github.com/ZhaoJun233/astrbot_plugin_xiaozhao_smart_mention)。

官方上下文文档也说明旧历史与工具结果会增加输入量，总结压缩本身还会调用模型。当前保留有界近期历史，没有为每条消息另加一次总结：[AstrBot 上下文压缩](https://docs.astrbot.app/use/context-compress.html)。

## 最终设置与行为

本地插件 1.2.9，主聊天人格和模型不变；仅改变专用判断 Provider `qq-reply-judge-fast` 的底层模型为 `siliconflow/Qwen/Qwen3-30B-A3B-Instruct-2507`。同源轻量模型小样本比较中，三例用时 4.14/3.03/2.84 秒，原 DeepSeek 为 3.09/11.31/6.72 秒；这不是固定延迟或全面质量评测。

- 本地判断完成、否决、把握不足或调用失败后，本条不再交业镜重复判断。高把握请求仍直接进入正文。
- 原生 @、引用机器人与原生唤醒不调用本地判断模型。
- 还没有调用本地模型的普通群聊继续交业镜，静默仍 5 秒，冷却仍 60 秒。
- 判断最多等待 8 秒，调用失败后同群暂停语义判断 15 秒；暂停不会阻止明确 @。代价是上游故障期间，未点名的模糊追问可能不回复，而不是无上限地重试。
- 判断上下文最多取近期 12 条、总 3600 字符，另附 AI 任务锚点、当前消息；原路由缓存仍保留 24 条摘要。
- 对“群友在让另一个人改文案”“群友互相索要表情”等场景补充了收件人优先说明。
- 没有删记忆、表情包、画图和搜索功能。原有上下文限额、按需回忆、图前提示保留。

去重通过 `single_judge.py` 复用业镜 1.5.1 的 `COMMAND_HANDLED_KEY` 逐事件入口守卫，不改社区插件源码，不终止全局消息事件。它是对该固定版本内部接口的兼容，升级业镜需重跑回调验证。设置 `reply_conditions.single_judge=false` 可关闭这层去重；配置与原代码均已备份。

## 验证及尚存限制

27 项确定性规则、12 项实际回调通过，覆盖超时退避、明确 @ 绕过、否决/超时不调第二次模型，以及普通未分类消息仍保留业镜路径。

首轮 29 例中 Qwen 出现两个人类对话误接话，不能只看小样本速度。加强收件人规则后这两例通过；第二轮全量检查有两个正例因 6 秒超时取消，其余 27 例通过。最终改为 8 秒，其中一例复测 7.91 秒通过，另一例仍一度超时，随后复测 4.55 秒通过。所有原例最终均有通过记录，但不能据此宣称单轮零超时或彻底解决服务波动。原始失败报告均保留。

最新原生主模型流程诊断为 3.46 秒（模型 3.41 秒、输入 9468 tokens），没有调用工具。与真实空 @ 的 25.32 秒模型请求对比，说明服务等待仍可能显著变化。排除串行路由等待后，进一步缩短这部分需要检查 LiteLLM 的上游耗时、队列、限流与重试，或比较其他上游渠道；仅卸载本地插件无法保证解决。当前没有 LiteLLM 管理权限，不修改其服务端配置。

所有验证均使用合成场景或读取现有历史，不向 QQ 发测试消息，不执行模型返回的工具；原生诊断跳过会持久化模拟回复的记忆反思钩子。真实群聊收发耗时仍以实际使用为准。

报告：`logs/reply-judge-community-benchmark.json`、`logs/single-judge-scenarios-first-pass.json`、`logs/single-judge-scenarios-six-second-budget.json`、`logs/single-judge-timeout-recheck.json`、`logs/single-judge-focused-recheck.json`、`logs/single-judge-additional-scenarios.json`、`logs/reply-hooks-verification.json`、`logs/performance-native-verification.json`。

当前配置脚本：`scripts/configure-single-judge.py`。备份：`secrets/enhancement-backup/*before-single-judge*`、`backups/persona-models-1.2.8-before-single-judge/`。
