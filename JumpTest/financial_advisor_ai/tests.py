from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timedelta

from .models import (
    AgentTask, TaskStep, OngoingInstruction, WebhookEvent,
    HubspotContact, EmailInteraction, CalendarEvent, UserProfile
)
from .agent_service import AgentService
from .views import (
    agent_tasks, agent_task_detail, complete_task,
    suggested_tasks, generate_task_suggestions, approve_task_suggestion,
    test_instruction, webhook_receiver
)


class AgentServiceTests(TestCase):
    """Tests for the AgentService class"""

    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword'
        )
        # Get the automatically created profile and update it
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.openai_api_key = 'test_api_key'  # Dummy API key for testing
        self.profile.save()

        # Create a test contact
        self.contact = HubspotContact.objects.create(
            user=self.user,
            contact_id='test123',
            name='Test Contact',
            email='contact@example.com'
        )

        # Create a test calendar event
        self.event = CalendarEvent.objects.create(
            user=self.user,
            event_id='event123',
            title='Test Event',
            description='Test event description',
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, hours=1),
            status='confirmed'
        )

    def test_create_task(self):
        """Test creating a task"""
        agent_service = AgentService(self.user.id)
        task = agent_service.create_task(
            title='Test Task',
            description='This is a test task',
            priority='high',
            contact=self.contact
        )

        self.assertIsNotNone(task)
        self.assertEqual(task.title, 'Test Task')
        self.assertEqual(task.description, 'This is a test task')
        self.assertEqual(task.priority, 'high')
        self.assertEqual(task.status, 'pending')
        self.assertEqual(task.contact, self.contact)

    def test_update_task_status(self):
        """Test updating a task status"""
        # Create a task first
        task = AgentTask.objects.create(
            user=self.user,
            title='Status Test',
            description='Testing status update',
            status='pending'
        )

        agent_service = AgentService(self.user.id)
        result = agent_service.update_task_status(
            task.id, 'in_progress', 'Working on it'
        )

        # Refresh task from database
        task.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(task.status, 'in_progress')
        self.assertEqual(task.next_action, 'Working on it')

    def test_add_task_step(self):
        """Test adding a step to a task"""
        # Create a task first
        task = AgentTask.objects.create(
            user=self.user,
            title='Step Test',
            description='Testing task steps',
            status='in_progress'
        )

        agent_service = AgentService(self.user.id)
        step = agent_service.add_task_step(
            task.id, 'First step description'
        )

        self.assertIsNotNone(step)
        self.assertEqual(step.step_number, 1)
        self.assertEqual(step.description, 'First step description')
        self.assertEqual(step.status, 'pending')

    def test_complete_task_step(self):
        """Test completing a task step"""
        # Create a task first
        task = AgentTask.objects.create(
            user=self.user,
            title='Complete Step Test',
            description='Testing step completion',
            status='in_progress'
        )

        # Add two steps
        step1 = TaskStep.objects.create(
            task=task,
            step_number=1,
            description='Step 1',
            status='pending'
        )

        step2 = TaskStep.objects.create(
            task=task,
            step_number=2,
            description='Step 2',
            status='pending'
        )

        agent_service = AgentService(self.user.id)
        result = agent_service.complete_task_step(
            task.id, 1, 'Completed successfully'
        )

        # Refresh objects from database
        task.refresh_from_db()
        step1.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(step1.status, 'completed')
        self.assertEqual(step1.result, 'Completed successfully')
        self.assertEqual(task.progress, 50)  # 1 of 2 steps completed = 50%

    @patch('openai.OpenAI')
    def test_analyze_and_suggest_tasks(self, mock_openai):
        """Test generating task suggestions"""
        # Mock the OpenAI API response
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        # Set up the mock response
        mock_message.content = json.dumps({
            "tasks": [
                {
                    "title": "Follow up with Test Contact",
                    "description": "It's been a while since you last spoke with Test Contact. Consider reaching out to check on their financial goals.",
                    "priority": "medium"
                }
            ]
        })
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        # Test the method
        agent_service = AgentService(self.user.id)
        suggested_tasks = agent_service.analyze_and_suggest_tasks()

        # Check the results
        self.assertEqual(len(suggested_tasks), 1)
        self.assertEqual(suggested_tasks[0].title,
                         "Follow up with Test Contact")
        self.assertTrue(suggested_tasks[0].is_suggestion)
        self.assertEqual(suggested_tasks[0].status, "draft")

    def test_approve_suggested_task(self):
        """Test approving a suggested task"""
        # Create a suggested task
        suggested_task = AgentTask.objects.create(
            user=self.user,
            title='Suggested Task',
            description='This is a suggested task',
            priority='medium',
            status='draft',
            is_suggestion=True
        )

        agent_service = AgentService(self.user.id)
        result = agent_service.approve_suggested_task(suggested_task.id)

        # Refresh from database
        suggested_task.refresh_from_db()

        self.assertTrue(result)
        self.assertFalse(suggested_task.is_suggestion)
        self.assertEqual(suggested_task.status, 'pending')


class APIEndpointTests(TestCase):
    """Tests for the API endpoints"""

    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='apiendpoint_testuser',
            email='apiendpoint@example.com',
            password='testpassword'
        )
        # Get the automatically created profile and update it
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.openai_api_key = 'test_api_key'
        self.profile.save()

        # Set up API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create some test tasks
        self.task = AgentTask.objects.create(
            user=self.user,
            title='Test Task',
            description='This is a regular task',
            priority='medium'
        )

        self.suggested_task = AgentTask.objects.create(
            user=self.user,
            title='Suggested Task',
            description='This is a suggested task',
            priority='high',
            status='draft',
            is_suggestion=True
        )

        # Create test instruction
        self.instruction = OngoingInstruction.objects.create(
            user=self.user,
            name='Test Instruction',
            instruction='When someone emails about meeting, schedule it',
            triggers=['email_received'],
            conditions='meeting OR schedule OR appointment',
            status='active'
        )

    def test_list_tasks(self):
        """Test listing tasks"""
        response = self.client.get(reverse('api_tasks'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_create_task(self):
        """Test creating a task via API"""
        data = {
            'title': 'New Task',
            'description': 'Created via API',
            'priority': 'low'
        }

        response = self.client.post(reverse('api_tasks'), data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['title'], 'New Task')

        # Check it was created in the database
        self.assertTrue(
            AgentTask.objects.filter(title='New Task').exists()
        )

    def test_get_task_detail(self):
        """Test getting task details"""
        url = reverse('api_task_detail', args=[self.task.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.task.id)
        self.assertEqual(response.data['title'], self.task.title)

    def test_update_task(self):
        """Test updating a task"""
        url = reverse('api_task_detail', args=[self.task.id])
        data = {
            'title': 'Updated Title',
            'status': 'in_progress'
        }

        response = self.client.put(url, data)
        self.assertEqual(response.status_code, 200)

        # Refresh from database
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Updated Title')
        self.assertEqual(self.task.status, 'in_progress')

    def test_get_suggested_tasks(self):
        """Test retrieving suggested tasks"""
        response = self.client.get(reverse('api_suggested_tasks'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.suggested_task.id)

    @patch('financial_advisor_ai.agent_service.AgentService.analyze_and_suggest_tasks')
    def test_generate_task_suggestions(self, mock_analyze):
        """Test generating task suggestions"""
        # Mock the analyze_and_suggest_tasks method
        suggested_task = AgentTask(
            id=999,
            user=self.user,
            title='New Suggestion',
            description='Generated suggestion',
            status='draft',
            is_suggestion=True
        )
        mock_analyze.return_value = [suggested_task]

        response = self.client.post(reverse('api_generate_task_suggestions'))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['title'], 'New Suggestion')

    def test_approve_suggestion(self):
        """Test approving a suggested task"""
        url = reverse('api_approve_task_suggestion',
                      args=[self.suggested_task.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)

        # Refresh task from database
        self.suggested_task.refresh_from_db()
        self.assertFalse(self.suggested_task.is_suggestion)
        self.assertEqual(self.suggested_task.status, 'pending')

    @patch('financial_advisor_ai.agent_service.AgentService.test_instruction')
    def test_test_instruction(self, mock_test):
        """Test the instruction testing endpoint"""
        # Mock the test_instruction method
        mock_test.return_value = {
            'matches': True,
            'source': 'gmail',
            'test_data': {'some_test': 'data'},
            'analysis': {
                'is_clear': True,
                'is_actionable': True,
                'feedback': 'Instruction is clear and actionable'
            }
        }

        url = reverse('api_test_instruction', args=[self.instruction.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['matches'])
        self.assertEqual(response.data['source'], 'gmail')


class WebhookTests(TestCase):
    """Tests for webhook handling"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create test user - using a unique username
        cls.user = User.objects.create_user(
            username='webhook_testuser',
            email='webhook@example.com',
            password='testpassword'
        )

        # Get the automatically created profile and update it
        cls.profile = UserProfile.objects.get(user=cls.user)
        cls.profile.openai_api_key = 'test_api_key'
        cls.profile.save()
        
        # Set up the request factory
        cls.factory = RequestFactory()

        # Create an instruction
        cls.instruction = OngoingInstruction.objects.create(
            user=cls.user,
            name='Email Instruction',
            instruction='When someone emails about meeting, create a task',
            triggers=['email_received'],
            conditions='meeting OR schedule',
            status='active'
        )

    @patch('financial_advisor_ai.views._process_gmail_webhook')
    def test_gmail_webhook(self, mock_process):
        """Test handling Gmail webhook"""
        # Set up test data
        webhook_data = {
            'message': {
                # Base64 encoded JSON
                'data': 'eyJpZCI6ImVtYWlsMTIzIiwic3VtbWFyeSI6IlRoaXMgaXMgYSB0ZXN0IGVtYWlsIn0=',
                'messageId': 'msg123'
            }
        }

        # Set up the mock to return a webhook event ID
        mock_process.return_value = 123

        # Make the request
        url = reverse('webhook_receiver', args=['gmail'])
        request = self.factory.post(
            url,
            data=json.dumps(webhook_data),
            content_type='application/json'
        )

        response = webhook_receiver(request, 'gmail')        # Check the response
        self.assertEqual(response.status_code, 200)
        
        # Verify the mock was called correctly
        mock_process.assert_called_once()
    
    def test_webhook_verification(self):
        """Test webhook verification requests"""
        # Test Gmail/Calendar verification
        challenge = 'test_challenge_string'
        url = reverse('webhook_receiver', args=['gmail'])
        url = f"{url}?hub.mode=subscribe&hub.challenge={challenge}&hub.verify_token=token"
        
        request = self.factory.get(url)
        response = webhook_receiver(request, 'gmail')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, challenge)


class TaskProcessorTests(TestCase):
    """Tests for the task processor functionality"""

    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='taskprocessor_testuser',
            email='taskprocessor@example.com',
            password='testpassword'
        )
        # Get the automatically created profile and update it
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.openai_api_key = 'test_api_key'  # Dummy API key for testing
        self.profile.save()

        # Create a test contact
        self.contact = HubspotContact.objects.create(
            user=self.user,
            contact_id='test123',
            name='Test Contact',
            email='contact@example.com'
        )

        # Create a test webhook event
        self.webhook_event = WebhookEvent.objects.create(
            user=self.user,
            source='gmail',
            event_type='message.received',
            payload={
                'id': 'email123',
                'threadId': 'thread123',
                'snippet': 'Would like to schedule a meeting to discuss investments',
                'payload': {
                    'headers': [
                        {'name': 'From', 'value': 'contact@example.com'},
                        {'name': 'Subject', 'value': 'Meeting Request'}
                    ]
                }
            },
            status='received',
            summary='Email about scheduling a meeting'
        )

        # Create a matching instruction
        self.instruction = OngoingInstruction.objects.create(
            user=self.user,
            name='Meeting Request Handler',
            instruction='When someone emails about a meeting, create a task to schedule it',
            triggers=['email_received'],
            conditions='meeting OR schedule OR appointment',
            status='active'
        )

    @patch('financial_advisor_ai.task_processor.AgentService')
    def test_process_webhook_events(self, mock_agent_service):
        """Test processing webhook events"""
        from .task_processor import TaskProcessor

        # Set up mock for execute_instruction
        mock_instance = MagicMock()
        mock_agent_service.return_value = mock_instance
        mock_instance.execute_instruction.return_value = 101  # Task ID

        # Create task processor
        processor = TaskProcessor()

        # Process events
        processor._process_webhook_events()

        # Check that execute_instruction was called
        mock_instance.execute_instruction.assert_called_once_with(
            self.instruction, self.webhook_event.id
        )

        # Check that webhook event status was updated
        self.webhook_event.refresh_from_db()
        self.assertEqual(self.webhook_event.status, 'processed')

    def test_parse_instruction_triggers(self):
        """Test parsing instruction triggers"""
        from .task_processor import TaskProcessor

        processor = TaskProcessor()

        # Test basic email trigger
        matches = processor._parse_instruction_triggers(
            self.instruction, self.webhook_event
        )
        self.assertTrue(matches)

        # Test non-matching event type
        non_matching_event = WebhookEvent.objects.create(
            user=self.user,
            source='calendar',  # Different source
            event_type='event.created',
            payload={},
            status='received'
        )

        matches = processor._parse_instruction_triggers(
            self.instruction, non_matching_event
        )
        self.assertFalse(matches)  # Should not match - different event source

        # Test matching conditions but wrong trigger
        calendar_instruction = OngoingInstruction.objects.create(
            user=self.user,
            name='Calendar Handler',
            instruction='When calendar event is created, do something',
            triggers=['calendar_created'],  # Different trigger
            conditions='meeting OR appointment',
            status='active'
        )

        matches = processor._parse_instruction_triggers(
            calendar_instruction, self.webhook_event
        )
        self.assertFalse(matches)  # Should not match - wrong trigger type


class IntegrationTests(TestCase):
    """Integration tests for the agent functionality"""

    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='integration_testuser',
            email='integration@example.com',
            password='testpassword'
        )
        # Get the automatically created profile and update it
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.openai_api_key = 'test_api_key'
        self.profile.google_token = 'test_google_token'
        self.profile.hubspot_token = 'test_hubspot_token'
        self.profile.save()

        # Set up API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch('financial_advisor_ai.agent_service.AgentService.execute_instruction')
    def test_end_to_end_webhook_flow(self, mock_execute_instruction):
        """Test the end-to-end flow from webhook to task creation"""
        # Mock execute_instruction to return a task ID
        mock_execute_instruction.return_value = 101

        # 1. Create an instruction
        instruction_data = {
            'name': 'Email Handler',
            'instruction': 'When someone emails about meeting, schedule it',
            'triggers': ['email_received'],
            'conditions': 'meeting OR schedule',
            'status': 'active'
        }

        instruction_response = self.client.post(
            reverse('api_instructions'),
            data=instruction_data
        )

        self.assertEqual(instruction_response.status_code, 201)
        instruction_id = instruction_response.data['id']

        # 2. Send a webhook event
        webhook_data = {
            'message': {
                'data': 'eyJpZCI6ImVtYWlsMTIzIiwic25pcHBldCI6IkNhbiB3ZSBzY2hlZHVsZSBhIG1lZXRpbmc/IiwicGF5bG9hZCI6eyJoZWFkZXJzIjpbeyJuYW1lIjoiRnJvbSIsInZhbHVlIjoiY29udGFjdEBleGFtcGxlLmNvbSJ9XX19',  # Base64 encoded JSON
                'messageId': 'msg123'
            }
        }

        webhook_response = self.client.post(
            reverse('webhook_receiver', args=['gmail']),
            data=json.dumps(webhook_data),
            content_type='application/json'
        )

        self.assertEqual(webhook_response.status_code, 200)

        # Check that a webhook event was created
        webhook_events = WebhookEvent.objects.filter(source='gmail')
        self.assertEqual(webhook_events.count(), 1)

        # 3. Process webhook events (normally done by the task processor)
        webhook_event = webhook_events.first()

        # Simulate task processor calling execute_instruction
        AgentService(self.user.id).execute_instruction(
            OngoingInstruction.objects.get(id=instruction_id),
            webhook_event.id
        )

        # Verify mock was called
        mock_execute_instruction.assert_called_once()

    @patch('openai.OpenAI')
    def test_suggestion_generation_and_approval_flow(self, mock_openai):
        """Test the flow of generating and approving task suggestions"""
        # Mock OpenAI
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        # Set up the mock response
        mock_message.content = json.dumps({
            "tasks": [
                {
                    "title": "Contact Inactive Client",
                    "description": "It's been over 30 days since you've contacted this client.",
                    "priority": "high"
                }
            ]
        })
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        # 1. Generate task suggestions
        generate_response = self.client.post(
            reverse('api_generate_task_suggestions'))
        self.assertEqual(generate_response.status_code, 201)
        self.assertEqual(len(generate_response.data), 1)

        suggestion_id = generate_response.data[0]['id']

        # 2. Get suggested tasks
        suggestions_response = self.client.get(reverse('api_suggested_tasks'))
        self.assertEqual(suggestions_response.status_code, 200)
        self.assertEqual(len(suggestions_response.data), 1)

        # 3. Approve the suggestion
        approve_response = self.client.post(
            reverse('api_approve_task_suggestion', args=[suggestion_id])
        )
        self.assertEqual(approve_response.status_code, 200)

        # 4. Verify the task is now a regular task and not a suggestion
        task = AgentTask.objects.get(id=suggestion_id)
        self.assertEqual(task.status, 'pending')
        self.assertFalse(task.is_suggestion)


def run_tests():
    """Helper function to run the tests"""
    from django.test.runner import DiscoverRunner
    test_runner = DiscoverRunner(verbosity=2)
    failures = test_runner.run_tests(['financial_advisor_ai'])
    return failures
