"""Keep task completion distinct from permission to speak; prompt only."""

MARKER = '\n[本轮任务完成方式]\n'


def apply_response_task_contract(event, request):
    prompt = request.system_prompt or ''
    if MARKER in prompt:return
    names = set(request.func_tool.names()) if getattr(request, 'func_tool', None) else set()
    clauses = []
    if event.get_extra('self_initiated_reply'):
        clauses.append('本轮由主动接话流程发起，只表示已获准在群中发言。请结合群聊原文判断是在闲聊、问候还是提出实际任务；“简短接一句”的要求不能把一个实际任务降为报到或等待话术。有具体问题就给实质回答，需要已有工具时在本轮调用；没有具体任务时仍可自然闲聊。')
    if 'view_context_images' in names:
        clauses.append('图片目录及聊天中的“图片”标记不是图像内容。回答确实依赖历史图片的可见内容、且本轮尚未看到相应像素时，应自行结合来源目录与聊天记录选择图片并调用 view_context_images，再根据读取结果回答。多图有关联时按任务选择完整集合，不默认最近一张；仅讨论能力或与图片无关时不用看图。目录不足时可用实际可用的历史工具查找，歧义仍无法消除再澄清。')
    if names:
        clauses.append('只使用本轮实际提供且权限允许的工具。普通最终文字不会启动后台任务：不要只说“我看看、稍等、我去查一下”就结束需要工具的任务；应在当前回合读取或执行后回答，或如实说明具体阻碍。不要声称已经读取尚未读取的资料，也不要承诺不存在的后台续答。')
    if clauses:request.system_prompt = prompt + MARKER + ''.join(clauses) + '\n'
