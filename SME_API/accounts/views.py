from collections import OrderedDict
import uuid
from rest_framework.response import Response # type: ignore # ✅ Correct import
from rest_framework import status # type: ignore # ✅ Correct import
from django.utils import timezone  # type: ignore # ✅ Correct import
from .models import Account, CapitalTransaction, Expense, Product, SaleItem, StockIn, SalesCash, Sale ,SalesCredit, Customer, Account
from .serializers import AccountSerializer,BatchSerializer, AddProductStockInSerializer, CapitalTransactionSerializer, CustomerSerializer, DeleteInventorySerializer, ProductSerializer, SalesCashSerializer, SalesCreditRecordSerializer,AccountNameSerializer,ExpenseSerializer, UpdateStockInSerializer
from datetime import date, time,datetime, time as dt_time, date as dt_date
from rest_framework import viewsets, generics # type: ignore # ✅ Correct import
from django.db.models import Sum # type: ignore
from . import serializers
from rest_framework.parsers import MultiPartParser, FormParser  # type: ignore
from rest_framework.decorators import api_view, parser_classes # type: ignore
from django.utils.dateparse import parse_date # type: ignore
from django.http import JsonResponse # type: ignore
from django.shortcuts import render # type: ignore
# ✅ Add Product and Stock-In (combined API)
from django.db import transaction # type: ignore
from rest_framework.exceptions import ValidationError # type: ignore
from django.db.models import F, Sum, DecimalField, ExpressionWrapper # type: ignore
from decimal import Decimal, ROUND_HALF_UP
import time as pytime  # only if you use time.time() elsewhere (e.g., OR numbers)
import time

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




# ADD CAPITAL ( CAPITAL MANAGEMENT ) --------------------------------------------------------------------------------------------------------------------------------------------------
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

    # ✅ make sure we have the account_id, pass it to the serializer context
    account_id = request.data.get('account_id')
    if not account_id:
        return Response({"error": "account_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    serializer = AddProductStockInSerializer(
        data=request.data,
        context={'account_id': account_id}  # 👈 important
    )

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

                # ✅ Deduct from capital (this is separate from Expense; your post_save signal writes the Expense)
                CapitalTransaction.objects.create(
                    amount=total_cost,
                    transaction_type='withdraw',
                    remarks=f"Stock-in: {product.product_name}"
                )

                return Response({"message": "✅ Product added and capital deducted."}, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response({"error": str(e.detail[0])}, status=400)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# THIS VIEW FOR INVENTORTY LIST ( MANAGE INVENTORY PAGE ) ----------------------------------------------------------------------------------------------------------------------------
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

    products = products.order_by('product_name')  # order after filtering
    serializer = ProductSerializer(products, many=True)
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



from .models import (
    Product,
    Sale,
    SalesCash,
    SalesCredit,
    CapitalTransaction,
    Customer
)

# THIS VIEW FOR RECORDING SALES ( RECORD SALES ) ----------------------------------------------------------------------------------------------------------------------------------------

@api_view(['POST'])
def record_sale(request):
    sale_type = (request.data.get('sale_type') or 'cash').lower()
    account_id = request.data.get('account_id')
    or_num = request.data.get('or_num') or f"OR{int(time.time())}"
    products_data = request.data.get('products') or []
    customer_data = request.data.get('customer_data')
    today = date.today()

    # --- Validate account_id ---
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        return Response({'error': 'account_id is required and must be an integer'}, status=400)

    # --- Validate products payload ---
    if not isinstance(products_data, list) or len(products_data) == 0:
        return Response({'error': 'products must be a non-empty list'}, status=400)

    # --- Parse due_date (utang only) ---
    due_date = None
    if sale_type == 'utang':
        due_date_str = (customer_data or {}).get('due_date')
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({'error': 'Invalid due_date format. Use YYYY-MM-DD.'}, status=400)

    # Start atomic transaction
    with transaction.atomic():
        # Step 1: Load/create customer if UTANG
        customer = None
        if sale_type == 'utang':
            if not customer_data:
                return Response({'error': 'customer_data required for utang sale'}, status=400)

            customer_id = customer_data.get('id')
            if customer_id:
                try:
                    customer = Customer.objects.get(id=customer_id)
                except Customer.DoesNotExist:
                    return Response({'error': 'Customer not found with given ID'}, status=400)
            else:
                first_name = (customer_data.get('first_name') or '').strip() or 'Unknown'
                last_name = (customer_data.get('last_name') or '').strip() or 'Unknown'
                contact_num = (customer_data.get('contact_num') or '').strip()
                address = (customer_data.get('address') or '').strip()

                if not contact_num:
                    return Response({'error': 'contact_num is required to create a new customer'}, status=400)

                customer = Customer.objects.filter(contact_num__iexact=contact_num).first()
                if not customer:
                    customer = Customer.objects.create(
                        first_name=first_name,
                        last_name=last_name,
                        address=address,
                        contact_num=contact_num
                    )

        # Step 2: Pre-check products and stock (build list of tuples for later)
        product_objs = []  # list of (product, quantity, [stock_batches])
        for item in products_data:
            # Prefer ID, fallback to name
            product_obj = None
            product_id = item.get('product_id')
            product_name = item.get('product_name')

            if product_id:
                try:
                    product_obj = Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    return Response({'error': f'Product ID {product_id} not found'}, status=400)
            else:
                if not product_name:
                    return Response({'error': 'Each product needs product_id or product_name'}, status=400)
                try:
                    product_obj = Product.objects.get(product_name=product_name)
                except Product.DoesNotExist:
                    return Response({'error': f'Product {product_name} not found'}, status=400)

            try:
                quantity = int(item.get('quantity', 0))
            except (TypeError, ValueError):
                return Response({'error': f'Invalid quantity for product {product_obj.product_name}'}, status=400)

            if quantity <= 0:
                return Response({'error': f'Quantity must be > 0 for {product_obj.product_name}'}, status=400)

            # FIFO batches with stock
            stock_batches = StockIn.objects.filter(
                product=product_obj, remaining_quantity__gt=0
            ).order_by('created_at')

            total_available = sum(b.remaining_quantity for b in stock_batches)
            if total_available < quantity:
                return Response({'error': f'Insufficient stock for {product_obj.product_name}'}, status=400)

            product_objs.append((product_obj, quantity, stock_batches))

        # Step 3: For UTANG, simulate total charge vs credit limit
        if sale_type == 'utang':
            simulated_total = Decimal('0.00')
            for product, qty, batches in product_objs:
                q = qty
                for batch in batches:
                    if q == 0:
                        break
                    deduct = min(q, batch.remaining_quantity)
                    selling = Decimal(batch.purchase_price) * (Decimal('1') + (Decimal(str(batch.markup_rate)) / Decimal('100')))
                    simulated_total += (selling * deduct)
                    q -= deduct

            if customer.credit_limit < simulated_total:
                return Response({
                    'error': f"Insufficient credit. Remaining: ₱{customer.credit_limit:,.2f}, Required: ₱{simulated_total:,.2f}"
                }, status=400)

        # Step 4: Create sales, deduct stock FIFO, and create SalesCash / SalesCredit rows
        for product, qty, stock_batches in product_objs:
            sale = Sale.objects.create(
                product=product,
                quantity=qty,
                selling_price=Decimal('0.00'),  # not used with batching
                sale_type=sale_type,
                customer=customer if sale_type == 'utang' else None
            )

            q = qty
            for batch in stock_batches:
                if q == 0:
                    break
                deduct = min(q, batch.remaining_quantity)

                # Selling price per unit from batch
                selling_unit = Decimal(batch.purchase_price) * (Decimal('1') + (Decimal(str(batch.markup_rate)) / Decimal('100')))
                line_total = (selling_unit * Decimal(deduct))

                SaleItem.objects.create(
                    sale=sale,
                    stockin=batch,
                    quantity=deduct,
                    unit_price=selling_unit
                )

                batch.remaining_quantity -= deduct
                batch.save(update_fields=['remaining_quantity'])

                if sale_type == 'utang':
                    SalesCredit.objects.create(
                        account_id=account_id,
                        sale=sale,
                        product=product,
                        customer=customer,
                        amount=line_total,
                        quantity=deduct,
                        status=0,  # unpaid
                        credit_date=today,
                        paid_date=None,
                        or_num=or_num,
                        due_date=due_date
                    )
                else:
                    SalesCash.objects.create(
                        account_id=account_id,
                        sale=sale,
                        product=product,
                        amount=line_total,
                        quantity=deduct,
                        date=today,
                        or_num=or_num
                    )
                    # Record capital inflow for cash
                    CapitalTransaction.objects.create(
                        amount=line_total,
                        transaction_type='deposit',
                        remarks=f"Cash Sale: {product.product_name}"
                    )

                q -= deduct

        # Step 5: compute remaining credit (utang only)
        remaining_credit = None
        if sale_type == 'utang':
            total_utang = SalesCredit.objects.filter(customer=customer, status=0)\
                           .aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            remaining_credit = float(customer.credit_limit - total_utang)

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
    
# THIS VIEW FOR REVENUE  REPORTS ------------------------------------------------------------------------------------------------------------------------------------

@api_view(['GET'])
def revenue_report(request):
    start_date = parse_date(request.GET.get('start_date'))
    end_date   = parse_date(request.GET.get('end_date'))
    account_id = request.GET.get('account_id')

    if not start_date or not end_date or end_date < start_date:
        return Response({'error': 'Valid start_date and end_date are required.'}, status=400)

    # CASH sales (DateField) – OK to use __range on date
    cash_qs = SalesCash.objects.filter(date__range=(start_date, end_date))
    if account_id:
        cash_qs = cash_qs.filter(account_id=account_id)
    cash_sales_total = cash_qs.aggregate(total=Sum('amount'))['total'] or 0

    # CREDIT sales recognized on credit_date (DateField) – OK
    credit_qs = SalesCredit.objects.filter(credit_date__range=(start_date, end_date))
    if account_id:
        credit_qs = credit_qs.filter(account_id=account_id)
    credit_sales_total = credit_qs.aggregate(total=Sum('amount'))['total'] or 0

    # Collections / unpaid breakdowns (DateFields) – OK
    paid_qs = SalesCredit.objects.filter(status=1, paid_date__isnull=False,
                                         paid_date__range=(start_date, end_date))
    unpaid_qs = SalesCredit.objects.filter(status=0, credit_date__range=(start_date, end_date))
    if account_id:
        paid_qs   = paid_qs.filter(account_id=account_id)
        unpaid_qs = unpaid_qs.filter(account_id=account_id)

    paid_credit_total   = paid_qs.aggregate(total=Sum('amount'))['total'] or 0
    unpaid_credit_total = unpaid_qs.aggregate(total=Sum('amount'))['total'] or 0

    # EXPENSES (DateTimeField) – use Manila-local window
    def local_bounds(d):
    # Naïve datetimes in local time because USE_TZ = False
        start_local = datetime.combine(d, dt_time.min)
        end_local   = datetime.combine(d, dt_time.max)
        return start_local, end_local

    start_dt_local, _ = local_bounds(start_date)
    _, end_dt_local   = local_bounds(end_date)


    expenses_qs = Expense.objects.all()
    if account_id:
        expenses_qs = expenses_qs.filter(account_id=account_id)
    expenses_qs = expenses_qs.filter(created_at__gte=start_dt_local,
                                     created_at__lte=end_dt_local)
    expenses_total = expenses_qs.aggregate(total=Sum('amount'))['total'] or 0

    total_revenue = (cash_sales_total or 0) + (credit_sales_total or 0)
    cogs = 0
    gross_profit = total_revenue - cogs
    net_profit   = gross_profit - (expenses_total or 0)

    return Response({
        'cash_sales':           round(float(cash_sales_total), 2),
        'credit_sales':         round(float(credit_sales_total), 2),
        'paid_credit_sales':    round(float(paid_credit_total), 2),
        'unpaid_credit_sales':  round(float(unpaid_credit_total), 2),
        'total_revenue':        round(float(total_revenue), 2),
        'cost_of_goods':        float(cogs),
        'gross_profit':         round(float(gross_profit), 2),
        'expenses':             round(float(expenses_total), 2),
        'net_profit':           round(float(net_profit), 2),
    })




# --- EXPENSES SUMMARY (for Income Statement PDF) ------------------------------
@api_view(['GET'])
def expenses_summary(request):
    start_date = request.GET.get('start_date')
    end_date   = request.GET.get('end_date')
    account_id = request.GET.get('account_id')

    if not start_date or not end_date:
        return Response({'error': 'start_date and end_date are required (YYYY-MM-DD).'}, status=400)

    start = parse_date(start_date)
    end   = parse_date(end_date)
    if not start or not end or end < start:
        return Response({'error': 'Invalid date range.'}, status=400)

    def local_bounds(d):
    # Naïve datetimes in local time because USE_TZ = False
        start_local = datetime.combine(d, dt_time.min)
        end_local   = datetime.combine(d, dt_time.max)
        return start_local, end_local


    start_dt_local, _ = local_bounds(start)
    _, end_dt_local   = local_bounds(end)

    qs = Expense.objects.all()
    if account_id:
        qs = qs.filter(account_id=account_id)

    qs = qs.filter(created_at__gte=start_dt_local,
                   created_at__lte=end_dt_local)

    rows = qs.values('category').annotate(amount=Sum('amount')).order_by('category')

    items = [{
        'name': r['category'],
        'amount': str(Decimal(r['amount'] or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    } for r in rows]

    return Response({'items': items})


# NEW: secure full-name update that requires a valid PIN
@api_view(['PUT'])
def update_full_name_secure(request, phone_number):
    try:
        account = Account.objects.get(phone_number=phone_number)
    except Account.DoesNotExist:
        return Response({"error": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

    pin    = (request.data.get("pin") or "").strip()
    first  = (request.data.get("first_name") or "").strip()
    middle = (request.data.get("middle_name") or "").strip()
    last   = (request.data.get("last_name") or "").strip()

    if not pin:
        return Response({"error": "PIN is required."}, status=400)
    if account.pin != pin:
        return Response({"error": "Invalid PIN."}, status=403)

    if not first or not last:
        return Response({"error": "First and last name are required."}, status=400)

    account.first_name  = first
    account.middle_name = middle  # may be ""
    account.last_name   = last
    account.save()

    return Response({"message": "Full name updated.",
                     "full_name": account.full_name}, status=200)





@api_view(['GET'])
def transactions_list(request):
    """
    GET /api/transactions/?account=12&start=YYYY-MM-DD&end=YYYY-MM-DD&filter=all|sales|expenses
    Newest-first across Expenses, Cash Sales, and Utang, using real timestamps.
    """
    from decimal import ROUND_HALF_UP

    account_id = request.GET.get("account")
    start_s    = request.GET.get("start")
    end_s      = request.GET.get("end")
    filt       = (request.GET.get("filter") or "all").lower()

    start = parse_date(start_s) if start_s else None
    end   = parse_date(end_s) if end_s else None

    # -------------------- SALES: CASH --------------------
    cash_qs = SalesCash.objects.select_related("product")
    if account_id:
        cash_qs = cash_qs.filter(account_id=account_id)
    if start:
        cash_qs = cash_qs.filter(created_at__date__gte=start)
    if end:
        cash_qs = cash_qs.filter(created_at__date__lte=end)
    cash_qs = cash_qs.order_by("-created_at", "-id")

    cash_list = []
    for sc in cash_qs:
        line_total = Decimal(sc.amount or 0)
        if sc.product_id and sc.quantity and sc.product and line_total == (sc.product.selling_price or 0):
            line_total *= sc.quantity

        sort_dt = sc.created_at
        desc = f"{sc.product.product_name} ({sc.quantity} pcs)" if sc.product_id else "Sale"

        cash_list.append({
            "type": "sale",
            "category": "Sale",
            "description": desc,
            "amount": float(line_total),
            "payment_method": "Cash",
            "date": sort_dt.isoformat(),
            "_sort_dt": sort_dt.timestamp(),
            "_seq": sc.id,
        })

    # -------------------- SALES: CREDIT (UTANG) --------------------
    credit_qs = SalesCredit.objects.select_related("product")
    if account_id:
        credit_qs = credit_qs.filter(account_id=account_id)
    if start:
        credit_qs = credit_qs.filter(created_at__date__gte=start)
    if end:
        credit_qs = credit_qs.filter(created_at__date__lte=end)
    credit_qs = credit_qs.order_by("-created_at", "-id")

    credit_list = []
    for cr in credit_qs:
        line_total = Decimal(cr.amount or 0)
        if cr.product_id and cr.quantity and cr.product and line_total == (cr.product.selling_price or 0):
            line_total *= cr.quantity

        base = f"{cr.product.product_name} ({cr.quantity} pcs)" if cr.product_id else "Utang Sale"
        desc = f"{base} (Paid)" if cr.status == 1 else f"{base} (Unpaid)"

        sort_dt = cr.created_at
        credit_list.append({
            "type": "sale",
            "category": "Sale",
            "description": desc,
            "amount": float(line_total),
            "payment_method": "Utang",
            "date": sort_dt.isoformat(),
            "_sort_dt": sort_dt.timestamp(),
            "_seq": cr.id,
        })

    # -------------------- EXPENSES --------------------
    exp_qs = Expense.objects.select_related("product")
    if account_id:
        exp_qs = exp_qs.filter(account_id=account_id)
    if start:
        exp_qs = exp_qs.filter(created_at__date__gte=start)
    if end:
        exp_qs = exp_qs.filter(created_at__date__lte=end)
    exp_qs = exp_qs.order_by("-created_at", "-id")

    expenses_list = []

    def _match_stockin_qty_for_expense(e):
        if not e.product_id:
            return None
        si_qs = StockIn.objects.filter(product_id=e.product_id)
        if account_id:
            si_qs = si_qs.filter(account_id=account_id)
        si_qs = si_qs.filter(created_at__date=e.created_at.date()).select_related("product")
        if not si_qs.exists():
            latest = StockIn.objects.filter(product_id=e.product_id).order_by("-created_at").first()
            if latest and latest.purchase_price:
                try:
                    return int(Decimal(e.amount) / Decimal(latest.purchase_price))
                except Exception:
                    return None
            return None
        amt = Decimal(e.amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for si in si_qs:
            total = (Decimal(si.quantity) * Decimal(si.purchase_price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if abs(total - amt) <= Decimal("0.01"):
                return si.quantity
        si_list = list(si_qs)
        si_list.sort(key=lambda si: abs((Decimal(si.quantity) * Decimal(si.purchase_price)) - amt))
        best = si_list[0] if si_list else None
        return best.quantity if best else None

    for e in exp_qs:
        is_stockin = (
            (e.category == Expense.INVENTORY_PURCHASE)
            if hasattr(Expense, "INVENTORY_PURCHASE")
            else (e.category == "Inventory Purchase")
        )
        category = "Stock-in" if is_stockin else "Expense"

        if e.product_id:
            name = e.product.product_name
            if is_stockin:
                qty = getattr(e, "quantity", None) or _match_stockin_qty_for_expense(e)
                desc = f"{name} ({qty} pcs)" if qty else name
            else:
                desc = e.description or name
        else:
            desc = e.description or e.category or "Expense"

        sort_dt = e.created_at
        expenses_list.append({
            "type": "expense",
            "category": category,
            "description": desc,
            "amount": float(e.amount or 0),
            "payment_method": None,
            "date": sort_dt.isoformat(),
            "_sort_dt": sort_dt.timestamp(),
            "_seq": e.id,
        })

    # -------------------- MERGE + FILTER + SORT --------------------
    combined = cash_list + credit_list + expenses_list

    if filt == "sales":
        combined = [x for x in combined if x["type"] == "sale"]
    elif filt == "expenses":
        combined = [x for x in combined if x["type"] == "expense"]

    combined.sort(key=lambda x: (x["_sort_dt"], x["_seq"]), reverse=True)

    for x in combined:
        x.pop("_sort_dt", None)

    return Response(combined)

# JESEL UPDATE --------------------------------------------------------------------------------------------------------------------------------

@api_view(['GET'])
def customer_debts(request, customer_id: int):
    """
    Returns sales grouped with products and sale-level due_date/status.

    status rules (per sale):
      - paid:    every line is paid (status==1) or amount<=0
      - unpaid:  every line is unpaid (status==0) and amount>0
      - partial: a mix of paid and unpaid (or some zero-amounts)
    due_date rule: the latest non-null due_date among the sale's lines.
    """
    # Important: fetch ALL credit lines (both paid and unpaid) to compute sale status correctly
    qs = (
        SalesCredit.objects
        .filter(customer_id=customer_id)
        .select_related('product', 'sale')
        .order_by('sale_id', 'id')
    )

    grouped = OrderedDict()

    for sc in qs:
        sale_id = sc.sale_id

        # unit price: prefer amount/quantity; fallback to product.selling_price
        if sc.quantity:
            unit_price = float(sc.amount or 0) / sc.quantity
        else:
            unit_price = float(sc.product.selling_price) if sc.product else 0.0

        product_item = {
            "product_name": sc.product.product_name if sc.product else "",
            "quantity": sc.quantity or 0,
            "selling_price": unit_price,
        }

        if sale_id not in grouped:
            grouped[sale_id] = {
                "sale_id": sale_id,
                "date": sc.credit_date.isoformat() if sc.credit_date else "",
                "due_date": "",        # fill after loop
                "status": "",          # fill after loop
                "products": [],
                # temp counters/holders
                "__paid": 0,
                "__unpaid": 0,
                "__due_latest": None,
            }

        g = grouped[sale_id]
        g["products"].append(product_item)

        # temp counters for status calculation
        is_paid_line = (sc.status == 1) or (float(sc.amount or 0) <= 0)
        if is_paid_line:
            g["__paid"] += 1
        else:
            g["__unpaid"] += 1

        # track the latest due_date among lines
        if sc.due_date:
            if g["__due_latest"] is None or sc.due_date > g["__due_latest"]:
                g["__due_latest"] = sc.due_date

    # finalize per-sale fields
    result = []
    for sale in grouped.values():
        paid, unpaid = sale["__paid"], sale["__unpaid"]

        if unpaid == 0:
            sale_status = "paid"
        elif paid == 0:
            sale_status = "unpaid"
        else:
            sale_status = "partial"

        sale["status"] = sale_status
        sale["due_date"] = sale["__due_latest"].isoformat() if sale["__due_latest"] else ""

        # drop temp keys
        for k in ("__paid", "__unpaid", "__due_latest"):
            sale.pop(k, None)

        result.append(sale)

    return Response(result, status=status.HTTP_200_OK) 

# Inside the 'apply_customer_payment' view: JESEL UPDATE ----------------------------------------------------------------------------------
PAID = 1
UNPAID = 0
# PARTIAL = 2  # (optional) if you add this state later

@api_view(['POST'])
def apply_customer_payment(request, customer_id: int):
    """
    Applies a payment to a customer's outstanding SalesCredit.
    Deduction is applied to the remaining total (stored in amount here).
    """
    try:
        amt = Decimal(str(request.data.get('amount', 0)))
    except Exception:
        return Response({'error': 'Invalid amount'}, status=400)

    if amt <= 0:
        return Response({'error': 'Amount must be > 0'}, status=400)

    # Only unpaid rows (where there's still an amount to cover)
    qs = (
        SalesCredit.objects
        .filter(customer_id=customer_id, amount__gt=0)
        .order_by('due_date', 'credit_date', 'id')
    )

    remaining_amt = amt
    allocations = []

    # (Optional) lock rows to avoid race conditions on concurrent payments
    # with transaction.atomic():
    for sc in qs:
        if remaining_amt <= 0:
            break

        line_remaining = Decimal(sc.amount or 0)
        applied = min(line_remaining, remaining_amt)

        new_remaining = line_remaining - applied
        sc.amount = new_remaining

        # ✅ Write an integer to the IntegerField
        if sc.amount <= 0:
            sc.status = PAID
            # (Optional) set paid_date
            # sc.paid_date = timezone.now().date()

        # If not fully paid, leave status as-is (0 = unpaid)
        sc.save(update_fields=['amount', 'status'])  # add 'paid_date' if you set it

        allocations.append({
            'sale_id': sc.sale_id,
            'applied': float(applied),
            'remaining': float(sc.amount),
            'due_date': sc.due_date.isoformat() if sc.due_date else ''
        })

        remaining_amt -= applied

    return Response({
        'allocations': allocations,
        'applied_total': float(amt - remaining_amt),
        'unapplied_balance': float(remaining_amt),
    }, status=200)







