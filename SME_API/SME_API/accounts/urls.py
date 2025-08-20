from django.urls import path # type: ignore
from . import views
from .views import CapitalTransactionListCreateView 
from django.urls import path

urlpatterns = [
    # Account
    path('accounts/create/', views.create_account),
    path('accounts/login/', views.login),
    path('accounts/<str:phone_number>/', views.get_account),
    path('accounts/fullname/<str:phone_number>/', views.get_full_name),
    path('accounts/fullname/update/<str:phone_number>/', views.update_full_name),
    path('accounts/update-pin/<str:phone_number>/', views.update_pin),

    # Customer
    path('customers/create/', views.create_customer),
    path('customers/', views.customers),
    path('customers/<int:customer_id>/records/', views.customer_record),
    path('customers/<int:customer_id>/remaining_credit/', views.get_remaining_credit),

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


    #Capital
    path('capital/', CapitalTransactionListCreateView.as_view(), name='capital-transactions'),
    path('capital/balance/', views.get_current_capital_balance),

    path('expenses/', views.list_expenses),
    path('expenses/record/', views.record_expense),

    #Financial Report
    path('revenue-report/', views.revenue_report, name='revenue-report'),

    #Expense Report
    path('expenses/summary/', views.expenses_summary),

]
