# 1.14.0 源码与文档整理

整理日期：2026-11-03（Asia/Shanghai）。本次保存此前已完成和部署的 1.11.5–1.14.0 改动，整理文档并回归验证；不重新部署应用，不改运行配置，不调用付费模型或向 QQ 发测试消息。

## 本次保存的行为

| 改动 | 结果与边界 | 说明 |
| --- | --- | --- |
| 人格模型选择器 | 使用 AstrBot 原生人格 / Provider 下拉框；迁移旧字典时保留自定义值 | [操作入口](personas-and-tools.md#选择每个人格使用的聊天模型1115) |
| 生命周期与页面 | 冷启动等待原生依赖、兼容桥接状态、有限重连、卸载恢复适配器 | [故障与修复](context-lifecycle-incident-2026-10-29.md) |
| 群会话范围 | 接受同一真实群的原生别名；不开放其他群 / 人格档案；可按明确消息 ID 补收漏收资料 | [新群故障](new-group-image-context-2026-11-01.md) |
| 统一近期上下文 | 本地 / ContextAware、普通 / 业镜入口使用同源事实；近期图片预算内直接送主模型 | [架构](shared-context-architecture-2026-11-01.md) |
| 请求与证据 | 独立请求状态、资料实际可见性、明确矛盾最多一次同 Agent 纠正；漏报不强行推断 | [证据与纠正](task-evidence-and-correction-2026-11-01.md) |
| 官方 API 配置工具 | 大肥鱼与判断器分别配置，保留原 Provider；脚本中的诊断默认不执行真实工具 | [主聊天](deepseek-official-trial-2026-11-01.md)、[判断器](official-judge-trial-2026-11-01.md) |
| 首段发送 | 插件可逆适配，首段跳过人工等待；后续仍用原生间隔，保留引用 / @ / 发送钩子 | [设置、实测及边界](first-segment-delivery-2026-11-02.md) |

当前配置以 [STATUS.md](../STATUS.md) 为准。旧模型和群范围已在主文档中明确标记为历史，原状态页完整移至[部署历史](deployment-history-through-2026-11-02.md)。新增群的各层范围、模型绑定和耗时开关见[使用说明](personas-and-tools.md)。

## 本次检查

- 114 项单元测试通过：附件存储 24、群身份 4、人格绑定 11、任务证据 15、回复路由 56、历史裁剪 4。
- 226 项禁网原生运行检查通过，包含首段发送、并发独立状态、资料交付、纠正预算和适配器恢复。
- 27 项独立架构审查通过；后端页面桥接、切换、忙碌拒绝、有限重连、超时和卸载检查通过。
- 后台只读核对：扩展 1.14.0 已启用；两条人格绑定验证通过；ContextAware、任务检查和首段适配器状态正常。大肥鱼为官方 Flash、判断器为官方 Pro，龙娘当前为 Terra，未把历史 Sol / low 写成现状。
- 提交前检查 Python / JSON 语法、文档本地文件链接和待提交内容中的密钥 / 运行数据。诊断报告、凭据、下载源码、应用数据卷与真实聊天内容不随本次提交发布。

Windows 受限沙箱第一次附件测试因临时目录原子替换权限失败，受限环境中的组合测试运行未完成；改用工作区临时目录及独立进程正常权限运行后通过。没有为规避环境问题放宽生产文件权限或修改实现。

## 时延解释

本次禁网合成运行基准每后端 40 个样本：ContextAware 本地准备 p50 7.390 ms、p95 8.569 ms、首次 41.734 ms；本地后端 p95 10.215 ms、首次 56.670 ms。测试不包含网络、模型推理、真实 QQ 和复杂生产群聊，不是线上 p95，也不是重构前后受控性能对照。

上线后的三个真实首段样本为 3.998 / 3.808 / 4.703 秒；旧版本没有首段埋点，能确定移除的是原生 0.3–0.8 秒人工等待，不能由此声称整条业务零开销或回复速度固定提升数秒。图片输入增加 token，按需工具和一次纠正仍可能增加模型轮次。

## 复核命令

从仓库根目录运行，各单元脚本使用独立进程：

```powershell
python scripts/test-attachment-store.py
python scripts/test-group-context-identity.py
python scripts/test-persona-bindings.py
python scripts/test-task-evidence.py
python scripts/test-reply-routing.py
python scripts/test-performance-context.py
node scripts/test-context-backend-page.cjs
python scripts/evaluate-context-runtime.py
python scripts/evaluate-context-runtime.py --architecture-audit
```

后两项需要已运行的 WSL Docker、现有 AstrBot 镜像和忽略目录中的固定候选源码；脚本以禁网、只读源代码和临时数据运行。新克隆只有源代码时，应先按[上下文运行层](context-runtime-2026-10-25.md)准备相同依赖；测试命令不是完整安装器。不要为了回归启用 `--models` 或再次运行配置 / 部署脚本。

## 保存与回退

公开 Git 只保存源码、无密钥模板及文档；密钥、模型源原生配置、QQ 登录态、人格与记忆数据库、图片和运行报告需要独立备份。`secrets/`、`logs/`、`downloads/`、`apps/`、`backups/` 继续被忽略。

提交并推送不触发自动部署。本地扩展已经在运行实例中；若从较早版本升级，需按对应文档逐次执行窄范围脚本并保留配置备份。不能直接对旧实例运行所有历史脚本；回退应恢复匹配版本的源码和原生配置，不清空群历史或删除数据卷。
