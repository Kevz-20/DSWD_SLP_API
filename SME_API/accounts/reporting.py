from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, date, time as dt_time
from typing import List, Optional

from django.utils import timezone  # type: ignore

from .models import (
    CapitalTransaction, SalesCash, SalesCredit, SalesCreditPayment,
    Expense, Payable, PayablePayment, StockIn
)

# ---------- helpers ----------

def _money(x) -> Decimal:
    if x is None:
        return Decimal("0.00")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))

def _label(name: str) -> str:
    # central place to map internal names to printed account titles if you ever need it
    return name

def _naive_local(dt_in):
    """
    Normalize any Date/DateTime to a *naive local* datetime:

    - DateField -> naive midnight local (yyyy-mm-dd 00:00)
    - Aware datetime -> make naive in current TZ
    - Naive datetime -> return as-is
    """
    if isinstance(dt_in, date) and not isinstance(dt_in, datetime):
        # Date -> midnight
        return datetime.combine(dt_in, dt_time.min)

    if isinstance(dt_in, datetime):
        if timezone.is_aware(dt_in):
            return timezone.make_naive(dt_in, timezone.get_current_timezone())
        return dt_in

    return dt_in  # leave unexpected types alone

def _in_range(dt: datetime, start: Optional[date], end: Optional[date]) -> bool:
    """
    Compare a naive datetime 'dt' to optional date bounds [start..end].
    """
    d = dt.date()
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True

# ---------- journal data classes ----------

@dataclass
class Split:
    account_name: str
    dc: str  # "Dr" or "Cr"
    amount: Decimal

@dataclass
class JournalEntry:
    when: datetime           # naive local datetime
    memo: str
    splits: List[Split] = field(default_factory=list)

    def add(self, acct: str, dc: str, amount):
        amt = _money(amount)
        if amt != 0:
            self.splits.append(Split(acct, dc, amt))

# ---------- builder ----------

def build_journal(
    account_id: Optional[int] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> List[JournalEntry]:
    """
    Build a double-entry journal across your sources.
    All 'when' values are normalized to *naive local* datetimes,
    so sorting and PDF rendering won't hit naive/aware comparisons.
    """
    entries: List[JournalEntry] = []

    # ----- CAPITAL (cashbook) -----
    qs_cap = CapitalTransaction.objects.all()
    if account_id:
        qs_cap = qs_cap.filter(account_id=account_id)

    for tx in qs_cap:
        when = _naive_local(tx.date)  # DateTimeField
        if not _in_range(when, start, end):
            continue

        je = JournalEntry(when, f"Capital {tx.transaction_type.capitalize()}")
        amt = _money(tx.amount)
        if tx.transaction_type == "deposit":
            je.add(_label("Cash"), "Dr", amt)
            je.add(_label("Owner’s Capital"), "Cr", amt)
        else:
            je.add(_label("Owner’s Drawings"), "Dr", amt)
            je.add(_label("Cash"), "Cr", amt)
        entries.append(je)

    # ----- CASH SALES -----
    sc_qs = SalesCash.objects.select_related("product")
    if account_id:
        sc_qs = sc_qs.filter(account_id=account_id)

    for sc in sc_qs:
        when = _naive_local(sc.date)  # DateField
        if not _in_range(when, start, end):
            continue

        product_name = sc.product.product_name if sc.product_id else "Product"
        amt = _money(sc.amount)
        memo_bits = [f"Cash Sale — {product_name} x{sc.quantity}"]
        if getattr(sc, "or_num", None):
            memo_bits.append(f"OR #{sc.or_num}")

        je = JournalEntry(when, " | ".join(memo_bits))
        je.add(_label("Cash"), "Dr", amt)
        je.add(_label("Sales Revenue"), "Cr", amt)
        entries.append(je)

    # ----- CREDIT SALES (Utang) -----
    cr_qs = SalesCredit.objects.select_related("product", "customer")
    if account_id:
        cr_qs = cr_qs.filter(account_id=account_id)

    for cr in cr_qs:
        when = _naive_local(cr.credit_date)  # DateField
        if not _in_range(when, start, end):
            continue

        product_name = cr.product.product_name if cr.product_id else "Product"
        cust = (
            f"{cr.customer.first_name} {cr.customer.last_name}".strip()
            if cr.customer_id else "Customer"
        )
        amt = _money(cr.amount)  # NOTE: remaining balance (mutable)
        memo_bits = [f"Credit Sale — {product_name} x{cr.quantity} to {cust}"]
        if getattr(cr, "or_num", None):
            memo_bits.append(f"OR #{cr.or_num}")
        if getattr(cr, "due_date", None):
            memo_bits.append(f"Due {cr.due_date:%Y-%m-%d}")

        je = JournalEntry(when, " | ".join(memo_bits))
        je.add(_label("Accounts Receivable"), "Dr", amt)
        je.add(_label("Sales Revenue"), "Cr", amt)
        entries.append(je)

    # ----- CUSTOMER PAYMENTS (utang collections) -----
    pay_qs = SalesCreditPayment.objects.select_related("customer")
    if account_id:
        pay_qs = pay_qs.filter(account_id=account_id)

    for p in pay_qs:
        when = _naive_local(p.paid_at)  # DateTimeField
        if not _in_range(when, start, end):
            continue

        cust = (
            f"{p.customer.first_name} {p.customer.last_name}".strip()
            if p.customer_id else "Customer"
        )
        amt = _money(p.amount)
        memo = f"Customer Payment — {cust}"
        if getattr(p, "remarks", None):
            memo += f" | {p.remarks}"

        je = JournalEntry(when, memo)
        je.add(_label("Cash"), "Dr", amt)
        je.add(_label("Accounts Receivable"), "Cr", amt)
        entries.append(je)

    # ----- EXPENSES (cash) -----
    ex_qs = Expense.objects.select_related("product")
    if account_id:
        ex_qs = ex_qs.filter(account_id=account_id)

    for e in ex_qs:
        when = _naive_local(e.created_at)  # DateTimeField
        if not _in_range(when, start, end):
            continue

        cat = e.category or "Expense"
        desc = f" ({e.description})" if e.description else ""
        amt = _money(e.amount)
        memo = f"Expense — {cat}{desc}"

        je = JournalEntry(when, memo)
        if getattr(Expense, "INVENTORY_PURCHASE", "Inventory Purchase") == e.category:
            je.add(_label("Inventory"), "Dr", amt)
        else:
            je.add(_label(cat), "Dr", amt)
        je.add(_label("Cash"), "Cr", amt)
        entries.append(je)

    # ----- PAYABLES (creation) -----
    ap_qs = Payable.objects.all()
    if account_id:
        ap_qs = ap_qs.filter(account_id=account_id)

    for ap in ap_qs:
        when = _naive_local(ap.created_at)  # DateTimeField
        if not _in_range(when, start, end):
            continue

        amt = _money(ap.original_amount)
        memo_bits = [f"Supplier Payable — {ap.supplier_name}"]
        if getattr(ap, "due_date", None):
            memo_bits.append(f"Due {ap.due_date:%Y-%m-%d}")
        if getattr(ap, "note", None):
            memo_bits.append(ap.note)

        je = JournalEntry(when, " | ".join(memo_bits))
        je.add(_label("Inventory"), "Dr", amt)     # or your expense policy
        je.add(_label("Accounts Payable"), "Cr", amt)
        entries.append(je)

    # ----- PAYABLE PAYMENTS -----
    app_qs = PayablePayment.objects.select_related("payable")
    if account_id:
        app_qs = app_qs.filter(payable__account_id=account_id)

    for pp in app_qs:
        when = _naive_local(pp.date)  # DateField
        if not _in_range(when, start, end):
            continue

        amt = _money(pp.amount)
        supplier = pp.payable.supplier_name if pp.payable_id else "Supplier"
        memo = f"Payment to Supplier — {supplier}"
        if getattr(pp, "note", None):
            memo += f" | {pp.note}"

        je = JournalEntry(when, memo)
        je.add(_label("Accounts Payable"), "Dr", amt)
        je.add(_label("Cash"), "Cr", amt)
        entries.append(je)

    # final ordering
    entries.sort(key=lambda x: x.when)
    return entries
