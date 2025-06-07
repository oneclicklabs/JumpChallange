from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    google_token = models.TextField(blank=True, null=True)
    google_refresh_token = models.TextField(blank=True, null=True)
    hubspot_token = models.TextField(blank=True, null=True, default='')
    hubspot_refresh_token = models.TextField(blank=True, null=True)


class HubspotContact(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    contact_id = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    last_interaction = models.DateTimeField(null=True, blank=True)


class EmailInteraction(models.Model):
    contact = models.ForeignKey(
        HubspotContact, on_delete=models.CASCADE, related_name='emails')
    subject = models.CharField(max_length=255)
    snippet = models.TextField()
    received_at = models.DateTimeField()
    sentiment_score = models.FloatField(null=True, blank=True)


class CalendarEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    contact = models.ForeignKey(
        HubspotContact, on_delete=models.SET_NULL, null=True, blank=True)
    event_id = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=50)
