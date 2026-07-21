"""Render a compact A6 Delhivery shipping label directly from Delhivery's own documented
packing-slip JSON (GET /api/p/packing_slip?wbns=<AWB>, no pdf=True) - no A4 PDF is fetched,
cropped, or transformed. See DelhiveryService.label_data() for the fetch side.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.graphics.barcode.code128 import Code128
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# True A6 (105mm x 148mm), matching the Delhivery One portal's own compact label - not the
# literal 4x6in (288x432pt) size, per the desired portal output (~298x420pt).
PAGE_WIDTH = 298.0
PAGE_HEIGHT = 420.0
MARGIN = 10.0
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

# Fields the renderer cannot produce a usable label without. Everything else on the label is
# optional and simply omitted/blanked when absent - see _line()/_block() below.
#
# Note: Delhivery's "barcode" field is NOT a short scannable value - inspecting a real response
# showed it is a ~5,600 character string (almost certainly base64 image data for Delhivery's own
# pre-rendered barcode graphic, matching their FAQ wording "rendered ... using encoding 128").
# Feeding that into a Code128 encoder produces thousands of sub-pixel bars that rasterize as a
# solid black smear, not a scannable barcode. We deliberately do NOT read/encode "barcode" at
# all; the AWB ("wbn") is what actually gets Code128-encoded, which is the standard convention
# on every physical courier label and is exactly what's meant to be scanned.
_MANDATORY_FIELDS = ("wbn", "name", "address", "pin")

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


class DelhiveryLabelError(RuntimeError):
    """Raised when the packing-slip JSON can't be turned into a usable label."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"none", "null", "nan"} else text


def _truncate_to_width(text: str, font: str, size: float, max_width: float) -> str:
    if stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = "…"
    while text and stringWidth(text + ellipsis, font, size) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _wrap_lines(text: str, font: str, size: float, max_width: float, max_lines: int) -> list[str]:
    """Word-wrap text to max_width; a single word wider than max_width is character-truncated
    with an ellipsis rather than overflowing the page. Excess lines are dropped with a trailing
    ellipsis on the last kept line, never silently losing the fact that content was cut."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = _truncate_to_width(word, font, size, max_width) if stringWidth(word, font, size) > max_width else word
    if current:
        lines.append(current)
    if not lines:
        return []
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _truncate_to_width(lines[-1].rstrip("…") + "…", font, size, max_width)
    return lines


class _LabelCanvas:
    """Thin top-down cursor over reportlab's bottom-left-origin canvas."""

    def __init__(self, pdf: canvas.Canvas) -> None:
        self.pdf = pdf
        self.y = PAGE_HEIGHT - MARGIN

    def gap(self, amount: float) -> None:
        self.y -= amount

    def rule(self) -> None:
        self.pdf.setLineWidth(0.75)
        self.pdf.line(MARGIN, self.y, PAGE_WIDTH - MARGIN, self.y)
        self.gap(6)

    def line(self, text: str, *, font: str = _FONT, size: float = 8, x: float | None = None, gap_after: float = 10) -> None:
        if not text:
            return
        self.pdf.setFont(font, size)
        self.pdf.drawString(MARGIN if x is None else x, self.y - size, _truncate_to_width(text, font, size, CONTENT_WIDTH))
        self.gap(gap_after)

    def two_col(self, left: str, right: str, *, font: str = _FONT_BOLD, size: float = 9, gap_after: float = 12) -> None:
        if not left and not right:
            return
        self.pdf.setFont(font, size)
        if left:
            self.pdf.drawString(MARGIN, self.y - size, _truncate_to_width(left, font, size, CONTENT_WIDTH * 0.6))
        if right:
            self.pdf.drawRightString(PAGE_WIDTH - MARGIN, self.y - size, _truncate_to_width(right, font, size, CONTENT_WIDTH * 0.4))
        self.gap(gap_after)

    def block(self, text: str, *, font: str = _FONT, size: float = 7.5, max_lines: int = 4, leading: float = 9, gap_after: float = 4) -> None:
        for wrapped in _wrap_lines(text, font, size, CONTENT_WIDTH, max_lines):
            self.pdf.setFont(font, size)
            self.pdf.drawString(MARGIN, self.y - size, wrapped)
            self.gap(leading)
        self.gap(gap_after)


def render_delhivery_label(data: dict[str, Any], order: Any | None = None) -> bytes:
    """Draw one A6 (298x420pt) label page from a single Delhivery packing-slip "packages[0]"
    record, enriched with the matching Mumchies OS/Shopify order (product price, order total,
    order date, partial-COD-aware collectable amount) where Delhivery's JSON doesn't provide
    them. `order` is best-effort: if it's None (lookup failed/unavailable) the label still
    renders from Delhivery's own fields alone - those extra lines are simply omitted, never
    guessed. Raises DelhiveryLabelError if mandatory fields (AWB, consignee name/address,
    pincode) are missing rather than emit a broken/blank label."""
    if not isinstance(data, dict):
        raise DelhiveryLabelError("Delhivery label data is malformed.")
    missing = [field for field in _MANDATORY_FIELDS if not _text(data.get(field))]
    if missing:
        raise DelhiveryLabelError(f"Delhivery label data is missing required field(s): {', '.join(missing)}.")

    awb = _text(data.get("wbn"))
    seller_name = "Mumchies"
    seller_address = _text(data.get("sadd"))
    consignee_name = _text(data.get("name"))
    consignee_address = _text(data.get("address"))
    consignee_city = _text(data.get("destination_city"))
    consignee_state = _text(data.get("customer_state")) or _text(data.get("st"))
    pin = _text(data.get("pin"))
    phone = _text(data.get("contact"))
    sort_code = _text(data.get("sort_code"))
    destination = _text(data.get("destination"))
    return_address = _text(data.get("radd"))
    return_city = _text(data.get("rcty"))
    return_state = _text(data.get("rst"))
    return_pin = _text(data.get("rpin"))
    hsn_code = _text(data.get("hsn_code"))
    order_ref = _text(data.get("oid")) or (_text(getattr(order, "order_number", None)) if order is not None else "")

    # Payment mode / collectable amount: prefer Mumchies OS's own partial-COD-aware order data;
    # fall back to Delhivery's own field only when no matching order was found.
    order_payment_type = _text(getattr(order, "payment_type", None)) if order is not None else ""
    if order_payment_type in {"cod", "partial_cod"}:
        payment_type = "COD"
        cod_amount = _text(getattr(order, "cod_collectable_amount", None))
    elif order_payment_type == "prepaid":
        payment_type, cod_amount = "PREPAID", ""
    else:
        payment_type = _text(data.get("pt")).upper()
        cod_amount = _text(data.get("cod")) if payment_type == "COD" else ""

    # Product/quantity/price: prefer the structured Shopify line items (they carry price, which
    # Delhivery's JSON doesn't); fall back to Delhivery's own opaque description/qty strings.
    products = list(getattr(order, "products", None) or []) if order is not None else []
    fallback_product = _text(data.get("prd"))
    fallback_qty = _text(data.get("qty"))
    order_total = _text(getattr(order, "order_total", None)) if order is not None else ""
    order_date = ""
    created = getattr(order, "created_date", None) if order is not None else None
    if created:
        try:
            order_date = datetime.fromisoformat(str(created).replace("Z", "+00:00")).strftime("%d %b %Y")
        except ValueError:
            order_date = _text(created)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c = _LabelCanvas(pdf)

    # Header: seller name (Mumchies branding) + Delhivery wordmark.
    c.two_col(seller_name, "Delhivery", font=_FONT_BOLD, size=10, gap_after=10)
    c.rule()

    # Sort/destination code - large, since it drives manual sorting at the hub.
    if sort_code or destination:
        pdf.setFont(_FONT_BOLD, 20)
        pdf.drawString(MARGIN, c.y - 20, _truncate_to_width(sort_code or "—", _FONT_BOLD, 20, CONTENT_WIDTH * 0.55))
        if destination:
            pdf.setFont(_FONT, 8)
            pdf.drawRightString(PAGE_WIDTH - MARGIN, c.y - 8, _truncate_to_width(destination, _FONT, 8, CONTENT_WIDTH * 0.4))
        c.gap(26)

    # Payment mode / COD amount - kept prominent and unambiguous.
    if payment_type == "COD" and cod_amount:
        c.two_col(f"COD: Rs {cod_amount}", "", font=_FONT_BOLD, size=12, gap_after=14)
    elif payment_type:
        c.two_col(payment_type, "", font=_FONT_BOLD, size=12, gap_after=14)

    # AWB barcode (Code128), centred, with the human-readable AWB directly beneath it.
    # barWidth is fit to the AWB's length but floored so bars stay individually visible even
    # for an unexpectedly long AWB, rather than collapsing into an unscannable smear.
    bar_width = max(0.4, min(1.1, (CONTENT_WIDTH - 4) / max(len(awb) * 11, 1)))
    barcode = Code128(awb, barHeight=46, barWidth=bar_width)
    barcode_x = MARGIN + max((CONTENT_WIDTH - barcode.width) / 2, 0)
    barcode.drawOn(pdf, barcode_x, c.y - 46)
    c.gap(50)
    c.line(f"AWB: {awb}", font=_FONT_BOLD, size=10, gap_after=14)
    c.rule()

    # Consignee.
    c.line("TO", font=_FONT_BOLD, size=7, gap_after=9)
    c.line(consignee_name, font=_FONT_BOLD, size=10, gap_after=11)
    c.block(consignee_address, size=8, max_lines=4, leading=10, gap_after=2)
    locality = ", ".join(part for part in (consignee_city, consignee_state, pin) if part)
    c.line(locality, size=8, gap_after=10)
    if phone:
        c.line(f"Ph: {phone}", size=8, gap_after=12)
    c.rule()

    # Product details - structured (with price) when we have the matching order, else Delhivery's
    # own opaque description/qty strings.
    if products:
        c.line("PRODUCT", font=_FONT_BOLD, size=7, gap_after=9)
        for item in products[:3]:
            name = _text(getattr(item, "product_name", None))
            item_qty = _text(getattr(item, "quantity", None))
            item_price = _text(getattr(item, "price", None))
            if not name:
                continue
            suffix = f" x{item_qty}" if item_qty else ""
            suffix += f" - Rs {item_price}" if item_price else ""
            c.block(f"{name}{suffix}", size=8, max_lines=1, leading=10, gap_after=1)
        if len(products) > 3:
            c.line(f"+{len(products) - 3} more item(s)", size=7, gap_after=4)
    elif fallback_product:
        c.line("PRODUCT", font=_FONT_BOLD, size=7, gap_after=9)
        c.block(fallback_product, size=8, max_lines=2, leading=10, gap_after=2)
        if fallback_qty:
            c.line(f"Qty: {fallback_qty}", size=8, gap_after=6)
    if order_total:
        c.line(f"Order Total: Rs {order_total}", font=_FONT_BOLD, size=8, gap_after=8)
    if hsn_code:
        c.line(f"HSN: {hsn_code}", size=6.5, gap_after=8)
    c.rule()

    # Seller + return address, compact footer.
    c.line("SELLER", font=_FONT_BOLD, size=6.5, gap_after=8)
    c.block(f"{seller_name}, {seller_address}" if seller_address else seller_name, size=6.5, max_lines=2, leading=8, gap_after=4)

    c.line("RETURN ADDRESS", font=_FONT_BOLD, size=6.5, gap_after=8)
    return_locality = ", ".join(part for part in (return_city, return_state, return_pin) if part)
    return_text = ", ".join(part for part in (return_address, return_locality) if part)
    c.block(return_text or "Same as seller", size=6.5, max_lines=2, leading=8, gap_after=2)

    if order_ref:
        c.line(f"Order Ref: {order_ref}", size=7, gap_after=6)
    if order_date:
        c.line(f"Order Date: {order_date}", size=7, gap_after=8)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
