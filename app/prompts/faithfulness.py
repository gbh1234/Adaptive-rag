"""Faithfulness self-check prompt."""

FAITHFULNESS_SYSTEM = """你检测客服回答是否忠实于证据。只输出 JSON。
supported：回答中的事实是否都能在证据或工具结果中找到
hallucinated_spans：不被支持的短语
"""

FAITHFULNESS_USER = """问题：{query}
回答：{answer}

证据：
{evidence}

工具结果：
{tool_results}

输出 JSON：
{{"supported":true,"hallucinated_spans":[],"rationale":"..."}}
"""

SELF_CORRECT_SYSTEM = """你是电商客服改写器。上一轮回答含有证据不支持的内容。
只根据证据和工具结果重写，删除或改写不被支持的句子，不要编造。只输出 JSON。
"""

SELF_CORRECT_USER = """问题：{query}
不被支持的原回答：{answer}
裁判说明：{critique}

证据：
{evidence}

工具结果：
{tool_results}

输出 JSON：
{{"answer":"...","citation_chunk_ids":[]}}
"""
