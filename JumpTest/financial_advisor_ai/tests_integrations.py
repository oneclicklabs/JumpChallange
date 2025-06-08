from django.test import TestCase
from django.test import TestCase
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock
import json
from datetime import datetime, timedelta

from .models import UserProfile, HubspotContact, EmailInteraction, CalendarEvent
from .integrations import gmail, calendar, hubspot


class GmailIntegrationTests(TestCase):
    """Tests for Gmail integration"""
    
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='gmail_testuser',
            email='gmail@example.com',
            password='testpassword'
        )
        # Get the automatically created profile and update it
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.google_token = 'test_token'
        self.profile.google_refresh_token = 'test_refresh_token'
        self.profile.save()
    
    @patch('googleapiclient.discovery.build')
    def test_get_user_gmail_service(self, mock_build):
        """Test getting the Gmail service client"""
        # Set up mock
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Call the function
        service = gmail.get_user_gmail_service(self.user)
        
        # Assertions
        self.assertIsNotNone(service)
        mock_build.assert_called_once_with('gmail', 'v1', credentials=None)
    
    @patch('googleapiclient.discovery.build')
    def test_sync_emails(self, mock_build):
        """Test syncing emails from Gmail"""
        # Set up mocks
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Mock the Gmail API response
        mock_messages = {
            'messages': [
                {'id': 'email1', 'threadId': 'thread1'},
                {'id': 'email2', 'threadId': 'thread2'}
            ],
            'nextPageToken': None
        }
        
        # Mock email content
        mock_email1 = {
            'id': 'email1',
            'threadId': 'thread1',
            'labelIds': ['INBOX'],
            'snippet': 'This is email 1',
            'payload': {
                'headers': [
                    {'name': 'From', 'value': 'contact@example.com'},
                    {'name': 'Subject', 'value': 'Email 1 Subject'}
                ]
            }
        }
        
        mock_email2 = {
            'id': 'email2',
            'threadId': 'thread2',
            'labelIds': ['INBOX'],
            'snippet': 'This is email 2',
            'payload': {
                'headers': [
                    {'name': 'From', 'value': 'another@example.com'},
                    {'name': 'Subject', 'value': 'Email 2 Subject'}
                ]
            }
        }
        
        # Configure mock calls
        mock_service.users().messages().list().execute.return_value = mock_messages
        mock_service.users().messages().get().execute.side_effect = [mock_email1, mock_email2]
        
        # Create a test contact
        contact = HubspotContact.objects.create(
            user=self.user,
            contact_id='contact123',
            name='Test Contact',
            email='contact@example.com'
        )
        
        # Call the function
        with patch('financial_advisor_ai.integrations.gmail.process_email_content') as mock_process:
            mock_process.return_value = ('This is the full content', 0.5)  # Sentiment score 0.5
            results = gmail.sync_emails(self.user)
        
        # Assertions
        self.assertEqual(len(results), 2)  # 2 emails processed
        self.assertEqual(EmailInteraction.objects.count(), 1)  # Only 1 from known contact
        
        # Check the email interaction
        interaction = EmailInteraction.objects.first()
        self.assertEqual(interaction.contact, contact)
        self.assertEqual(interaction.subject, 'Email 1 Subject')
        self.assertEqual(interaction.snippet, 'This is email 1')
        self.assertEqual(interaction.full_content, 'This is the full content')
        self.assertEqual(interaction.sentiment_score, 0.5)


class CalendarIntegrationTests(TestCase):
    """Tests for Calendar integration"""
    
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='calendar_testuser',
            email='calendar@example.com',
            password='testpassword'
        )
        # Get the automatically created profile and update it
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.google_token = 'test_token'
        self.profile.google_refresh_token = 'test_refresh_token'
        self.profile.save()
    
    @patch('googleapiclient.discovery.build')
    def test_get_user_calendar_service(self, mock_build):
        """Test getting the Calendar service client"""
        # Set up mock
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Call the function
        service = calendar.get_user_calendar_service(self.user)
        
        # Assertions
        self.assertIsNotNone(service)
        mock_build.assert_called_once_with('calendar', 'v3', credentials=None)
    
    @patch('googleapiclient.discovery.build')
    def test_sync_calendar_events(self, mock_build):
        """Test syncing events from Google Calendar"""
        # Set up mocks
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        
        # Mock the Calendar API response
        now = datetime.utcnow()
        tomorrow = now + timedelta(days=1)
        
        mock_events = {
            'items': [
                {
                    'id': 'event1',
                    'summary': 'Test Event 1',
                    'description': 'Event description',
                    'start': {
                        'dateTime': now.isoformat(),
                        'timeZone': 'UTC'
                    },
                    'end': {
                        'dateTime': tomorrow.isoformat(),
                        'timeZone': 'UTC'
                    },
                    'status': 'confirmed',
                    'attendees': [
                        {'email': 'contact@example.com', 'displayName': 'Test Contact'}
                    ]
                },
                {
                    'id': 'event2',
                    'summary': 'Test Event 2',
                    'start': {
                        'dateTime': now.isoformat(),
                        'timeZone': 'UTC'
                    },
                    'end': {
                        'dateTime': tomorrow.isoformat(),
                        'timeZone': 'UTC'
                    },
                    'status': 'confirmed'
                }
            ]
        }
        
        # Configure mock calls
        mock_service.events().list().execute.return_value = mock_events
        
        # Create a test contact
        contact = HubspotContact.objects.create(
            user=self.user,
            contact_id='contact123',
            name='Test Contact',
            email='contact@example.com'
        )
        
        # Call the function
        results = calendar.sync_calendar_events(self.user)
        
        # Assertions
        self.assertEqual(len(results), 2)  # 2 events processed
        self.assertEqual(CalendarEvent.objects.count(), 2)  # 2 events created
        
        # Check the events
        event1 = CalendarEvent.objects.get(event_id='event1')
        self.assertEqual(event1.title, 'Test Event 1')
        self.assertEqual(event1.description, 'Event description')
        self.assertEqual(event1.contact, contact)
        
        event2 = CalendarEvent.objects.get(event_id='event2')
        self.assertEqual(event2.title, 'Test Event 2')
        self.assertIsNone(event2.contact)


class HubspotIntegrationTests(TestCase):
    """Tests for HubSpot integration"""
    
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='hubspot_testuser',
            email='hubspot@example.com',
            password='testpassword'
        )
        # Get the automatically created profile and update it
        self.profile = UserProfile.objects.get(user=self.user)
        self.profile.hubspot_token = 'test_token'
        self.profile.hubspot_refresh_token = 'test_refresh_token'
        self.profile.save()
    
    @patch('requests.get')
    def test_get_hubspot_contacts(self, mock_get):
        """Test getting contacts from HubSpot"""
        # Set up mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'results': [
                {
                    'id': 'contact1',
                    'properties': {
                        'email': 'contact1@example.com',
                        'firstname': 'First',
                        'lastname': 'Contact',
                        'lastmodifieddate': '2023-06-01T10:00:00Z'
                    }
                },
                {
                    'id': 'contact2',
                    'properties': {
                        'email': 'contact2@example.com',
                        'firstname': 'Second',
                        'lastname': 'Contact',
                        'lastmodifieddate': '2023-06-02T11:00:00Z'
                    }
                }
            ],
            'paging': None
        }
        mock_get.return_value = mock_response
        
        # Call the function
        results = hubspot.get_hubspot_contacts(self.user)
        
        # Assertions
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], 'contact1')
        self.assertEqual(results[1]['id'], 'contact2')
    
    @patch('requests.get')
    def test_sync_hubspot_contacts(self, mock_get):
        """Test syncing contacts from HubSpot"""
        # Set up mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'results': [
                {
                    'id': 'contact1',
                    'properties': {
                        'email': 'contact1@example.com',
                        'firstname': 'First',
                        'lastname': 'Contact',
                        'lastmodifieddate': '2023-06-01T10:00:00Z'
                    }
                },
                {
                    'id': 'contact2',
                    'properties': {
                        'email': 'contact2@example.com',
                        'firstname': 'Second',
                        'lastname': 'Contact',
                        'lastmodifieddate': '2023-06-02T11:00:00Z'
                    }
                }
            ],
            'paging': None
        }
        mock_get.return_value = mock_response
        
        # Call the function with sync=True
        count = hubspot.sync_hubspot_contacts(self.user)
        
        # Assertions
        self.assertEqual(count, 2)  # 2 contacts synced
        self.assertEqual(HubspotContact.objects.count(), 2)  # 2 contacts created
        
        # Check the contacts
        contact1 = HubspotContact.objects.get(contact_id='contact1')
        self.assertEqual(contact1.name, 'First Contact')
        self.assertEqual(contact1.email, 'contact1@example.com')
        
        contact2 = HubspotContact.objects.get(contact_id='contact2')
        self.assertEqual(contact2.name, 'Second Contact')
        self.assertEqual(contact2.email, 'contact2@example.com')
    
    @patch('requests.post')
    def test_create_hubspot_contact(self, mock_post):
        """Test creating a contact in HubSpot"""
        # Set up mock response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            'id': 'new_contact',
            'properties': {
                'email': 'new@example.com',
                'firstname': 'New',
                'lastname': 'Contact'
            }
        }
        mock_post.return_value = mock_response
        
        # Contact data
        contact_data = {
            'email': 'new@example.com',
            'firstname': 'New',
            'lastname': 'Contact'
        }
        
        # Call the function
        result = hubspot.create_hubspot_contact(self.user, contact_data)
        
        # Assertions
        self.assertEqual(result['id'], 'new_contact')
        
        # Check that the post was called with the right data
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertTrue('json' in kwargs)
        self.assertEqual(kwargs['json']['properties']['email'], 'new@example.com')


def run_integration_tests():
    """Helper function to run the integration tests"""
    from django.test.runner import DiscoverRunner
    test_runner = DiscoverRunner(verbosity=2)
    failures = test_runner.run_tests(['financial_advisor_ai.tests_integrations'])
    return failures
