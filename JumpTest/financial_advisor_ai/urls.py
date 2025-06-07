from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.login, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('hubspot-auth/', views.hubspot_auth, name='hubspot_auth'),
    path('hubspot-callback/', views.hubspot_callback, name='hubspot_callback'),
    path('sync-gmail/', views.sync_gmail, name='sync_gmail'),
    path('sync-calendar/', views.sync_calendar, name='sync_calendar'),
    path('ai-insights/', views.ai_insights, name='ai_insights'),
    # path('/oauth/complete/google-oauth2/',
    #      views.GoogleAuthRed, name='GRedirect'),

]
