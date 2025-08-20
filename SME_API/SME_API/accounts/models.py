# accounts/models.py
from django.db import models # type: ignore


# ADD CAPITAL

class CapitalTransaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [
        ('deposit', 'Deposit'),
        ('withdraw', 'Withdraw'),
    ]

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    remarks = models.TextField(blank=True, null=True)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction_type.capitalize()} - {self.amount}"

class Account(models.Model):
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=50, default='N/A')
    last_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15, unique=True)
    pin = models.CharField(max_length=4)

class Product(models.Model):
    product_name = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2) 
    image = models.ImageField(upload_to='product_images/', null=True, blank=True)  # ✅ ADD THIS LINE
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.product_name




class Sale(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    sale_type = models.CharField(max_length=10)  # 'cash' or 'utang'
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, blank=True)  # ✅ ADD THIS
    created_at = models.DateTimeField(auto_now_add=True)



class Expense(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)  # ✅ Add this
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=50)
    description = models.TextField()
    receipt = models.ImageField(upload_to='receipts/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)



class StockIn(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)  # Total added
    remaining_quantity = models.IntegerField(default=1)  # Decreases on sale
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    markup_rate = models.FloatField()
    image = models.ImageField(upload_to='uploads/', null=True, blank=True)  # ✅ ADD THIS LINE
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.product_name} @ {self.purchase_price} ({self.remaining_quantity} left)"
    
class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    stockin = models.ForeignKey(StockIn, on_delete=models.PROTECT)  # Link to batch
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.stockin.product.product_name} x{self.quantity}"



class Capital(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class SalesCash(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True)  
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    date = models.DateField()
    or_num = models.CharField(max_length=50)

class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    address = models.TextField()
    contact_num = models.CharField(max_length=20, unique=True)
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, default=1000.00) 
    

class SalesCredit(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True) 
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=1)
    status = models.IntegerField()  # 1 = paid, 0 = unpaid
    credit_date = models.DateField()
    paid_date = models.DateField(null=True, blank=True)
    or_num = models.CharField(max_length=50)
    due_date = models.DateField(null=True, blank=True)  # ✅ ADD THIS LINE
