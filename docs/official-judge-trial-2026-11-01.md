# 官方判断模型试用

2026-11-01 23:50，将共享判断 Provider `qq-reply-judge-fast` 从 LiteLLM/硅基流动改到已有官方来源 `deepseek-official`，模型为 `deepseek-v4-pro`。主聊天仍为官方 `deepseek-flash`。

## 为什么切换

23:34:18 的真实请求总耗时约11.80秒，其中旧判断模型接口7.253秒、官方正文1.259秒、分段及发送约3.162秒，本地其余约0.12秒。这次耗时最长的是判断接口。

官方 Flash 首轮10个合成判断样本中9个达到原0.88阈值；独立表情请求虽判向Bot，却返回0.85。该边界额外3次核对均未达阈值（0.80/0.85/0.85）。没有降低阈值、修改提示词或隐去失败记录。

官方Pro同一组10个场景全部通过，非思考模式，中位1.534秒、最大2.353秒。因此采用Pro作文字判断；它不负责看图，也不改变正文主模型的视觉能力。样本较少，不能作为线上准确率或p95保证。

## 当前配置

- Provider ID：`qq-reply-judge-fast`，来源 `deepseek-official`。
- 模型：`deepseek-v4-pro`。
- 请求参数：`thinking={"type":"disabled"}`，`max_tokens=240`，`temperature=0.1`，`response_format={"type":"json_object"}`。
- 本地语义路由与业镜继续引用同一个Provider，不新增一轮判断。
- 原有8秒超时、0.88阈值、消息窗口、发言规则、人格和主模型绑定保留。分段发送间隔仍为0.3–0.8秒，没有本次修改。

空闲时备份、更新后，通过实际AstrBot判断接口运行4个虚构场景：

| 场景 | 耗时 | 结果 |
| --- | --- | --- |
| 跨成员追加文案请求 | 1.157秒 | 接话 |
| 群友之间带饭 | 1.518秒 | 沉默 |
| 先图后文字的翻译请求 | 1.583秒 | 接话 |
| 独立表情请求 | 1.280秒 | 接话 |

4项均通过，实际日志确认由官方Pro处理。未发送QQ、未生成正文或图片、未重放真实聊天。这不是对原7.25秒消息的原文复现，不能保证之后所有请求都在这个范围。

## 管理与回退

在AstrBot模型提供商中找到 `qq-reply-judge-fast`。本地插件和业镜中的判断模型选择不必分别修改，仍是此ID；日志应显示 `purpose=reply_judge` 或 `background_reply_judge`、模型 `deepseek-v4-pro`。

切换前配置备份为忽略目录内的 `secrets/enhancement-backup/judge-before-official-deepseek-20261101-235020.json`。回退只恢复该Provider原来源、模型和参数，不需要清空历史或更换人格。

脚本：`scripts/evaluate-official-judge.py`（Flash合成检查）、`--confidence-audit`（边界核对）、`--model deepseek-v4-pro`（Pro对照）；`scripts/configure-official-judge.py` 在空闲时切换并原生验证，失败回滚。所有凭据沿用已有忽略文件，不写入脚本或报告。

报告位于忽略的 `logs/official-deepseek-judge-evaluation.json`、`logs/official-deepseek-judge-confidence-audit.json`、`logs/official-deepseek-pro-judge-evaluation.json`、`logs/judge-official-deepseek-configuration.json`。
