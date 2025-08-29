# accounts/serializers.py
from datetime import date
from decimal import Decimal

from django.utils import timezone  # type: ignore
from django.db.models import Sum # type: ignore
from rest_framework import serializers  # type: ignore

from decimal import Decimal
from rest_framework import serializers # type: ignore
from .models import Product, StockIn

from .models import (
    Account, CapitalTransaction, Expense, Product, Sale, SaleItem,
    StockIn, SalesCash, Customer, SalesCredit
)


class AccountSerializer(serializers.ModelSerializer):
    # FIX: let DRF read the model's @property full_name
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = Account
        fields = ['id', 'first_name', 'middle_name', 'last_name', 'phone_number', 'pin', 'full_name']


# ADD CAPITAL

class CapitalTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapitalTransaction
        fields = '__all__'


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
        quantity = validated_data['quantity']
        purchase_price = validated_data['purchase_price']
        markup_rate = validated_data['markup_rate']
        image = validated_data.get('image')

        # find or create product
        product = Product.objects.filter(
            account_id=account_id,
            product_name__iexact=normalized_name,
            category=category
        ).first()

        if not product:
            selling_price = purchase_price * (Decimal(1) + Decimal(markup_rate) / Decimal(100))
            product = Product.objects.create(
                account_id=account_id,  
                product_name=normalized_name,
                category=category,
                selling_price=selling_price
            )

        # create StockIn (IMPORTANT: attach account_id)
        StockIn.objects.create(
            account_id=account_id,                 # ← ensures the signal creates Expense for this account
            product=product,
            quantity=quantity,
            remaining_quantity=quantity,
            purchase_price=purchase_price,
            markup_rate=markup_rate,
            image=image
        )

        return product





class SalesCashSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(write_only=True)
    quantity = serializers.IntegerField(write_only=True)
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, write_only=True)

    class Meta:
        model = SalesCash
        fields = ['product_name', 'quantity', 'selling_price', 'or_num', 'sale', 'date']

    def create(self, validated_data):
        product_name = validated_data.pop('product_name')
        quantity = validated_data.pop('quantity')
        selling_price = validated_data.pop('selling_price')  # treated as you originally did

        # Look up product
        product = Product.objects.filter(product_name__iexact=product_name).first()
        if not product:
            raise serializers.ValidationError({"product_name": "Product does not exist."})

        # Check stock via StockIn
        batches = StockIn.objects.filter(product=product, remaining_quantity__gt=0).order_by('created_at')
        total_available = sum(b.remaining_quantity for b in batches)
        if total_available < quantity:
            raise serializers.ValidationError({"quantity": f"Only {total_available} items left in stock."})

        # Create Sale (no 'account' field on Sale model)
        sale = Sale.objects.create(
            product=product,                 # legacy fields kept for compatibility
            quantity=quantity,
            selling_price=selling_price,
            sale_type='cash',
            created_at=timezone.now()
        )

        # FIFO deduct from batches + create SaleItem lines
        q = int(quantity)
        for batch in batches:
            if q == 0:
                break
            take = min(q, batch.remaining_quantity)

            # Use provided selling_price as the unit price (matches your existing behavior)
            SaleItem.objects.create(
                sale=sale,
                stockin=batch,
                quantity=take,
                unit_price=selling_price
            )

            batch.remaining_quantity -= take
            batch.save(update_fields=['remaining_quantity'])
            q -= take

        # Create SalesCash row (keeps your original 'amount' behavior)
        sales_cash = SalesCash.objects.create(
            sale=sale,
            product=product,
            amount=selling_price,                    # ← matches your original code
            quantity=quantity,
            date=validated_data.get(('date', dt_date.today())), # type: ignore
            or_num=validated_data.get('or_num', f"OR-{timezone.now().timestamp()}")
        )
        return sales_cash


# For Utang Add New Customer to the List
class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'


class SaleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleItem
        fields = ['stockin', 'quantity', 'unit_price']



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
        selling_price = validated_data.get('selling_price')
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

        # Total charge (for credit limit check)
        total_cost = selling_price * quantity
        if customer.credit_limit < total_cost:
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

        # Create SalesCredit row (keeps your original 'amount' behavior)
        SalesCredit.objects.create(
            sale=sale,
            product=product,
            customer=customer,
            amount=selling_price,     # ← if you want total, change to selling_price * quantity
            quantity=quantity,
            status=0,
            credit_date=dt_date.today(), # type: ignore
            paid_date=None,
            or_num=or_num,
            due_date=due_date,
        )

        # Deduct customer credit_limit (you were doing this)
        customer.credit_limit -= total_cost
        customer.save(update_fields=['credit_limit'])

        return {
            "sale_id": sale.id,
            "remaining_credit": float(customer.credit_limit),
            "due_date": due_date
        }

    

class DeleteInventorySerializer(serializers.Serializer):
    stockin_id = serializers.IntegerField()
    quantity = serializers.IntegerField()
    reason = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    account_id = serializers.IntegerField()



class StockInBatchSerializer(serializers.ModelSerializer):
    stockin_date = serializers.DateTimeField(format='%Y-%m-%d', read_only=True)
    product_name = serializers.CharField(source='product.product_name', read_only=True)

    class Meta:
        model = StockIn
        fields = ['id', 'created_at', 'remaining_quantity', 'purchase_price', 'markup_rate', 'product_name']


class BatchSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")  # or your desired format

    class Meta:
        model = StockIn  # or Batch
        fields = ['id', 'product', 'remaining_quantity', 'purchase_price', 'created_at','markup_rate',]


    
#New Add for AddSales 06-24-25

# ✅ FIXED ProductSerializer

class ProductSerializer(serializers.ModelSerializer):
    quantity = serializers.SerializerMethodField()  # ✅ Use method, not source='stock'
    purchase_price = serializers.SerializerMethodField()
    markup_rate = serializers.SerializerMethodField()
    selling_price = serializers.SerializerMethodField()
    category = serializers.CharField(read_only=True)
    image = serializers.ImageField(read_only=True) 

    class Meta:
        model = Product
        fields = [
            'id', 'product_name', 'category', 'quantity',
            'purchase_price', 'markup_rate', 'selling_price','image'
        ]

    def get_quantity(self, obj):
        total_quantity = StockIn.objects.filter(product=obj).aggregate(
        total=Sum('remaining_quantity')
    )['total'] or 0
        return int(total_quantity)


    def get_purchase_price(self, obj):
        latest_stockin = StockIn.objects.filter(product=obj).order_by('-created_at').first()
        return latest_stockin.purchase_price if latest_stockin else 0.00

    def get_markup_rate(self, obj):
        latest_stockin = StockIn.objects.filter(product=obj).order_by('-created_at').first()
        return latest_stockin.markup_rate if latest_stockin else 0.00

    def get_selling_price(self, obj):
        latest_stockin = StockIn.objects.filter(product=obj).order_by('-created_at').first()
        if latest_stockin:
            return round(
            latest_stockin.purchase_price * (Decimal(1) + Decimal(latest_stockin.markup_rate) / Decimal(100)),
            2
        )
        return Decimal("0.00")



    
# EXPENSES

class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = '__all__'


# EDITING STOCK IN MISTAKE STOCK IN OR ETC

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
    

# UTANG / DEBTORS PAGE

class CreditItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.product_name')
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = SalesCredit
        fields = ['product_name', 'quantity', 'subtotal']

    def get_subtotal(self, obj):
        return obj.quantity * obj.amount


class CreditTransactionSerializer(serializers.Serializer):
    credit_date = serializers.DateField()
    items = CreditItemSerializer(many=True)


class AccountNameSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    middle_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        # Combine names with spaces, ignoring 'N/A' middle name if you want
        middle = '' if obj.middle_name == 'N/A' else f' {obj.middle_name} '
        return f"{obj.first_name}{middle}{obj.last_name}"

class FullNameSecureUpdateSerializer(serializers.Serializer):
    pin = serializers.RegexField(regex=r'^\d{4}$', max_length=4)
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100)

