"""Restore tool-response rules after persona replacement, without model calls."""

TOOL_RULE_HEADING='# QQ Tool Response Rules'
IMAGE_RULE_HEADING='[图片工具完成后的文字收尾]'
IMAGE_COMPLETION_RULE=(
    '当本轮 generate_image 或 generate_selfie 的工具结果明确报告已成功下发图片，且数量大于0时，图片已交付。'
    '若没有其他待完成的任务，默认按当前人格用一句简短自然的中文确认这个真实结果，不要空回复；'
    '不要因图片已发送就省略普通文字收尾，也不要重复调用绘图、自拍或发送工具。'
    '不要套固定话术，不编造生成图中的细节。若用户还提出了其他问题或任务，继续完成剩余要求。'
    '工具失败、数量为0或发送未确认时不能宣称成功。遵从用户明确指定的输出格式。'
)


def restore_tool_response_contract(request,native_rule):
    tools=getattr(getattr(request,'func_tool',None),'tools',None)
    if not tools:
        return {'native_restored':False,'image_rule_added':False}
    text=getattr(request,'system_prompt','') or ''
    native_restored=bool(native_rule and native_rule not in text)
    if native_restored:
        text+='\n'+TOOL_RULE_HEADING+'\n'+native_rule+'\n'
    image_rule_added=any(getattr(tool,'name','') in ('generate_image','generate_selfie') for tool in tools) and IMAGE_RULE_HEADING not in text
    if image_rule_added:
        text+='\n'+IMAGE_RULE_HEADING+'\n'+IMAGE_COMPLETION_RULE+'\n'
    request.system_prompt=text
    return {'native_restored':native_restored,'image_rule_added':image_rule_added}
