"""
Gmail API integration for accessing and managing emails
"""
import os
import base64
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.contrib.auth.models import User
from django.conf import settings
from ..models import HubspotContact, EmailInteraction, UserProfile

logger = logging.getLogger(__name__)


class GmailAPI:
    """Gmail API wrapper for email operations"""

    def __init__(self, user_id):
        """Initialize the Gmail API client

        Args:
            user_id: ID of the Django user
        """
        self.user = User.objects.get(id=user_id)
        self.profile = None
        self.service = None
        self.initialized = False
        self.error = None

        try:
            self.profile = self.user.userprofile
            if not self.profile.google_token:
                self.error = "Google access token not available"
                return

            # Create credentials from stored token
            creds_data = json.loads(self.profile.google_token)
            credentials = Credentials(
                token=creds_data.get('access_token'),
                refresh_token=self.profile.google_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
                scopes=["https://www.googleapis.com/auth/gmail.readonly",
                        "https://www.googleapis.com/auth/gmail.send"]
            )

            # Create Gmail API service
            self.service = build('gmail', 'v1', credentials=credentials)
            self.initialized = True

        except Exception as e:
            logger.error(f"Error initializing Gmail API: {str(e)}")
            self.error = str(e)

    def get_messages(self, query='', max_results=10) -> List[Dict]:
        """Get emails matching a query

        Args:
            query: Gmail search query
            max_results: Maximum number of results to return

        Returns:
            List of message dictionaries
        """
        if not self.initialized:
            logger.error("Gmail API not initialized")
            return []

        try:
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()

            messages = []
            for msg in results.get('messages', []):
                full_msg = self.service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()

                # Extract email details
                headers = full_msg.get('payload', {}).get('headers', [])
                subject = next(
                    (h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
                from_email = next(
                    (h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')
                date_str = next(
                    (h['value'] for h in headers if h['name'].lower() == 'date'), None)

                # Get snippet
                snippet = full_msg.get('snippet', '')

                # Get email body
                body = self._get_email_body(full_msg.get('payload', {}))

                # Format message data
                messages.append({
                    'id': msg['id'],
                    'thread_id': full_msg.get('threadId'),
                    'subject': subject,
                    'from': from_email,
                    'date': date_str,
                    'snippet': snippet,
                    'body': body,
                    'labels': full_msg.get('labelIds', [])
                })

            return messages

        except Exception as e:
            logger.error(f"Error getting Gmail messages: {str(e)}")
            return []

    def get_recent_emails(self, days=7, max_results=20) -> List[Dict]:
        """Get recent emails from the inbox

        Args:
            days: Number of days back to look for emails
            max_results: Maximum number of results to return

        Returns:
            List of message dictionaries
        """
        # Create query for emails received in the last X days
        query = f"in:inbox newer_than:{days}d"
        return self.get_messages(query, max_results)

    def get_emails_from_contact(self, email_address: str, max_results=10) -> List[Dict]:
        """Get emails from a specific contact

        Args:
            email_address: Email address to search for
            max_results: Maximum number of results to return

        Returns:
            List of message dictionaries
        """
        query = f"from:{email_address}"
        return self.get_messages(query, max_results)

    def send_email(self, to: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        """Send an email

        Args:
            to: Recipient email address
            subject: Email subject
            body: Plain text email body
            html_body: Optional HTML version of the email body

        Returns:
            True if email was sent successfully, False otherwise
        """
        if not self.initialized:
            logger.error("Gmail API not initialized")
            return False

        try:
            # Create message
            message = MIMEMultipart('alternative')
            message['to'] = to
            message['subject'] = subject

            # Add plain text part
            part1 = MIMEText(body, 'plain')
            message.attach(part1)

            # Add HTML part if provided
            if html_body:
                part2 = MIMEText(html_body, 'html')
                message.attach(part2)

            # Encode message
            encoded_message = base64.urlsafe_b64encode(
                message.as_bytes()).decode()

            # Send message
            result = self.service.users().messages().send(
                userId='me',
                body={'raw': encoded_message}
            ).execute()

            logger.info(f"Email sent to {to}, message_id: {result.get('id')}")
            return True

        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return False

    def setup_watch(self, topic_name: str) -> bool:
        """Set up push notifications for Gmail inbox changes

        Args:
            topic_name: Google Cloud Pub/Sub topic name

        Returns:
            True if watch was set up successfully, False otherwise
        """
        if not self.initialized:
            logger.error("Gmail API not initialized")
            return False

        try:
            # Set up notification for inbox changes
            result = self.service.users().watch(
                userId='me',
                body={
                    'topicName': topic_name,
                    'labelIds': ['INBOX']
                }
            ).execute()

            logger.info(f"Gmail watch set up: {result}")
            return True

        except Exception as e:
            logger.error(f"Error setting up Gmail watch: {str(e)}")
            return False

    def _get_email_body(self, payload: Dict) -> str:
        """Extract email body from payload

        Args:
            payload: Gmail API message payload

        Returns:
            Email body text
        """
        if not payload:
            return ""

        # Check if this part has a body
        if 'body' in payload and 'data' in payload['body']:
            data = payload['body']['data']
            return base64.urlsafe_b64decode(data).decode('utf-8')

        # Check parts recursively
        if 'parts' in payload:
            for part in payload['parts']:
                # Prefer plain text parts
                if part.get('mimeType') == 'text/plain':
                    if 'data' in part.get('body', {}):
                        data = part['body']['data']
                        return base64.urlsafe_b64decode(data).decode('utf-8')

            # If no plain text, try HTML
            for part in payload['parts']:
                if part.get('mimeType') == 'text/html':
                    if 'data' in part.get('body', {}):
                        data = part['body']['data']
                        return base64.urlsafe_b64decode(data).decode('utf-8')

            # Check nested parts
            for part in payload['parts']:
                body = self._get_email_body(part)
                if body:
                    return body

        return ""

    def sync_emails_to_db(self, days=7) -> List[Dict]:
        """Sync recent emails to database

        Args:
            days: Number of days back to look for emails

        Returns:
            List of emails processed
        """
        if not self.initialized:
            logger.error("Gmail API not initialized")
            return []

        try:
            # Get recent emails
            emails = self.get_recent_emails(days=days, max_results=50)

            processed_emails = []
            for email in emails:
                # Try to match sender with a contact
                from_email = email.get('from', '')
                if '<' in from_email and '>' in from_email:
                    # Extract email from "Name <email@example.com>" format
                    from_email = from_email.split('<')[1].split('>')[0].strip()

                # Look for matching contact
                contacts = HubspotContact.objects.filter(
                    user=self.user, email__iexact=from_email)

                if contacts.exists():
                    contact = contacts.first()

                    # Check if we already have this email
                    existing = EmailInteraction.objects.filter(
                        contact=contact,
                        subject=email.get('subject', ''),
                        snippet=email.get('snippet', '')
                    )

                    if not existing.exists():
                        # Parse date
                        received_at = datetime.now()
                        if email.get('date'):
                            try:
                                from email.utils import parsedate_to_datetime
                                received_at = parsedate_to_datetime(
                                    email.get('date'))
                            except:
                                pass

                        # Create new email record
                        EmailInteraction.objects.create(
                            contact=contact,
                            subject=email.get('subject', 'No Subject'),
                            snippet=email.get('snippet', ''),
                            received_at=received_at,
                            full_content=email.get('body', '')
                        )

                        # Add to processed list
                        processed_emails.append({
                            'id': email.get('id'),
                            'subject': email.get('subject', 'No Subject'),
                            'from': from_email,
                            'date': email.get('date'),
                            'contact_name': contact.name
                        })

                        # Update last interaction time
                        contact.last_interaction = received_at
                        contact.save()

            return processed_emails

        except Exception as e:
            logger.error(f"Error syncing emails to DB: {str(e)}")
            return []


# Module-level functions for compatibility with tests
def get_user_gmail_service(user):
    """Get Gmail service for a user

    Args:
        user: Django User object

    Returns:
        GmailAPI instance or None if failed
    """
    try:
        gmail_api = GmailAPI(user.id)
        if gmail_api.initialized:
            return gmail_api
        else:
            logger.error(
                f"Failed to initialize Gmail API for user {user.id}: {gmail_api.error}")
            return None
    except Exception as e:
        logger.error(
            f"Error getting Gmail service for user {user.id}: {str(e)}")
        return None


def sync_emails(user, days=7):
    """Sync emails from Gmail to the database

    Args:
        user: Django User object
        days: Number of days back to sync

    Returns:
        List of emails synced
    """
    try:
        gmail_api = GmailAPI(user.id)
        if gmail_api.initialized:
            return gmail_api.sync_emails_to_db(days)
        else:
            logger.error(
                f"Failed to sync emails for user {user.id}: {gmail_api.error}")
            return []
    except Exception as e:
        logger.error(f"Error syncing emails for user {user.id}: {str(e)}")
        return []


def process_email_content(email_data):
    """Process email content and extract relevant information

    Args:
        email_data: Dictionary containing email information

    Returns:
        Dictionary with processed email data
    """
    try:
        # Extract key information from the email
        processed_data = {
            'subject': email_data.get('subject', ''),
            'from_email': email_data.get('from', ''),
            'body': email_data.get('body', ''),
            'snippet': email_data.get('snippet', ''),
            'date': email_data.get('date'),
            'message_id': email_data.get('id'),
            'thread_id': email_data.get('thread_id'),
            'labels': email_data.get('labels', []),
            'processed_at': datetime.now().isoformat()
        }

        # Add any additional processing logic here
        # For example, sentiment analysis, keyword extraction, etc.

        return processed_data

    except Exception as e:
        logger.error(f"Error processing email content: {str(e)}")
        return {
            'error': str(e),
            'processed_at': datetime.now().isoformat()
        }
