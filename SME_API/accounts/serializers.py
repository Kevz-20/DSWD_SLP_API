# accounts/serializers.py
from datetime import date, time as dtime, datetime as dt_datetime, time as dt_time
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone  # type: ignore
from django.db.models import Sum, Case, When, F, DecimalField  # type: ignore
from django.db.models.functions import Coalesce # type: ignore
from rest_framework import serializers  # type: ignore
from rest_framework.exceptions import ValidationError # type: ignore
from django.db import IntegrityError, transaction # type: ignore
from decimal import Decimal
from django.utils import timezone # type: ignore

from .models import (
    Account,
    CapitalTransaction,
    Expense,
    Product,
    Sale,
    SaleItem,
    StockIn,
    SalesCash,
    Customer,
    SalesCredit,
    Payable,
    PayablePayment,
    BankTransaction,
    Transaction,
    FixedAsset,         
    BalanceAssets,       
)

# ==========================
# ACCOUNT
# ==========================

class AccountSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Account
        fields = [
            'id', 'first_name', 'middle_name', 'last_name',
            'phone_number', 'pin', 'security_question_id', 'full_name'
        ]
        read_only_fields = ['security_question_id', 'full_name']

    def get_full_name(self, obj):
        parts = [obj.first_name, obj.middle_name, obj.last_name]
        return " ".join([p for p in parts if p and p.strip()])


class AccountCreateSerializer(serializers.ModelSerializer):
    security_answer = serializers.CharField(write_only=True)

    class Meta:
        model = Account
        fields = [
            "first_name", "middle_name", "last_name",
            "phone_number", "pin",
            "security_question_id", "security_answer",
        ]

    def create(self, validated_data):
        answer = validated_data.pop("security_answer", "")
        acct = Account(**validated_data)
        acct.set_security_answer(answer)  # hashes into security_answer_hash
        acct.save()
        return acct


class ForgotStartSerializer(serializers.Serializer):
    phone_number = serializers.RegexField(r"^09\d{9}$")


class ForgotVerifySerializer(serializers.Serializer):
    phone_number = serializers.RegexField(r"^09\d{9}$")
    answer = serializers.CharField()


class ForgotResetSerializer(serializers.Serializer):
    reset_token = serializers.UUIDField()
    new_pin = serializers.RegexField(r"^\d{4}$")


# ==========================
# CAPITAL
# ==========================

class CapitalTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapitalTransaction
        fields = '__all__'


# ==========================
# STOCK-IN (ADD PRODUCT / BATCH)
# ==========================

class AddProductStockInSerializer(serializers.Serializer):
    # incoming payload fields
    product_name = serializers.CharField(max_length=255)
    category = serializers.CharField(max_length=100)
    quantity = serializers.IntegerField()
    purchase_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    markup_rate = serializers.FloatField()
    image = serializers.ImageField(required=False, allow_null=True)

    # allow account_id via request body (optional if using context)
    account_id = serializers.IntegerField(write_only=True, required=False)

    def create(self, validated_data):
        # --- get account_id from context OR payload ---
        account_id = self.context.get('account_id') or validated_data.pop('account_id', None)
        if not account_id:
            raise serializers.ValidationError({"account_id": "account_id is required (context or payload)."})

        normalized_name = validated_data['product_name'].strip().title()
        category = validated_data['category'].strip()
        quantity = int(validated_data['quantity'])
        purchase_price: Decimal = validated_data['purchase_price']
        markup_rate = float(validated_data['markup_rate'])
        image = validated_data.get('image')

        # Per-account lookup
        product = Product.objects.filter(
            account_id=account_id,
            product_name__iexact=normalized_name
        ).first()

        if not product:
            # Compute selling price with proper Decimal math
            selling_price = (purchase_price * (Decimal('1') + Decimal(str(markup_rate)) / Decimal('100')))\
                .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            product = Product.objects.create(
                account_id=account_id,
                product_name=normalized_name,
                category=category,
                selling_price=selling_price,
                image=image if image else None
            )
        else:
            # Keep category up to date, and set image if empty
            update_fields = []
            if product.category != category:
                product.category = category
                update_fields.append('category')
            if (not product.image) and image:
                product.image = image
                update_fields.append('image')
            if update_fields:
                product.save(update_fields=update_fields)

        # Create StockIn tied to this account
        StockIn.objects.create(
            account_id=account_id,
            product=product,
            quantity=quantity,
            remaining_quantity=quantity,
            purchase_price=purchase_price,
            markup_rate=markup_rate,
            image=image  # optional batch photo
        )

        return product


# ==========================
# SALES (CASH)
# ==========================

class SalesCashSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(write_only=True)
    quantity = serializers.IntegerField(write_only=True)
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, write_only=True)

    class Meta:
        model = SalesCash
        fields = ['product_name', 'quantity', 'selling_price', 'or_num', 'sale', 'date']

    def create(self, validated_data):
        from datetime import date as py_date

        product_name = validated_data.pop('product_name')
        quantity = int(validated_data.pop('quantity'))
        selling_price: Decimal = validated_data.pop('selling_price')

        # Look up product
        product = Product.objects.filter(product_name__iexact=product_name).first()
        if not product:
            raise serializers.ValidationError({"product_name": "Product does not exist."})

        # Check stock
        batches = (StockIn.objects
                   .filter(product=product, remaining_quantity__gt=0)
                   .order_by('created_at'))
        total_available = sum(b.remaining_quantity for b in batches)
        if total_available < quantity:
            raise serializers.ValidationError({"quantity": f"Only {total_available} items left in stock."})

        # Create Sale
        sale = Sale.objects.create(
            product=product,
            quantity=quantity,
            selling_price=selling_price,  # legacy
            sale_type='cash',
            created_at=timezone.now(),
            account=product.account,  
        )

        # FIFO + SaleItems (unit at selling_price to keep legacy behavior)
        q = quantity
        for batch in batches:
            if q == 0:
                break
            take = min(q, batch.remaining_quantity)
            SaleItem.objects.create(sale=sale, stockin=batch, quantity=take, unit_price=selling_price)
            batch.remaining_quantity -= take
            batch.save(update_fields=['remaining_quantity'])
            q -= take

        # amount should be total, not unit price
        line_total = (selling_price * Decimal(quantity)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        sales_cash = SalesCash.objects.create(
            sale=sale,
            product=product,
            amount=line_total,
            quantity=quantity,
            date=validated_data.get('date', py_date.today()),
            or_num=validated_data.get('or_num', f"OR-{timezone.now().timestamp()}"),
             account=product.account,
    
        )
        return sales_cash


# ==========================
# CUSTOMERS (for Utang list / creation)
# ==========================

class CustomerSerializer(serializers.ModelSerializer):
    """
    remaining_credit = credit_limit - sum(unpaid SalesCredit.amount) for THIS account.
    """
    remaining_credit = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'first_name', 'last_name', 'address', 'contact_num',
            'credit_limit', 'remaining_credit'
        ]

    def get_remaining_credit(self, obj):
        # Prefer account_id from context (views set this),
        # otherwise fall back to the customer's own account_id.
        account_id = (
            self.context.get('account_id')
            or self.context.get('account')
            or getattr(obj, 'account_id', None)
        )

        qs = SalesCredit.objects.filter(customer=obj, status=0)
        if account_id:
            qs = qs.filter(account_id=account_id)

        total_unpaid = qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        limit = Decimal(str(obj.credit_limit or 0))
        remaining = limit - total_unpaid
        if remaining < 0:
            remaining = Decimal('0.00')
        return float(remaining)


# ==========================
# SALE ITEMS (shared)
# ==========================

class SaleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleItem
        fields = ['stockin', 'quantity', 'unit_price']


# ==========================
# SALES CREDIT (Utang) – list/record
# ==========================

class SalesCreditRecordSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.product_name', read_only=True)
    sale_id = serializers.IntegerField(source='sale.id', read_only=True)
    status = serializers.SerializerMethodField()
    credit_date = serializers.DateField(format="%Y-%m-%d", read_only=True)
    paid_date = serializers.DateField(format="%Y-%m-%d", read_only=True, allow_null=True)

    class Meta:
        model = SalesCredit
        fields = [
            'sale_id',
            'product_name',
            'amount',
            'quantity',
            'status',
            'credit_date',
            'paid_date',
            'or_num',
        ]

    def get_status(self, obj):
        return "Paid" if obj.status == 1 else "Unpaid"


# ===== Customers: write serializer to ensure account_id is saved =====
class CustomerCreateSerializer(serializers.ModelSerializer):
    # client must send this; snake_case
    account_id = serializers.IntegerField(write_only=True, required=True)

    class Meta:
        model = Customer
        fields = ['first_name', 'last_name', 'address', 'contact_num', 'credit_limit', 'account_id']

    def create(self, validated_data):
        account_id = validated_data.pop('account_id')
        return Customer.objects.create(account_id=account_id, **validated_data)


class SalesCreditCreateSerializer(serializers.Serializer):
    product_name = serializers.CharField()
    quantity = serializers.IntegerField()
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    customer_id = serializers.IntegerField()
    or_num = serializers.CharField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)

    def validate_due_date(self, value):
        if value and value < date.today():
            raise serializers.ValidationError("Due date cannot be in the past.")
        return value

    def create(self, validated_data):
        product_name = validated_data.get('product_name')
        quantity = int(validated_data.get('quantity'))
        selling_price: Decimal = validated_data.get('selling_price')
        customer_id = validated_data.get('customer_id')
        or_num = validated_data.get('or_num', f"OR-{timezone.now().timestamp()}")
        due_date = validated_data.get('due_date')

        # Customer
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            raise serializers.ValidationError({'customer_id': 'Customer not found'})

        # Product
        try:
            product = Product.objects.get(product_name__iexact=product_name)
        except Product.DoesNotExist:
            raise serializers.ValidationError({'product_name': 'Product not found'})

        # Check stock via StockIn
        batches = StockIn.objects.filter(product=product, remaining_quantity__gt=0).order_by('created_at')
        total_available = sum(b.remaining_quantity for b in batches)
        if total_available < quantity:
            raise serializers.ValidationError({'quantity': f"Only {total_available} items in stock"})

        # Total charge (for credit limit check) – Decimal & 2dp
        total_cost = (selling_price * Decimal(quantity)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Credit limit check: you treat credit_limit as remaining balance
        if (customer.credit_limit or Decimal('0')) < total_cost:
            raise serializers.ValidationError({
                'credit_limit': f"Insufficient credit limit. Remaining: {customer.credit_limit}"
            })

        # Create Sale (legacy fields preserved)
        sale = Sale.objects.create(
            product=product,
            quantity=quantity,
            selling_price=selling_price,
            sale_type='utang',
            customer=customer,
            created_at=timezone.now()
        )

        # FIFO deduct + SaleItem lines
        q = quantity
        for batch in batches:
            if q == 0:
                break

            take = min(q, batch.remaining_quantity)

            SaleItem.objects.create(
                sale=sale,
                stockin=batch,
                quantity=take,
                unit_price=selling_price  # keep your behavior (unit at provided selling_price)
            )
            batch.remaining_quantity -= take
            batch.save(update_fields=['remaining_quantity'])
            q -= take

        # Create SalesCredit row (unit-price style; subtotal elsewhere)
        SalesCredit.objects.create(
            sale=sale,
            product=product,
            customer=customer,
            amount=selling_price,         # unit price stored
            quantity=quantity,
            status=0,
            credit_date=date.today(),
            paid_date=None,
            or_num=or_num,
            due_date=due_date,
        )

        # Deduct customer credit_limit (you are using it as remaining balance)
        customer.credit_limit = (customer.credit_limit or Decimal('0')) - total_cost
        customer.save(update_fields=['credit_limit'])

        return {
            "sale_id": sale.id,
            "remaining_credit": float(customer.credit_limit or Decimal('0')),
            "due_date": due_date
        }


# ==========================
# DELETE / ADJUST INVENTORY
# ==========================

class DeleteInventorySerializer(serializers.Serializer):
    stockin_id = serializers.IntegerField()
    quantity = serializers.IntegerField()
    reason = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    account_id = serializers.IntegerField()


# ==========================
# STOCK-IN LISTING / BATCH INFO
# ==========================

class StockInBatchSerializer(serializers.ModelSerializer):
    stockin_date = serializers.DateTimeField(format='%Y-%m-%d', read_only=True)
    product_name = serializers.CharField(source='product.product_name', read_only=True)

    class Meta:
        model = StockIn
        fields = ['id', 'created_at', 'remaining_quantity', 'purchase_price', 'markup_rate', 'product_name']


class BatchSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")

    class Meta:
        model = StockIn
        fields = ['id', 'product', 'remaining_quantity', 'purchase_price', 'created_at', 'markup_rate']


# ==========================
# PRODUCT LISTING FOR APP (RecordSalesPage)
# ==========================

class ProductSerializer(serializers.ModelSerializer):
    quantity = serializers.SerializerMethodField()
    purchase_price = serializers.SerializerMethodField()
    markup_rate = serializers.SerializerMethodField()
    selling_price = serializers.SerializerMethodField()
    category = serializers.CharField(read_only=True)

    image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()  # small image for list/grid

    class Meta:
        model = Product
        fields = [
            'id', 'product_name', 'category', 'quantity',
            'purchase_price', 'markup_rate', 'selling_price',
            'image_url', 'thumbnail_url'
        ]

    def get_quantity(self, obj):
        return int(
            StockIn.objects
            .filter(product=obj, account_id=obj.account_id)
            .aggregate(total=Coalesce(Sum('remaining_quantity'), 0))['total'] or 0
        )

    def _latest_stockin(self, obj):
        return (
            StockIn.objects
            .filter(product=obj, account_id=obj.account_id)
            .order_by('-created_at')
            .first()
        )

    def get_purchase_price(self, obj):
        si = self._latest_stockin(obj)
        return si.purchase_price if si else Decimal("0.00")

    def get_markup_rate(self, obj):
        si = self._latest_stockin(obj)
        return si.markup_rate if si else 0.0

    def get_selling_price(self, obj):
        si = self._latest_stockin(obj)
        if si:
            return (si.purchase_price * (Decimal('1') + Decimal(str(si.markup_rate)) / Decimal('100')))\
                .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return Decimal("0.00")

    def get_image_url(self, obj):
        """
        Full image for detail screens.
        Prefer Product.image; fall back to latest StockIn.image.
        """
        request = self.context.get('request')
        if obj.image:
            url = obj.image.url
        else:
            si = (
                StockIn.objects
                .filter(product=obj, account_id=obj.account_id, image__isnull=False)
                .order_by('-created_at')
                .first()
            )
            url = si.image.url if si and si.image else None
        return request.build_absolute_uri(url) if (request and url) else url

    def get_thumbnail_url(self, obj):
        """
        Small image for list/grid (RecordSalesPage).
        Prefer Product.thumbnail; if missing, gracefully fall back to image_url
        so the UI still shows something while you backfill thumbnails.
        """
        request = self.context.get('request')
        if getattr(obj, 'thumbnail', None):
            url = obj.thumbnail.url if obj.thumbnail else None
            return request.build_absolute_uri(url) if (request and url) else url
        return self.get_image_url(obj)


# ==========================
# EXPENSES
# ==========================

class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = '__all__'


# ==========================
# EDITING STOCK-IN BATCH
# ==========================

class UpdateStockInSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.product_name', required=True)
    category = serializers.CharField(source='product.category', required=True)
    created_at = serializers.DateTimeField(format='%Y-%m-%d', read_only=True)

    class Meta:
        model = StockIn
        fields = [
            'id',  # batch ID
            'product_name',
            'category',
            'purchase_price',
            'markup_rate',
            'remaining_quantity',
            'created_at'
        ]

    def update(self, instance, validated_data):
        product_data = validated_data.pop('product', {})

        # Update Product fields (product_name and category)
        if product_data:
            for attr, value in product_data.items():
                setattr(instance.product, attr, value)
            instance.product.save()

        # Update StockIn fields (purchase_price, markup_rate, remaining_quantity)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance


# ==========================
# UTANG / DEBTORS PAGE
# ==========================

class CreditItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.product_name')
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = SalesCredit
        fields = ['product_name', 'quantity', 'subtotal']

    def get_subtotal(self, obj):
        # amount is unit price in your current schema
        return (Decimal(obj.quantity) * Decimal(obj.amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class CreditTransactionSerializer(serializers.Serializer):
    credit_date = serializers.DateField()
    items = CreditItemSerializer(many=True)


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            'id', 'account', 'date', 'type', 'amount',
            'source', 'destination', 'remarks', 'group_id',
        ]
    read_only_fields = ['id', 'group_id', 'date']


# ==========================
# ACCOUNT NAME UTILITIES
# ==========================

class AccountNameSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    middle_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        middle = '' if obj.middle_name == 'N/A' else f' {obj.middle_name} '
        return f"{obj.first_name}{middle}{obj.last_name}"


class FullNameSecureUpdateSerializer(serializers.Serializer):
    pin = serializers.RegexField(regex=r'^\d{4}$', max_length=4)
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100)


# ==========================
# PAYABLES
# ==========================

class PayableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payable
        fields = [
            'id', 'account', 'supplier_name', 'item',
            'original_amount', 'remaining_amount',
            'due_date', 'note', 'is_paid',
            # ⬇️ new plan fields
            'has_plan', 'plan_months', 'plan_monthly', 'first_due_date', 'next_due_date',
            # ⬇️ optional asset flags (if you mark a payable as an asset purchase)
            'is_asset', 'asset_category',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PayableCreateSerializer(serializers.ModelSerializer):
    # ---- Back-compat helpers (write-only) ----
    account_id = serializers.IntegerField(write_only=True, required=False)
    purpose = serializers.ChoiceField(choices=['inventory', 'expense'], required=False)

    # inventory helpers
    product_id = serializers.IntegerField(required=False, write_only=True)
    quantity = serializers.IntegerField(required=False, write_only=True)
    purchase_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, write_only=True)

    # legacy extras
    expense_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, write_only=True)
    expense_note = serializers.CharField(required=False, allow_blank=True, write_only=True)

    # how the downpayment was paid (cash/bank)
    payment_method = serializers.ChoiceField(
        choices=['cash', 'bank'],
        required=False,
        write_only=True,
        default='cash'
    )

    downpayment = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)

    # ---- Plan fields (accepted but ignored/popped) ----
    has_plan = serializers.BooleanField(required=False, default=False, write_only=True)
    plan_months = serializers.IntegerField(required=False, write_only=True)
    plan_monthly = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, write_only=True)
    first_due_date = serializers.DateField(required=False, allow_null=True, write_only=True)

    # ---- Persist asset flags ----
    is_asset = serializers.BooleanField(required=False, default=False)
    asset_category = serializers.CharField(required=False, allow_blank=True, max_length=100)

    class Meta:
        model = Payable
        fields = [
            # model fields
            'account', 'supplier_name', 'item',
            'original_amount', 'due_date', 'note',
            'downpayment',
            'is_asset', 'asset_category',
            # helpers / compat
            'account_id', 'purpose', 'product_id', 'quantity', 'purchase_price',
            'expense_amount', 'expense_note',
            'payment_method',
            # plan (accepted, ignored)
            'has_plan', 'plan_months', 'plan_monthly', 'first_due_date',
        ]
        extra_kwargs = {
            'account': {'required': False, 'allow_null': True},
        }

    def create(self, validated):

        # ---- helpers from payload ----
        down = Decimal(str(validated.pop('downpayment', 0) or 0)).quantize(Decimal('0.01'))
        purpose = (validated.pop('purpose', 'expense') or 'expense').lower()
        payment_method = (validated.pop('payment_method', 'cash') or 'cash').lower()

        # legacy helpers (accepted, not used here)
        validated.pop('product_id', None)
        validated.pop('quantity', None)
        validated.pop('purchase_price', None)
        validated.pop('expense_amount', None)
        validated.pop('expense_note', None)

        # discard plan fields
        validated.pop('has_plan', None)
        validated.pop('plan_months', None)
        validated.pop('plan_monthly', None)
        validated.pop('first_due_date', None)

        with transaction.atomic():
            # 1) Create the payable at FULL amount first (no pre-subtract here)
            p = Payable(**validated)
            p.remaining_amount = (p.original_amount or Decimal('0.00'))
            p.is_paid = False
            p.save()

            # 2) Asset bookkeeping (unchanged)
            if p.is_asset:
                FixedAsset.objects.get_or_create(
                    account=p.account,
                    name=p.item or p.supplier_name,
                    defaults={
                        'cost': p.original_amount,
                        'category': p.asset_category or 'equipment',
                        'date_acquired': p.due_date or timezone.now().date(),  # date only
                    },
                )
                assets, _ = BalanceAssets.objects.get_or_create(account=p.account)
                assets.fixed_assets = (assets.fixed_assets or Decimal('0')) + (p.original_amount or Decimal('0'))
                assets.save(update_fields=['fixed_assets'])

            # 3) If there is a downpayment:
            if down > Decimal('0.00'):
                remark = f"Downpayment - {p.supplier_name or ''} {p.item or ''}".strip()
                pay_dt = timezone.now()
                pay_d  = pay_dt.date()

                # 3a) Move cash now
                if payment_method == 'bank':
                    BankTransaction.objects.create(
                        account=p.account, amount=down, transaction_type='withdraw',
                        remarks=remark, date=pay_dt
                    )
                else:
                    CapitalTransaction.objects.create(
                        account=p.account, amount=down, transaction_type='withdraw',
                        remarks=remark, date=pay_dt
                    )

                # 3b) Record the payment so it shows in history
                PayablePayment.objects.create(
                    payable=p, amount=down, date=pay_d, note="Downpayment",
                    idempotency_key=f"down:{p.id}:{int(pay_dt.timestamp())}"
                )

                # 3c) Manually decrement remaining ONCE here
                #     (since we didn’t pre-subtract at creation)
                #p.remaining_amount = (p.remaining_amount or Decimal('0.00')) - down
                #if p.remaining_amount <= Decimal('0.00'):
                #    p.remaining_amount = Decimal('0.00')
                #    p.is_paid = True
                #p.save(update_fields=['remaining_amount', 'is_paid'])

            # else: no downpayment; remaining stays at full amount

        return p

    


# --- keep existing imports above ---

class PayablePaymentSerializer(serializers.ModelSerializer):
    # Optional label for cash ledger
    item_label = serializers.CharField(write_only=True, required=False, allow_blank=True)
    # Client-sent idempotency key to guard against double taps/retries
    idempotency_key = serializers.CharField(write_only=True, required=False, allow_blank=True)

    # Read-only extras for client refresh
    new_balance = serializers.SerializerMethodField(read_only=True)
    transaction = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PayablePayment
        fields = [
            'id', 'payable', 'amount', 'date', 'note', 'created_at',
            'item_label', 'idempotency_key',
            'new_balance', 'transaction'
        ]
        read_only_fields = ['id', 'created_at', 'new_balance', 'transaction']

    # Prefer a payable locked by the view; fall back to attrs['payable']
    def _get_locked_payable(self, attrs):
        return self.context.get("payable_locked") or attrs.get('payable')

    def validate(self, attrs):
        payable = self._get_locked_payable(attrs)
        amount = attrs.get('amount')

        if payable is None:
            raise serializers.ValidationError("Payable is required.")
        if payable.is_paid:
            raise serializers.ValidationError("This payable is already marked as paid.")
        if amount is None or amount <= 0:
            raise serializers.ValidationError("Amount must be greater than 0.")

        remaining = Decimal(payable.remaining_amount or 0)
        if Decimal(amount) > remaining:
            raise serializers.ValidationError(f"Payment exceeds remaining amount (₱{remaining:,.2f}).")
        return attrs

    def _compute_cash_balance(self, account_id=None):
        qs = CapitalTransaction.objects.all()
        if account_id:
            qs = qs.filter(account_id=account_id)
        return (qs.aggregate(
            bal=Sum(
                Case(
                    When(transaction_type='deposit', then=F('amount')),
                    When(transaction_type='withdraw', then=-F('amount')),
                    default=Decimal('0'),
                    output_field=DecimalField(max_digits=14, decimal_places=2)
                )
            )
        )['bal'] or Decimal('0'))

    def create(self, validated_data):
        item_label = (validated_data.pop('item_label', '') or '').strip()
        idem_key   = (validated_data.pop('idempotency_key', '') or '').strip() or None

        payable = self._get_locked_payable(validated_data)
        if payable is None:
            raise serializers.ValidationError("Payable is required.")

        amount = Decimal(validated_data['amount'])

        with transaction.atomic():
            try:
                payment = PayablePayment.objects.create(
                    payable=payable,
                    amount=amount,
                    note=validated_data.get('note') or '',
                    date=validated_data.get('date'),
                    idempotency_key=idem_key,
                )
            except IntegrityError:
                raise serializers.ValidationError({"idempotency_key": "Duplicate payment."})

            label = item_label or payable.supplier_name
            pay_dt = dt_datetime.combine(payment.date, dt_time.min)

            tx = CapitalTransaction.objects.create(
                account=payable.account,
                amount=payment.amount,
                transaction_type='withdraw',
                remarks=f"Payable payment - {label}",
                date=pay_dt
            )

            self._tx = tx
            self._new_balance = self._compute_cash_balance(account_id=payable.account_id)

        return payment

    def get_new_balance(self, obj):
        if hasattr(self, '_new_balance'):
            return float(self._new_balance)
        p = obj.payable
        return float(self._compute_cash_balance(account_id=p.account_id))

    def get_transaction(self, obj):
        tx = getattr(self, '_tx', None)
        if not tx:
            return {
                "type": "withdraw",
                "amount": float(obj.amount),
                "description": f"Payment - {obj.payable.supplier_name}",
                "date": obj.date.isoformat()
            }
        return {
            "id": tx.id,
            "type": "withdraw",
            "amount": float(tx.amount),
            "description": tx.remarks or "",
            "date": tx.date.isoformat()
        }



# ==========================
# CASH BREAKDOWN HELPERS
# ==========================

class CashBreakdownSerializer(serializers.Serializer):
    cash_on_hand = serializers.DecimalField(max_digits=12, decimal_places=2)
    capital      = serializers.DecimalField(max_digits=12, decimal_places=2)
    cash_on_bank = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_cash   = serializers.DecimalField(max_digits=12, decimal_places=2)  


def _dec(v) -> Decimal:
    try:
        return Decimal(v)
    except Exception:
        return Decimal("0.00")


def compute_capital_balance(account_id: int) -> Decimal:
    """
    deposits - withdraws from CapitalTransaction
    Exclude system withdrawals like payable payments, stock-in, expenses, etc.
    """
    qs = CapitalTransaction.objects.filter(account_id=account_id)

    # Exclude system-related remarks (not actual owner withdrawals)
    qs = qs.exclude(remarks__icontains='payable')
    qs = qs.exclude(remarks__icontains='stock-in')
    qs = qs.exclude(remarks__icontains='expense')
    qs = qs.exclude(remarks__icontains='customer payment')
    qs = qs.exclude(remarks__icontains='transfer')

    agg = qs.aggregate(
        bal=Sum(
            Case(
                When(transaction_type='deposit', then=F('amount')),
                When(transaction_type='withdraw', then=-F('amount')),
                default=0,
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )
    return _dec(agg['bal'] or 0)



def compute_cash_on_hand(account_id: int) -> Decimal:
    """
    Cash on hand =
      (cash sales)
    – (cash expenses)
    – (capital 'withdraw' rows tagged as transfer → to bank)
    + (capital 'deposit'  rows tagged as transfer ← from bank)
    """
    sales_cash = SalesCash.objects.filter(account_id=account_id)\
        .aggregate(total=Coalesce(Sum('amount'), 0))['total'] or 0

    # If your Expense model has payment_method; otherwise remove the filter.
    cash_exp = Expense.objects.filter(account_id=account_id, payment_method='cash')\
        .aggregate(total=Coalesce(Sum('amount'), 0))['total'] or 0

    # Adjust for internal transfers recorded in CapitalTransaction
    xfer_out = CapitalTransaction.objects.filter(
        account_id=account_id,
        transaction_type='withdraw',
        remarks__icontains='transfer'
    ).aggregate(total=Coalesce(Sum('amount'), 0))['total'] or 0

    xfer_in = CapitalTransaction.objects.filter(
        account_id=account_id,
        transaction_type='deposit',
        remarks__icontains='transfer'
    ).aggregate(total=Coalesce(Sum('amount'), 0))['total'] or 0

    return _dec(sales_cash) - _dec(cash_exp) - _dec(xfer_out) + _dec(xfer_in)


def compute_cash_on_bank(account_id: int) -> Decimal:
    """
    Cash on bank = sum(deposits) - sum(withdrawals) from BankTransaction.
    """
    agg = BankTransaction.objects.filter(account_id=account_id).aggregate(
        bal=Sum(
            Case(
                When(transaction_type='deposit', then=F('amount')),
                When(transaction_type='withdraw', then=-F('amount')),
                default=0,
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
    )
    return _dec(agg['bal'] or 0)


def get_cash_breakdown_data(account_id: int) -> dict:
    data = {
        "cash_on_hand": compute_cash_on_hand(account_id),
        "capital":      compute_capital_balance(account_id),
        "cash_on_bank": compute_cash_on_bank(account_id),
        "total_cash":   on_hand + on_bank, # type: ignore
    }
    # Serialize to ensure proper formatting (2dp)
    return CashBreakdownSerializer(data).data


#CASH FLOW 1018
# ==========================
# CASH FLOW (report)
# ==========================

class CashFlowLineSerializer(serializers.Serializer):
    section = serializers.CharField()   # "Operating" | "Investing" | "Financing"
    label   = serializers.CharField()
    amount  = serializers.DecimalField(max_digits=14, decimal_places=2)


class CashFlowSerializer(serializers.Serializer):
    start      = serializers.DateField()
    end        = serializers.DateField()
    operating  = serializers.DecimalField(max_digits=14, decimal_places=2)
    investing  = serializers.DecimalField(max_digits=14, decimal_places=2)
    financing  = serializers.DecimalField(max_digits=14, decimal_places=2)
    net_change = serializers.DecimalField(max_digits=14, decimal_places=2)
    cash_begin = serializers.DecimalField(max_digits=14, decimal_places=2)
    cash_end   = serializers.DecimalField(max_digits=14, decimal_places=2)
    # NEW — simple totals for your top card
    cash_in_total  = serializers.DecimalField(max_digits=14, decimal_places=2)
    cash_out_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    # optional detailed lines (useful for UI breakdowns)
    lines      = CashFlowLineSerializer(many=True, required=False)

def _sum_or_0(qs, field="amount"):
    return _dec(qs.aggregate(total=Coalesce(Sum(field), 0))["total"] or 0)


def _capital_agg_until(account_id: int, end_date: date):
    """
    Sum of deposits - withdrawals in CapitalTransaction up to (and including) end_date.
    """
    qs = CapitalTransaction.objects.filter(account_id=account_id, date__date__lte=end_date)
    return _dec(qs.aggregate(
        bal=Sum(
            Case(
                When(transaction_type='deposit',  then=F('amount')),
                When(transaction_type='withdraw', then=-F('amount')),
                default=0,
                output_field=DecimalField(max_digits=14, decimal_places=2)
            )
        )
    )["bal"] or 0)


def _bank_agg_until(account_id: int, end_date: date):
    """
    Sum of deposits - withdrawals in BankTransaction up to (and including) end_date.
    """
    qs = BankTransaction.objects.filter(account_id=account_id, date__date__lte=end_date)
    return _dec(qs.aggregate(
        bal=Sum(
            Case(
                When(transaction_type='deposit',  then=F('amount')),
                When(transaction_type='withdraw', then=-F('amount')),
                default=0,
                output_field=DecimalField(max_digits=14, decimal_places=2)
            )
        )
    )["bal"] or 0)


def compute_cashflow(account_id: int, start: date, end: date) -> dict:
    """
    Computes a simple indirect-style Cash Flow using your existing ledgers:
      • Operating  = Cash Sales – Operating Expenses (excludes inventory purchases)
      • Investing  = - Asset purchases recorded as Payables with is_asset=True
      • Financing  = (Capital + Bank deposits) – (Capital + Bank withdrawals)
      • Cash begin = (Capital ledger + Bank ledger) up to day before 'start'
      • Cash end   = begin + net_change
    """
    if end < start:
        # keep behavior predictable for callers
        start, end = end, start

    # ---------- Operating ----------
    # Inflows: cash sales within range
    inflow_sales = _sum_or_0(
        SalesCash.objects.filter(account_id=account_id, date__range=(start, end))
    )

    # Outflows: operating expenses (exclude inventory purchases)
    outflow_expenses = _sum_or_0(
        Expense.objects.filter(
            account_id=account_id,
            created_at__date__range=(start, end)
        ).exclude(category=Expense.INVENTORY_PURCHASE)
    )

    operating = _dec(inflow_sales) - _dec(outflow_expenses)

    # ---------- Investing ----------
    # Treat flagged asset payables as capex cash OUT at creation time
    invest_out = _sum_or_0(
        Payable.objects.filter(
            account_id=account_id,
            is_asset=True,
            created_at__date__range=(start, end)
        ),
        field="original_amount",
    )
    investing = -_dec(invest_out)

    # ---------- Financing ----------
    cap_in  = _sum_or_0(CapitalTransaction.objects.filter(
        account_id=account_id, transaction_type="deposit",  date__date__range=(start, end)))
    cap_out = _sum_or_0(CapitalTransaction.objects.filter(
        account_id=account_id, transaction_type="withdraw", date__date__range=(start, end)))
    bank_in  = _sum_or_0(BankTransaction.objects.filter(
        account_id=account_id, transaction_type="deposit",  date__date__range=(start, end)))
    bank_out = _sum_or_0(BankTransaction.objects.filter(
        account_id=account_id, transaction_type="withdraw", date__date__range=(start, end)))


    financing = (cap_in + bank_in) - (cap_out + bank_out)

    cash_in_total  = _dec(inflow_sales) + _dec(cap_in) + _dec(bank_in)
    cash_out_total = _dec(outflow_expenses) + _dec(invest_out) + _dec(cap_out) + _dec(bank_out)

    # ---------- Beginning / Ending Cash ----------
    # beginning = balances up to the day BEFORE 'start'
    begin_ref = start.fromordinal(start.toordinal() - 1)
    cash_begin = _capital_agg_until(account_id, begin_ref) + _bank_agg_until(account_id, begin_ref)

    net_change = operating + investing + financing
    cash_end   = cash_begin + net_change

    # optional detail lines to show in the app
    lines = [
        {"section": "Operating", "label": "Cash Sales",                 "amount": _dec(inflow_sales)},
        {"section": "Operating", "label": "Operating Expenses",         "amount": -_dec(outflow_expenses)},
        {"section": "Investing", "label": "Asset Purchases (Payables)", "amount": -_dec(invest_out)},
        {"section": "Financing", "label": "Owner Deposits",             "amount": _dec(cap_in)},
        {"section": "Financing", "label": "Owner Withdrawals",          "amount": -_dec(cap_out)},
        {"section": "Financing", "label": "Bank Deposits",              "amount": _dec(bank_in)},
        {"section": "Financing", "label": "Bank Withdrawals",           "amount": -_dec(bank_out)},
    ]

    payload = {
        "start": start,
        "end":   end,
        "operating":  operating,
        "investing":  investing,
        "financing":  financing,
        "net_change": net_change,
        "cash_begin": cash_begin,
        "cash_end":   cash_end,
        "cash_in_total":  cash_in_total,   # NEW
        "cash_out_total": cash_out_total,  # NEW
        "lines":      lines,

    }
    return CashFlowSerializer(payload).data