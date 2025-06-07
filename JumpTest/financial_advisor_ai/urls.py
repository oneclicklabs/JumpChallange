from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
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
    # Add these URL patterns
    path('chat/', views.chat_list, name='chat_list'),
    path('chat/new/', views.chat_new, name='chat_new'),
    path('chat/<int:chat_id>/', views.chat_detail, name='chat_detail'),
    path('chat/<int:chat_id>/message/', views.chat_message, name='chat_message'),
    path('settings/', views.user_settings, name='user_settings'),
]
