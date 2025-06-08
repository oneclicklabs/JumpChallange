from django.db import models
from django.contrib.auth.models import User
import json


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    google_token = models.TextField(blank=True, null=True)
    google_refresh_token = models.TextField(blank=True, null=True)
    hubspot_token = models.TextField(blank=True, null=True, default='')
    hubspot_refresh_token = models.TextField(blank=True, null=True, default='')
    openai_api_key = models.CharField(max_length=255, blank=True, null=True)

# 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


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

    chat = models.ForeignKey(
        Chat, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    contact = models.ForeignKey(
        HubspotContact, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.role}: {self.content[:30]}..."

    class Meta:
        ordering = ['created_at']


class AgentTask(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('waiting_response', 'Waiting for Response'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('draft', 'Draft')  # Added draft status for suggested tasks
    ]

    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low')
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='agent_tasks')
    title = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default='medium')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    due_date = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_suggestion = models.BooleanField(
        default=False, help_text='Whether this task was suggested by AI')

    # Related entities for the task
    contact = models.ForeignKey(
        HubspotContact, on_delete=models.SET_NULL, null=True, blank=True)
    calendar_event = models.ForeignKey(
        CalendarEvent, on_delete=models.SET_NULL, null=True, blank=True)

    # Task state and context
    current_state = models.JSONField(default=dict, blank=True)
    next_action = models.TextField(blank=True, null=True)

    # For tracking progress in multi-step tasks
    progress = models.IntegerField(default=0)  # Percentage from 0-100

    def __str__(self):
        return f"{self.title} ({self.status})"

    class Meta:
        ordering = ['-created_at']

    def update_state(self, new_state):
        """Update the task's state with new information"""
        if isinstance(new_state, dict):
            # Merge the new state with the current state
            current = self.current_state
            current.update(new_state)
            self.current_state = current
            self.save()

    def advance_status(self, new_status, next_action=None):
        """Update status and optionally set the next action"""
        self.status = new_status
        if next_action:
            self.next_action = next_action
        self.save()


class TaskStep(models.Model):
    """Model to track steps in a multi-step task"""
    task = models.ForeignKey(
        AgentTask, on_delete=models.CASCADE, related_name='steps')
    step_number = models.IntegerField()
    description = models.TextField()
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.TextField(blank=True)

    class Meta:
        ordering = ['step_number']

    def __str__(self):
        return f"Step {self.step_number}: {self.description[:30]}..."


class OngoingInstruction(models.Model):
    """Model for storing ongoing instructions for the agent"""
    TRIGGER_CHOICES = [
        ('email_received', 'Email Received'),
        ('email_sent', 'Email Sent'),
        ('calendar_created', 'Calendar Event Created'),
        ('calendar_updated', 'Calendar Event Updated'),
        ('hubspot_contact_created', 'HubSpot Contact Created'),
        ('hubspot_contact_updated', 'HubSpot Contact Updated'),
        ('manual', 'Manual Trigger')
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('archived', 'Archived')
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='ongoing_instructions')
    name = models.CharField(max_length=255)
    instruction = models.TextField()
    triggers = models.JSONField(default=list)  # List of trigger types
    # Natural language conditions
    conditions = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_triggered = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.status})"

    def add_trigger(self, trigger_type):
        """Add a trigger type to this instruction"""
        if trigger_type not in self.triggers:
            triggers = self.triggers
            triggers.append(trigger_type)
            self.triggers = triggers
            self.save()

    class Meta:
        ordering = ['-updated_at']


class AgentMemory(models.Model):
    """Model to store agent memory and context"""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='agent_memories')
    key = models.CharField(max_length=255)  # Memory identifier
    value = models.TextField()  # Memory content
    context = models.TextField(blank=True)  # Additional context
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(
        null=True, blank=True)  # Optional expiration

    def __str__(self):
        return f"{self.key}: {self.value[:30]}..."

    class Meta:
        verbose_name_plural = "Agent memories"
        unique_together = ['user', 'key']


class WebhookEvent(models.Model):
    """Model to store incoming webhook events"""
    SOURCE_CHOICES = [
        ('gmail', 'Gmail'),
        ('calendar', 'Google Calendar'),
        ('hubspot', 'HubSpot')
    ]

    STATUS_CHOICES = [
        ('received', 'Received'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('failed', 'Failed')
    ]
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='webhook_events')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    summary = models.TextField(
        blank=True, help_text='Human-readable summary of the event')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='received')
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    def __str__(self):
        return f"{self.source} - {self.event_type} ({self.status})"

    class Meta:
        ordering = ['-received_at']
