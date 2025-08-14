import uuid
from rest_framework.decorators import api_view # type: ignore # ✅ Correct import
from rest_framework.response import Response # type: ignore # ✅ Correct import
from rest_framework import status # type: ignore # ✅ Correct import
from django.utils import timezone  # type: ignore # ✅ Correct import
from .models import Account, CapitalTransaction, Expense, Product, SaleItem, StockIn, SalesCash, Sale ,SalesCredit, Customer, Account
from .serializers import AccountSerializer,BatchSerializer, AddProductStockInSerializer, CapitalTransactionSerializer, CustomerSerializer, DeleteInventorySerializer, ProductSerializer, SalesCashSerializer, SalesCreditRecordSerializer,AccountNameSerializer,ExpenseSerializer, UpdateStockInSerializer
from datetime import date, time,datetime
from rest_framework import viewsets, generics # type: ignore # ✅ Correct import
from django.db.models import Sum # type: ignore
from . import serializers
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import api_view, parser_classes
from django.utils.dateparse import parse_date
from django.http import JsonResponse
from django.shortcuts import render
# ✅ Add Product and Stock-In (combined API)
from django.db import transaction
from rest_framework.exceptions import ValidationError


from decimal import Decimal


# THIS VIEW FOR CREATING ACCOUNT PAGE ( CREATE ACCOUNT ) -----------------------------------------------------------------------------------------------------------------------------
@api_view(['POST'])
def create_account(request):
    serializer = AccountSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# THIS VIEW FOR LOGIN ( LOG IN ) ------------------------------------------------------------------------------------------------------------------------------------------------------
@api_view(['POST'])
def login(request):
    phone = request.data.get('phone_number')
    pin = request.data.get('pin')
    try:
        account = Account.objects.get(phone_number=phone, pin=pin)
        serializer = AccountSerializer(account)
        return Response(serializer.data)
    except Account.DoesNotExist:
        return Response('Invalid PIN', status=401)


# THIS VIEW FOR LOG IN ACCOUNT ( LOG IN ) ---------------------------------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def get_account(request, phone_number):
    try:
        account = Account.objects.get(phone_number=phone_number)
        serializer = AccountSerializer(account)
        return Response(serializer.data)
    except Account.DoesNotExist:
        return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)
    
    

# THIS VIEW FOR GETTING THE AVAILABLE BALANCE ( CAPITAL MANAGEMENT ) --------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def get_current_capital_balance(request):
    deposits = CapitalTransaction.objects.filter(transaction_type__iexact='deposit').aggregate(Sum('amount'))['amount__sum'] or 0
    withdrawals = CapitalTransaction.objects.filter(transaction_type__iexact='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0
    balance = deposits - withdrawals

    return Response({'balance': float(balance)})




# ADD CAPITAL
class CapitalTransactionListCreateView(generics.ListCreateAPIView):
    queryset = CapitalTransaction.objects.all().order_by('-date')
    serializer_class = CapitalTransactionSerializer

    def perform_create(self, serializer):
        transaction_type = serializer.validated_data['transaction_type']
        amount = serializer.validated_data['amount']

        # Get current balance
        deposits = CapitalTransaction.objects.filter(transaction_type='deposit').aggregate(Sum('amount'))['amount__sum'] or 0
        withdrawals = CapitalTransaction.objects.filter(transaction_type='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0
        balance = deposits - withdrawals

        if transaction_type == 'withdraw':
            if amount > balance:
                raise serializers.ValidationError("❌ Insufficient capital for this withdrawal.")

        serializer.save()


    



# THIS VIEW FOR STOCK IN PRODUCTS ( STOCK - IN ) ----------------------------------------------------------------------------------------------------------------------------------------
@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])  # 👈 Required for image upload
def add_product_with_stockin(request):
    print("FILES received:", request.FILES)
    print("Image:", request.FILES.get('image'))

    serializer = AddProductStockInSerializer(data=request.data)

    if serializer.is_valid():
        try:
            with transaction.atomic():
                # ✅ Save product and stockin using serializer
                product = serializer.save()

                # ✅ Save product image if not yet set
                image = request.FILES.get('image')
                if image and not product.image:
                    product.image = image
                    product.save()

                # ✅ Find latest stockin for cost calculation
                latest_stockin = StockIn.objects.filter(product=product).order_by('-created_at').first()
                if not latest_stockin:
                    return Response({"error": "Stock-in not found after saving."}, status=500)

                # ✅ Capital validation
                total_cost = latest_stockin.purchase_price * latest_stockin.quantity

                deposits = CapitalTransaction.objects.filter(transaction_type='deposit').aggregate(Sum('amount'))['amount__sum'] or 0
                withdrawals = CapitalTransaction.objects.filter(transaction_type='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0
                balance = deposits - withdrawals

                if total_cost > balance:
                    raise ValidationError("❌ Not enough capital to stock this product.")

                # ✅ Deduct from capital
                CapitalTransaction.objects.create(
                    amount=total_cost,
                    transaction_type='withdraw',
                    remarks=f"Stock-in: {product.product_name}"
                )

                return Response({"message": "✅ Product added and capital deducted."}, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response({"error": str(e.detail[0])}, status=400)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




@api_view(['GET'])
def inventory_list(request):
    stockins = StockIn.objects.select_related('product').all()
    serializer = ProductSerializer(stockins, many=True)
    return Response(serializer.data)


# THIS VIEW FOR LIST OF ALL PRODUCT ( RECORD SALES ) -----------------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def product_list(request):
    keyword = request.GET.get('search', '')
    products = Product.objects.all()

    if keyword:
        products = products.filter(product_name__icontains=keyword)

    serializer = ProductSerializer(products.order_by('product_name'), many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


# THIS VIEW FOR MANAGE INVENTORY PAGE ( MANAGE INVENTORY ) ----------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def manage_inventory_view(request):
    products = Product.objects.all().order_by('product_name')
    inventory_data = []

    for product in products:
        # Sum only remaining stocks > 0
        total_stock_agg = StockIn.objects.filter(product=product, remaining_quantity__gt=0).aggregate(
            total=Sum('remaining_quantity'))
        total_stock = total_stock_agg['total'] if total_stock_agg['total'] is not None else 0

        # Filter stocks with remaining_quantity > 0
        stocks = StockIn.objects.filter(product=product, remaining_quantity__gt=0).order_by('-created_at')

        batches = []
        for stock in stocks:
            selling_price = round(
                stock.purchase_price * (Decimal('1') + (Decimal(str(stock.markup_rate)) / Decimal('100'))), 2
            )
            batches.append({
                "batch_id": stock.id,
                "purchase_price": float(stock.purchase_price),
                "selling_price": float(selling_price),
                "stock": stock.remaining_quantity,
                "created_at": stock.created_at.strftime('%Y-%m-%d')
            })

        latest_stock = stocks.first()
        if latest_stock:
            purchase_price = latest_stock.purchase_price
            markup_rate = latest_stock.markup_rate
            markup_decimal = Decimal(markup_rate) / Decimal('100')
            selling_price = round(purchase_price * (Decimal('1') + markup_decimal), 2)
        else:
            purchase_price = Decimal('0')
            markup_rate = Decimal('0')
            selling_price = Decimal('0')

        inventory_data.append({
            'id': product.id,
            'product_name': product.product_name,
            'category': product.category,
            'purchase_price': float(purchase_price),
            'markup_rate': float(markup_rate),
            'selling_price': float(selling_price),
            'quantity': int(total_stock),
            'batches': batches
        })

    return Response(inventory_data)



@api_view(['PUT'])
def update_product_category(request, product_id):
    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=404)

    new_category = request.data.get('category', '').strip()
    if new_category:
        product.category = new_category
        product.save()
        return Response({'message': 'Product category updated successfully'}, status=200)

    return Response({'error': 'No valid category provided'}, status=400)


    
# THIS VIEW FOR DELETING PRODUCT EXPIRED OR DAMAGE ( MANAGE INVENTORY ) ----------------------------------------------------------------------------------------------------------------
@api_view(['POST'])
def delete_inventory(request):
    serializer = DeleteInventorySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    stockin_id = data['stockin_id']
    quantity = data['quantity']
    reason = data['reason']
    amount = data['amount']
    account_id = data['account_id']

    try:
        stock_batch = StockIn.objects.get(id=stockin_id)
    except StockIn.DoesNotExist:
        return Response({'error': 'Stock batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if stock_batch.remaining_quantity < quantity:
        return Response({'error': 'Not enough stock in selected batch to delete.'}, status=status.HTTP_400_BAD_REQUEST)

    # Deduct quantity
    stock_batch.remaining_quantity -= quantity
    stock_batch.save()

    product = stock_batch.product

    # Record expense
    Expense.objects.create(
        account_id=account_id,
        product=product,
        amount=amount,
        category="Deleted Product",
        description=f"Reason: {reason}"
    )

    # Deduct from capital
    CapitalTransaction.objects.create(
        amount=amount,
        transaction_type='withdraw',
        remarks=f"Deleted product: {product.product_name} - {reason}"
    )

    return Response({'message': 'Deleted quantity from batch and recorded expense.'}, status=status.HTTP_200_OK)




# THIS VIEW FOR RECORD EXPENSES BILLS, UTILITIES ETC ( RECORD EXPENSES ) ---------------------------------------------------------------------------------------------------------------
@api_view(['POST'])
def record_expense(request):
    try:
        account_id = request.data.get('account_id')
        amount = request.data.get('amount')
        category = request.data.get('category')
        description = request.data.get('description')
        receipt = request.FILES.get('receipt')  # optional

        # Basic validation
        if not all([account_id, amount, category, description]):
            return Response({'error': 'Missing required fields'}, status=status.HTTP_400_BAD_REQUEST)

        # Get account
        account = Account.objects.get(id=account_id)

        # Create Expense record
        Expense.objects.create(
            account=account,
            amount=amount,
            category=category,
            description=description,
            receipt=receipt
        )

        # Deduct from capital
        CapitalTransaction.objects.create(
            amount=amount,
            transaction_type='withdraw',
            remarks=f"Expense: {category} - {description}"
        )

        return Response({'message': 'Expense recorded and capital deducted.'}, status=status.HTTP_201_CREATED)

    except Account.DoesNotExist:
        return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
def list_expenses(request):
    expenses = Expense.objects.all().order_by('-created_at')
    serializer = ExpenseSerializer(expenses, many=True)
    return Response(serializer.data)


# FOR RECORD SALE PAGE

from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from decimal import Decimal
import time

from .models import (
    Product,
    Sale,
    SalesCash,
    SalesCredit,
    CapitalTransaction,
    Customer
)

# THIS VIEW FOR RECORDING SALES ( RECORD SALES ) -----------------------------------------------------------------------------------------------------------------------------------------
@api_view(['POST'])
def record_sale(request):
    sale_type = request.data.get('sale_type', 'cash').lower()
    account_id = request.data.get('account_id')
    or_num = request.data.get('or_num') or f"OR{int(time.time())}"
    products_data = request.data.get('products')
    customer_data = request.data.get('customer_data')
    today = timezone.now().date()
    due_date_str = customer_data.get("due_date") if customer_data else None


    due_date = None
    if due_date_str:
        try:
         due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
         return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)



    # ✅ Step 1: Load or create customer if UTANG
    customer = None
    if sale_type == 'utang':
        if not customer_data:
            return Response({'error': 'Customer data required for utang sale'}, status=400)

        customer_id = customer_data.get('id')
        if customer_id:
            try:
                customer = Customer.objects.get(id=customer_id)
            except Customer.DoesNotExist:
                return Response({'error': 'Customer not found with given ID'}, status=400)
        else:
            first_name = customer_data.get('first_name', '').strip()
            last_name = customer_data.get('last_name', '').strip()
            contact_num = customer_data.get('contact_num', '').strip()

            if not contact_num:
                return Response({'error': 'Contact number is required for new customers'}, status=400)

            customer = Customer.objects.filter(contact_num__iexact=contact_num).first()


            if not customer:
                customer = Customer.objects.create(
                    first_name=first_name or 'Unknown',
                    last_name=last_name or 'Unknown',
                    address=customer_data.get('address', '').strip(),
                    contact_num=contact_num
                )

    # ✅ Step 2: Pre-check all products and calculate total cost
    total_cost = Decimal("0.00")
    product_objs = []

    for item in products_data:
        product_name = item.get('product_name')
        quantity = int(item.get('quantity', 0))

        try:
            product = Product.objects.get(product_name=product_name)
        except Product.DoesNotExist:
            return Response({'error': f'Product {product_name} not found'}, status=400)

        # FIFO: Check stock availability from StockIn batches
        stock_batches = StockIn.objects.filter(product=product, remaining_quantity__gt=0).order_by('created_at')
        total_available = sum(batch.remaining_quantity for batch in stock_batches)

        if total_available < quantity:
            return Response({'error': f'Insufficient stock for {product_name}'}, status=400)

        product_objs.append((product, quantity, stock_batches))

    # ✅ Step 3: If UTANG, calculate total cost based on FIFO prices
    if sale_type == 'utang':
        simulated_total = Decimal("0.00")
        for product, quantity, batches in product_objs:
            q = quantity
            for batch in batches:
                if q == 0:
                    break
                deduct = min(q, batch.remaining_quantity)
                unit_price = Decimal(batch.purchase_price) + (Decimal(batch.purchase_price) * Decimal(batch.markup_rate) / 100)
                simulated_total += unit_price * deduct
                q -= deduct

        if customer.credit_limit < simulated_total:
            return Response({
                'error': f"Insufficient credit. Remaining: ₱{customer.credit_limit:,.2f}, Required: ₱{simulated_total:,.2f}"
            }, status=400)

    # ✅ Step 4: Create Sale and deduct stock from FIFO batches
    for product, quantity, stock_batches in product_objs:
        sale = Sale.objects.create(
            product=product,
            quantity=quantity,
            selling_price=0,  # Not used when batching
            sale_type=sale_type,
            customer=customer if sale_type == 'utang' else None
        )

        q = quantity
        for batch in stock_batches:
            if q == 0:
                break
            deduct = min(q, batch.remaining_quantity)
            unit_price = Decimal(batch.purchase_price) + (Decimal(batch.purchase_price) * Decimal(batch.markup_rate) / 100)

            # 📆 Save SaleItem
            SaleItem.objects.create(
                sale=sale,
                stockin=batch,
                quantity=deduct,
                unit_price=unit_price

            )

            batch.remaining_quantity -= deduct
            batch.save()

            total = unit_price * deduct



            if sale_type == 'utang':

                SalesCredit.objects.create(
                    sale=sale,
                    product=product,
                    customer=customer,
                    due_date=due_date, # type: ignore
                    amount=total,
                    quantity=deduct,
                    status=0,
                    credit_date=today,
                    or_num=or_num,
                )
            else:
                SalesCash.objects.create(
                    sale=sale,
                    product=product,
                    amount=total,
                    quantity=deduct,
                    date=today,
                    or_num=or_num
                )

                CapitalTransaction.objects.create(
                    amount=total,
                    transaction_type='deposit',
                    remarks=f"Cash Sale: {product.product_name}"
                )

            q -= deduct

    # ✅ Step 5: Deduct total cost from credit limit
    if sale_type == 'utang':
    # Recalculate unpaid credit after sale
        total_utang = SalesCredit.objects.filter(customer=customer, status=0).aggregate(total=Sum('amount'))['total'] or 0
        remaining_credit = float(customer.credit_limit - total_utang)
    else:
        remaining_credit = None

    return Response({
        'message': 'All sales recorded successfully',
        'remaining_credit': remaining_credit
    }, status=201)








@api_view(['POST'])
def create_customer(request):
    serializer = CustomerSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.all().order_by('product_name')
    serializer_class = ProductSerializer



# THIS VIEW FOR CUSTOMER PAGE/ DEBTORS PAGE ( DEBTORS ) ---------------------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def customers(request):
    customers = Customer.objects.all()
    serializer = CustomerSerializer(customers, many=True)
    return Response(serializer.data)

# CUSTOMER CREDITS
@api_view(['GET'])
def get_remaining_credit(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)

        # ✅ Fix: Sum all unpaid utang
        total_utang = SalesCredit.objects.filter(customer=customer, status=0) \
            .aggregate(total=Sum('amount'))['total'] or 0

        remaining = customer.credit_limit - total_utang

        return Response({'remaining_credit': float(remaining)}, status=200)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found'}, status=404)


@api_view(['GET'])
def customer_record(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found'}, status=404)

    sales_credits = SalesCredit.objects.filter(customer=customer)

    data = {
        "Customer": CustomerSerializer(customer).data,
        "SalesCredits": SalesCreditRecordSerializer(sales_credits, many=True).data
    }
    return Response(data)


@api_view(['GET'])
def get_product_selling_price(request, product_name):
    if not product_name:
        return Response({'error': 'Product name is required'}, status=400)

    try:
        product = Product.objects.get(product_name__iexact=product_name)
        # Get latest StockIn for that product to get purchase price and markup
        latest_stock = StockIn.objects.filter(product=product).order_by('-created_at').first()
        if not latest_stock:
            return Response({'error': 'No stock info found for product'}, status=404)

        purchase_price = latest_stock.purchase_price
        markup_rate = latest_stock.markup_rate

        selling_price = purchase_price * (1 + markup_rate / 100)
        return Response({
            'product_name': product.product_name,
            'selling_price': round(selling_price, 2)
        })
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=404)


# THIS VIEW FOR UPDATING STOCK PRICE, QUANTITY, NAME, SELLING PRICE, PURCHASE PRICE ( MANAGE INVENTORY ) ------------------------------------------------------------------------------------
@api_view(['PUT'])
def edit_stockin_batch(request, batch_id):
    try:
        stockin = StockIn.objects.get(id=batch_id)
    except StockIn.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=404)

    serializer = UpdateStockInSerializer(stockin, data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)

@api_view(['GET'])
def get_product_batches(request, product_id):
    try:
        batches = StockIn.objects.filter(product_id=product_id, remaining_quantity__gt=0).order_by('created_at')
        data = [{
            'stockin_id': batch.id,
            'stockin_date': batch.created_at.strftime('%Y-%m-%d'),
            'remaining_quantity': batch.remaining_quantity,
            'purchase_price': float(batch.purchase_price),
            'markup_rate': float(batch.markup_rate)
        } for batch in batches]
        return Response(data)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=404)
    

    
# THIS VIEW FOR GETTING THE PRODUCT BY BATCH ( MANAGE INVENTORY ) -------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def get_batches_by_product_name(request):
    product_name = request.query_params.get('product_name')
    if not product_name:
        return Response({"detail": "product_name query parameter is required"}, status=400)
    
    batches = StockIn.objects.filter(product__product_name=product_name)
    serializer = BatchSerializer(batches, many=True) # type: ignore
    return Response(serializer.data)



# EDITING PRODUCTS MISTAKE OF STOCK IN OR ETC

@api_view(['PUT'])
def update_stock_batch(request, stockin_id):
    try:
        stockin = StockIn.objects.get(id=stockin_id)

        purchase_price = request.data.get('purchase_price')
        markup_rate = request.data.get('markup_rate')
        remaining_quantity = request.data.get('remaining_quantity')

        if purchase_price is not None:
            stockin.purchase_price = Decimal(purchase_price)

        if markup_rate is not None:
            stockin.markup_rate = Decimal(markup_rate)

        if remaining_quantity is not None:
            stockin.remaining_quantity = int(remaining_quantity)

        stockin.save()
        return Response({'message': 'Stock batch updated successfully.'}, status=200)

    except StockIn.DoesNotExist:
        return Response({'error': 'Stock batch not found'}, status=404)
    except Exception as e:
        return Response({'error': str(e)}, status=500)
    
# EDITING PRODUCTS MISTAKE STOCK IN OR ETC

@api_view(['PUT'])
def update_product_name(request, product_id):
    try:
        product = Product.objects.get(id=product_id)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=404)

    new_name = request.data.get('product_name', '').strip()
    if new_name:
        product.product_name = new_name
        product.save()
        return Response({'message': 'Product name updated successfully'}, status=200)

    return Response({'error': 'No valid name provided'}, status=400)


        
# THIS VIEW FOR GETTING FULL NAME ( SETTINGS ) -------------------------------------------------------------------------------------------------------------------

@api_view(['GET'])
def get_full_name(request, phone_number):
    try:
        account = Account.objects.get(phone_number=phone_number)
        full_name = f"{account.first_name} {account.middle_name} {account.last_name}"
        return Response({"full_name": full_name}, status=status.HTTP_200_OK)
    except Account.DoesNotExist:
        return Response({"error": "Account not found."}, status=status.HTTP_404_NOT_FOUND)


# THIS VIEW FOR UPDATING FULL NAME (SETTINGS) -------------------------------------------------------------------------------------------------------------------
@api_view(['PUT'])
def update_full_name(request, phone_number):
    try:
        account = Account.objects.get(phone_number=phone_number)
    except Account.DoesNotExist:
        return Response({"error": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

    # Expecting JSON body with full_name string, e.g. "Maria Santos"
    full_name = request.data.get("full_name")
    if not full_name:
        return Response({"error": "Full name is required."}, status=status.HTTP_400_BAD_REQUEST)

    # Assuming full name has first, middle, last separated by spaces
    parts = full_name.strip().split()
    if len(parts) < 2:
        return Response({"error": "Please enter at least first and last name."}, status=status.HTTP_400_BAD_REQUEST)

    # Simple split: first, optional middle(s), last
    account.first_name = parts[0]
    account.last_name = parts[-1]
    account.middle_name = " ".join(parts[1:-1]) if len(parts) > 2 else ""

    account.save()
    return Response({"message": "Full name updated successfully."}, status=status.HTTP_200_OK)



# THIS VIEW FOR UPDATING THE PIN -------------------------------------------------------------------------------------------------------------------
@api_view(['PUT'])
def update_pin(request, phone_number):
    current_pin = request.data.get('current_pin')
    new_pin = request.data.get('new_pin')

    try:
        account = Account.objects.get(phone_number=phone_number)

        if account.pin != current_pin:
            return Response({"error": "Current PIN is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

        account.pin = new_pin
        account.save()

        return Response({"message": "PIN updated successfully."}, status=status.HTTP_200_OK)

    except Account.DoesNotExist:
        return Response({"error": "Account not found."}, status=status.HTTP_404_NOT_FOUND)
    

def revenue_report(request):
    start_date = parse_date(request.GET.get('start_date'))
    end_date = parse_date(request.GET.get('end_date'))

    if not start_date or not end_date:
        return JsonResponse({'error': 'Start date and end date are required.'}, status=400)

    # Get total from SalesCash within date range
    cash_sales_total = SalesCash.objects.filter(
        date__range=[start_date, end_date]
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Get total from paid SalesCredit within date range
    credit_sales_total = SalesCredit.objects.filter(
        credit_date__range=[start_date, end_date],
        status=1  # Only include fully paid credits
    ).aggregate(total=Sum('amount'))['total'] or 0

    total_revenue = cash_sales_total + credit_sales_total

    return JsonResponse({
        'cash_sales': round(cash_sales_total, 2),
        'paid_credit_sales': round(credit_sales_total, 2),
        'total_revenue': round(total_revenue, 2)
    })






