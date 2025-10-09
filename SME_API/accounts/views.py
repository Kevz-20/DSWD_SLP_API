from collections import OrderedDict
import uuid
from rest_framework.response import Response  # type: ignore  # ✅ Correct import
from rest_framework import status  # type: ignore  # ✅ Correct import
from django.utils import timezone  # type: ignore  # ✅ Correct import
from .models import Account, CapitalTransaction, Expense, Product, SaleItem, StockIn, SalesCash, Sale, SalesCredit, Customer, Account, Payable, PayablePayment
from .serializers import AccountSerializer, BatchSerializer, AddProductStockInSerializer, CapitalTransactionSerializer, CustomerCreateSerializer, CustomerSerializer, DeleteInventorySerializer, ProductSerializer, SalesCashSerializer, SalesCreditRecordSerializer, AccountNameSerializer, ExpenseSerializer, UpdateStockInSerializer, PayableSerializer, PayableCreateSerializer, PayablePaymentSerializer
from datetime import date, time, datetime, time as dt_time, date as dt_date, timedelta
from rest_framework import viewsets, generics  # type: ignore  # ✅ Correct import
from django.db.models import Sum  # type: ignore
from . import serializers
from rest_framework.parsers import MultiPartParser, FormParser  # type: ignore
from rest_framework.decorators import api_view, parser_classes , action, permission_classes # type: ignore
from django.utils.dateparse import parse_date  # type: ignore
from django.http import JsonResponse  # type: ignore
from django.shortcuts import render  # type: ignore
# ✅ Add Product and Stock-In (combined API)
from django.db import transaction  # type: ignore
from rest_framework.exceptions import ValidationError  # type: ignore
from django.db.models import F, Sum, DecimalField, ExpressionWrapper  # type: ignore
from decimal import Decimal, ROUND_HALF_UP
import time as pytime  # only if you use time.time() elsewhere (e.g., OR numbers)
import time
from django.core.exceptions import FieldError  # type: ignore
from rest_framework.permissions import AllowAny
from django.http import HttpResponse
from .reporting import build_journal
from .pdf_ledger import render_ledger_pdf
from django.db.models.functions import Lower

def _require_account_id(request) -> int:
    aid = request.GET.get('account_id') or request.data.get('account_id')
    if not aid:
        raise ValidationError("account_id is required")
    try:
        return int(aid)
    except ValueError:
        raise ValidationError("account_id must be an integer")

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
# 08-27-2025 ---------------------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def get_current_capital_balance(request):
    account_id = request.GET.get('account_id')

    qs = CapitalTransaction.objects.all()
    if account_id:
        qs = qs.filter(account_id=account_id)

    deposits = qs.filter(transaction_type__iexact='deposit').aggregate(Sum('amount'))['amount__sum'] or 0
    withdrawals = qs.filter(transaction_type__iexact='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0
    balance = deposits - withdrawals

    return Response({'balance': float(balance)})


# ADD CAPITAL ( CAPITAL MANAGEMENT ) --------------------------------------------------------------------------------------------------------------------------------------------------
# 08-27-2025---------------------------------------------------------------------------------------------------------------------------------
class CapitalTransactionListCreateView(generics.ListCreateAPIView):
    queryset = CapitalTransaction.objects.all().order_by('-date')
    serializer_class = CapitalTransactionSerializer

    def perform_create(self, serializer):
        transaction_type = serializer.validated_data['transaction_type']
        amount = serializer.validated_data['amount']

        # get from body; accept either id or None (coerce to int/None)
        raw = self.request.data.get('account_id')
        try:
            acct = int(raw) if raw not in (None, "",) else None
        except ValueError:
            acct = None

        qs = CapitalTransaction.objects.all()
        if acct is not None:
            qs = qs.filter(account_id=acct)

        deposits = qs.filter(transaction_type='deposit').aggregate(Sum('amount'))['amount__sum'] or 0
        withdrawals = qs.filter(transaction_type='withdraw').aggregate(Sum('amount'))['amount__sum'] or 0
        balance = deposits - withdrawals

        if transaction_type == 'withdraw' and amount > balance:
            raise serializers.ValidationError("❌ Insufficient capital for this withdrawal.")

        serializer.save(account_id=acct)  # <-- IMPORTANT


# THIS VIEW FOR STOCK IN PRODUCTS ( STOCK - IN ) ----------------------------------------------------------------------------------------------------------------------------------------
@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def add_product_with_stockin(request):
    print("FILES received:", request.FILES)
    print("Image:", request.FILES.get('image'))

    account_id = request.data.get('account_id')
    if not account_id:
        return Response({"error": "account_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    serializer = AddProductStockInSerializer(
        data=request.data,
        context={'account_id': account_id}
    )

    if serializer.is_valid():
        try:
            with transaction.atomic():
                product = serializer.save()

                image = request.FILES.get('image')
                if image and not product.image:
                    product.image = image
                    product.save()

                # ✅ No capital deduction here
                return Response({"message": "✅ Product added successfully (capital unchanged)."},
                                status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response({"error": str(e.detail[0])}, status=400)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# THIS VIEW FOR INVENTORTY LIST ( MANAGE INVENTORY PAGE ) ----------------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def inventory_list(request):
    """
    GET /api/inventory/?account=12
    Returns product cards (with quantity & urls) using ProductSerializer.
    """
    account_id = request.GET.get('account') or request.GET.get('account_id')
    if not account_id:
        return Response({'error': 'account is required'}, status=400)

    products = (
        Product.objects
        .filter(account_id=account_id)
        .order_by('product_name')
    )
    # ✅ pass request so image_url/thumbnail_url are absolute when serializer builds them
    serializer = ProductSerializer(products, many=True, context={'request': request})
    return Response(serializer.data)




# THIS VIEW FOR LIST OF ALL PRODUCT ( RECORD SALES ) -----------------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def product_list(request):
    """
    GET /api/products/?account=12&search=cola
    """
    account_id = request.GET.get('account') or request.GET.get('account_id')
    if not account_id:
        return Response({'error': 'account is required'}, status=400)

    keyword = (request.GET.get('search') or '').strip()
    qs = Product.objects.filter(account_id=account_id)
    if keyword:
        qs = qs.filter(product_name__icontains=keyword)

    # ✅ include request in context so serializer can build absolute URLs
    serializer = ProductSerializer(qs.order_by('product_name'), many=True, context={'request': request})
    return Response(serializer.data, status=200)




# THIS VIEW FOR MANAGE INVENTORY PAGE ( MANAGE INVENTORY ) ----------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def manage_inventory_view(request):
    account_id = request.GET.get('account') or request.GET.get('account_id')
    if not account_id:
        return Response({'error': 'account is required'}, status=400)

    products = Product.objects.filter(account_id=account_id).order_by('product_name')
    inventory_data = []

    for product in products:
        total_stock_agg = StockIn.objects.filter(
            account_id=account_id, product=product, remaining_quantity__gt=0
        ).aggregate(total=Sum('remaining_quantity'))
        total_stock = total_stock_agg['total'] or 0

        stocks = StockIn.objects.filter(
            account_id=account_id, product=product, remaining_quantity__gt=0
        ).order_by('-created_at')

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

            latest_stock_payload = {
                "id": latest_stock.id,
                "stockin_date": latest_stock.created_at.strftime('%Y-%m-%d'),   # 👈 matches C# JSON map
                "purchase_price": float(latest_stock.purchase_price),
                "markup_rate": float(latest_stock.markup_rate),
                "remaining_quantity": int(latest_stock.remaining_quantity),
            }
        else:
            purchase_price = Decimal('0')
            markup_rate = Decimal('0')
            selling_price = Decimal('0')
            latest_stock_payload = None

        inventory_data.append({
            'id': product.id,
            'product_name': product.product_name,
            'category': product.category,
            'purchase_price': float(purchase_price),
            'markup_rate': float(markup_rate),
            'selling_price': float(selling_price),
            'quantity': int(total_stock),
            'batches': batches,
            'latest_stock': latest_stock_payload,                # 👈 now provided
            # 'created_at': product.created_at.isoformat() if hasattr(product, 'created_at') else None
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
        return Response(serializer.errors, status=400)

    data = serializer.validated_data
    stockin_id = data['stockin_id']
    quantity = data['quantity']
    reason = data['reason']
    amount = data['amount']
    account_id = data['account_id']

    try:
        stock_batch = StockIn.objects.get(id=stockin_id, account_id=account_id)
    except StockIn.DoesNotExist:
        return Response({'error': 'Stock batch not found for this account'}, status=404)

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
        account_id=account_id,  # 08-27-2025------------------------------------------------------------------------------------------------------
        amount=amount,
        transaction_type='withdraw',
        remarks=f"Deleted product: {product.product_name} - {reason}"
    )

    return Response({'message': 'Deleted quantity from batch and recorded expense.'}, status=status.HTTP_200_OK)


# THIS VIEW FOR RECORD EXPENSES BILLS, UTILITIES ETC ( RECORD EXPENSES ) -----------------------------------
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

        # ✅ Save Expense
        expense = Expense.objects.create(
            account=account,
            amount=amount,
            category=category,
            description=description,
            receipt=receipt
        )

        # ✅ Deduct from Capital (Withdraw)
        CapitalTransaction.objects.create(
            account_id=account.id,
            amount=amount,
            transaction_type='withdraw',
            remarks=f"Expense: {category} - {description}"
        )

        return Response(
            {
                'message': 'Expense recorded and deducted from capital successfully.',
                'expense_id': expense.id
            },
            status=status.HTTP_201_CREATED
        )

    except Account.DoesNotExist:
        return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def list_expenses(request):
    """
    GET /api/expenses/?account=12&start=YYYY-MM-DD&end=YYYY-MM-DD
    Returns all non–Stock-In expenses for the given account.
    """
    account_id = request.GET.get('account') or request.GET.get('account_id')
    if not account_id:
        return Response({'error': 'account is required'}, status=400)

    qs = Expense.objects.filter(account_id=account_id)

    # 🧹 Exclude stock-in related entries
    qs = qs.exclude(category__iexact='Inventory Purchase')

    start = request.GET.get('start')
    end = request.GET.get('end')
    if start:
        qs = qs.filter(created_at__date__gte=parse_date(start))
    if end:
        qs = qs.filter(created_at__date__lte=parse_date(end))

    serializer = ExpenseSerializer(qs.order_by('-created_at'), many=True)
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
    """
    POST /api/record-sale/
    Body JSON (example):
    {
      "sale_type": "cash" | "utang",
      "account_id": 12,
      "or_num": "OR123" (optional),
      "products": [
        {"product_id": 5, "quantity": 2}
        // or {"product_name": "Coke", "quantity": 2}
      ],
      "customer_data": {
        "id": 99 (optional if existing),
        "first_name": "...",
        "last_name": "...",
        "contact_num": "...",
        "address": "...",
        "due_date": "YYYY-MM-DD"
      }
    }
    """
    from decimal import Decimal
    sale_type = (request.data.get('sale_type') or 'cash').lower()
    raw_account_id = request.data.get('account_id')
    or_num = request.data.get('or_num') or f"OR{int(time.time())}"
    products_data = request.data.get('products') or []
    customer_data = request.data.get('customer_data')
    today = date.today()

    # --- Validate account_id ---
    try:
        account_id = int(raw_account_id)
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

    # Ensure this is set for all code paths (cash/utang)
    remaining_credit = None

    with transaction.atomic():
        # Step 1: Load/create customer if UTANG
        customer = None
        if sale_type == 'utang':
            if not customer_data:
                return Response({'error': 'customer_data required for utang sale'}, status=400)

            customer_id = customer_data.get('id')
            if customer_id:
                try:
                    customer = Customer.objects.get(id=customer_id, account_id=account_id)  # scoped to account
                except Customer.DoesNotExist:
                    return Response({'error': 'Customer not found with given ID for this account'}, status=400)
            else:
                first_name = (customer_data.get('first_name') or '').strip() or 'Unknown'
                last_name  = (customer_data.get('last_name')  or '').strip() or 'Unknown'
                contact    = (customer_data.get('contact_num') or '').strip()
                address    = (customer_data.get('address') or '').strip()
                if not contact:
                    return Response({'error': 'contact_num is required to create a new customer'}, status=400)

                # Try to reuse an existing customer under the SAME account
                customer = Customer.objects.filter(contact_num__iexact=contact, account_id=account_id).first()
                if not customer:
                    customer = Customer.objects.create(
                        account_id=account_id,
                        first_name=first_name,
                        last_name=last_name,
                        address=address,
                        contact_num=contact
                    )

        # Step 2: Prepare products and validate stock (per-account + FIFO)
        product_rows = []  # [(product, qty, [batches])]
        for item in products_data:
            product_id = item.get('product_id')
            product_name = (item.get('product_name') or '').strip()

            # 🔒 Product lookup is account-scoped
            if product_id:
                try:
                    product = Product.objects.get(id=product_id, account_id=account_id)
                except Product.DoesNotExist:
                    return Response({'error': f'Product ID {product_id} not found for this account'}, status=400)
            else:
                if not product_name:
                    return Response({'error': 'Each product needs product_id or product_name'}, status=400)
                try:
                    product = Product.objects.get(product_name=product_name, account_id=account_id)
                except Product.DoesNotExist:
                    return Response({'error': f'Product {product_name} not found for this account'}, status=400)

            # quantity
            try:
                qty = int(item.get('quantity', 0))
            except (TypeError, ValueError):
                return Response({'error': f'Invalid quantity for product {product.product_name}'}, status=400)
            if qty <= 0:
                return Response({'error': f'Quantity must be > 0 for {product.product_name}'}, status=400)

            # FIFO batches (account-scoped) with stock
            batches = (
                StockIn.objects
                .filter(product=product, account_id=account_id, remaining_quantity__gt=0)
                .order_by('created_at')
            )

            available = sum(b.remaining_quantity for b in batches)
            if available < qty:
                return Response({'error': f'Insufficient stock for {product.product_name}'}, status=400)

            product_rows.append((product, qty, list(batches)))

        # Step 3: (Utang) quick credit check against simulated total
        if sale_type == 'utang' and customer:
            simulated_total = Decimal('0.00')
            for product, qty, batches in product_rows:
                needed = qty
                for batch in batches:
                    if needed == 0:
                        break
                    take = min(needed, batch.remaining_quantity)
                    unit = Decimal(batch.purchase_price) * (Decimal('1') + (Decimal(str(batch.markup_rate)) / Decimal('100')))
                    simulated_total += (unit * take)
                    needed -= take

            # Compute remaining credit (limit minus existing unpaid)
            existing_unpaid = (
                SalesCredit.objects
                .filter(customer=customer, status=0, account_id=account_id)
                .aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            )
            credit_limit = Decimal(str(customer.credit_limit or 0))
            remaining_limit = credit_limit - existing_unpaid

            if simulated_total > remaining_limit:
                return Response({
                    'error': (
                        f"Insufficient credit. Remaining: ₱{remaining_limit:,.2f}, "
                        f"Required: ₱{simulated_total:,.2f}"
                    )
                }, status=400)

        # Step 4: Create sales, deduct stock FIFO, create SalesCash / SalesCredit + capital
        for product, qty, batches in product_rows:
            sale = Sale.objects.create(
                account_id=account_id, 
                product=product,
                quantity=qty,
                selling_price=Decimal('0.00'),  # line prices are stored on SaleItem
                sale_type=sale_type,
                customer=customer if sale_type == 'utang' else None
            )

            remaining = qty
            for batch in batches:
                if remaining == 0:
                    break

                take = min(remaining, batch.remaining_quantity)
                unit_price = Decimal(batch.purchase_price) * (Decimal('1') + (Decimal(str(batch.markup_rate)) / Decimal('100')))
                line_total = (unit_price * Decimal(take))

                SaleItem.objects.create(
                    sale=sale,
                    stockin=batch,
                    quantity=take,
                    unit_price=unit_price
                )

                # Deduct FIFO stock
                batch.remaining_quantity -= take
                batch.save(update_fields=['remaining_quantity'])

                if sale_type == 'utang':
                    SalesCredit.objects.create(
                        account_id=account_id,
                        sale=sale,
                        product=product,
                        customer=customer,
                        amount=line_total,   # remaining balance for this line
                        quantity=take,
                        status=0,            # unpaid
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
                        quantity=take,
                        date=today,
                        or_num=or_num
                    )
                    # Mirror cash sale into capital as deposit
                    CapitalTransaction.objects.create(
                        account_id=account_id,
                        amount=line_total,
                        transaction_type='deposit',
                        remarks=f"Cash Sale: {product.product_name}"
                    )

                remaining -= take

        # Step 5: For utang, compute remaining credit for UX
        if sale_type == 'utang' and customer:
            total_unpaid = (
                SalesCredit.objects
                .filter(customer=customer, status=0, account_id=account_id)
                .aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            )
            remaining_credit = float(customer.credit_limit - total_unpaid)

    # outside the transaction: build response
    return Response({
        'message': 'All sales recorded successfully',
        'remaining_credit': remaining_credit  # None for cash, float for utang
    }, status=201)





@api_view(['POST'])
def create_customer(request):
    ser = CustomerCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    customer = ser.save()  # <- persists account_id
    # return the read shape the app expects
    return Response(CustomerSerializer(customer).data, status=status.HTTP_201_CREATED)



class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductSerializer

    def get_queryset(self):
        account_id = self.request.query_params.get('account') or self.request.query_params.get('account_id')
        qs = Product.objects.all()
        if account_id:
            qs = qs.filter(account_id=account_id)
        return qs.order_by('product_name')

    # ✅ make absolute URLs work here too
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx




# THIS VIEW FOR CUSTOMER PAGE/ DEBTORS PAGE ( DEBTORS ) ---------------------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def customers(request):
    account_id = request.GET.get('account') or request.GET.get('account_id')
    if not account_id:
        return Response({'error': 'account is required'}, status=400)

    qs = Customer.objects.filter(account_id=account_id).order_by('first_name', 'last_name')
    # 👇 add context with account_id so remaining_credit is computed per account
    data = CustomerSerializer(qs, many=True, context={'account_id': account_id}).data
    return Response(data)




# CUSTOMER CREDITS
@api_view(['GET'])
def get_remaining_credit(request, customer_id: int):
    account_id = _require_account_id(request)

    try:
        customer = Customer.objects.get(id=customer_id, account_id=account_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found'}, status=404)

    # Sum remaining balances (amount is per-line remaining); include PARTIAL + UNPAID
    total_utang = (SalesCredit.objects
                   .filter(customer_id=customer_id, account_id=account_id, amount__gt=0)
                   .aggregate(total=Sum('amount'))['total']) or Decimal('0.00')

    credit_limit = Decimal(customer.credit_limit or 0)
    remaining = credit_limit - total_utang
    if remaining < 0:
        remaining = Decimal('0.00')

    # pick ONE key and stick to it (see client note below)
    return Response({'remaining_credit': float(remaining)}, status=200)


@api_view(['GET'])
def customer_record(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found'}, status=404)

    account_id = request.GET.get('account') or request.GET.get('account_id')  # ⬅️ add this
    sales_credits = SalesCredit.objects.filter(customer=customer)

    data = {
        # ⬇️ pass context here too
        "Customer": CustomerSerializer(customer, context={'account_id': account_id}).data,
        "SalesCredits": SalesCreditRecordSerializer(sales_credits, many=True).data
    }
    return Response(data)



@api_view(['GET'])
def get_product_selling_price(request, product_name):
    account_id = request.GET.get('account') or request.GET.get('account_id')
    if not account_id:
        return Response({'error': 'account is required'}, status=400)
    if not product_name:
        return Response({'error': 'Product name is required'}, status=400)

    try:
        product = Product.objects.get(product_name__iexact=product_name, account_id=account_id)
        latest_stock = StockIn.objects.filter(product=product, account_id=account_id).order_by('-created_at').first()
        if not latest_stock:
            return Response({'error': 'No stock info found for product'}, status=404)

        # Decimal-safe calculation
        purchase_price = Decimal(latest_stock.purchase_price)
        markup_rate = Decimal(str(latest_stock.markup_rate)) / Decimal('100')
        selling_price = (purchase_price * (Decimal('1') + markup_rate)).quantize(Decimal('0.01'))

        return Response({
            'product_name': product.product_name,
            'selling_price': float(selling_price)
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
def get_product_batches(request):
    """
    GET /api/product-batches/?product_id=123&account=12
    Returns remaining batches (qty > 0) for the product under the given account.
    """
    account_id = request.GET.get('account') or request.GET.get('account_id')
    product_id = request.GET.get('product_id')

    if not account_id:
        return Response({'error': 'account is required'}, status=400)
    if not product_id:
        return Response({'error': 'product_id is required'}, status=400)

    try:
        # Optional: verify product belongs to this account
        product = Product.objects.get(id=product_id, account_id=account_id)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found for this account'}, status=404)

    batches = (
        StockIn.objects
        .filter(product=product, account_id=account_id, remaining_quantity__gt=0)
        .order_by('created_at')
    )

    data = [{
        'stockin_id': b.id,
        'stockin_date': b.created_at.strftime('%Y-%m-%d'),
        'remaining_quantity': b.remaining_quantity,
        'purchase_price': float(b.purchase_price),
        'markup_rate': float(b.markup_rate),
    } for b in batches]

    return Response(data, status=200)



# THIS VIEW FOR GETTING THE PRODUCT BY BATCH ( MANAGE INVENTORY ) -------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def get_batches_by_product_name(request):
    account_id = request.query_params.get('account') or request.query_params.get('account_id')
    product_name = request.query_params.get('product_name')
    if not account_id or not product_name:
        return Response({"detail": "account and product_name are required"}, status=400)

    batches = StockIn.objects.filter(
        product__product_name=product_name, account_id=account_id
    ).order_by('created_at')
    serializer = BatchSerializer(batches, many=True)
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
    end_date = parse_date(request.GET.get('end_date'))
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
        paid_qs = paid_qs.filter(account_id=account_id)
        unpaid_qs = unpaid_qs.filter(account_id=account_id)

    paid_credit_total = paid_qs.aggregate(total=Sum('amount'))['total'] or 0
    unpaid_credit_total = unpaid_qs.aggregate(total=Sum('amount'))['total'] or 0

    # EXPENSES (DateTimeField) – use Manila-local window
    def local_bounds(d):
        # Naïve datetimes in local time because USE_TZ = False
        start_local = datetime.combine(d, dt_time.min)
        end_local = datetime.combine(d, dt_time.max)
        return start_local, end_local

    start_dt_local, _ = local_bounds(start_date)
    _, end_dt_local = local_bounds(end_date)

    expenses_qs = Expense.objects.all()
    if account_id:
        expenses_qs = expenses_qs.filter(account_id=account_id)
    expenses_qs = expenses_qs.filter(created_at__gte=start_dt_local,
                                     created_at__lte=end_dt_local)
    expenses_total = expenses_qs.aggregate(total=Sum('amount'))['total'] or 0

    total_revenue = (cash_sales_total or 0) + (credit_sales_total or 0)
    cogs = 0
    gross_profit = total_revenue - cogs
    net_profit = gross_profit - (expenses_total or 0)

    return Response({
        'cash_sales': round(float(cash_sales_total), 2),
        'credit_sales': round(float(credit_sales_total), 2),
        'paid_credit_sales': round(float(paid_credit_total), 2),
        'unpaid_credit_sales': round(float(unpaid_credit_total), 2),
        'total_revenue': round(float(total_revenue), 2),
        'cost_of_goods': float(cogs),
        'gross_profit': round(float(gross_profit), 2),
        'expenses': round(float(expenses_total), 2),
        'net_profit': round(float(net_profit), 2),
    })


# --- EXPENSES SUMMARY (for Income Statement PDF) ------------------------------
@api_view(['GET'])
def expenses_summary(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    account_id = request.GET.get('account_id')

    if not start_date or not end_date:
        return Response({'error': 'start_date and end_date are required (YYYY-MM-DD).'}, status=400)

    start = parse_date(start_date)
    end = parse_date(end_date)
    if not start or not end or end < start:
        return Response({'error': 'Invalid date range.'}, status=400)

    def local_bounds(d):
        # Naïve datetimes in local time because USE_TZ = False
        start_local = datetime.combine(d, dt_time.min)
        end_local = datetime.combine(d, dt_time.max)
        return start_local, end_local

    start_dt_local, _ = local_bounds(start)
    _, end_dt_local = local_bounds(end)

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

    pin = (request.data.get("pin") or "").strip()
    first = (request.data.get("first_name") or "").strip()
    middle = (request.data.get("middle_name") or "").strip()
    last = (request.data.get("last_name") or "").strip()

    if not pin:
        return Response({"error": "PIN is required."}, status=400)
    if account.pin != pin:
        return Response({"error": "Invalid PIN."}, status=403)

    if not first or not last:
        return Response({"error": "First and last name are required."}, status=400)

    account.first_name = first
    account.middle_name = middle  # may be ""
    account.last_name = last
    account.save()

    return Response({"message": "Full name updated.",
                     "full_name": account.full_name}, status=200)

#----JESEL UPDATE 0923
#---- TRANSACTION HISTORY API ----
@api_view(['GET'])
def transactions_list(request):
    """
    GET /api/transactions/?account=12&start=YYYY-MM-DD&end=YYYY-MM-DD&filter=all|sales|expenses|capital
    Newest-first across Cash Sales, Credit (Utang), Customer Payments, Payable Payments, Expenses, and Capital Movements.
    """
    from decimal import ROUND_HALF_UP
    account_id = request.GET.get("account") or request.GET.get("account_id")
    start_s = request.GET.get("start")
    end_s = request.GET.get("end")
    filt = (request.GET.get("filter") or "all").lower()

    start = parse_date(start_s) if start_s else None
    end = parse_date(end_s) if end_s else None

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
        sort_dt = sc.created_at
        desc = f"{sc.product.product_name} ({sc.quantity} pcs)" if sc.product_id else "Sale"
        cash_list.append({
            "type": "sale",
            "category": "Sale",
            "description": desc,
            "amount": float(sc.amount or 0),
            "payment_method": "Cash",
            "date": sort_dt.isoformat(),
            "occurred_at": sort_dt.isoformat(),
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
        try:
            items = SaleItem.objects.filter(sale_id=cr.sale_id, stockin__product_id=cr.product_id)
            total_val = sum((i.unit_price or 0) * (i.quantity or 0) for i in items)
            line_total = float(total_val)
        except Exception:
            line_total = float(cr.amount or 0)

        base = f"{cr.product.product_name} ({cr.quantity} pcs)" if cr.product_id else "Utang Sale"
        desc = f"{base} (Paid)" if cr.status == 1 else f"{base} (Unpaid)"

        sort_dt = cr.created_at
        credit_list.append({
            "type": "sale",
            "category": "Sale",
            "description": desc,
            "amount": line_total,
            "payment_method": "Utang",
            "date": sort_dt.isoformat(),
            "occurred_at": sort_dt.isoformat(),
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
    for e in exp_qs:
        # 🛑 Skip Inventory Purchase (Stock-in) expenses
        is_stockin = (
            (e.category == Expense.INVENTORY_PURCHASE)
            if hasattr(Expense, "INVENTORY_PURCHASE")
            else (e.category == "Inventory Purchase")
        )
        if is_stockin:
            continue  # ← don’t include in transaction history

        desc = e.description or e.category or "Expense"
        sort_dt = e.created_at
        expenses_list.append({
            "type": "expense",
            "category": "Expense",
            "description": desc,
            "amount": float(e.amount or 0),
            "payment_method": None,
            "date": sort_dt.isoformat(),
            "occurred_at": sort_dt.isoformat(),
            "_sort_dt": sort_dt.timestamp(),
            "_seq": e.id,
        })


    # -------------------- CUSTOMER PAYMENTS (Capital deposits) --------------------
    pay_qs = CapitalTransaction.objects.filter(
        transaction_type='deposit',
        remarks__icontains='Customer payment'
    )
    if account_id:
        pay_qs = pay_qs.filter(account_id=account_id)
    if start:
        pay_qs = pay_qs.filter(date__date__gte=start)
    if end:
        pay_qs = pay_qs.filter(date__date__lte=end)
    pay_qs = pay_qs.order_by('-date', '-id')

    payments_list = []
    for ct in pay_qs:
        sort_dt = ct.date
        payments_list.append({
            "type": "sale",
            "category": "Customer Payment",
            "description": ct.remarks or "Customer payment",
            "amount": float(ct.amount),
            "payment_method": "Cash",
            "date": sort_dt.isoformat(),
            "occurred_at": sort_dt.isoformat(),
            "_sort_dt": sort_dt.timestamp(),
            "_seq": ct.id,
        })

    # -------------------- PAYABLE PAYMENTS --------------------
    pp_qs = PayablePayment.objects.select_related('payable')
    if account_id:
        pp_qs = pp_qs.filter(payable__account_id=account_id)
    if start:
        pp_qs = pp_qs.filter(created_at__date__gte=start)
    if end:
        pp_qs = pp_qs.filter(created_at__date__lte=end)
    pp_qs = pp_qs.order_by('-created_at', '-id')

    payable_payments_list = []
    for pp in pp_qs:
        sort_dt = pp.created_at
        payable_payments_list.append({
            "type": "expense",
            "category": "Payable Payment",
            "description": pp.note or f"Payment - {pp.payable.supplier_name}",
            "amount": float(pp.amount),
            "payment_method": None,
            "date": sort_dt.isoformat(),
            "occurred_at": sort_dt.isoformat(),
            "_sort_dt": sort_dt.timestamp(),
            "_seq": pp.id,
        })

    # -------------------- CAPITAL MOVEMENTS --------------------
    cap_qs = CapitalTransaction.objects.all()
    if account_id:
        cap_qs = cap_qs.filter(account_id=account_id)
    if start:
        cap_qs = cap_qs.filter(date__date__gte=start)
    if end:
        cap_qs = cap_qs.filter(date__date__lte=end)
    cap_qs = cap_qs.order_by('-date', '-id')

    capital_list = []
    for ct in cap_qs:
        sort_dt = ct.date

        # 🚨 Show ONLY manual Capital deposits/withdraws
        if ct.remarks:
            rm = ct.remarks.lower()
            if (
                "downpayment" in rm or
                "payable" in rm or
                "payment" in rm or
                "expense" in rm or
                "stock-in" in rm or
                "deleted product" in rm or
                "cash sale" in rm or
                "customer payment" in rm
            ):
                continue  # skip anything system-generated

        if ct.transaction_type == "deposit":
            sign = "+"
        else:
            sign = "-"

        capital_list.append({
            "type": "capital",
            "category": "Capital",
            "description": ct.remarks or f"Capital {ct.transaction_type}",
            "amount": float(ct.amount),
            "sign": sign,
            "payment_method": ct.transaction_type,
            "date": sort_dt.isoformat(),
            "occurred_at": sort_dt.isoformat(),
            "_sort_dt": sort_dt.timestamp(),
            "_seq": ct.id,
        })


# -------------------- MERGE + FILTER + SORT --------------------
    combined = (
        cash_list
        + credit_list
        + payments_list
        + payable_payments_list
        + expenses_list
        + capital_list
        )

    if filt == "sales":
        combined = [x for x in combined if x["type"] == "sale"]
    elif filt == "expenses":
        combined = [x for x in combined if x["type"] == "expense"]
    elif filt == "capital":
        combined = [x for x in combined if x["category"] == "Capital"]

    combined.sort(key=lambda x: (x["_sort_dt"], x["_seq"]), reverse=True)

    for x in combined:
        x.pop("_sort_dt", None)

    return Response(combined)
   

# JESEL UPDATE --------------------------------------------------------------------------------------------------------------------------------
@api_view(['GET'])
def customer_debts(request, customer_id: int):
    account_id = _require_account_id(request)
    try:
        Customer.objects.get(id=customer_id, account_id=account_id)
    except Customer.DoesNotExist:
        return Response({'error': 'Customer not found or forbidden'}, status=404)

    qs = (SalesCredit.objects
          .filter(customer_id=customer_id, account_id=account_id)
          .select_related('product', 'sale')
          .order_by('sale_id', 'id'))

    grouped = OrderedDict()

    for sc in qs:
        sale_id = sc.sale_id

        # ----- immutable unit price (unchanged) -----
        unit_price = 0.0
        try:
            items = SaleItem.objects.filter(sale_id=sale_id, stockin__product_id=sc.product_id)
            total_qty = sum(i.quantity or 0 for i in items) or 0
            if total_qty > 0:
                total_val = sum((i.unit_price or 0) * (i.quantity or 0) for i in items)
                unit_price = float(total_val / total_qty)
        except Exception:
            unit_price = 0.0
        if unit_price == 0.0 and sc.product:
            unit_price = float(sc.product.selling_price or 0)

        if sale_id not in grouped:
            grouped[sale_id] = {
                "sale_id": sale_id,
                "date": sc.credit_date.isoformat() if sc.credit_date else "",
                "due_date": "",
                "status": "",
                "products": [],
                # temp fields
                "__paid": 0,
                "__unpaid": 0,
                "__has_partial": False,     # 👈 NEW
                "__due_latest": None,
                "__remaining_sum": 0.0,
            }

        g = grouped[sale_id]
        g["products"].append({
            "product_name": sc.product.product_name if sc.product else "",
            "quantity": sc.quantity or 0,
            "selling_price": unit_price,
        })

        # accumulate remaining
        g["__remaining_sum"] += float(sc.amount or 0)

        # 👇 correct use of enum: mark partial lines
        if sc.status == SalesCredit.CreditStatus.PARTIAL:
            g["__has_partial"] = True

        # 👇 a line is paid only if status = PAID (or amount <= 0)
        is_paid_line = (sc.status == SalesCredit.CreditStatus.PAID) or (float(sc.amount or 0) <= 0)
        if is_paid_line:
            g["__paid"] += 1
        else:
            g["__unpaid"] += 1

        # latest due date
        if sc.due_date:
            if g["__due_latest"] is None or sc.due_date > g["__due_latest"]:
                g["__due_latest"] = sc.due_date

    # finalize
    result = []
    for sale in grouped.values():
        paid, unpaid = sale["__paid"], sale["__unpaid"]

        remaining_total = Decimal(str(sale["__remaining_sum"] or 0))
        TOL = Decimal("0.0049")
        if remaining_total < TOL:
            remaining_total = Decimal("0.00")

        # 👇 decide label for the card
        if remaining_total == 0:
            sale["status"] = "paid"
        elif sale["__has_partial"] or (paid > 0 and unpaid > 0):
            sale["status"] = "partial"     # <-- this drives your yellow “Partially Paid”
        else:
            sale["status"] = "unpaid"

        sale["due_date"] = sale["__due_latest"].isoformat() if sale["__due_latest"] else ""
        sale["remaining_total"] = float(remaining_total.quantize(Decimal("0.01")))

        for k in ("__paid", "__unpaid", "__has_partial", "__due_latest", "__remaining_sum"):
            sale.pop(k, None)

        # hide fully paid cards
        if remaining_total > Decimal("0.00"):
            result.append(sale)

    resp = Response(result, status=status.HTTP_200_OK)
    resp["Cache-Control"] = "no-store"
    return resp


from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import SalesCredit, CapitalTransaction


@api_view(['POST'])
def apply_customer_payment(request, customer_id: int):
    """
    Applies a payment to a customer's outstanding SalesCredit for the given account.
    Allocates oldest dues first (due_date, then credit_date, then id).
    Deducts from remaining per-line amount (SalesCredit.amount = remaining balance).
    Creates a CapitalTransaction entry for the applied amount.
    """

    # ---- validate amount ----
    try:
        amt = Decimal(str(request.data.get('amount', 0))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)

    if amt <= 0:
        return Response({'error': 'Amount must be > 0'}, status=status.HTTP_400_BAD_REQUEST)

    # ---- validate account ----
    raw_account_id = request.data.get('account_id')
    try:
        account_id = int(raw_account_id)
    except (TypeError, ValueError):
        return Response({'error': 'account_id is required and must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

    # ---- fetch open credits ----
    qs = (
        SalesCredit.objects
        .filter(customer_id=customer_id, account_id=account_id, amount__gt=0)
        .order_by('due_date', 'credit_date', 'id')
    )

    remaining_amt = amt
    allocations = []

    with transaction.atomic():
        locked = list(qs.select_for_update())

        for sc in locked:
            if remaining_amt <= 0:
                break

            line_remaining = Decimal(sc.amount or 0).quantize(Decimal('0.01'))
            if line_remaining <= 0:
                continue

            applied = min(line_remaining, remaining_amt)
            new_remaining = (line_remaining - applied).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            # Clamp tiny residuals
            if new_remaining < Decimal('0.005'):
                new_remaining = Decimal('0.00')

            sc.amount = new_remaining

            if new_remaining <= 0:
                sc.status = SalesCredit.CreditStatus.PAID
                sc.paid_date = timezone.now().date()
                update_fields = ['amount', 'status', 'paid_date']
            elif applied > 0:
                sc.status = SalesCredit.CreditStatus.PARTIAL
                update_fields = ['amount', 'status']
            else:
                update_fields = ['amount']

            sc.save(update_fields=update_fields)

            allocations.append({
                'sale_id': sc.sale_id,
                'applied': float(applied),
                'remaining': float(sc.amount),
                'due_date': sc.due_date.isoformat() if sc.due_date else ''
            })

            remaining_amt = (remaining_amt - applied).quantize(Decimal('0.01'))

        applied_total = amt - remaining_amt
        if applied_total <= 0:
            return Response({'error': 'No open balances to apply this payment.'}, status=status.HTTP_400_BAD_REQUEST)

        # ---- log into CapitalTransaction ----
        CapitalTransaction.objects.create(
            account_id=account_id,
            amount=applied_total,
            transaction_type='deposit',
            remarks=f'Customer payment (customer_id={customer_id}, account_id={account_id})'
        )

    return Response({
        'allocations': allocations,
        'applied_total': float(applied_total),
        'unapplied_balance': float(remaining_amt),
    }, status=status.HTTP_200_OK)



class PayableViewSet(viewsets.ModelViewSet):
    """
    Endpoints (via router):
      GET    /api/payables/?account=ID&search=abc&status=all|overdue|soon|paid
      POST   /api/payables/                        (create)
      PATCH  /api/payables/{id}/                   (partial update)
      POST   /api/payables/{id}/mark_paid/         (mark fully paid)
      POST   /api/payables/{id}/record_payment/    (partial payment)
    """
    queryset = Payable.objects.all().order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return PayableCreateSerializer
        return PayableSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # filter by account
        account = self.request.query_params.get('account')
        if account:
            qs = qs.filter(account_id=account)

        # search supplier
        search = (self.request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(supplier_name__icontains=search)

        # status filter
        status_f = (self.request.query_params.get('status') or 'all').lower()
        today = date.today()
        if status_f == 'overdue':
            qs = qs.filter(is_paid=False, due_date__lt=today)
        elif status_f == 'soon':
            qs = qs.filter(is_paid=False, due_date__gte=today, due_date__lte=today + timedelta(days=7))
        elif status_f == 'paid':
            qs = qs.filter(is_paid=True)
        # else: all

        return qs

    @action(detail=True, methods=['POST']) # type: ignore
    def mark_paid(self, request, pk=None):
        payable = self.get_object()
        if payable.is_paid:
            return Response({"detail": "Already paid."}, status=status.HTTP_400_BAD_REQUEST)
        payable.remaining_amount = 0
        payable.is_paid = True
        payable.save(update_fields=['remaining_amount', 'is_paid', 'updated_at'])
        return Response(PayableSerializer(payable).data)

    @action(detail=True, methods=['POST'])
    def record_payment(self, request, pk=None):
        payable = self.get_object()
        payload = request.data.copy()
        payload['payable'] = payable.id

        with transaction.atomic():  # ✅ wrap in atomic
            ser = PayablePaymentSerializer(data=payload)
            ser.is_valid(raise_exception=True)
            payment = ser.save()        

            payable.refresh_from_db()

        return Response(PayablePaymentSerializer(payment).data, status=status.HTTP_201_CREATED)



# Summary chips endpoint (function-based for simplicity)
@api_view(['GET'])
def payables_summary(request):
    """
    GET /api/payables/summary/?account=ID
    Returns: overdue / this_week / next_30_days / total_unpaid counts + amounts
    """
    account = request.query_params.get('account')
    if not account:
        return Response({"detail": "account is required"}, status=400)

    qs = Payable.objects.filter(account_id=account)
    today = date.today()
    end_week = today + timedelta(days=7)
    end_30 = today + timedelta(days=30)

    def _sum(q):
        return sum([p.remaining_amount for p in q], start=Decimal('0.00'))

    overdue_q = qs.filter(is_paid=False, due_date__lt=today)
    week_q    = qs.filter(is_paid=False, due_date__gte=today, due_date__lte=end_week)
    next30_q  = qs.filter(is_paid=False, due_date__gt=end_week, due_date__lte=end_30)
    total_q   = qs.filter(is_paid=False)

    data = {
        "overdue":       {"count": overdue_q.count(), "amount": str(_sum(overdue_q))},
        "this_week":     {"count": week_q.count(),    "amount": str(_sum(week_q))},
        "next_30_days":  {"count": next30_q.count(),  "amount": str(_sum(next30_q))},
        "total_unpaid":  {"count": total_q.count(),   "amount": str(_sum(total_q))}
    }
    return Response(data)

@api_view(["GET"])
@permission_classes([AllowAny])
def balance_sheet(request):
    """
    GET /api/balance-sheet/?account=12&as_of=YYYY-MM-DD
    Returns Assets/Liabilities/Owner's Equity.
    NOTE: We treat CapitalTransaction as your cashbook.
    """
    from decimal import Decimal
    account_id = request.GET.get("account") or request.GET.get("account_id")
    as_of_s = request.GET.get("as_of")
    as_of = parse_date(as_of_s) if as_of_s else None

    def scoped(qs):
        return qs.filter(account_id=account_id) if account_id else qs

    def as_of_date(qs, field):
        if not as_of:
            return qs
        model_field = qs.model._meta.get_field(field)
        if model_field.get_internal_type() == "DateField":
            return qs.filter(**{f"{field}__lte": as_of})
        else:
            # DateTimeField
            return qs.filter(**{f"{field}__lte": datetime.combine(as_of, datetime.max.time())})

    def _sum(qs, field="amount"):
        return qs.aggregate(total=Sum(field))["total"] or Decimal("0")

    # ---- CASH (asset) — use cashbook
    caps = scoped(CapitalTransaction.objects.all())
    caps = as_of_date(caps, "date")
    deposits = _sum(caps.filter(transaction_type="deposit"))
    withdrawals = _sum(caps.filter(transaction_type="withdraw"))
    cash = deposits - withdrawals

    # ---- Revenue (for Net Income)
    cash_sales = scoped(SalesCash.objects.all())
    cash_sales = as_of_date(cash_sales, "created_at")
    revenue_cash = _sum(cash_sales, "amount")

    credit_sales = scoped(SalesCredit.objects.all())
    credit_sales = as_of_date(credit_sales, "created_at")
    # WARNING: SalesCredit.amount is mutable (reduced by payments). This counts remaining, not original.
    revenue_credit = _sum(credit_sales, "amount")

    total_revenue = revenue_cash + revenue_credit

    # ---- COGS (approx via StockIn purchase_price * quantities sold)
    # ---- COGS (approx via StockIn purchase_price * quantities sold)
    si = SaleItem.objects.select_related("stockin", "sale")
    if account_id:
        si = si.filter(sale__account_id=account_id)   # 👈 scope to account
    if as_of:
        si = si.filter(sale__created_at__date__lte=as_of)
    cogs = si.aggregate(total=Sum(F("quantity") * F("stockin__purchase_price")))["total"] or Decimal("0")


    # ---- Operating expenses (exclude inventory purchases)
    exp = scoped(Expense.objects.all())
    exp = as_of_date(exp, "created_at")
    if hasattr(Expense, "INVENTORY_PURCHASE"):
        exp = exp.exclude(category=Expense.INVENTORY_PURCHASE)
    else:
        exp = exp.exclude(category="Inventory Purchase")
    operating_expenses = _sum(exp, "amount")

    # ---- Accounts Receivable (AR) — sum of unpaid credit lines AS OF
    ar_lines = scoped(SalesCredit.objects.filter(status=0))
    ar_lines = as_of_date(ar_lines, "created_at")
    accounts_receivable = _sum(ar_lines, "amount")

    # ---- Inventory (snapshot)
    stock = scoped(StockIn.objects.all())
    stock = as_of_date(stock, "created_at")
    inventory = stock.aggregate(
        total=Sum(F("remaining_quantity") * F("purchase_price"))
    )["total"] or Decimal("0")

    # ---- Payables (open)
    payables_open = scoped(Payable.objects.filter(is_paid=False))
    accounts_payable = payables_open.aggregate(total=Sum("remaining_amount"))["total"] or Decimal("0")

    # ---- Net income & equity
    net_income = total_revenue - cogs - operating_expenses

    # You previously called this "Capital, beginning" using deposits-withdrawals,
    # but that equals current cash when CapitalTransaction is used as a cashbook.
    # To keep your output labels, we’ll show it as deposits-withdrawals (as-of):
    capital_beginning = deposits - withdrawals

    total_equity = capital_beginning + net_income

    # ---- Totals & check
    total_assets = cash + accounts_receivable + inventory
    total_liabilities = accounts_payable
    check = total_assets - (total_liabilities + total_equity)

    return Response({
        "as_of": (as_of.isoformat() if as_of else date.today().isoformat()),
        "account_id": account_id,
        "Assets": {
            "Cash":                f"{cash:.2f}",
            "Accounts Receivable": f"{accounts_receivable:.2f}",
            "Inventory":           f"{inventory:.2f}",
            "Total Assets":        f"{total_assets:.2f}",
        },
        "Liabilities": {
            "Accounts Payable":    f"{accounts_payable:.2f}",
            "Total Liabilities":   f"{total_liabilities:.2f}",
        },
        "Owner’s Equity": {
            "Capital, beginning":  f"{capital_beginning:.2f}",
            "Add: Net Income":     f"{net_income:.2f}",
            "Total Equity":        f"{total_equity:.2f}",
        },
        "Total Liabilities + Equity": f"{(total_liabilities + total_equity):.2f}",
        "balance_check": f"{check:.2f}"
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def ledger_pdf(request):
    """
    GET /api/reports/ledger.pdf?account=12&start=YYYY-MM-DD&end=YYYY-MM-DD
    (also accepts account_id, start_date, end_date)
    """
    account_s = request.GET.get("account") or request.GET.get("account_id")
    account_id = int(account_s) if account_s else None

    # accept both start/end and start_date/end_date
    start_str = request.GET.get("start") or request.GET.get("start_date") or ""
    end_str   = request.GET.get("end")   or request.GET.get("end_date")   or ""

    start = parse_date(start_str) if start_str else None
    end   = parse_date(end_str)   if end_str   else None

    # normalize if reversed
    if start and end and end < start:
        start, end = end, start

    entries = build_journal(account_id=account_id, start=start, end=end)

    subtitle_bits = []
    if account_id: subtitle_bits.append(f"Account {account_id}")
    if start:      subtitle_bits.append(f"From {start.isoformat()}")
    if end:        subtitle_bits.append(f"To {end.isoformat()}")
    subtitle = " • ".join(subtitle_bits) if subtitle_bits else "All Transactions"

    pdf = render_ledger_pdf(entries, title="General Ledger", subtitle=subtitle)

    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="ledger.pdf"'
    return resp


@api_view(['GET'])
def categories_list(request):
    """
    GET /api/categories/?account=12
    Returns a case-insensitive, distinct, sorted list of non-empty categories
    for the given account.
    """
    account = request.GET.get('account') or request.GET.get('account_id')
    if not account:
        return Response({'error': 'account is required'}, status=400)

    qs = (Product.objects
          .filter(account_id=account)
          .exclude(category__isnull=True)
          .exclude(category__exact='')
          .order_by(Lower('category'))
          .values_list('category', flat=True)
          .distinct())

    return Response(list(qs), status=200)

