# 生图前的模型对白

2026-10-23，本地插件 1.2.10。

自然语言绘图、改图或自拍开始前，由当前聊天主模型按人格和任务写一句对白：大肥鱼使用 DeepSeek 1017，龙娘使用 Sol low。Qwen 接话判断器不负责这句话。

普通聊天的图片工具定义副本新增 `pending_message`，作为该次调用所需参数；不修改全局工具或万象画卷接口。模型可以在决定绘图和整理提示词的同一次调用中写好对白，程序在图片工具执行前先发送它，再移除该辅助字段。

真实测试发现 DeepSeek 有时仍照旧工具历史的格式漏写新增字段，单靠“必填”并不可靠。因此漏写时才用同一个人格主模型补写一句：只带人格、当前用户要求和图片描述，不带长历史、不提供工具，最多等 10 秒。这条补充可能增加少量等待和一次文本模型调用；不保证上游服务始终及时。补写失败不发送固定模板，也不阻断生图。

模型被要求贴合内容自然说话，不机械报到，不把改图一概称为拍照，不提前宣称成功，不承诺完成时间。同一轮最多提示一次。自然对白内容由模型决定，不能保证每次都与历史措辞不同。

后台路径：插件 → QQ 人格模型与回复条件 → 自然语言生图前提示。

- `enabled=true`：启用。
- `model_generated=true`：使用模型对白。
- `fallback_timeout_seconds=10`：漏写时短生成的等待上限。
- 旧 `draw_text` / `selfie_text` 不参与当前流程，仅手动关闭模型模式时才会使用。

`/画`、`/自拍` 的指令响应继续由万象画卷自身处理。图库表情不触发图片开工对白。

验证使用真实 DeepSeek 文本调用、当前人格及既有会话构造请求，图片执行器替换为只记录参数的替身，没有向 QQ 发测试消息，没有调用生图 API。15 项前置钩子检查包含逐字发送模型对白、顺序、去重、辅助参数清理、作用范围、失败不阻断；10 项参考图检查包含双图选择、原路径限制、全局定义不变及新字段清理。

同次模型调用曾生成“这个可以，戴厨师帽炒饭的小鲸鱼，我来画～”。也保留了模型漏写、补写超过原先 6 秒预算的失败记录；最终为漏写场景增加 10 秒补写预算。实际原生执行器验证报告：`logs/model-image-notice-missing-executor-verification.json`。其他报告：`logs/model-image-notice-native-verification.json`、`logs/image-pending-notice-verification.json`、`logs/model-notice-image-reference-verification.json`。

配置脚本：`scripts/configure-image-pending-notice.py`。配置备份：`secrets/enhancement-backup/router-before-model-image-notice.json`。源代码备份：`backups/persona-models-1.2.9-before-model-notice/`。
