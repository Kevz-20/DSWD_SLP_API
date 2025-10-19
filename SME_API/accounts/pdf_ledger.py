from io import BytesIO
from datetime import datetime
from decimal import Decimal
from reportlab.pdfgen import canvas # type: ignore
from reportlab.lib.pagesizes import A4 # type: ignore
from reportlab.lib.units import mm # type: ignore
from reportlab.lib import colors # type: ignore
from reportlab.lib.colors import black # type: ignore

PAGE_W, PAGE_H = A4
LEFT   = 20 * mm
RIGHT  = PAGE_W - 15 * mm
TOP    = PAGE_H - 25 * mm
BOTTOM = 18 * mm

COLS = [
    ("Date",    28 * mm),
    ("Account", 60 * mm),
    ("Debit",   35 * mm),
    ("Credit",  35 * mm),
    ("Remarks", RIGHT - LEFT - (28+60+35+35) * mm),
]

ROW_H = 12
HDR_H = 16

def _fmt_money(v: Decimal | float | int):
    v = Decimal(v)
    if v == 0:
        return ""
    return f"₱{v:,.2f}"

def _draw_title(c: canvas.Canvas, title: str, subtitle: str, y: float) -> float:
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 18); c.drawString(LEFT, y, title); y -= 16
    c.setFont("Helvetica", 11);      c.drawString(LEFT, y, subtitle); y -= 10
    c.setLineWidth(1); c.line(LEFT, y, RIGHT, y); y -= 10
    return y

def _draw_table_header(c: canvas.Canvas, y: float) -> float:
    c.setFillColor(colors.HexColor("#F2F2F2"))
    c.rect(LEFT, y - HDR_H + 3, RIGHT - LEFT, HDR_H, stroke=0, fill=1)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 11)
    x = LEFT
    for name, width in COLS:
        c.drawString(x + 2, y, name)
        x += width
    y -= HDR_H
    c.setLineWidth(0.6)
    c.setStrokeColor(colors.HexColor("#C8CDD3"))
    c.line(LEFT, y + 2, RIGHT, y + 2)
    c.setStrokeColor(black)
    return y - 4

def _new_page(c: canvas.Canvas, title: str, subtitle: str) -> float:
    c.showPage()
    y = TOP
    y = _draw_title(c, title, subtitle, y)
    y = _draw_table_header(c, y)
    return y

def render_ledger_pdf(entries, title: str, subtitle: str) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle(title)
    c.setAuthor("SME"); c.setCreator("SME Server"); c.setSubject(title)

    y = TOP
    y = _draw_title(c, title, subtitle, y)
    y = _draw_table_header(c, y)

    total_debit  = Decimal("0")
    total_credit = Decimal("0")
    c.setFont("Helvetica", 10)

    for je in entries:
        memo_text = (je.memo or "").strip()
        for s in je.splits:
            if y < BOTTOM + ROW_H + 18:
                y = _new_page(c, title, subtitle)

            date_str   = je.when.strftime("%Y-%m-%d")
            account    = s.account_name or ""
            dc         = (getattr(s, "dc", "") or "").strip()
            amt        = Decimal(s.amount or 0)
            debit_val  = amt if dc == "Dr" else Decimal("0")
            credit_val = amt if dc == "Cr" else Decimal("0")
            remarks    = memo_text

            total_debit  += debit_val
            total_credit += credit_val

            x = LEFT
            c.drawString(x + 2, y, date_str); x += COLS[0][1]
            c.drawString(x + 2, y, account);  x += COLS[1][1]
            c.drawRightString(x - 2, y, _fmt_money(debit_val));  x += COLS[2][1]
            c.drawRightString(x - 2, y, _fmt_money(credit_val)); x += COLS[3][1]
            c.drawString(x + 2, y, (remarks or "")[:120])

            y -= ROW_H

    if y < BOTTOM + ROW_H + 18:
        y = _new_page(c, title, subtitle)

    c.setLineWidth(0.8)
    c.setStrokeColor(colors.HexColor("#C8CDD3"))
    c.line(LEFT, y + 4, RIGHT, y + 4)

    c.setFont("Helvetica-Bold", 11)
    x = LEFT + COLS[0][1] + COLS[1][1]
    c.drawRightString(x + COLS[2][1] - 2, y - 2, _fmt_money(total_debit))
    x += COLS[2][1]
    c.drawRightString(x + COLS[3][1] - 2, y - 2, _fmt_money(total_credit))

    c.setFillColor(black)
    c.setFont("Helvetica", 10)
    c.drawRightString(RIGHT, 12*mm, datetime.now().strftime("Generated %Y-%m-%d %H:%M"))

    # NOTE: do NOT call c.showPage() here; it would add a blank trailing page
    c.save()
    out = buf.getvalue()
    buf.close()
    return out
