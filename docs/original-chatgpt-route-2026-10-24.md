# 原 LiteLLM ChatGPT 接口试用

用户要求尝试原 LiteLLM 中的 ChatGPT。原 Provider 是 `litellm-lan/cliproxyapi/gpt-6.1-sol`，模型 ID 为 `cliproxyapi/gpt-6.1-sol`，源为 `litellm-lan`，使用 Chat Completions。此前它被停用，龙娘绑定了另一个 Responses Provider `qq-dragon-sol-low`。本次切回原 Provider，模型名称和人格均未更换。

## 配置结果

- 仅将 `bindings["ChatGPT龙娘"]` 改为 `litellm-lan/cliproxyapi/gpt-6.1-sol`。
- 启用原 Provider，类型 `openai_chat_completion`，声明文字、图像、工具能力。
- 请求附加参数：`{"max_tokens":4096,"reasoning_effort":"low","allowed_openai_params":["reasoning_effort"]}`。
- `allowed_openai_params` 只用于这个 Provider。旧 LiteLLM 能力表曾拒绝直接传入 `reasoning_effort`；本次确认显式允许透传后请求成功。未更改 LiteLLM 全局参数检查，也未使用 `none` 或 `minimal` 推理档位。
- 大肥鱼的 DeepSeek 1017 绑定、人格定义、群规则、管理员、记忆隔离均通过回读校验。测试群仍为当前的 ChatGPT龙娘。
- 原 Responses Provider 保留，未删除其配置；既有 DeepSeek 故障备用策略保留。插件版本仍为 1.6.1。

此结论仅适用于实测的 LiteLLM/CLIProxy 路线。OpenAI 官方 Sol 工具调用的协议说明仍以 [模型文档](https://developers.openai.com/api/docs/models/gpt-6.1-sol) 为准；本地代理兼容成功不能据此推广到官方 Chat Completions 接口。

## 实测

| 检查 | 结果 | 单次耗时 |
| --- | --- | --- |
| 原配置短文本 | 返回 OK | 3.172 秒 |
| 原配置模拟工具调用、工具结果续答 | 两阶段通过，续答非空 | 3.062 / 3.437 秒 |
| low 参数透传短文本 | 返回 OK | 4.203 秒 |
| low 参数透传模拟工具调用、工具结果续答 | 两阶段通过，续答非空 | 2.469 / 3.062 秒 |
| low 参数透传读图 | 正确识别合成红色图片 | 5.672 秒 |
| AstrBot 原生主模型、现有人格与上下文、生图工具前置流程 | 选中 generate_image；模型写出开工对白；先提示再执行；内部参数被清理；跨任务关闭无异常 | 12.83 秒 |

模拟工具只是返回本地 echo 结果；原生生图流程使用替身执行器并捕获发送。没有调用图片模型，没有发送 QQ，没有清空或写入真实聊天历史。原生工具准备检查只覆盖首轮决策与执行前置；完整工具往返检查是独立的合成协议测试，不能等同于真实群聊整轮生图验收。

这些是少量测试样本，不是延迟平均值。群聊的真实上下文、工具数量、上游负载及备用模型切换都可能改变时间。本次也没有解决审计中参考图计数为 0 的旧任务状态问题；要验证改图，应重新引用目标图片并观察引用图计数，不能把无参考生成当作编辑成功。

## 查看、复现和回滚

AstrBot 模型页 → `litellm-lan` → 原 `cliproxyapi/gpt-6.1-sol` 模型，可查看启用状态和高级请求参数。人格绑定在本地插件 `astrbot_plugin_qq_persona_models` 的 `bindings` 中，群里切换人格仍由多人格管理负责。

复现脚本使用现有本地凭据，不在输出中打印密钥：

```powershell
python scripts/probe-original-chatgpt.py
python scripts/probe-original-chatgpt.py --low-tools
python scripts/configure-original-chatgpt.py
python scripts/verify-original-chatgpt.py
```

切换脚本要求两个工具往返报告通过，先备份 Provider 与绑定到忽略的 `secrets/enhancement-backup/`，只修改目标模型及龙娘绑定；校验失败会恢复两项配置。它不修改群人格。后台模型列表是动态选项，群规则校验只比较真实规则和配置修订，避免将模型启用后的选项变化误报为群规则改变。

若需恢复旧 Responses 路线，将龙娘绑定改回 `qq-dragon-sol-low` 并保存。不要重新运行旧的全量 `configure-enhancement.py` 作为回滚，它还会重设其他早期配置。

本地报告位于忽略的 `logs/original-chatgpt-{probe,low-tools,configuration,native-verification}.json`；原始凭据和本地报告均不纳入 Git。
