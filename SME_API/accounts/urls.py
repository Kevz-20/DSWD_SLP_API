# accounts/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .views import CapitalTransactionListCreateView, PayableViewSet, ledger_pdf

router = DefaultRouter()
router.register(r'payables', PayableViewSet, basename='payables')

urlpatterns = [
    # Account
    path('accounts/create/', views.create_account),
    path('accounts/login/', views.login),
    path('accounts/<str:phone_number>/', views.get_account),
    path('accounts/fullname/<str:phone_number>/', views.get_full_name),
    path('accounts/fullname/update-secure/<str:phone_number>/', views.update_full_name_secure, name='update_full_name_secure'),
    path('accounts/update-pin/<str:phone_number>/', views.update_pin),

    # 🔐 Forgot PIN (needed by MAUI)
    path('auth/forgot-pin/start', views.forgot_pin_start),
    path('auth/forgot-pin/verify', views.forgot_pin_verify),
    path('auth/forgot-pin/reset', views.forgot_pin_reset),

    # Customer
    path('customers/create/', views.create_customer),
    path('customers/', views.customers),
    path('customers/<int:customer_id>/records/', views.customer_record),
    path('customers/<int:customer_id>/remaining_credit/', views.get_remaining_credit),
    path('customers/<int:customer_id>/debts/', views.customer_debts),
    path('customers/<int:customer_id>/apply-payment/', views.apply_customer_payment),

    # Products and Sales
    path('add-product-stockin/', views.add_product_with_stockin),
    path('record_sale/', views.record_sale),  # underscore matches MAUI
    path('products/', views.product_list),
    path('product-selling-price/<str:product_name>/', views.get_product_selling_price),
    path('manage-inventory/', views.manage_inventory_view),
    path('inventory/delete/', views.delete_inventory, name='delete_inventory'),
    path('product/<int:product_id>/batches/', views.get_product_batches, name='get_product_batches'),

    # Stock-in edit / batches
    path('stockin/<int:batch_id>/update/', views.edit_stockin_batch, name='edit_stockin_batch'),
    path('batches/', views.get_batches_by_product_name, name='get_batches_by_product_name'),

    # Categories
    path('categories/', views.categories_list, name='categories_list'),
    path('product/<int:product_id>/category/', views.update_product_category, name='update_product_category'),

    # Capital
    path('capital/', CapitalTransactionListCreateView.as_view(), name='capital-transactions'),
    path('capital/balance/', views.get_current_capital_balance),

    # Expenses
    path('expenses/', views.list_expenses),
    path('expenses/record/', views.record_expense),
    path('expenses/summary/', views.expenses_summary),

    # Reports
    path('revenue-report/', views.revenue_report, name='revenue-report'),
    path('transactions/', views.transactions_list, name='transactions_list'),
    path('balance-sheet/', views.balance_sheet, name='balance_sheet'),
    path('reports/ledger.pdf', ledger_pdf, name='ledger-pdf'),

    # Payables
    path('payables/summary/', views.payables_summary, name="payables_summary"),
    path('', include(router.urls)),
]
