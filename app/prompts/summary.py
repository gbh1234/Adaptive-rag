"""Conversation summarisation prompt."""

SUMMARY_SYSTEM = (
    """把电商客服对话压成简短摘要，保留：用户诉求、订单号、已查状态、待确认操作。只输出 JSON。"""
)

SUMMARY_USER = """历史：
{history}

输出 JSON：
{{"summary":"..."}}
"""
