import requests
import json
import base64
import sys
import os
import argparse
from datetime import datetime, timedelta

# Change if using a different port or ngrok URL
BASE_URL = "http://localhost:8000"

# Helper function to print colored output


def print_colored(text, color):
    colors = {
        'red': '\033[91m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'end': '\033[0m'
    }
    print(f"{colors.get(color, '')}{text}{colors['end']}")


def test_gmail_webhook(email_content=None):
    """Test a Gmail webhook"""
    print_colored("Testing Gmail webhook...", "blue")

    if not email_content:
        email_content = {
            "id": "email-12345",
            "threadId": "thread-12345",
            "labelIds": ["INBOX", "UNREAD"],
            "snippet": "This is a test email for webhook testing.",
            "payload": {
                "headers": [
                    {"name": "From", "value": "test@example.com"},
                    {"name": "To", "value": "financial-advisor@example.com"},
                    {"name": "Subject", "value": "Meeting Request"}
                ],
                "body": {
                    "data": base64.b64encode("I'd like to schedule a meeting to discuss my portfolio. Is next Tuesday at 2 PM available?".encode()).decode()
                }
            },
            "sizeEstimate": 2800,
            "historyId": "12345"
        }

    # Base64 encode the email content
    encoded_data = base64.b64encode(
        json.dumps(email_content).encode()).decode()

    # Create the Gmail Pub/Sub message format
    payload = {
        "message": {
            "data": encoded_data,
            "messageId": "message-12345",
            "publishTime": datetime.now().isoformat()
        },
        "subscription": "projects/financial-advisor/subscriptions/gmail-notifications"
    }

    response = requests.post(
        f"{BASE_URL}/webhooks/gmail/",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    print_response(response)


def test_calendar_webhook(event_data=None):
    """Test a Google Calendar webhook"""
    print_colored("Testing Calendar webhook...", "blue")

    if not event_data:
        # Default event data
        event_data = {
            "kind": "calendar#event",
            "etag": "\"3404859948632000\"",
            "id": "event-12345",
            "status": "confirmed",
            "htmlLink": "https://www.google.com/calendar/event?eid=...",
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
            "summary": "Financial Review Meeting",
            "description": "Quarterly review of investment portfolio",
            "location": "Office or Zoom",
            "creator": {
                "email": "client@example.com",
                "displayName": "Important Client"
            },
            "organizer": {
                "email": "financial-advisor@example.com",
                "displayName": "Financial Advisor"
            },
            "start": {
                "dateTime": (datetime.now() + timedelta(days=3)).isoformat(),
                "timeZone": "America/New_York"
            },
            "end": {
                "dateTime": (datetime.now() + timedelta(days=3, hours=1)).isoformat(),
                "timeZone": "America/New_York"
            },
            "attendees": [
                {
                    "email": "client@example.com",
                    "displayName": "Important Client",
                    "responseStatus": "accepted"
                }
            ]
        }

    # Calendar notification payload
    payload = {
        "kind": "calendar#notification",
        "resourceState": "exists",
        "resourceId": f"calendar-event-{event_data['id']}",
        "resourceUri": f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_data['id']}",
        "channelId": "channel-calendar-123",
        "channelExpiration": (datetime.now() + timedelta(days=30)).isoformat(),
        "event": event_data
    }

    response = requests.post(
        f"{BASE_URL}/webhooks/calendar/",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    print_response(response)


def test_hubspot_webhook(contact_data=None):
    """Test a HubSpot webhook"""
    print_colored("Testing HubSpot webhook...", "blue")

    if not contact_data:
        # Default contact data
        contact_data = {
            "objectId": 12345,
            "properties": {
                "email": "new.client@example.com",
                "firstname": "New",
                "lastname": "Client",
                "phone": "555-123-4567",
                "company": "Example Corp",
                "lifecyclestage": "opportunity"
            }
        }

    # HubSpot webhook payload for contact creation
    payload = {
        "subscriptionType": "contact.creation",
        "portalId": 7890123,
        "appId": 54321,
        "changeSource": "CRM_UI",
        "objectId": contact_data["objectId"],
        "propertyName": "createdate",
        "propertyValue": datetime.now().isoformat(),
        "object": contact_data
    }

    response = requests.post(
        f"{BASE_URL}/webhooks/hubspot/",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    print_response(response)


def print_response(response):
    """Print the response from the webhook endpoint"""
    try:
        if 200 <= response.status_code < 300:
            print_colored(f"Status: {response.status_code} (Success)", "green")
        else:
            print_colored(f"Status: {response.status_code} (Error)", "red")

        print("Response Headers:")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")

        print("\nResponse Body:")
        try:
            print(json.dumps(response.json(), indent=2))
        except:
            print(response.text)

    except Exception as e:
        print_colored(f"Error processing response: {str(e)}", "red")


def main():
    parser = argparse.ArgumentParser(
        description="Test webhooks for Financial Advisor AI")
    parser.add_argument('webhook_type', choices=['gmail', 'calendar', 'hubspot', 'all'],
                        help='Type of webhook to test')
    parser.add_argument(
        '--url', help='Base URL for the webhook endpoints (default: http://localhost:8000)')

    args = parser.parse_args()

    if args.url:
        global BASE_URL
        BASE_URL = args.url

    if args.webhook_type == 'gmail' or args.webhook_type == 'all':
        test_gmail_webhook()

    if args.webhook_type == 'calendar' or args.webhook_type == 'all':
        test_calendar_webhook()

    if args.webhook_type == 'hubspot' or args.webhook_type == 'all':
        test_hubspot_webhook()


if __name__ == "__main__":
    main()
