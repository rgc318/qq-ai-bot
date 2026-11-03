# LiteLLM 接话判断模型对照

2026-11-01 从现有 LiteLLM `/v1/models` 读取 127 个模型 ID。目录中的 ID 是本地服务标签，不据此推断它一定对应公开发布版本或独立上游节点。

使用现有路由器的系统提示，测试纯合成群聊：分段发图后要求翻译、跨成员追问、人类互相订饭、点名唤醒、转向群友、明确要求沉默、群友修改自己的文案、表情包交换、独立表情请求和未完成图片任务催办。无真实聊天或图片上传，无工具执行、QQ 发送或线上配置修改。

第一轮 5 个模型各 3 题，第二轮 3 个候选各 10 题，共 45 次短文本请求。并发上限 2，非流式，`max_tokens=240`、`temperature=0.1`、`response_format={"type":"json_object"}`。DeepSeek/GLM 显式 `enable_thinking=false`，Qwen Instruct 保留生产参数。每次客户端读取超时 12 秒，同时统计是否超过生产 8 秒期限。

## 完整 10 场景结果

| LiteLLM 模型 ID | 符合当前接话规则 | 中位耗时 | 最长耗时 | 超过 8 秒 |
| --- | --- | --- | --- | --- |
| `siliconflow/deepseek-ai/DeepSeek-V4.1-Flash` | 10/10 | 1.990 s | 3.418 s | 0 |
| `siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017` | 9/10 | 1.084 s | 2.005 s | 0 |
| `siliconflow/Qwen/Qwen3-30B-A3B-Instruct-2507` | 10/10 | 2.593 s | 3.736 s | 0 |

1017 的一条独立表情请求判定收件人为机器人、route 为 addressed，但置信度 0.85 低于生产阈值 0.88，会被拒绝。评分计入这项实际门槛；要求沉默的发言只要 `silence_requested=true` 即按成功不回复计算，不因 route 为 addressed 而误计失败。

初筛另有 `siliconflow/deepseek-ai/DeepSeek-V4-Flash`，3/3，中位 4.748 s、最长 5.364 s；`siliconflow/zai-org/GLM-5.3-Flash` 2/3，其中一次未返回可解析 JSON，另有请求耗时达到 9.988 s。现用 Qwen 初筛最长 6.392 s；线上此前确有 8 秒取消记录，不能因为这轮测试未超时就宣布问题消失。

## 建议

首选 **`siliconflow/deepseek-ai/DeepSeek-V4.1-Flash`，关闭思考**。在当前小样本中，它兼顾了置信度门槛、JSON 格式和速度；不为追求最低耗时降低全局接话阈值。1017 可作为更偏速度的备选。

实施时只修改专用 Provider `qq-reply-judge-fast` 的模型与请求参数，本地路由器和业镜继续引用此 ID。保留人格主模型、群范围和 8 秒判断期限。推荐请求体为 `enable_thinking=false`、`temperature=0.1`、`response_format={"type":"json_object"}`，并保留足够输出长度。硅基流动的参数说明见[官方 Chat Completions 文档](https://docs.siliconflow.cn/docs/api/chat-completions-post)。不同中转可能映射到共享后端，单纯换标签不能保证峰值时稳定。

用户随后明确要求替换判断模型，已通过 `scripts/configure-judge-replacement.py` 把线上 **`qq-reply-judge-fast`** 改为普通 DeepSeek V4.1 Flash，关闭思考，输出上限 240 tokens。只更新这一 Provider，原配置已备份，失败可自动回滚。两个判断入口继续引用同一 ID，8 秒超时、群范围和人格主模型均未修改。

切换后另做 3 次 AstrBot 原生隔离判断：跨成员追问 7.040 s、人类互聊保持沉默 2.405 s、分段图片翻译请求 1.904 s，三项通过，日志确认实际使用新模型。原生测试中出现了比直接接口小样本更长的 7.040 秒，因此不能承诺上线后的判断固定只需约 2 秒，仍需观察峰值等待。无正文生成、真实图片处理或 QQ 发送；模型筛选加上线验证共 48 次合成判断请求。

复现脚本：`scripts/evaluate-judge-candidates.py`；详细脱敏结果位于忽略目录 `logs/judge-candidate-screen.json`、`logs/judge-candidate-full.json`、`logs/judge-deepseek-replacement.json`。样本量小、集中在同一时间段，可能受缓存影响，表中数值不是长期均值、生产 P95 或普遍准确率。
