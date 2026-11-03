# DeepSeek 官方路线试用与提供商对照

2026-11-01，按用户要求使用官方测试 Key。凭据在忽略的 `secrets/deepseek-official.env`，本文与测试脚本不含密钥。官方列表实测支持 `deepseek-flash`，具有 text/image 输入；官方模型说明将该 ID 映射为 DeepSeek-V4.1-Flash-1017。

## 对照方法

从现有 AstrBot 容器同时请求官方直连和现有 LAN LiteLLM → 硅基流动路线，使用同一组合成消息、纯色样本图片、工具描述及输出上限。官方设置 `thinking.type=disabled`，硅基流动设置 `enable_thinking=false`，所有响应的 reasoning_content 均为空。测试客户端不自动重试。

只使用隔离运行器导出的虚构群聊与合成图片，不重放真实聊天。工具只看模型决策，绝不执行、发 QQ 或调用真实生图。短图和长图测试禁止工具调用，目录测试允许选择读图工具但不执行。

先测约 6600 token 的长上下文，再增加到与最近真实慢请求更接近的 11889 token。每轮每条路线各 5 次，共 20 次对照模型调用，均成功并通过颜色/图片 ID 检查。

| 样本 | 官方直连 | LiteLLM → 硅基流动 |
| --- | --- | --- |
| 首轮长图，6589 token，3 次中位数 | 1.200 秒 | 1.599 秒 |
| 第二轮短图，1159 token，1 次 | 0.811 秒 | 2.053 秒 |
| 第二轮长图，11889 token，3 次中位数 | 1.131 秒 | 1.407 秒 |
| 第二轮长图，3 次最大值 | 1.210 秒 | 1.747 秒 |
| 第二轮目录选图，1 次 | 0.898 秒 | 1.029 秒 |

样本较少，部分重复请求命中各自缓存，输出 token 数也有变化。不能用这些结果估计线上 p95 或证明某个组件是长尾原因。官方在多数样本中更快，两边均没有复现之前的 57/98 秒等待；“官方直连”与“LiteLLM/硅基”同时改变了中转和上游，不能据此单独归责于硅基流动。

## 当前试用配置

- AstrBot 来源：`deepseek-official`，地址 `https://api.deepseek.com/v1`，OpenAI Chat Completions 兼容接口。
- 模型 Provider：`deepseek-official/deepseek-flash`，text/image/tool_use。
- 参数：`max_tokens=4096`，`thinking={"type":"disabled"}`。
- 主聊天“大肥鱼”绑定官方Flash；随后23:50将共享判断Provider切为官方Pro，见[判断模型试用](official-judge-trial-2026-11-01.md)。龙娘、群权限、人格文本、长期记忆和生图沿用原设置。
- 原 Provider `litellm-lan/siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017` 保留。

AstrBot 原生 Provider 测试确认 `available`，第二次独立核验的模型调用约 0.714 秒；这个短问候不代表真实长上下文速度。绑定、现有来源、原 Provider、两群策略及 ContextAware/完成检查适配器均核验通过。没有向 QQ 发送测试消息。

主聊天日志的实际 Provider 应为 `deepseek-official/deepseek-flash`、模型为 `deepseek-flash`。判断阶段Provider仍名为 `qq-reply-judge-fast`，现在使用官方 `deepseek-v4-pro`，应与主聊天耗时分开比较。

## 回退与复查

在本地插件“人格与聊天模型绑定”中，将大肥鱼重新选择为原硅基 Provider 即可；无需删除官方来源或清除聊天历史。

试用前备份位于 `secrets/enhancement-backup/official-deepseek-bindings-before-20261101-233044.json` 和相同时间的 profile 备份，均被 Git 忽略。配置脚本 `scripts/configure-official-deepseek.py` 在空闲时添加独立来源、原生测试、切换并检查，失败回滚；已有同名官方来源时不会覆盖。原生测试必须检查内层 `data.status=available`，不能只看外层 HTTP/JSON 成功。

复测命令：`python scripts/compare-deepseek-providers.py`。结果仅保留耗时、token、缓存、成功标志和工具名等元数据，位于忽略的 `logs/deepseek-provider-comparison.json`，首轮结果另存 `logs/deepseek-provider-comparison-6k.local.json`。

官方资料：[模型与版本](https://api-docs.deepseek.com/quick_start/pricing/)、[视觉输入](https://api-docs.deepseek.com/guides/vision/)、[关闭思考](https://api-docs.deepseek.com/guides/thinking_mode/)。
