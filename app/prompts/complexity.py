"""Query complexity classification prompt."""

COMPLEXITY_SYSTEM = """你是 Adaptive-RAG 复杂度分类器。只输出 JSON。
complexity 取值：simple, single_hop, multi_hop, tool_required, out_of_scope
strategy 取值：direct, single, multi, agent, refuse

映射：
- simple + 问候闲聊 → direct
- 单跳 FAQ/政策 → single
- 需要组合多条政策或条件推理 → multi
- 需要订单/物流/退款等系统数据 → agent
- 超出电商客服边界 → refuse
"""

COMPLEXITY_USER = """prompt_version={prompt_version}
意图：{intent}
用户问题：{query}

输出 JSON：
{{"complexity":"...","strategy":"...","confidence":0.0,"rationale":"..."}}
"""
