# ContextAware 固定版本适配

状态：1.9.0 已接入生产门面和后台互斥开关，仅测试群灰度。运行说明、时延实测和限制见[接入记录](../../docs/context-runtime-2026-10-25.md)，部署状态以 [STATUS.md](../../STATUS.md) 最新段落为准。下方隔离候选实验保留用于复现。

候选固定为 ContextAware 3.11.0 / `f026c5635f49b43b18f2f4e53eefbc7a0180cd94`，MIT。
上游文件放在忽略的 `downloads/contextaware-f026c56/`；来源、Git blob SHA-1、SHA-256 和大小记录在 `source-lock.json`。保留上游 LICENSE，不改写上游源码。

## 模块

| 文件 | 职责 |
| --- | --- |
| adapter.py | 根据现有 User Policy 身份建立内部事件视图；真实平台路由和模型配置保持原值；场景只陈述事实；模型显式选图并说明各图用途；使用万象画卷公开 API，保留权限和额度检查 |
| archive_restore.py | 从已有 AttachmentStore 冷恢复原始图、生成图、来源和可恢复的父图关系；不新建索引数据库，不承担第二套语义选图 |
| coordinator.py | 单选本地/ContextAware；在途请求固定后端代次；只允许空闲切换；切换期间新消息等待；激活失败回退；回退失败停止分发 |
| semantic_fixture.py | 通过 AstrBot 原生 runner 在合成消息/图片上检验两条现有模型的自主回看与选图；只记录生图意图 |

新增 `loader.py` 校验固定源文件，只移除全局事件/工具注册装饰器。生产使用 `extensions/astrbot_plugin_qq_persona_models/context_runtime.py` 明确驱动上游钩子、共用档案和正常万象画卷工具路线；不使用隔离评估用 OmniDrawBridge 接管另一套生成流水线。部署脚本将本目录打包为插件内 `_ca_runtime/`。默认从本地基线启动，固定源码与原生历史接口就绪后才允许后台选择 ContextAware；选择结果持久化，重载可恢复。

## 复现

在项目根目录，使用配置好 WSL Docker 的 Windows Python：

```powershell
python scripts/evaluate-contextaware.py --download-source
wsl -d Ubuntu --exec python3 /mnt/e/AI/ai/qq-ai-bot/scripts/test-context-backends.py
```

首条命令只在源文件缺失时下载固定提交并校验散列，随后运行隔离测试。依赖使用现有 AstrBot 镜像；不安装到运行中的服务。

容器禁网、只读、临时数据目录、无权限提升、不挂生产卷或凭据。只挂载候选和测试代码。万象画卷公开方法取自已安装 3.3.23 的 `main.py`：测试原样编译该方法及相关参数校验方法，替换模型生成、发送与额度存储边界；这不是完整的图片 Provider SDK 验收。

可选的真实文本/视觉模型合成测试会产生少量调用费用：

```powershell
python scripts/evaluate-contextaware.py --models --max-model-requests 20
```

模型调用在主机通过既有 LiteLLM 发生，容器通过标准输入输出接收答案，仍不能联网、实际生图或发 QQ。只发送程序生成的色块与虚构群聊，不读取真实会话或照片。原始模型回复不落盘，报告只保留合成用途说明与统计；普通运行不打印上下文/像素。

报告在忽略的 `logs/contextaware-*.json`，公开结论见[第一阶段记录](../../docs/contextaware-development-2026-10-25.md)。

## 使用边界

- 冷恢复、持续消息/成功发送图片的唯一归档及切换恢复已接入；没有再建一套持久化数据库。独立多话题任务调度仍未完成。
- 原生权限包装后的 schema 已检查；没有修改 AstrBot 核心和多个第三方插件源码。
- 内部使用上游 Main、场景呈现、ImageIndex 元数据与清理接口，均固定版本并通过原生测试约束；升级时必须复验这些接缝。
- 图像用途是模型自由文本，不是预设“三视图”“衣服”等任务模板。代码只检查来源、权限、数量、完整性和参数对应关系。
- 不把额外选择旧生成图一律判错：它可能是编辑目标。必须分别检查必要原图是否齐全、每张图的用途以及后续真实输出是否遵守约束。
- 纯色合成图能验证消息、图片来源与调用链，不能验证人物身份/姿态还原质量。
- 上游仍会在诊断日志显示规则推断的发言对象；传给模型的是事实快照，运行日志已标明规则观察不等于模型决策。
