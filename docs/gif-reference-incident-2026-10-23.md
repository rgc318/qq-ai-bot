# 22:28 GIF 表情包改图失败

请求已引用群友表情包，万象画卷也已找到 1 张参考图，并在 22:28:29 切换到 `/v1/images/edits`。22:28:31 上游返回 HTTP 400，`invalid_image_file`，字段 `images[0].image_url`，原因 `Invalid image data`。这是上传参考图数据被拒绝，不是本地目录权限、QQ 掉线或所有图像能力不可用。

本次引用文件 `media_image_20261023222800822_fbc1.gif` 的真实格式为 GIF，180×225、28 帧、23238 字节，与 22:21 群友发送的表情包内容对应。万象画卷原流程接受 GIF 文件，但直接将 GIF 字节和 image/gif 上传；multipart 文件名统一写成 reference_1.png，并不会因此把内容转成 PNG。此前改图验收使用的是 PNG，没有覆盖动图。

黄色 `user_refs` 保留参数告警表示内部参考图信息没有作为普通高级参数透传；程序随后仍使用它读取并上传了参考图，因此该告警不是本次失败的直接原因。

## 兼容修改

本地插件 1.2.11 在指定节点 `litellm-image25` 的 OpenAIProvider 上传边界，先执行原有文件、URL、参考图数量和字节限制检查，再把 GIF 解码为首帧 RGBA PNG。只转换上传副本，不写回原图；PNG、JPEG 等非 GIF 数据不做此转换。转换后的字节继续受原有 20MB 单图、64MB 总图限制约束。

这是可恢复的运行时适配，没有修改万象画卷社区源码。卸载/重载本地插件时恢复原方法；万象画卷重新加载后自动重新适配。后台 `image_upload_compat.enabled=false` 可关闭。输出是静态图，动图的后续帧不会作为参考帧送入模型。

## 检查与记录

5 项离线测试通过：GIF 第一帧及尺寸、PNG 原字节不变、双参考图保留、转换后大小限制、损坏 GIF 在上传前拒绝。

同一张失败 GIF 通过现有插件 API 实际改图成功，返回 1 张图，耗时 50.06 秒。配置为低质量、单张，结果记录在 `logs/gif-image-editing-verification.json`。日志确认实际请求经过 `GIF首帧转PNG=1`，没有向 QQ 群发送测试消息。此测试验证 API 接受和图片返回，不等同于自动替用户重发原群聊请求。

源码：`extensions/astrbot_plugin_qq_persona_models/image_upload_compat.py`。配置与绑定回读：`logs/gif-upload-runtime-status.json`。源代码备份：`backups/persona-models-1.2.10-before-gif-upload-fix/`，配置备份：`secrets/enhancement-backup/router-before-gif-upload-fix.json`。
