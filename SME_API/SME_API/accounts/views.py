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
from django.db.models import F, Sum, DecimalField, ExpressionWrapper
from decimal import Decimal, ROUND_HALF_UP


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

# THIS VIEW FOR RECORDING SALES ( RECORD SALES ) ----------------------------------------------------------------------------------------------------------------------------------------

@api_view(['POST'])
def record_sale(request):
    sale_type = (request.data.get('sale_type') or 'cash').lower()
    account_id = request.data.get('account_id')
    or_num = request.data.get('or_num') or f"OR{int(time.time())}"
    products_data = request.data.get('products') or []
    customer_data = request.data.get('customer_data')
    today = timezone.now().date()

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
    
# THIS VIEW FOR REVENUE  REPORTS ------------------------------------------------------------------------------------------------------------------------------------

@api_view(['GET'])
def revenue_report(request):
    start_date = parse_date(request.GET.get('start_date'))
    end_date   = parse_date(request.GET.get('end_date'))
    account_id = request.GET.get('account_id')  # optional

    if not start_date or not end_date or end_date < start_date:
        return Response({'error': 'Valid start_date and end_date are required.'}, status=400)

    date_range = (start_date, end_date)

    # Revenue components
    cash_qs   = SalesCash.objects.filter(date__range=date_range)
    paid_qs   = SalesCredit.objects.filter(status=1, paid_date__isnull=False, paid_date__range=date_range)
    unpaid_qs = SalesCredit.objects.filter(status=0, credit_date__range=date_range)

    if account_id:
        cash_qs   = cash_qs.filter(account_id=account_id)
        paid_qs   = paid_qs.filter(account_id=account_id)
        unpaid_qs = unpaid_qs.filter(account_id=account_id)

    cash_sales_total    = cash_qs.aggregate(total=Sum('amount'))['total'] or 0
    paid_credit_total   = paid_qs.aggregate(total=Sum('amount'))['total'] or 0
    unpaid_credit_total = unpaid_qs.aggregate(total=Sum('amount'))['total'] or 0

    total_revenue = (cash_sales_total or 0) + (paid_credit_total or 0)

    # --- COGS (match the revenue you recognized) ---
    # COGS for cash sales within range + credit sales that were PAID within range
    cash_sale_ids = cash_qs.values_list('sale_id', flat=True)
    paid_sale_ids = paid_qs.values_list('sale_id', flat=True)

    cogs_items = SaleItem.objects.filter(sale_id__in=list(cash_sale_ids) + list(paid_sale_ids))
    cogs = cogs_items.annotate(
        line_cogs=ExpressionWrapper(
            F('quantity') * F('stockin__purchase_price'),
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )
    ).aggregate(total=Sum('line_cogs'))['total'] or 0

    # --- Expenses within range ---
    expenses_qs = Expense.objects.filter(created_at__date__range=date_range)
    if account_id:
        expenses_qs = expenses_qs.filter(account_id=account_id)
    expenses_total = expenses_qs.aggregate(total=Sum('amount'))['total'] or 0

    # --- Profits ---
    gross_profit = (total_revenue or 0) - (cogs or 0)
    net_profit   = gross_profit - (expenses_total or 0)

    return Response({
        # keep existing fields for compatibility
        'cash_sales':           round(float(cash_sales_total), 2),
        'paid_credit_sales':    round(float(paid_credit_total), 2),
        'unpaid_credit_sales':  round(float(unpaid_credit_total), 2),
        'total_revenue':        round(float(total_revenue), 2),

        # new fields used by your MAUI page
        'cost_of_goods':        round(float(cogs), 2),
        'gross_profit':         round(float(gross_profit), 2),
        'expenses':             round(float(expenses_total), 2),
        'net_profit':           round(float(net_profit), 2),
    })


# --- EXPENSES SUMMARY (for Income Statement PDF) ------------------------------
@api_view(['GET'])
def expenses_summary(request):
    """
    Returns expenses grouped by category within a date range.
    Query params:
      - start_date (YYYY-MM-DD)  [required]
      - end_date   (YYYY-MM-DD)  [required]
      - account_id               [optional]
    Response:
    {
      "items": [
        {"name": "Transportation", "amount": "150.00"},
        {"name": "Deleted Product", "amount": "75.50"}
      ]
    }
    """
    start_date = request.GET.get('start_date')
    end_date   = request.GET.get('end_date')
    account_id = request.GET.get('account_id')

    if not start_date or not end_date:
        return Response(
            {'error': 'start_date and end_date are required (YYYY-MM-DD).'},
            status=400
        )

    # base queryset
    qs = Expense.objects.all().order_by('category')

    # optional account filter
    if account_id:
        qs = qs.filter(account_id=account_id)

    # date filter on created_at's DATE part
    try:
        start = parse_date(start_date)
        end   = parse_date(end_date)
        if not start or not end or end < start:
            raise ValueError
        qs = qs.filter(created_at__date__gte=start, created_at__date__lte=end)
    except Exception:
        return Response({'error': 'Invalid date range.'}, status=400)

    # group by category and sum
    rows = qs.values('category').annotate(amount=Sum('amount')).order_by('category')

    # format output with 2 decimal places
    items = [
        {
            'name': r['category'],
            'amount': str(
                Decimal(r['amount'] or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            )
        }
        for r in rows
    ]

    return Response({'items': items})








