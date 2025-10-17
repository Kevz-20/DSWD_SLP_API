# accounts/models.py
from django.db import models  # type: ignore
from django.core.validators import RegexValidator  # type: ignore
from django.utils import timezone  # type: ignore

# === NEW: imports for thumbnail generation (no other behavior changed) ===
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os

from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
import uuid
from datetime import timedelta
from decimal import Decimal
from calendar import monthrange
from datetime import date
from django.core.validators import MinValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver

SECURITY_QUESTIONS = {
    101: "Unsa ang una nimo negosyo?",
    102: "Asa ka una nagbutang ug tindahan o pwesto?",
    103: "Kinsay imong unang silingan o suod nga amigo/amiga sa pagkabata?",
    104: "Asa nga tindahan o merkado ka una kanunay mamalit ug pagkaon o gamit?",
    105: "Asa imong paboritong lugar nga bisitahan?",
    106: "Unsa ang butang nga kanunay nimo dala kung mag-biyahe ka?",
}

# ----------------- CAPITAL -----------------
class CapitalTransaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [('deposit', 'Deposit'), ('withdraw', 'Withdraw')]

    account = models.ForeignKey('Account', on_delete=models.CASCADE, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    remarks = models.TextField(blank=True, null=True)
    # unchanged: use explicit default instead of auto_now_add
    date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        who = f" (acct {self.account_id})" if self.account_id else ""
        return f"{self.transaction_type.capitalize()} - {self.amount}{who}"


# ----------------- SALES CREDIT PAYMENT -----------------
class SalesCreditPayment(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE, null=True, blank=True)  # ← use string
    customer = models.ForeignKey('Customer', on_delete=models.CASCADE)                        # ← use string
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_at = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Payment ₱{self.amount} by {self.customer_id} (acct {self.account_id})"


# ----------------- ACCOUNT -----------------
class Account(models.Model):
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=11, unique=True)  # "09xxxxxxxxx"
    pin = models.CharField(max_length=4)

    # ✅ ADD DEFAULTS so existing rows can be populated
    security_question_id = models.IntegerField(default=0)          # 0 = “not set” (or use 101 if you prefer)
    security_answer_hash = models.CharField(max_length=255, default='')

    def set_security_answer(self, answer: str):
        norm = (answer or "").strip().lower()
        self.security_answer_hash = make_password(norm)

    def check_security_answer(self, answer: str) -> bool:
        norm = (answer or "").strip().lower()
        return check_password(norm, self.security_answer_hash)

    @property
    def security_question_text(self) -> str:
        return SECURITY_QUESTIONS.get(self.security_question_id, "")
    

class ForgotPinToken(models.Model):
    phone_number = models.CharField(max_length=11)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    @classmethod
    def issue(cls, phone_number: str, minutes_valid: int = 10):
        return cls.objects.create(
            phone_number=phone_number,
            expires_at=timezone.now() + timedelta(minutes=minutes_valid),
        )

    def is_valid(self) -> bool:
        return (not self.used) and (self.expires_at > timezone.now())


# ----------------- PRODUCT (thumbnail added; original image path unchanged) -----------------
class Product(models.Model):
    product_name = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    # keep original behavior/path:
    image = models.ImageField(upload_to='product_images/', null=True, blank=True)
    # NEW: small thumbnail generated automatically on save (WebP under product_images/thumbs/)
    thumbnail = models.ImageField(upload_to='product_images/thumbs/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # scope products to an account (unchanged)
    account = models.ForeignKey(
        'Account',
        on_delete=models.CASCADE,
        related_name='products',
        null=True, blank=True,
        db_index=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'product_name'],
                name='uniq_product_name_per_account',
            )
        ]

    def __str__(self):
        return self.product_name

    # === NEW: thumbnail generation (does not change existing image behavior) ===
    def _thumb_name_for(self) -> str:
        """
        Derive a thumbnail filename in product_images/thumbs/ with .webp extension,
        based on the basename of the original image.
        """
        if not self.image:
            return ""
        base = os.path.basename(self.image.name)  # e.g. product_images/foo.jpg -> foo.jpg
        name, _ext = os.path.splitext(base.lower())
        return f"{name}.webp"  # storage will place it under upload_to ('product_images/thumbs/')

    def make_thumbnail(self, size=(160, 160), quality=80):
        if not self.image:
            return
        # Ensure file is open; convert & downscale
        self.image.open()
        img = Image.open(self.image).convert("RGB")
        img.thumbnail(size)  # preserves aspect ratio

        buf = BytesIO()
        # Save compact WebP thumbnail
        img.save(buf, format="WEBP", quality=quality, method=6)
        buf.seek(0)

        thumb_basename = self._thumb_name_for() or "thumb.webp"
        # Save to the thumbnail field without triggering another full model save
        self.thumbnail.save(thumb_basename, ContentFile(buf.read()), save=False)

    def save(self, *args, **kwargs):
        creating = self.pk is None
        # First save to ensure we have a file path for image (unchanged behavior)
        super().save(*args, **kwargs)
        # If an image exists and no thumbnail yet, create one
        if self.image and (creating or not self.thumbnail):
            self.make_thumbnail()
            # Persist only the thumbnail field to avoid recursion
            super().save(update_fields=["thumbnail"])


# ----------------- SALE -----------------
class Sale(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    sale_type = models.CharField(max_length=10)  # 'cash' or 'utang'
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # scope sales to an account (unchanged)
    account = models.ForeignKey(
        'Account',
        on_delete=models.CASCADE,
        related_name='sales',
        null=True, blank=True,
        db_index=True,
    )


# ----------------- EXPENSE -----------------
class Expense(models.Model):
    INVENTORY_PURCHASE = "Inventory Purchase"
    CATEGORY_CHOICES = [
        (INVENTORY_PURCHASE, "Inventory Purchase"),
        ("Rent", "Rent"),
        ("Utilities", "Utilities"),
        ("Other", "Other"),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)    # ⬅️ choices (optional)
    description = models.TextField(blank=True, null=True)                   # ⬅️ allow blank
    receipt = models.ImageField(upload_to='receipts/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class FixedAsset(models.Model):
    account = models.ForeignKey('Account', on_delete=models.CASCADE, related_name='fixed_assets')
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=50, default='equipment')
    cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    date_acquired = models.DateField(default=timezone.localdate)
    accumulated_depreciation = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ₱{self.cost}"


# ----------------- STOCK IN -----------------
class StockIn(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True)  # temporary
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    remaining_quantity = models.IntegerField(default=1)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    markup_rate = models.FloatField()
    # keep original behavior/path:
    image = models.ImageField(upload_to='uploads/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total_cost(self):
        return self.quantity * self.purchase_price


# ----------------- SALE ITEM -----------------
class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    stockin = models.ForeignKey(StockIn, on_delete=models.PROTECT)  # Link to batch
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.stockin.product.product_name} x{self.quantity}"


# ----------------- BANK -----------------
class BankTransaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [('deposit', 'Deposit'), ('withdraw', 'Withdraw')]

    account = models.ForeignKey('Account', on_delete=models.CASCADE, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    remarks = models.TextField(blank=True, null=True)
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=['account', 'date'])]

    def __str__(self):
        return f"{self.transaction_type.capitalize()} ₱{self.amount} (acct {self.account_id})"


# ----------------- SALES CASH -----------------
class SalesCash(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    date = models.DateField()
    or_num = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)


# ----------------- CUSTOMER -----------------
class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    address = models.TextField()
    contact_num = models.CharField(max_length=20, unique=True)
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=1000.00)

    # scope customers to an account for /customers filtering (unchanged)
    account = models.ForeignKey(
        'Account',
        on_delete=models.CASCADE,
        related_name='customers',
        null=True, blank=True,
        db_index=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'contact_num'],
                name='uniq_contact_per_account',
            )
        ]


# ----------------- SALES CREDIT -----------------
class SalesCredit(models.Model):
    class CreditStatus(models.IntegerChoices):
        UNPAID  = 0, "Unpaid"
        PARTIAL = 1, "Partially Paid"
        PAID    = 2, "Paid"

    account  = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True) 
    sale     = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product  = models.ForeignKey(Product, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    amount   = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    status   = models.IntegerField(choices=CreditStatus.choices, default=CreditStatus.UNPAID)
    credit_date = models.DateField()
    paid_date   = models.DateField(null=True, blank=True)
    or_num      = models.CharField(max_length=50)
    due_date    = models.DateField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)


# ----------------- PAYABLES -----------------
class Payable(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="payables")
    supplier_name = models.CharField(max_length=255)

    # NEW: what the payable is for (e.g., “Freezer”)
    item = models.CharField(max_length=255, blank=True, default="")

    original_amount = models.DecimalField(max_digits=12, decimal_places=2)
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    is_paid = models.BooleanField(default=False)

    # === NEW: installment plan fields (all optional / nullable for backward compat) ===
    has_plan = models.BooleanField(default=False)
    plan_months = models.PositiveIntegerField(null=True, blank=True)
    plan_monthly = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    first_due_date = models.DateField(null=True, blank=True)
    next_due_date = models.DateField(null=True, blank=True)

    # === NEW: mark this payable as an asset purchase (optional) ===
    is_asset = models.BooleanField(default=False)
    asset_category = models.CharField(max_length=50, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.supplier_name} - ₱{self.remaining_amount}"

    @property
    def is_overdue(self):
        d = self.next_due_date or self.due_date
        return bool(d and d < timezone.localdate() and self.remaining_amount > 0)

    @property
    def next_installment_amount(self):
        if self.has_plan and self.plan_monthly:
            return min(self.plan_monthly, self.remaining_amount)
        return self.remaining_amount

    def save(self, *args, **kwargs):
        # keep is_paid in sync and seed next_due_date for plans (no change to other behavior)
        self.is_paid = (self.remaining_amount or 0) <= 0
        if self.has_plan and not self.next_due_date:
            self.next_due_date = self.first_due_date or self.due_date
        super().save(*args, **kwargs)



class PayablePayment(models.Model):
    payable = models.ForeignKey(Payable, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)])
    date = models.DateField()
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment ₱{self.amount} for {self.payable.supplier_name}"

    def _add_one_month(self, d: date) -> date: # type: ignore
        y = d.year + (1 if d.month == 12 else 0)
        m = 1 if d.month == 12 else d.month + 1
        day = min(d.day, monthrange(y, m)[1])
        return date(y, m, day)

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating:
            p = self.payable
            p.remaining_amount = max(Decimal(p.remaining_amount) - Decimal(self.amount), Decimal('0'))
            if p.has_plan:
                if p.next_due_date:
                    p.next_due_date = self._add_one_month(p.next_due_date)
                elif p.first_due_date:
                    p.next_due_date = p.first_due_date
                elif p.due_date:
                    p.next_due_date = p.due_date
            if p.remaining_amount <= 0:
                p.is_paid = True
                p.next_due_date = None
            p.save(update_fields=['remaining_amount', 'next_due_date', 'is_paid', 'updated_at'])



class Transaction(models.Model):
    """
    Unified transaction log used by the Transaction History screen.
    A 'transfer to bank' will create TWO rows sharing the same group_id:
    - transfer_cash_out (source=cash, destination=bank)
    - transfer_bank_in  (source=cash, destination=bank)
    """
    TYPE_CHOICES = [
        ('capital_deposit', 'Capital Deposit'),
        ('transfer_cash_out', 'Transfer - Cash Out'),
        ('transfer_bank_in', 'Transfer - Bank In'),
    ]
    SOURCE_CHOICES = [
        ('cash', 'Cash On Hand'),
        ('bank', 'Cash In Bank'),
        ('capital', 'Capital'),
    ]

    account = models.ForeignKey('Account', on_delete=models.CASCADE, related_name='transactions')
    date = models.DateTimeField(default=timezone.now, db_index=True)
    type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, null=True, blank=True)
    destination = models.CharField(max_length=16, choices=SOURCE_CHOICES, null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)
    group_id = models.UUIDField(default=uuid.uuid4, db_index=True)  # tie related rows (e.g., transfers)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.type} ₱{self.amount} (acct {self.account_id})"
    

    # ----------------- BALANCE ASSETS -----------------
class BalanceAssets(models.Model):
    """
    Holds the summarized asset values per account.
    This model is updated whenever capital, bank, payable, or other
    asset-related transactions occur, to make balance sheet generation faster.
    """

    account = models.OneToOneField(
        'Account',
        on_delete=models.CASCADE,
        related_name='balance_assets'
    )

    # 🔹 Basic current assets
    cash_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_in_bank = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    accounts_receivable = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    inventory = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # 🔹 Fixed / Long-term assets
    fixed_assets = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # 🔹 Computed fields for reporting
    @property
    def total_assets(self):
        """Total of all asset categories."""
        return (
            (self.cash_on_hand or 0)
            + (self.cash_in_bank or 0)
            + (self.accounts_receivable or 0)
            + (self.inventory or 0)
            + (self.fixed_assets or 0)
        )

    def __str__(self):
        return f"Assets (acct {self.account_id}) ₱{self.total_assets:,.2f}"

    class Meta:
        verbose_name = "Balance Sheet - Assets"
        verbose_name_plural = "Balance Sheet - Assets"

