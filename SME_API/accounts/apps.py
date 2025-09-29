from django.apps import AppConfig  # type: ignore

class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        import accounts.signals  # 👈 this makes sure signals.py runs
