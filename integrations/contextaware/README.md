# ContextAware 隔离候选

状态：已开发并验证三个接缝、冷恢复与切换控制器。**未安装进生产 AstrBot；未接入生产钩子或后台开关。**

候选固定为 ContextAware 3.11.0 / `f026c5635f49b43b18f2f4e53eefbc7a0180cd94`，MIT。
上游文件放在忽略的 `downloads/contextaware-f026c56/`；来源、Git blob SHA-1、SHA-256 和大小记录在 `source-lock.json`。保留上游 LICENSE，不改写上游源码。

## 模块

| 文件 | 职责 |
| --- | --- |
| adapter.py | 根据现有 User Policy 身份建立内部事件视图；真实平台路由和模型配置保持原值；场景只陈述事实；模型显式选图并说明各图用途；使用万象画卷公开 API，保留权限和额度检查 |
| archive_restore.py | 从已有 AttachmentStore 冷恢复原始图、生成图、来源和可恢复的父图关系；不新建索引数据库，不承担第二套语义选图 |
| coordinator.py | 单选本地/ContextAware；在途请求固定后端代次；只允许空闲切换；切换期间新消息等待；激活失败回退；回退失败停止分发 |
| semantic_fixture.py | 通过 AstrBot 原生 runner 在合成消息/图片上检验两条现有模型的自主回看与选图；只记录生图意图 |

当前 `contextaware` 默认不可用。只有后续接入代码验证完整钩子互斥、持续归档和运行期生命周期后，才能使其成为可选生产后端。不能通过直接修改一个配置字符串就宣称切换完成。

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

- 冷恢复已验证，持续收到消息/发送生成图时如何唯一归档仍待生产适配，不能把冷恢复等同于完整持久化接入。
- 原生权限包装后的 schema 已检查；没有修改 AstrBot 核心和多个第三方插件源码。
- 内部使用上游 Main、场景呈现、ImageIndex 元数据与清理接口，均固定版本并通过原生测试约束；升级时必须复验这些接缝。
- 图像用途是模型自由文本，不是预设“三视图”“衣服”等任务模板。代码只检查来源、权限、数量、完整性和参数对应关系。
- 不把额外选择旧生成图一律判错：它可能是编辑目标。必须分别检查必要原图是否齐全、每张图的用途以及后续真实输出是否遵守约束。
- 纯色合成图能验证消息、图片来源与调用链，不能验证人物身份/姿态还原质量。
- 上游仍会在诊断日志显示规则推断的发言对象；候选传给模型的是事实快照，不把这些规则结论作为指令。后续生产日志需明确标记二者。
