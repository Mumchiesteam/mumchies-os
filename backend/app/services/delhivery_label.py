"""Render a native 100x150mm Delhivery shipping label from Delhivery's documented
packing-slip JSON (GET /api/p/packing_slip?wbns=<AWB>, no pdf=True) - no A4 PDF is fetched,
cropped, or transformed. See DelhiveryService.label_data() for the fetch side.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.graphics.barcode.code128 import Code128
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# Exact TSC TE244 stock size. ReportLab uses PostScript points, so retaining the millimetre
# conversion makes Actual Size printing 100mm x 150mm rather than rounded A6 or 4x6 inches.
PAGE_WIDTH = 100 * mm
PAGE_HEIGHT = 150 * mm
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
_DELHIVERY_WORDMARK = Path(__file__).resolve().parent.parent / "assets" / "delhivery_wordmark.png"


class DelhiveryLabelError(RuntimeError):
    """Raised when the packing-slip JSON can't be turned into a usable label."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"none", "null", "nan"} else text


def _money(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _money_text(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        return _money(Decimal(text))
    except InvalidOperation:
        return text


def _weight_text(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        return f"{_money(Decimal(text))} g"
    except InvalidOperation:
        parts = text.split(maxsplit=1)
        try:
            number = _money(Decimal(parts[0]))
        except InvalidOperation:
            return text
        return f"{number} {parts[1]}" if len(parts) == 2 else number


def _discounted_product_rows(products: list[Any], order_total: Any) -> list[dict[str, str]]:
    """Allocate the authoritative post-discount order total across displayed line items.

    Shopify's line-item ``price`` is pre-order-discount in the current read model. Printing it
    beside the post-discount order total is misleading, so allocation is proportional to each
    line's gross value and the final row absorbs any paise rounding remainder.
    """
    source: list[tuple[str, Decimal, Decimal]] = []
    for item in products[:4]:
        name = _text(getattr(item, "product_name", None))
        if not name:
            continue
        try:
            qty = Decimal(_text(getattr(item, "quantity", None)) or "1")
            unit = Decimal(_text(getattr(item, "price", None)) or "0")
        except InvalidOperation:
            qty, unit = Decimal("1"), Decimal("0")
        source.append((name, qty, unit))
    if not source:
        return []
    try:
        payable = Decimal(_text(order_total))
    except InvalidOperation:
        payable = sum((qty * unit for _, qty, unit in source), Decimal("0"))
    gross = sum((qty * unit for _, qty, unit in source), Decimal("0"))
    remaining = payable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rows: list[dict[str, str]] = []
    for index, (name, qty, unit) in enumerate(source):
        if index == len(source) - 1:
            line_total = remaining
        elif gross:
            line_total = (payable * qty * unit / gross).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            remaining -= line_total
        else:
            line_total = Decimal("0")
        discounted_unit = line_total / qty if qty else line_total
        rows.append({
            "name": name,
            "qty": _money(qty),
            "price": f"Rs {_money(discounted_unit)}",
            "total": f"Rs {_money(line_total)}",
        })
    return rows


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


def _render_hierarchical_label(fields: dict[str, Any]) -> bytes:
    """Render a dense thermal layout using only already-normalized authoritative fields."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    left, right = MARGIN, PAGE_WIDTH - MARGIN
    width = right - left

    def rule(y: float, weight: float = 0.7) -> None:
        pdf.setLineWidth(weight)
        pdf.line(left, y, right, y)

    def wrapped(text: str, x: float, y: float, max_width: float, *, size: float = 7.2,
                font: str = _FONT, max_lines: int = 3, leading: float = 8.3) -> float:
        for line in _wrap_lines(text, font, size, max_width, max_lines):
            pdf.setFont(font, size)
            pdf.drawString(x, y, line)
            y -= leading
        return y

    awb, pin = fields["awb"], fields["pin"]
    y = PAGE_HEIGHT - MARGIN
    pdf.setFont(_FONT_BOLD, 11)
    pdf.drawString(left, y - 10, "Mumchies")
    pdf.setFont(_FONT_BOLD, 10)
    pdf.drawRightString(right, y - 10, "DELHIVERY")
    y -= 15
    rule(y, 1)
    y -= 11
    pdf.setFont(_FONT_BOLD, 10)
    pdf.drawString(left, y, f"AWB {awb}")
    quiet_width = width - 16
    barcode = Code128(awb, barHeight=42, barWidth=max(0.45, min(1.15, quiet_width / max(len(awb) * 11, 1))))
    barcode.drawOn(pdf, left + 8 + max((quiet_width - barcode.width) / 2, 0), y - 48)
    y -= 53
    rule(y, 1)

    y -= 6
    pdf.setFont(_FONT_BOLD, 17)
    pdf.drawString(left, y - 12, f"PIN {pin}")
    pdf.setFont(_FONT_BOLD, 8)
    pdf.drawRightString(right, y - 4, _truncate_to_width(fields["destination"], _FONT_BOLD, 8, width * 0.42))
    pdf.setFont(_FONT, 7)
    pdf.drawRightString(right, y - 15, _truncate_to_width(f"Sort: {fields['sort_code']}" if fields["sort_code"] else "", _FONT, 7, width * 0.42))
    y -= 23
    rule(y)

    block_top, split = y, left + width * 0.66
    block_bottom = block_top - 101
    pdf.line(split, block_top, split, block_bottom)
    pdf.setFont(_FONT_BOLD, 7)
    pdf.drawString(left + 3, block_top - 10, "SHIP TO")
    pdf.setFont(_FONT_BOLD, 9)
    pdf.drawString(left + 3, block_top - 22, _truncate_to_width(fields["name"], _FONT_BOLD, 9, split - left - 7))
    address_y = wrapped(fields["address"], left + 3, block_top - 33, split - left - 7, size=7.4, max_lines=4, leading=8.5)
    address_y = wrapped(fields["locality"], left + 3, address_y - 1, split - left - 7, size=7, max_lines=2, leading=8)
    pdf.setFont(_FONT_BOLD, 10)
    pdf.drawString(left + 3, max(block_bottom + 14, address_y - 3), pin)
    if fields["phone"]:
        pdf.setFont(_FONT, 6.5)
        pdf.drawString(left + 3, block_bottom + 4, _truncate_to_width(f"Ph: {fields['phone']}", _FONT, 6.5, split - left - 7))

    rx = split + 4
    pdf.setFont(_FONT_BOLD, 13)
    pdf.drawString(rx, block_top - 16, fields["payment_type"] or "-")
    if fields["payment_type"] == "COD" and fields["cod_amount"]:
        pdf.setFont(_FONT_BOLD, 10)
        pdf.drawString(rx, block_top - 31, _truncate_to_width(f"COD: Rs {fields['cod_amount']}", _FONT_BOLD, 10, right - rx))
    pdf.setFont(_FONT_BOLD, 6.5)
    pdf.drawString(rx, block_top - 48, "SERVICE")
    pdf.setFont(_FONT, 7)
    pdf.drawString(rx, block_top - 58, _truncate_to_width(fields["service_mode"] or "-", _FONT, 7, right - rx))
    if fields["order_date"]:
        pdf.setFont(_FONT_BOLD, 6.5)
        pdf.drawString(rx, block_top - 75, "ORDER DATE")
        pdf.setFont(_FONT, 6.5)
        pdf.drawString(rx, block_top - 85, _truncate_to_width(f"Order Date: {fields['order_date']}", _FONT, 6.5, right - rx))
    y = block_bottom
    rule(y)

    seller_bottom = y - 64
    pdf.setFont(_FONT_BOLD, 6.5)
    pdf.drawString(left + 3, y - 10, "SELLER / PICKUP")
    wrapped(fields["seller"], left + 3, y - 20, width * 0.54, size=6.5, max_lines=3, leading=7.4)
    order_ref = fields["order_ref"]
    if order_ref:
        ox = left + width * 0.57
        pdf.setFont(_FONT_BOLD, 7.5)
        pdf.drawString(ox, y - 11, _truncate_to_width(f"ORDER {order_ref}", _FONT_BOLD, 7.5, right - ox))
        order_width = right - ox - 8
        order_barcode = Code128(order_ref, barHeight=23, barWidth=max(0.4, min(0.75, order_width / max(len(order_ref) * 11, 1))))
        order_barcode.drawOn(pdf, ox + 4 + max((order_width - order_barcode.width) / 2, 0), y - 42)
    y = seller_bottom
    rule(y)

    product_bottom = y - 55
    pdf.setFont(_FONT_BOLD, 6.5)
    pdf.drawString(left + 3, y - 10, "CONTENTS")
    py = y - 20
    for product in fields["product_lines"][:2]:
        py = wrapped(product, left + 3, py, width - 6, size=7, max_lines=1, leading=9)
    if fields["summary"]:
        pdf.setFont(_FONT_BOLD, 6.5)
        pdf.drawString(left + 3, product_bottom + 5, _truncate_to_width(fields["summary"], _FONT_BOLD, 6.5, width - 6))
    y = product_bottom
    rule(y)

    pdf.setFont(_FONT_BOLD, 6.5)
    pdf.drawString(left + 3, y - 10, "RETURN TO")
    wrapped(fields["return_text"], left + 3, y - 20, width - 6, size=6.2, max_lines=3, leading=7)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _render_portal_reference_label(fields: dict[str, Any]) -> bytes:
    """Reproduce Delhivery One's A6 information architecture on exact 100x150mm stock."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    edge = 7.0
    left, right, bottom, top = edge, PAGE_WIDTH - edge, edge, PAGE_HEIGHT - edge
    width = right - left
    split = left + width * 0.60

    def rule(y: float, x1: float = left, x2: float = right, weight: float = 0.75) -> None:
        pdf.setLineWidth(weight)
        pdf.line(x1, y, x2, y)

    def wrapped(text: str, x: float, y: float, max_width: float, *, size: float = 7,
                font: str = _FONT, max_lines: int = 3, leading: float = 8.2) -> float:
        for line in _wrap_lines(text, font, size, max_width, max_lines):
            pdf.setFont(font, size)
            pdf.drawString(x, y, line)
            y -= leading
        return y

    pdf.setLineWidth(1.05)
    pdf.rect(left, bottom, width, top - bottom, stroke=1, fill=0)

    # Portal header.
    header_bottom = top - 36
    pdf.setFont(_FONT, 9)
    pdf.drawString(left + 4, top - 20, _truncate_to_width(fields["seller_name"], _FONT, 9, width * 0.48))
    logo_width = 78.0
    logo_height = logo_width * 217 / 1398
    pdf.drawImage(
        ImageReader(_DELHIVERY_WORDMARK), right - 4 - logo_width, top - 9 - logo_height,
        width=logo_width, height=logo_height, preserveAspectRatio=True, mask="auto",
    )
    rule(header_bottom, left + 4, right - 4, 0.65)

    # AWB block: text, dominant barcode, then PIN / human-readable AWB / sort code routing row.
    awb_bottom = header_bottom - 78
    pdf.setFont(_FONT, 9)
    pdf.drawString(left + 4, header_bottom - 15, f"AWB# {fields['awb']}")
    barcode_area_width = width - 66
    barcode = Code128(
        fields["awb"], barHeight=39,
        barWidth=max(0.45, min(1.18, 1.125 * (barcode_area_width - 20) / max(len(fields["awb"]) * 11, 1))),
    )
    # Ten-point quiet zones on both sides of the centred scan target.
    barcode_x = left + 33 + max((barcode_area_width - barcode.width) / 2, 0)
    barcode.drawOn(pdf, barcode_x, header_bottom - 60)
    pdf.setFont(_FONT, 6.5)
    pdf.drawString(left + 4, awb_bottom + 5, fields["pin"])
    pdf.setFont(_FONT_BOLD, 6.5)
    pdf.drawCentredString((left + right) / 2, awb_bottom + 5, f"AWB# {fields['awb']}")
    pdf.setFont(_FONT, 6.5)
    pdf.drawRightString(right - 4, awb_bottom + 5, _truncate_to_width(fields["sort_code"], _FONT, 6.5, width * 0.24))
    rule(awb_bottom, left + 4, right - 4, 0.65)

    # Ship-to and payment/date block with the same approximate 60/40 portal split.
    address_bottom = awb_bottom - 83
    pdf.line(split, awb_bottom - 4, split, address_bottom + 5)
    x = left + 4
    pdf.setFont(_FONT, 9)
    pdf.drawString(x, awb_bottom - 17, "Ship to -")
    pdf.setFont(_FONT_BOLD, 9)
    pdf.drawString(x + 34, awb_bottom - 17, _truncate_to_width(fields["name"], _FONT_BOLD, 9, split - x - 38))
    ay = wrapped(fields["address"], x, awb_bottom - 29, split - x - 4, size=7, max_lines=3, leading=8)
    ay = wrapped(fields["destination"], x, ay - 1, split - x - 4, size=8.2, font=_FONT_BOLD, max_lines=2, leading=9.5)
    pdf.setFont(_FONT_BOLD, 9.5)
    pdf.drawString(x, max(address_bottom + 10, ay - 1), f"PIN - {fields['pin']}")

    rx = split + 4
    payment_heading = fields["payment_type"]
    if fields["service_mode"]:
        payment_heading = f"{payment_heading} - {fields['service_mode']}" if payment_heading else fields["service_mode"]
    pdf.setFont(_FONT_BOLD, 7.5)
    pdf.drawString(rx, awb_bottom - 29, _truncate_to_width(payment_heading, _FONT_BOLD, 7.5, right - rx - 4))
    amount = fields["cod_amount"] or fields["order_total"]
    if amount:
        pdf.setFont(_FONT_BOLD, 9)
        pdf.drawString(rx, awb_bottom - 43, _truncate_to_width(f"INR {amount}", _FONT_BOLD, 9, right - rx - 4))
    rule(awb_bottom - 49, rx, right - 4, 0.55)
    if fields["order_date"]:
        pdf.setFont(_FONT_BOLD, 6.5)
        pdf.drawString(rx, awb_bottom - 61, "Date")
        pdf.setFont(_FONT, 6.2)
        pdf.drawString(rx, awb_bottom - 71, _truncate_to_width(fields["order_date"], _FONT, 6.2, right - rx - 4))
    rule(address_bottom, left + 4, right - 4, 0.65)

    # Seller and order reference barcode row.
    seller_bottom = address_bottom - 51
    pdf.setFont(_FONT, 6.8)
    pdf.drawString(left + 4, address_bottom - 16, "Seller:")
    pdf.setFont(_FONT_BOLD, 6.8)
    pdf.drawString(left + 31, address_bottom - 16, _truncate_to_width(fields["seller_name"], _FONT_BOLD, 6.8, split - left - 35))
    wrapped(fields["seller_address"], left + 4, address_bottom - 28, split - left - 8, size=6.3, max_lines=3, leading=7.2)
    if fields["order_ref"]:
        pdf.setFont(_FONT, 9)
        pdf.drawString(split + 2, address_bottom - 15, _truncate_to_width(fields["order_ref"], _FONT, 9, right - split - 6))
        order_width = right - split - 8
        order_barcode = Code128(
            fields["order_ref"], barHeight=25,
            barWidth=max(0.4, min(0.91, 1.075 * (order_width - 16) / max(len(fields["order_ref"]) * 11, 1))),
        )
        # ReportLab's Code128 retains its built-in quiet zones around the larger symbol.
        order_barcode.drawOn(pdf, split + 4 + max((order_width - order_barcode.width) / 2, 0), address_bottom - 44)
    rule(seller_bottom, left + 4, right - 4, 0.65)

    # Portal-style product table, followed by deliberate flexible whitespace for long products.
    product_top = seller_bottom
    pdf.setFont(_FONT_BOLD, 6.3)
    pdf.drawString(left + 4, product_top - 12, "Product Name")
    pdf.drawRightString(right - 69, product_top - 12, "Qty.")
    pdf.drawRightString(right - 36, product_top - 12, "Price")
    pdf.drawRightString(right - 4, product_top - 12, "Total")
    py = product_top - 23
    for product in fields["products"][:4]:
        py = wrapped(product["name"], left + 4, py, width - 96, size=6.2, max_lines=2, leading=7.2)
        pdf.setFont(_FONT, 6.2)
        pdf.drawRightString(right - 69, py + 7.2, product["qty"])
        pdf.drawRightString(right - 36, py + 7.2, product["price"])
        pdf.drawRightString(right - 4, py + 7.2, product["total"])

    # Compact return footer, fixed to the bottom like Delhivery One.
    footer_top = bottom + 24
    summary = "   ".join(part for part in (
        f"Order Total: Rs {fields['order_total']}" if fields["order_total"] else "",
        f"Weight: {fields['weight']}" if fields["weight"] else "",
        f"HSN: {fields['hsn_code']}" if fields["hsn_code"] else "",
    ) if part)
    if summary:
        pdf.setFont(_FONT_BOLD, 5.8)
        pdf.drawString(left + 4, footer_top + 7, _truncate_to_width(summary, _FONT_BOLD, 5.8, width - 8))
    rule(footer_top, left + 4, right - 4, 0.65)
    pdf.setFont(_FONT, 5.8)
    return_text = f"Return Address: {fields['return_text']}"
    wrapped(return_text, left + 4, footer_top - 9, width - 45, size=5.2, max_lines=2, leading=6)
    pdf.drawRightString(right - 4, bottom + 4, "Page 1 of 1")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def render_delhivery_label(data: dict[str, Any], order: Any | None = None, booked_at: Any | None = None) -> bytes:
    """Draw one exact 100x150mm label page from a Delhivery packing-slip "packages[0]"
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
    seller_name = _text(data.get("snm")) or "Mumchies"
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
    weight = _weight_text(data.get("weight") if data.get("weight") is not None else data.get("wt"))
    order_ref = _text(data.get("oid")) or (_text(getattr(order, "order_number", None)) if order is not None else "")

    # Payment mode / collectable amount: prefer Mumchies OS's own partial-COD-aware order data;
    # fall back to Delhivery's own field only when no matching order was found.
    order_payment_type = _text(getattr(order, "payment_type", None)) if order is not None else ""
    if order_payment_type in {"cod", "partial_cod"}:
        payment_type = "COD"
        cod_amount = _money_text(getattr(order, "cod_collectable_amount", None))
    elif order_payment_type == "prepaid":
        payment_type, cod_amount = "PREPAID", ""
    else:
        payment_type = _text(data.get("pt")).upper()
        cod_amount = _money_text(data.get("cod")) if payment_type == "COD" else ""

    # Product/quantity/price: prefer the structured Shopify line items (they carry price, which
    # Delhivery's JSON doesn't); fall back to Delhivery's own opaque description/qty strings.
    products = list(getattr(order, "products", None) or []) if order is not None else []
    fallback_product = _text(data.get("prd"))
    fallback_qty = _text(data.get("qty"))
    order_total = _money_text(getattr(order, "order_total", None)) if order is not None else ""
    order_date = ""
    authoritative_date = booked_at or (getattr(order, "created_date", None) if order is not None else None)
    if authoritative_date:
        try:
            parsed = authoritative_date if isinstance(authoritative_date, datetime) else datetime.fromisoformat(str(authoritative_date).replace("Z", "+00:00"))
            order_date = parsed.strftime("%d %b %Y | %I:%M %p")
        except (TypeError, ValueError):
            order_date = _text(authoritative_date)
    elif data.get("cd"):
        raw_date = _text(data.get("cd"))
        try:
            order_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).strftime("%d-%b-%Y | %I:%M %p")
        except ValueError:
            order_date = raw_date

    product_lines: list[str] = []
    if products:
        for item in products[:2]:
            name = _text(getattr(item, "product_name", None))
            qty = _text(getattr(item, "quantity", None))
            price = _text(getattr(item, "price", None))
            if name:
                product_lines.append(f"{name} | Qty: {qty or '-'}" + (f" | Rs {price}" if price else ""))
    elif fallback_product:
        product_lines.append(f"{fallback_product} | Qty: {fallback_qty or '-'}")
    summary = "   ".join(part for part in (
        f"Order Total: Rs {order_total}" if order_total else "",
        f"Weight: {weight}" if weight else "",
        f"HSN: {hsn_code}" if hsn_code else "",
    ) if part)
    return_locality = ", ".join(part for part in (return_city, return_state, return_pin) if part)
    return_text = ", ".join(part for part in (return_address, return_locality) if part) or "Same as seller"
    product_rows: list[dict[str, str]] = []
    if products:
        product_rows = _discounted_product_rows(products, order_total)
    elif fallback_product:
        product_rows.append({"name": fallback_product, "qty": fallback_qty or "-", "price": "-", "total": "-"})
    service_mode = _text(data.get("mot")) or _text(data.get("service_type")) or _text(data.get("mode"))
    service_mode = {"s": "Surface", "e": "Express"}.get(service_mode.casefold(), service_mode)
    return _render_portal_reference_label({
        "awb": awb, "pin": pin, "destination": destination or consignee_city,
        "sort_code": sort_code, "name": consignee_name, "address": consignee_address,
        "payment_type": payment_type.upper() if payment_type else "", "cod_amount": cod_amount,
        "service_mode": service_mode,
        "order_date": order_date, "seller_name": seller_name, "seller_address": seller_address,
        "order_ref": order_ref, "products": product_rows, "order_total": order_total,
        "weight": weight, "hsn_code": hsn_code, "return_text": return_text,
    })

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
    if weight:
        c.line(f"Weight: {weight}", size=7, gap_after=7)
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
        c.line(f"Order Ref: {order_ref}", font=_FONT_BOLD, size=7, gap_after=6)
        order_barcode = Code128(order_ref, barHeight=16, barWidth=max(0.35, min(0.7, (CONTENT_WIDTH - 4) / max(len(order_ref) * 11, 1))))
        order_barcode.drawOn(pdf, MARGIN + max((CONTENT_WIDTH - order_barcode.width) / 2, 0), c.y - 16)
        c.gap(19)
    if order_date:
        c.line(f"Order Date: {order_date}", size=7, gap_after=8)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
