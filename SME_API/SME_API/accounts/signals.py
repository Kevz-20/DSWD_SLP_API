# accounts/signals.py
from django.db.models.signals import post_save # type: ignore
from django.dispatch import receiver # type: ignore
from .models import StockIn, Expense

@receiver(post_save, sender=StockIn)
def create_stockin_expense(sender, instance: StockIn, created, **kwargs):
    if created:
        Expense.objects.create(
            account=instance.account,
            product=instance.product,
            amount=instance.quantity * instance.purchase_price,
            category=Expense.INVENTORY_PURCHASE,
            description=f"Stock-in: {instance.product.product_name} x{instance.quantity} @ {instance.purchase_price}"
        )
