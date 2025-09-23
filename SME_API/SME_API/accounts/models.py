# accounts/models.py
from django.db import models  # type: ignore
from django.core.validators import RegexValidator  # type: ignore
from django.utils import timezone  # type: ignore

# === NEW: imports for thumbnail generation (no other behavior changed) ===
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os


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
    first_name = models.CharField(max_length=100, blank=True, default="")
    middle_name = models.CharField(max_length=50, blank=True, default="")
    last_name = models.CharField(max_length=100, blank=True, default="")
    phone_number = models.CharField(max_length=15, unique=True)
    pin = models.CharField(
        max_length=4,
        validators=[RegexValidator(r'^\d{4}$', 'PIN must be exactly 4 digits.')]
    )

    @property
    def full_name(self) -> str:
        return " ".join(p for p in [self.first_name, self.middle_name, self.last_name] if p).strip()

    def __str__(self) -> str:
        label = self.full_name or "(no name)"
        return f"{label} — {self.phone_number}"


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
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)    # ⬅️ choices (optional)
    description = models.TextField(blank=True, null=True)                   # ⬅️ allow blank
    receipt = models.ImageField(upload_to='receipts/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


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


# ----------------- CAPITAL (simple) -----------------
class Capital(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


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
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    status = models.IntegerField()  # 1 = paid, 0 = unpaid
    credit_date = models.DateField()
    paid_date = models.DateField(null=True, blank=True)
    or_num = models.CharField(max_length=50)
    due_date = models.DateField(null=True, blank=True)  # ✅ ADD THIS LINE
    created_at = models.DateTimeField(auto_now_add=True)


# ----------------- PAYABLES -----------------
class Payable(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="payables")
    supplier_name = models.CharField(max_length=255)
    original_amount = models.DecimalField(max_digits=12, decimal_places=2)
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    is_paid = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.supplier_name} - ₱{self.remaining_amount}"


class PayablePayment(models.Model):
    payable = models.ForeignKey(Payable, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment ₱{self.amount} for {self.payable.supplier_name}"
