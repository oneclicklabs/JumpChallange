from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from rest_framework.schemas import get_schema_view

urlpatterns = [
    # Authentication and existing routes
    path('', views.login, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('google/login/', views.google_login, name='google_login'),
    path('google/callback/', views.google_callback, name='google_callback'),
    path('hubspot-auth/', views.hubspot_auth, name='hubspot_auth'),
    path('hubspot-callback/', views.hubspot_callback, name='hubspot_callback'),
    path('sync-gmail/', views.sync_gmail, name='sync_gmail'),
    path('sync-calendar/', views.sync_calendar, name='sync_calendar'),
    path('ai-insights/', views.ai_insights, name='ai_insights'),

    # Chat routes
    path('chat/', views.chat_list, name='chat_list'),
    path('chat/new/', views.chat_new, name='chat_new'),
    path('chat/<int:chat_id>/', views.chat_detail, name='chat_detail'),
    path('chat/<int:chat_id>/message/', views.chat_message, name='chat_message'),
    path('settings/', views.user_settings, name='user_settings'),

    # Agent API endpoints
    path('agent/', views.agent_dashboard, name='agent_dashboard'),
    path('api/tasks/', views.agent_tasks, name='api_tasks'),
    path('api/tasks/<int:task_id>/',
         views.agent_task_detail, name='api_task_detail'),
    path('api/tasks/<int:task_id>/complete/',
         views.complete_task, name='api_complete_task'),
    path('api/tasks/<int:task_id>/steps/',
         views.task_steps, name='api_task_steps'),
    path('api/tasks/<int:task_id>/steps/<int:step_number>/complete/',
         views.complete_step, name='api_complete_step'),

    # Task suggestion endpoints
    path('api/tasks/suggestions/', views.suggested_tasks,
         name='api_suggested_tasks'),
    path('api/tasks/suggestions/generate/', views.generate_task_suggestions,
         name='api_generate_task_suggestions'),
    path('api/tasks/suggestions/<int:task_id>/approve/',
         views.approve_task_suggestion, name='api_approve_task_suggestion'),

    path('api/instructions/', views.ongoing_instructions, name='api_instructions'),
    path('api/instructions/<int:instruction_id>/',
         views.ongoing_instruction_detail, name='api_instruction_detail'),
    path('api/instructions/<int:instruction_id>/test/',
         views.test_instruction, name='api_test_instruction'),

    # Webhook endpoints
    path('webhooks/<str:source>/', views.webhook_receiver, name='webhook_receiver'),

    # API Schema
    path('api/schema/', get_schema_view(
        title="Financial Advisor AI API",
        description="API endpoints for the Financial Advisor AI application",
        version="1.0.0"
    ), name='openapi-schema'),
]
