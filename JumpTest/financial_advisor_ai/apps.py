from django.apps import AppConfig


class FinancialAdvisorAiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'financial_advisor_ai'

    def ready(self):
        # Import signals to register them
        import financial_advisor_ai.signals
