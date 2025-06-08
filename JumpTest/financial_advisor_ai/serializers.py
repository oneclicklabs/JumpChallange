"""
Serializers for the agent functionality
"""
from rest_framework import serializers
from .models import AgentTask, TaskStep, OngoingInstruction, WebhookEvent


class TaskStepSerializer(serializers.ModelSerializer):
    """Serializer for TaskStep model"""

    class Meta:
        model = TaskStep
        fields = [
            'id', 'step_number', 'description', 'status',
            'created_at', 'completed_at', 'result'
        ]


class AgentTaskSerializer(serializers.ModelSerializer):
    """Serializer for AgentTask model"""
    steps = TaskStepSerializer(many=True, read_only=True)

    class Meta:
        model = AgentTask
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'created_at', 'updated_at', 'due_date', 'completed_at',
            'progress', 'steps', 'next_action'
        ]
        read_only_fields = ['id', 'created_at',
                            'updated_at', 'steps', 'progress']


class AgentTaskCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new task"""

    class Meta:
        model = AgentTask
        fields = ['title', 'description', 'priority', 'due_date']


class OngoingInstructionSerializer(serializers.ModelSerializer):
    """Serializer for OngoingInstruction model"""

    class Meta:
        model = OngoingInstruction
        fields = [
            'id', 'name', 'instruction', 'triggers', 'conditions',
            'status', 'created_at', 'updated_at', 'last_triggered'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_triggered']


class WebhookEventSerializer(serializers.ModelSerializer):
    """Serializer for WebhookEvent model"""

    class Meta:
        model = WebhookEvent
        fields = [
            'id', 'source', 'event_type', 'payload', 'status',
            'received_at', 'processed_at', 'error_message'
        ]
        read_only_fields = ['id', 'received_at', 'processed_at']
