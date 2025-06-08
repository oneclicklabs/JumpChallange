"""
Task processor for handling agent tasks asynchronously.
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List
import threading

from django.db.models import Q
from django.utils import timezone

from .models import AgentTask, OngoingInstruction, WebhookEvent
from .agent_service import AgentService

logger = logging.getLogger(__name__)


class TaskProcessor:
    """Process agent tasks in the background"""

    def __init__(self):
        self.running = False
        self.thread = None

    def start(self):
        """Start the task processor"""
        if self.running:
            logger.warning("Task processor already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._process_loop)
        self.thread.daemon = True
        self.thread.start()

        logger.info("Task processor started")

    def stop(self):
        """Stop the task processor"""
        if not self.running:
            logger.warning("Task processor not running")
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)
            if self.thread.is_alive():
                logger.warning(
                    "Task processor thread did not terminate cleanly")
            self.thread = None

        logger.info("Task processor stopped")

    def _process_loop(self):
        """Main processing loop"""
        while self.running:
            try:
                # Process pending and in-progress tasks
                self._process_tasks()

                # Process webhook events
                self._process_webhook_events()

                # Wait a bit before next cycle
                time.sleep(10)

            except Exception as e:
                logger.error(f"Error in task processor: {str(e)}")
                time.sleep(30)  # Wait longer after an error

    def _process_tasks(self):
        """Process pending and in-progress tasks"""
        # Find tasks that need processing
        tasks = AgentTask.objects.filter(
            Q(status='pending') | Q(status='in_progress')
        ).order_by('created_at')[:10]  # Process up to 10 tasks per cycle

        for task in tasks:
            try:
                # Skip if task was updated very recently to avoid processing conflicts
                if task.updated_at > timezone.now() - timedelta(seconds=30):
                    continue

                # Initialize service for this user
                service = AgentService(task.user_id)

                # Process the task
                result = service.process_task(task.id)
                logger.info(f"Processed task {task.id} with result: {result}")

            except Exception as e:
                logger.error(f"Error processing task {task.id}: {str(e)}")

    def _process_webhook_events(self):
        """Process incoming webhook events"""
        # Find events that need processing
        events = WebhookEvent.objects.filter(
            status='received'
        ).order_by('received_at')[:5]  # Process up to 5 events per cycle

        for event in events:
            try:
                # Initialize service for this user
                service = AgentService(event.user_id)

                # Process the event using the AgentService
                if service.process_webhook_event(event.id):
                    logger.info(
                        f"Successfully processed webhook event {event.id}")
                else:
                    logger.warning(
                        f"Failed to process webhook event {event.id}")

            except Exception as e:
                logger.error(
                    f"Error processing webhook event {event.id}: {str(e)}")

                # Mark as failed
                try:
                    event.status = 'failed'
                    event.error_message = str(e)
                    event.save()
                except:
                    pass

    def _parse_instruction_triggers(self, instruction: OngoingInstruction, webhook_event: WebhookEvent) -> bool:
        """Parse instruction triggers and determine if they match the webhook event

        Args:
            instruction: The ongoing instruction to check
            webhook_event: The webhook event to match against

        Returns:
            Boolean indicating if the instruction triggers match the event
        """
        try:
            # Check if the webhook event source matches any of the instruction triggers
            if not instruction.triggers:
                # If no specific triggers, assume it matches all events
                return True

            # Convert webhook source to instruction trigger format
            source_mapping = {
                'gmail': ['email_received', 'email_sent'],
                'calendar': ['calendar_created', 'calendar_updated'],
                'hubspot': ['hubspot_contact_created', 'hubspot_contact_updated']
            }

            matching_triggers = source_mapping.get(webhook_event.source, [])

            # Check if any of the instruction triggers match the event source
            for trigger in instruction.triggers:
                if trigger in matching_triggers:
                    return True

            return False

        except Exception as e:
            logger.error(f"Error parsing instruction triggers: {str(e)}")
            return False


# Create global task processor
task_processor = TaskProcessor()
