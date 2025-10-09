# accounts/serializers.py
from datetime import date, time as dtime, datetime as dt_datetime, time as dt_time
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone  # type: ignore
from django.db.models import Sum, Case, When, F, DecimalField  # type: ignore
from django.db.models.functions import Coalesce
from rest_framework import serializers  # type: ignore
from rest_framework.exceptions import ValidationError


from .models import (
    Account, CapitalTransaction, Expense, Product, Sale, SaleItem,
    StockIn, SalesCash, Customer, SalesCredit, Payable, PayablePayment
)

# ==========================
# ACCOUNT
# ==========================

class AccountSerializer(serializers.ModelSerializer):
    # Let DRF read the model's @property full_name
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = Account
        fields = ['id', 'first_name', 'middle_name', 'last_name', 'phone_number', 'pin', 'full_name']


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
            created_at=timezone.now()
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
            or_num=validated_data.get('or_num', f"OR-{timezone.now().timestamp()}")
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

        # Create SalesCredit row
        # Your current behavior: amount = unit price; subtotal = quantity * amount in serializer
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
            'id', 'account', 'supplier_name',
            'original_amount', 'remaining_amount',
            'due_date', 'note', 'is_paid',
            'created_at', 'updated_at'
        ]
    read_only_fields = ['id', 'created_at', 'updated_at']


class PayableCreateSerializer(serializers.ModelSerializer):
    # extra field for downpayment
    downpayment = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=0
    )

    class Meta:
        model = Payable
        fields = ['account', 'supplier_name', 'original_amount',
                  'due_date', 'note', 'downpayment']

    def create(self, validated_data):
        # pop downpayment if present
        down = validated_data.pop('downpayment', 0) or 0
        p = Payable(**validated_data)

        # compute remaining balance
        p.remaining_amount = p.original_amount - down
        if p.remaining_amount <= 0:
            p.remaining_amount = Decimal('0.00')
            p.is_paid = True
        p.save()

        # If downpayment > 0 → create a PayablePayment + CapitalTransaction
        if down > 0:
            PayablePayment.objects.create(
                payable=p,
                amount=down,
                date=date.today(),
                note="Downpayment"
            )
            CapitalTransaction.objects.create(
                account=p.account,
                transaction_type="withdraw",
                amount=down,
                remarks=f"Downpayment for {p.supplier_name} ({p.note})"
            )

        return p


class PayablePaymentSerializer(serializers.ModelSerializer):
    # Optional label to show in the cash ledger "Payment - <item_label>"
    item_label = serializers.CharField(write_only=True, required=False, allow_blank=True)

    # Read-only extras so the client can refresh UI immediately
    new_balance = serializers.SerializerMethodField(read_only=True)
    transaction = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PayablePayment
        fields = ['id', 'payable', 'amount', 'date', 'note', 'created_at',
                  'item_label', 'new_balance', 'transaction']
        read_only_fields = ['id', 'created_at', 'new_balance', 'transaction']

    def validate(self, attrs):
        payable = attrs['payable']
        amount = attrs['amount']
        if payable.is_paid:
            raise serializers.ValidationError("This payable is already marked as paid.")
        if amount <= 0:
            raise serializers.ValidationError("Amount must be greater than 0.")
        if amount > payable.remaining_amount:
            raise serializers.ValidationError("Payment exceeds remaining amount.")
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
                    default=0,
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )['bal'] or 0)

    def create(self, validated_data):
        # Pop write-only extras
        item_label = (validated_data.pop('item_label', '') or '').strip()

        # 1) Create the payment
        payment = super().create(validated_data)

        # 2) Update the payable
        p = payment.payable
        p.remaining_amount = p.remaining_amount - payment.amount
        if p.remaining_amount <= 0:
            p.remaining_amount = Decimal('0.00')
            p.is_paid = True
        p.save(update_fields=['remaining_amount', 'is_paid', 'updated_at'])

        # 3) Mirror to cash ledger as WITHDRAW
        label = item_label or p.supplier_name
        # Align the ledger timestamp to the payment date (start of day, aware)
        pay_dt = dt_datetime.combine(payment.date, dt_time.min)

        tx = CapitalTransaction.objects.create(
            account=p.account,
            amount=payment.amount,
            transaction_type='withdraw',
            remarks=f"Payment - {label}",
            date=pay_dt
        )

        # 4) Cache for SerializerMethodField getters
        self._tx = tx
        self._new_balance = self._compute_cash_balance(account_id=p.account_id)

        return payment

    # === Read-only fields for response ===
    def get_new_balance(self, obj):
        # Prefer cached value from create(); fallback compute (e.g., when used for GET)
        if hasattr(self, '_new_balance'):
            return float(self._new_balance)
        p = obj.payable
        return float(self._compute_cash_balance(account_id=p.account_id))

    def get_transaction(self, obj):
        # Small preview block for client UI
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
