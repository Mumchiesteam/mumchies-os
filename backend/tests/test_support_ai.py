from app.services.support_ai import answer_support_message


def test_product_sugar_answer():
    result = answer_support_message("Does dry fruit laddu have sugar?")
    assert result["needs_human"] is False
    assert "naturally occurring" in result["reply"]


def test_order_requires_verification():
    result = answer_support_message("Where is my order?")
    assert result["needs_human"] is True
    assert "after verification" in result["reply"]


def test_refund_escalates():
    assert answer_support_message("Refund my damaged pack")["needs_human"] is True


def test_unknown_escalates():
    assert answer_support_message("What is your MOQ?")["needs_human"] is True
