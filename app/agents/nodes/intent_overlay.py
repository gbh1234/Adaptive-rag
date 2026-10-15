"""High-precision lexical overlay applied after the LLM intent classifier.

The LLM remains the primary classifier. Overlay only fires on phrases that
are stable in Chinese e-commerce CS and that historically confuse nearby labels
(handoff vs refund, policy vs return, coupon vs points FAQ).
"""

from __future__ import annotations

import re

from app.core.enums import IntentLabel

_GREETING_ONLY = re.compile(
    r"^(你好|您好|hi|hello|早上好|哈喽|哈喽客服)(，在吗|在吗)?[!！。.~]*$",
    re.IGNORECASE,
)

_HANDOFF = ("转人工", "人工客服", "接人工", "转接", "人工审核", "值班经理")
_JAILBREAK = ("ignore previous", "jailbreak", "系统提示词")
_OOS = ("股市", "写作业", "炸弹", "总统", "医疗诊断", "炒股", "造炸弹")
_COMPLAINT = ("投诉", "差评", "态度太差", "欺诈", "消协", "撒谎")
_LOGISTICS = ("物流", "快递", "运单", "到哪了", "催发货", "物流轨迹")
_REFUND_MONEY = ("退款", "到账", "原路返回", "退的钱", "的钱")
_RETURN = ("退货", "换货", "退货地址")
_CANCEL = ("取消订单", "不想要了", "怎么关", "能不能取消", "取消未发货")
_COUPON = ("优惠券", "满减", "新客券", "包邮券", "券")
_RECOMMEND = ("推荐", "有没有类似", "热销", "礼物", "基础款")
_PRODUCT_SPEC = ("参数", "纯棉", "头戴", "续航", "印照片", "库存", "有货吗")
_ORDER = ("订单", "支付成功", "有没有发货", "订单号")


def high_precision_intent(query: str) -> IntentLabel | None:
    """Return a label only when the rule is confident; otherwise None."""
    text = query.strip()
    if not text:
        return None
    lowered = text.lower()

    if any(token in lowered for token in _JAILBREAK) or any(token in text for token in _OOS):
        return IntentLabel.OUT_OF_SCOPE
    if any(token in text for token in _HANDOFF):
        return IntentLabel.HUMAN_HANDOFF
    if _GREETING_ONLY.match(text) or _GREETING_ONLY.match(lowered):
        return IntentLabel.GREETING
    if (
        text in {"今天天气真好", "你是机器人吗", "讲个笑话", "你叫什么名字", "在忙什么"}
        or "吃什么" in text
    ):
        return IntentLabel.CHITCHAT
    if any(token in text for token in _COMPLAINT):
        return IntentLabel.COMPLAINT
    if "催发货" in text or "运单号" in text or "物流轨迹" in text or "物流停滞" in text:
        return IntentLabel.LOGISTICS
    if text.startswith("SF") or "到哪了" in text or ("快递" in text and "投诉" not in text):
        return IntentLabel.LOGISTICS
    if "什么时候能送到" in text:
        return IntentLabel.LOGISTICS
    if "取消" in text or any(token in text for token in _CANCEL):
        return IntentLabel.CANCEL_ORDER
    if "预售什么时候发货" in text:
        return IntentLabel.FAQ_POLICY
    if "积分怎么用" in text:
        return IntentLabel.FAQ_POLICY
    if "积分能抵" in text or any(
        token in text for token in ("优惠券", "NEW10", "新客券", "包邮券")
    ):
        return IntentLabel.COUPON
    if "满减和包邮" in text:
        return IntentLabel.COUPON
    if "怎么算" in text or "运费谁出" in text or "拆封了还能退吗" in text:
        return IntentLabel.FAQ_POLICY
    if any(
        token in text
        for token in (
            "开发票",
            "电子发票",
            "花呗",
            "客服工作时间",
            "保修多久",
            "满59",
            "偏远地区",
            "新疆包邮",
            "签收后怎么验货",
            "人为损坏",
            "进水能修",
        )
    ):
        return IntentLabel.FAQ_POLICY
    if (
        "质量问题怎么退款" in text
        or "退款什么时候" in text
        or "申请退款" in text
        or "退款进度" in text
    ):
        return IntentLabel.REFUND
    if "原路返回" in text or "要退" in text and "钱" in text:
        return IntentLabel.REFUND
    if (
        any(token in text for token in _RETURN)
        or "还能退吗" in text
        or "能退货吗" in text
        or "七天无理由吗" in text
    ):
        return IntentLabel.RETURN_EXCHANGE
    if any(token in text for token in _RECOMMEND):
        return IntentLabel.RECOMMENDATION
    if any(token in text for token in _PRODUCT_SPEC) or text.startswith("SKU-"):
        return IntentLabel.PRODUCT_CONSULT
    if "降噪耳机是" in text or "T恤是" in text or "定制杯可以" in text or "这款耳机" in text:
        return IntentLabel.PRODUCT_CONSULT
    if any(token in text for token in _ORDER) or "ORD" in text:
        if any(token in text for token in ("物流", "快递", "运单", "轨迹")):
            return IntentLabel.LOGISTICS
        return IntentLabel.ORDER_INQUIRY
    if "送到了吗" in text:
        return IntentLabel.ORDER_INQUIRY
    return None


def apply_intent_overlay(query: str, label: IntentLabel) -> tuple[IntentLabel, str | None]:
    forced = high_precision_intent(query)
    if forced is None or forced == label:
        return label, None
    return forced, f"overlay:{forced.value}"
