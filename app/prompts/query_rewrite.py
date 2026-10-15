"""Query rewrite prompt."""

REWRITE_SYSTEM = """你改写电商检索查询。只输出 JSON。
生成 1-3 条更适合检索的短查询，保留关键约束（时效、品类、是否定制、是否质量问题）。
"""

REWRITE_USER = """原始问题：{query}
仍缺少的信息：{missing_aspect}

输出 JSON：
{{"queries":["..."]}}
"""
