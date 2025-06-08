from django.contrib import admin
import financial_advisor_ai.models as models

# Register your models here.
admin.site.register(models.UserProfile)
admin.site.register(models.HubspotContact)
admin.site.register(models.EmailInteraction)
admin.site.register(models.CalendarEvent)
admin.site.register(models.Chat)
admin.site.register(models.ChatMessage)

# Register agent-related models with custom admin classes
@admin.register(models.AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'status', 'priority', 'created_at', 'progress')
    list_filter = ('status', 'priority', 'user')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(models.TaskStep)
class TaskStepAdmin(admin.ModelAdmin):
    list_display = ('task', 'step_number', 'description', 'status', 'created_at')
    list_filter = ('status', 'task__user')
    search_fields = ('description', 'task__title')
    readonly_fields = ('created_at', 'completed_at')


@admin.register(models.OngoingInstruction)
class OngoingInstructionAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'status', 'created_at', 'last_triggered')
    list_filter = ('status', 'user')
    search_fields = ('name', 'instruction')
    readonly_fields = ('created_at', 'updated_at', 'last_triggered')


@admin.register(models.AgentMemory)
class AgentMemoryAdmin(admin.ModelAdmin):
    list_display = ('key', 'user', 'created_at', 'updated_at', 'expires_at')
    list_filter = ('user',)
    search_fields = ('key', 'value')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(models.WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('source', 'event_type', 'summary', 'user', 'status', 'received_at')
    list_filter = ('source', 'status', 'user')
    search_fields = ('event_type', 'payload', 'summary')
    readonly_fields = ('received_at', 'processed_at')
    list_display_links = ('source', 'summary')
