from django.contrib import admin
import financial_advisor_ai.models as models

# Register your models here.
admin.site.register(models.UserProfile)
admin.site.register(models.HubspotContact)
admin.site.register(models.EmailInteraction)
admin.site.register(models.CalendarEvent)
