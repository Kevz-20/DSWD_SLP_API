from django.urls import path # type: ignore
from . import views 
from .views import CapitalTransactionListCreateView,PayableViewSet, payables_summary,ledger_pdf
from rest_framework.routers import DefaultRouter # type: ignore
from django.urls import path, include # type: ignore

router = DefaultRouter()
router.register(r'payables', PayableViewSet, basename='payables') # type: ignore

urlpatterns = [
    # Account
    path('accounts/create/', views.create_account),
    path('accounts/login/', views.login),
    path('accounts/<str:phone_number>/', views.get_account),
    path('accounts/fullname/<str:phone_number>/', views.get_full_name),
    path('accounts/fullname/update-secure/<str:phone_number>/', views.update_full_name_secure, name='update_full_name_secure'),
    path('accounts/update-pin/<str:phone_number>/', views.update_pin),

    # Customer
    path('customers/create/', views.create_customer),
    path('customers/', views.customers),
    path('customers/<int:customer_id>/records/', views.customer_record),
    path('customers/<int:customer_id>/remaining_credit/', views.get_remaining_credit),
    path('customers/<int:customer_id>/debts/', views.customer_debts), # jesel update
    path('customers/<int:customer_id>/apply-payment/', views.apply_customer_payment), # jesel update

    # Products and Sales
    path('add-product-stockin/', views.add_product_with_stockin),
    path('record_sale/', views.record_sale),
    path('products/', views.product_list),
    path('product-selling-price/<str:product_name>/', views.get_product_selling_price),
    path('manage-inventory/', views.manage_inventory_view),
    path('inventory/delete/', views.delete_inventory, name='delete_inventory'),
    path('product/<int:product_id>/batches/', views.get_product_batches, name='get_product_batches'),

    # STOCK IN EDIT BATCH
    path('stockin/<int:batch_id>/update/', views.edit_stockin_batch, name='edit_stockin_batch'),
    path('batches/', views.get_batches_by_product_name, name='get_batches_by_product_name'),


    path('categories/', views.categories_list, name='categories_list'),
    path('product/<int:product_id>/category/', views.update_product_category, name='update_product_category'),

    #Capital
    path('capital/', CapitalTransactionListCreateView.as_view(), name='capital-transactions'),
    path('capital/balance/', views.get_current_capital_balance),

    path('expenses/', views.list_expenses),
    path('expenses/record/', views.record_expense),

    #Financial Report
    path('revenue-report/', views.revenue_report, name='revenue-report'),

    #Transaction History
    path("transactions/", views.transactions_list, name="transactions_list"),

    #Expense Report
    path('expenses/summary/', views.expenses_summary),
    
    #Balance Sheet
    path('balance-sheet/', views.balance_sheet, name='balance_sheet'),

    #Ledger
    path('reports/ledger.pdf', ledger_pdf, name='ledger-pdf'),

    #Account Payable
    path('payables/summary/', views.payables_summary),
    path('', include(router.urls)),  # type: ignore
]
