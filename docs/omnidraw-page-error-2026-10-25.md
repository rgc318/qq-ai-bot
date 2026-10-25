# 万象画卷配置页 ERROR 修复

截图中的 ERROR 来自配置页初始化的异常捕获。后台配置、用量、缓存统计三个接口均正常，插件已启用，不表示图片模型连不上。

安装版本的 `pages/插件配置/index.html` 已移除 `opt_astrbot` 开关，`app.js` 的 `bindBasicFields()` 仍直接给这个空元素设置 `checked`，复现为 `TypeError: Cannot set properties of null (setting 'checked')`。页面在更新节点计数之前中断，所以侧栏同时显示 0 个节点。`readBasicFields()` 的保存数据构造路径也存在同类引用。

修复只对两处 DOM 访问增加存在性检查：开关缺失时保留已有 `use_astrbot_provider` 值；如果后续 HTML 包含该开关，则仍可以读写。脚本 URL 更新为 `app.js?v=3.4.0-qq-page-fix1`，刷新页面后加载修复版本。未修改生产配置、模型、插件版本或群权限，也没有重启服务、生成图片或发送 QQ。

仓库保留 `scripts/patch-omnidraw-page.py`，使用 `--root` 和 `--backup` 指定安装目录及备份目录，支持 `--dry-run`。只接受已识别的两处源代码和脚本 URL，遇到不匹配版本会停止，重复应用无额外修改。运行中原文件备份位于容器的 `/AstrBot/data/plugin_data/astrbot_plugin_omnidraw/local-patches/frontend-null-control/`。第三方插件重装会覆盖静态文件，补丁脚本供核对后恢复。

验证使用真实 HTML 的元素 ID 和实际页面脚本，在 Node VM 中执行表单绑定与 `buildPayload()`：原脚本可复现异常，修复脚本在缺少开关时保留 true/false，在存在开关时支持切换，两种情况共四项通过。通过已认证的原生页面入口读取实际服务的 HTML、JS，确认缓存标识和两处保护生效，三个后台接口仍正常。没有提交保存表单，没有模型调用。

当前内置浏览器后端不可用，因此未完成真实浏览器的视觉验收；需要刷新现有页面观察 ERROR 是否消失。脱敏验证结果保存在忽略的 `logs/omnidraw-page-fix-verification.json`。
