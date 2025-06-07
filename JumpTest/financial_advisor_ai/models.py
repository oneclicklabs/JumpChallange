from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    google_token = models.TextField(blank=True, null=True)
    google_refresh_token = models.TextField(blank=True, null=True)
    hubspot_token = models.TextField(blank=True, null=True, default='')
    hubspot_refresh_token = models.TextField(blank=True, null=True, default='')
    openai_api_key = models.CharField(max_length=255, blank=True, null=True)


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
    full_content = models.TextField(blank=True)
    
    def serialize_for_vector_db(self):
        """Serialize email for vector DB storage"""
        return {
            'id': self.id,
            'subject': self.subject,
            'snippet': self.snippet,
            'full_content': self.full_content,
            'date_str': self.received_at.strftime("%Y-%m-%d %H:%M"),
            'from': self.contact.email,
            'contact_name': self.contact.name,
            'contact_id': self.contact.contact_id
        }


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


class Chat(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=255, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
    class Meta:
        ordering = ['-updated_at']


class ChatMessage(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    contact = models.ForeignKey(HubspotContact, on_delete=models.SET_NULL, null=True, blank=True)
    
    def __str__(self):
        return f"{self.role}: {self.content[:30]}..."
    
    class Meta:
        ordering = ['created_at']
