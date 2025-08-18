# accounts/serializers.py
from datetime import date
from rest_framework import serializers # type: ignore
from .models import Account, CapitalTransaction, Expense, Product, Sale, SaleItem, StockIn, SalesCash,Customer,SalesCredit,models
from django.utils import timezone # type: ignore
from decimal import Decimal 

class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ['id', 'first_name', 'middle_name', 'last_name', 'phone_number', 'pin']  # ✅ include "id"


# ADD CAPITAL

class CapitalTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapitalTransaction
        fields = '__all__'

from decimal import Decimal
from rest_framework import serializers
from .models import Product, StockIn

class AddProductStockInSerializer(serializers.Serializer):
    product_name = serializers.CharField(max_length=255)
    category = serializers.CharField(max_length=100)
    quantity = serializers.IntegerField()
    purchase_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    markup_rate = serializers.FloatField()
    image = serializers.ImageField(required=False, allow_null=True)  # ✅ Added

    def create(self, validated_data):
        normalized_name = validated_data['product_name'].strip().title()
        category = validated_data['category'].strip()
        quantity = validated_data['quantity']
        purchase_price = validated_data['purchase_price']
        markup_rate = validated_data['markup_rate']
        image = validated_data.get('image')  # ✅ Get image if provided

        # Check if product already exists
        product = Product.objects.filter(product_name__iexact=normalized_name, category=category).first()

        if not product:
            # Compute selling price from markup
            selling_price = purchase_price * (Decimal(1) + Decimal(markup_rate) / Decimal(100))

            # ✅ Create new product without purchase_price and markup_rate
            product = Product.objects.create(
                product_name=normalized_name,
                category=category,
                selling_price=selling_price
            )

        # ✅ Always create StockIn record
        StockIn.objects.create(
            product=product,
            quantity=quantity,
            purchase_price=purchase_price,
            markup_rate=markup_rate,
            remaining_quantity=quantity,
            image=image  # ✅ Added image here
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
        selling_price = validated_data.pop('selling_price')

        # Get the current logged-in account from context
        account = self.context['account']

        # 🔍 Check if product exists
        product = Product.objects.filter(product_name__iexact=product_name).first()
        if not product:
            raise serializers.ValidationError({"product_name": "Product does not exist."})

        # ✅ Check if product has enough stock
        if product.stock < quantity:
            raise serializers.ValidationError({
                "quantity": f"Only {product.stock} items left in stock."
            })

        # 🧮 Deduct stock
        product.stock -= quantity
        product.save()

        # 🧾 Create Sale object (Cash type)
        sale = Sale.objects.create(
            account=account,
            sale_type='cash',
            created_at=timezone.now()
        )

        # 🧾 Create SalesCash record
        sales_cash = SalesCash.objects.create(
            sale=sale,
            product=product,
            amount=selling_price,
            quantity=quantity,
            date=timezone.now().date(),
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
    due_date = serializers.DateField(required=False, allow_null=True)  # ✅ Add this Records Sales UUUUUUUUUUTAAAAAAAAANGGGGGGGGGGGGGGGGGG

    def validate_due_date(self, value):
        if value < date.today():
            raise serializers.ValidationError("Due date cannot be in the past.")
        return value

    def create(self, validated_data):
        product_name = validated_data.get('product_name')
        quantity = validated_data.get('quantity')
        selling_price = validated_data.get('selling_price')
        customer_id = validated_data.get('customer_id')
        or_num = validated_data.get('or_num', f"OR-{timezone.now().timestamp()}")
        due_date = validated_data.get('due_date')  # ✅ Get due date Sales UUUUUUUUUUUUUTTTTTTTAAAAAAANNNNNNNNNNNGGGGGGGGGGGGGG

        # ✅ Validate customer
        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            raise serializers.ValidationError({'customer_id': 'Customer not found'})

        # ✅ Validate product
        try:
            product = Product.objects.get(product_name__iexact=product_name)
        except Product.DoesNotExist:
            raise serializers.ValidationError({'product_name': 'Product not found'})

        # ✅ Check stock
        if product.stock < quantity:
            raise serializers.ValidationError({'quantity': f"Only {product.stock} items in stock"})

        # ✅ Compute total cost
        total_cost = selling_price * quantity

        # ✅ Check credit limit
        if customer.credit_limit < total_cost:
            raise serializers.ValidationError({
                'credit_limit': f"Insufficient credit limit. Remaining: {customer.credit_limit}"
            })

        # ✅ Deduct stock
        product.stock -= quantity
        product.save()

        # ✅ Deduct from customer's credit limit
        customer.credit_limit -= total_cost
        customer.save()

        # ✅ Create Sale
        sale = Sale.objects.create(
            product=product,
            quantity=quantity,
            selling_price=selling_price,
            sale_type='utang',
            customer=customer,
            created_at=timezone.now()
        )

        # ✅ Create SalesCredit
        SalesCredit.objects.create(
            sale=sale,
            product=product,
            customer=customer,
            amount=selling_price,
            quantity=quantity,
            status=0,
            credit_date=timezone.now().date(),
            due_date=due_date,  # ✅ Store due date SALESSSSSSSS UUUUUUUUUUUTAAAAAAAAAANNNNNNNNNNNNNNNNNGGGGGGGGGGG
            or_num=or_num,
        )

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
            total=models.Sum('remaining_quantity')  # type: ignore
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
    

