"""Self-RAG retrieval grading prompt."""

GRADE_SYSTEM = """你评估检索结果是否足以回答问题。只输出 JSON。
relevant：是否至少有一条证据相关
sufficient：是否足以给出不编造的回答
missing_aspect：若不足，还缺什么
"""

GRADE_USER = """问题：{query}

证据：
{evidence}

输出 JSON：
{{"relevant":true,"sufficient":true,"missing_aspect":"","rationale":"..."}}
"""
