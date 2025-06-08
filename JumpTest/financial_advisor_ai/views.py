from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from datetime import datetime
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
# Create your views here.
import os
import json
import requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from openai import OpenAI
from django.db.models import Q
from .models import (
    UserProfile, HubspotContact, EmailInteraction, CalendarEvent, Chat, ChatMessage,
    AgentTask, TaskStep, OngoingInstruction, AgentMemory, WebhookEvent
)
from .serializers import (
    AgentTaskSerializer, AgentTaskCreateSerializer, TaskStepSerializer,
    OngoingInstructionSerializer, WebhookEventSerializer
)

from .utils import RAGService  # Assuming you have a utility for RAG processing
from .agent_service import AgentService


def google_login(request):
    """
    Initiates the Google OAuth2 login flow.
    """
    # Create flow instance to manage the OAuth 2.0 Authorization flow
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        },
        scopes=settings.GOOGLE_AUTH_SCOPES
    )

    # Set the redirect URI to the callback endpoint
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

    # Generate authorization URL and state
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    # Store the state in the session for later validation
    request.session[settings.GOOGLE_OAUTH_STATE_SESSION_KEY] = state

    # Redirect to Google's authorization page
    return redirect(authorization_url)


def login(request):
    error = request.GET.get('error', '')
    error_description = request.GET.get('error_description', '')

    if error:
        messages.error(request, f"Auth error: {error} - {error_description}")

    # If user is already authenticated, make sure they have a profile
    if request.user.is_authenticated:
        UserProfile.objects.get_or_create(user=request.user)

    return render(request, 'login.html')


@login_required
def dashboard(request):
    try:
        profile = UserProfile.objects.get(user=request.user)
        has_google = profile.google_token is not None and profile.google_refresh_token != ''
        has_hubspot = profile.hubspot_token is not None and profile.hubspot_refresh_token != ''
        print(
            f"User {request.user.username} - Profile found - Google: {has_google}, HubSpot: {has_hubspot}")
    except UserProfile.DoesNotExist:
        # Create profile if it doesn't exist
        profile = UserProfile.objects.create(user=request.user)
        has_google = False
        has_hubspot = False
        print(
            f"User {request.user.username} - Profile created - Google: {has_google}, HubSpot: {has_hubspot}")

    context = {
        'has_google': has_google,
        'has_hubspot': has_hubspot,
    }

    if has_google and has_hubspot:
        # Fetch data for the dashboard
        contacts = HubspotContact.objects.filter(user=request.user)
        upcoming_events = CalendarEvent.objects.filter(
            user=request.user,
            start_time__gte=datetime.now()
        ).order_by('start_time')[:5]

        context.update({
            'contacts': contacts,
            'upcoming_events': upcoming_events,
        })
        fetch_hubspot_contacts(request.user)  # Ensure contacts are fetched
    return render(request, 'dashboard.html', context)


@login_required
def hubspot_auth(request):
    # Initiate HubSpot OAuth flow
    auth_url = (
        f"https://app.hubspot.com/oauth/authorize"
        f"?client_id={settings.HUBSPOT_CLIENT_ID}"
        f"&redirect_uri={settings.HUBSPOT_REDIRECT_URI}"
        f"&scope=crm.objects.contacts.read%20timeline"
    )

    # Debug info
    print(f"\n\n=== HUBSPOT AUTH DEBUGGING ===")
    print(f"User: {request.user.username}")
    print(f"Client ID: {settings.HUBSPOT_CLIENT_ID}")
    print(f"Redirect URI: {settings.HUBSPOT_REDIRECT_URI}")
    print(f"Full Auth URL: {auth_url}")
    print(f"=== END DEBUGGING ===\n\n")

    # Ensure we have a user profile
    UserProfile.objects.get_or_create(user=request.user)

    messages.info(request, "Redirecting to HubSpot for authorization...")
    return redirect(auth_url)


# @login_required
def hubspot_callback(request):
    code = request.GET.get('code')
    error = request.GET.get('error')

    print(f"\n\n=== HUBSPOT CALLBACK DEBUGGING ===")
    print(f"User: {request.user.username}")
    print(f"Code present: {code is not None}")
    print(f"Error present: {error is not None}")
    if error:
        print(f"Error details: {error}")
    print(f"Query parameters: {request.GET}")
    print(f"=== END DEBUGGING ===\n\n")

    if error:
        messages.error(request, f"HubSpot error: {error}")
        return redirect('dashboard')

    if not code:
        messages.error(
            request, "Failed to connect with HubSpot: No authorization code received.")
        return redirect('dashboard')

    try:
        # Exchange code for token
        token_url = 'https://api.hubapi.com/oauth/v1/token'
        token_data = {
            'grant_type': 'authorization_code',
            'client_id': settings.HUBSPOT_CLIENT_ID,
            'client_secret': settings.HUBSPOT_CLIENT_SECRET,
            'redirect_uri': settings.HUBSPOT_REDIRECT_URI,
            'code': code
        }

        print(f"\n=== TOKEN REQUEST DETAILS ===")
        print(f"URL: {token_url}")
        print(f"Client ID: {settings.HUBSPOT_CLIENT_ID}")
        print(f"Redirect URI: {settings.HUBSPOT_REDIRECT_URI}")
        print(f"=== END DETAILS ===\n")

        response = requests.post(token_url, data=token_data)

        print(f"\n=== TOKEN RESPONSE ===")
        print(f"Status code: {response.status_code}")
        print(f"Response content: {response.text}")
        print(f"=== END RESPONSE ===\n")

        if response.status_code == 200:
            data = response.json()
            profile, created = UserProfile.objects.get_or_create(
                user=request.user)

            # Debug profile
            print(f"Profile created: {created}")
            print(f"Profile ID: {profile.id}")

            profile.hubspot_token = data['access_token']
            profile.hubspot_refresh_token = data.get('refresh_token')
            profile.save()

            # Debug after save
            print(f"Token saved: {profile.hubspot_token is not None}")
            print(
                f"Refresh token saved: {profile.hubspot_refresh_token is not None}")

            # Re-fetch to verify
            updated_profile = UserProfile.objects.get(id=profile.id)
            print(
                f"Token verified in DB: {updated_profile.hubspot_token == data['access_token']}")

            # Fetch initial contact data
            fetch_hubspot_contacts(request.user)

            messages.success(request, "Successfully connected with HubSpot!")
        else:
            error_detail = response.text
            print(
                f"HubSpot token error: Status {response.status_code}, Response: {error_detail}")
            messages.error(
                request, f"Failed to connect with HubSpot. Error: {error_detail}")

    except Exception as e:
        import traceback
        print(f"Exception in HubSpot callback: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        messages.error(request, f"Error in HubSpot connection: {str(e)}")

    return redirect('dashboard')


def refresh_hubspot_token(profile):
    print("HubSpot token expired, attempting to refresh...")
    refresh_url = 'https://api.hubapi.com/oauth/v1/token'
    refresh_data = {
        'grant_type': 'refresh_token',
        'client_id': settings.HUBSPOT_CLIENT_ID,
        'client_secret': settings.HUBSPOT_CLIENT_SECRET,
        'refresh_token': profile.hubspot_refresh_token
    }

    refresh_response = requests.post(refresh_url, data=refresh_data)
    if refresh_response.status_code == 200:
        refresh_data = refresh_response.json()
        profile.hubspot_token = refresh_data['access_token']
        if 'refresh_token' in refresh_data:
            profile.hubspot_refresh_token = refresh_data['refresh_token']
            profile.save()


def fetch_hubspot_contacts(user):
    print(f"Fetching HubSpot contacts for user: {user.username}")
    try:
        profile = UserProfile.objects.get(user=user)
        headers = {
            'Authorization': f'Bearer {profile.hubspot_token}',
            'Content-Type': 'application/json'
        }

        # Get first 100 contacts
        response = requests.get(
            'https://api.hubapi.com/crm/v3/objects/contacts',
            headers=headers,
            params={'limit': 100}
        )
        # Check for 401 unauthorized - token expired
        if response.status_code == 401:
            refresh_hubspot_token(profile)
            # Retry the original request with new token
            headers['Authorization'] = f'Bearer {profile.hubspot_token}'
            response = requests.get(
                'https://api.hubapi.com/crm/v3/objects/contacts',
                headers=headers,
                params={'limit': 100}
            )
        print(f"HubSpot API response status: {response.content}")
        if response.status_code == 200:
            data = response.json()
            for contact in data.get('results', []):
                props = contact.get('properties', {})
                HubspotContact.objects.update_or_create(
                    user=user,
                    contact_id=contact.get('id'),
                    defaults={
                        'name': f"{props.get('firstname', '')} {props.get('lastname', '')}".strip(),
                        'email': props.get('email', ''),
                    }
                )
            return True
        return False
    except Exception as e:
        print(f"Error fetching HubSpot contacts: {e}")
        return False


@login_required
def sync_gmail(request):
    print("Syncing Gmail...")
    try:
        profile = UserProfile.objects.get(user=request.user)

        # Set up credentials
        credentials = google.oauth2.credentials.Credentials(
            token=profile.google_token,
            refresh_token=profile.google_refresh_token,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            token_uri='https://oauth2.googleapis.com/token'
        )

        # Build Gmail service
        service = build('gmail', 'v1', credentials=credentials)

        # Get list of emails
        results = service.users().messages().list(userId='me', maxResults=20).execute()
        print(f"Results from Gmail API: {results}")
        Gmessages = results.get('messages', [])
        print(f"Found {len(Gmessages)} messages in Gmail.")
        for msg in Gmessages:
            message = service.users().messages().get(
                userId='me', id=msg['id']).execute()
            headers = message['payload']['headers']
            # print(f"Processing message ID: {message}")
            # Extract email details
            subject = next(
                (h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            from_email = next(
                (h['value'] for h in headers if h['name'] == 'From'), 'Unknown')

            # Extract email address only
            if '<' in from_email and '>' in from_email:
                from_email = from_email.split('<')[1].split('>')[0]
            print(f"Processing email from: {from_email}, subject: {subject}")
            # Check if this is from a contact we know
            contacts = HubspotContact.objects.filter(
                user=request.user, email=from_email)

            if contacts.exists():
                contact = contacts.first()                # Get full message body
                msg_body = ""
                if 'payload' in message and 'parts' in message['payload']:
                    parts = message['payload']['parts']
                    for part in parts:
                        if part.get('mimeType') == 'text/plain':
                            if 'data' in part.get('body', {}):
                                import base64
                                data = part['body']['data']
                                # Decode base64url data
                                msg_body = base64.urlsafe_b64decode(
                                    data).decode('utf-8')
                                break

                # Create or update email interaction
                EmailInteraction.objects.update_or_create(
                    contact=contact,
                    subject=subject,
                    defaults={
                        'snippet': message.get('snippet', ''),
                        'full_content': msg_body,
                        'received_at': datetime.fromtimestamp(int(message['internalDate'])/1000),
                    }
                )

        print("Gmail data synchronized successfully!")
        messages.success(request, "Gmail data synchronized successfully!")
    except Exception as e:
        print(f"Error synchronizing Gmail: {str(e)}")
        messages.error(request, f"Error synchronizing Gmail: {str(e)}")

    return redirect('dashboard')


@login_required
def sync_calendar(request):
    try:
        profile = UserProfile.objects.get(user=request.user)

        # Set up credentials
        credentials = google.oauth2.credentials.Credentials(
            token=profile.google_token,
            refresh_token=profile.google_refresh_token,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            token_uri='https://oauth2.googleapis.com/token'
        )

        # Build Calendar service
        service = build('calendar', 'v3', credentials=credentials)

        # Get upcoming events
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        for event in events:
            # Get start and end times
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))

            # Parse datetime strings
            if 'T' in start:  # This is a datetime, not just a date
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            else:
                # For all-day events, use date
                start_dt = datetime.strptime(start, '%Y-%m-%d')
                end_dt = datetime.strptime(end, '%Y-%m-%d')

            # Create or update calendar event
            CalendarEvent.objects.update_or_create(
                user=request.user,
                event_id=event['id'],
                defaults={
                    'title': event.get('summary', 'Untitled Event'),
                    'description': event.get('description', ''),
                    'start_time': start_dt,
                    'end_time': end_dt,
                    'status': event.get('status', 'confirmed'),
                }
            )

        messages.success(request, "Calendar events synchronized successfully!")
    except Exception as e:
        messages.error(request, f"Error synchronizing Calendar: {str(e)}")

    return redirect('dashboard')


@login_required
def ai_insights(request):
    # This would connect to an AI service to generate insights
    # For now, we'll just return a sample response
    return JsonResponse({
        'insights': [
            {
                'contact_name': 'John Smith',
                'email': 'john.smith@example.com',
                'last_interaction': '2023-06-15',
                'sentiment': 'Positive',
                'suggestion': 'Follow up about retirement planning discussion'
            },
            {
                'contact_name': 'Sarah Johnson',
                'email': 'sarah.j@example.com',
                'last_interaction': '2023-06-10',
                'sentiment': 'Neutral',
                'suggestion': 'Share new investment opportunity'
            }
        ]
    })


# @login_required
# def chat_list(request):
#     """View for listing all chats for the user"""
#     chats = Chat.objects.filter(user=request.user)

#     # If there's at least one chat, redirect to the most recent
#     if chats.exists():
#         return redirect('chat_detail', chat_id=chats.first().id)

#     # Otherwise just show the empty list page
#     return render(request, 'chat.html', {'chats': chats})


# @login_required
# def chat_new(request):
#     """Create a new chat and redirect to it"""
#     chat = Chat.objects.create(
#         user=request.user,
#         title="New Chat"
#     )

#     # Add system message to initialize the chat
#     ChatMessage.objects.create(
#         chat=chat,
#         role="system",
#         content="I'm your financial advisor assistant. I can help you find information about your clients using data from emails and HubSpot."
#     )

#     return redirect('chat_detail', chat_id=chat.id)


# @login_required
# def chat_detail(request, chat_id):
#     """View for a specific chat with pagination"""
#     chat = get_object_or_404(Chat, id=chat_id, user=request.user)
#     chats = Chat.objects.filter(user=request.user)

#     # Paginate messages
#     from django.core.paginator import Paginator

#     messages_list = chat.messages.all()
#     paginator = Paginator(messages_list, 25)  # 25 messages per page

#     page_number = request.GET.get('page')
#     page_obj = paginator.get_page(page_number)

#     return render(request, 'chat.html', {
#         'chat': chat,
#         'chats': chats,
#         'page_obj': page_obj
#     })


# @login_required
# def chat_message(request, chat_id):
#     """Handle new messages in a chat"""
#     if request.method != 'POST':
#         return JsonResponse({'error': 'Method not allowed'}, status=405)

#     chat = get_object_or_404(Chat, id=chat_id, user=request.user)
#     message_text = request.POST.get('message', '').strip()

#     if not message_text:
#         return JsonResponse({'error': 'Message cannot be empty'}, status=400)

#     # Save user message
#     ChatMessage.objects.create(
#         chat=chat,
#         role='user',
#         content=message_text
#     )

#     # Update chat details
#     if chat.title == "New Chat":
#         # Use first few words of first message as title
#         words = message_text.split()
#         title = " ".join(words[:4])
#         if len(words) > 4:
#             title += "..."
#         chat.title = title
#         chat.save()

#     # Process message with RAG to get answer
#     try:
#         profile = UserProfile.objects.get(user=request.user)
#         if not profile.openai_api_key:
#             return JsonResponse({
#                 'message': "Please add your OpenAI API key in settings to use the chat feature.",
#                 'title': chat.title
#             })

#         # Initialize RAG service
#         rag_service = RAGService(api_key=profile.openai_api_key)

#         # Get email data for the user
#         email_data = []
#         contacts = HubspotContact.objects.filter(user=request.user)
#         for contact in contacts:
#             emails = EmailInteraction.objects.filter(contact=contact)
#             for email in emails:
#                 email_data.append(email.serialize_for_vector_db())

#         # Process emails
#         if email_data:
#             rag_service.process_emails(email_data)

#         # Get chat history
#         history = [{
#             'role': msg.role,
#             'content': msg.content
#         } for msg in chat.messages.all()]

#         # Check if the message is asking about a specific person with ambiguous reference
#         contact_name_match = None
#         contact_id = None

#         # Check for contact references in the message
#         name_matches = extract_name_from_query(message_text)

#         if name_matches:
#             # Find matching contacts
#             potential_contacts = find_matching_contacts(
#                 request.user, name_matches)

#             if len(potential_contacts) == 0:
#                 answer = f"I couldn't find any contacts matching '{name_matches}'. Please try another name or check the spelling."
#             elif len(potential_contacts) == 1:
#                 # Single match, use this contact's ID for filtering
#                 contact_id = potential_contacts[0].contact_id
#                 contact_name_match = potential_contacts[0].name
#                 answer = rag_service.answer_question(
#                     message_text, history, contact_id)
#             else:
#                 # Multiple matches, ask for clarification
#                 contact_options = ", ".join(
#                     [f"{c.name} ({c.email})" for c in potential_contacts[:5]])
#                 answer = f"I found multiple contacts matching '{name_matches}'. Which one do you mean? {contact_options}"

#                 # Create a ChatMessage linking to potential contacts for follow-up
#                 for contact in potential_contacts[:5]:
#                     chat_msg = ChatMessage.objects.create(
#                         chat=chat,
#                         role='system',
#                         content=f"Potential contact: {contact.name}",
#                         contact=HubspotContact.objects.get(
#                             user=request.user, contact_id=contact.contact_id)
#                     )
#         else:
#             # No specific person mentioned, process normally
#             answer = rag_service.answer_question(message_text, history)

#         # Save assistant response
#         ChatMessage.objects.create(
#             chat=chat,
#             role='assistant',
#             content=answer
#         )

#         # Touch chat to update last_modified
#         chat.save()

#         return JsonResponse({
#             'message': answer,
#             'title': chat.title
#         })

#     except Exception as e:
#         print(f"Error processing message: {str(e)}")

#         # Save error as assistant response
#         ChatMessage.objects.create(
#             chat=chat,
#             role='assistant',
#             content=f"I'm sorry, I encountered an error while processing your question. Please try again."
#         )

#         return JsonResponse({
#             'message': f"I'm sorry, I encountered an error while processing your question. Technical details: {str(e)}",
#             'title': chat.title
#         })


# def extract_name_from_query(query):
#     """
#     Extract potential person name from a query.
#     Returns the name or None if no clear name is found.
#     """
#     # Very simple extraction for common question patterns
#     # Could be improved with NLP in a production environment
#     query = query.lower()

#     # Patterns like "Why did [name] say..."
#     patterns = [
#         r"why did ([a-z]+) say",
#         r"what did ([a-z]+) say about",
#         r"when did ([a-z]+) mention",
#         r"how did ([a-z]+) feel about",
#         r"where is ([a-z]+) from"
#     ]

#     for pattern in patterns:
#         import re
#         match = re.search(pattern, query)
#         if match:
#             return match.group(1)

#     return None


# def find_matching_contacts(user, name_query):
#     """
#     Find contacts matching a name query.
#     Returns a list of matching contact objects.
#     """
#     # First try exact matches on first name
#     contacts = HubspotContact.objects.filter(
#         user=user,
#         name__icontains=name_query
#     )

#     return contacts


def google_callback(request):
    """
    Handle the callback from Google OAuth2 authorization.
    This is where we exchange the authorization code for access tokens
    and extract user information.
    """
    # Get state from session for validation
    saved_state = request.session.get(
        settings.GOOGLE_OAUTH_STATE_SESSION_KEY, '')

    # Check if there's an error parameter in the request
    if 'error' in request.GET:
        error = request.GET.get('error')
        messages.error(request, f"Google authentication error: {error}")
        return redirect('login')

    # Handle any potential spaces or additional parameters in URL
    code = request.GET.get('code', '')
    if not code:
        messages.error(request, "No authorization code received from Google.")
        return redirect('login')

    try:
        # Create flow instance with the same configuration
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
                }
            },
            scopes=settings.GOOGLE_AUTH_SCOPES
        )

        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

        # Exchange authorization code for tokens, no need to pass state as we're not validating here
        flow.fetch_token(code=code, include_granted_scopes=True)

        # Get credentials
        credentials = flow.credentials

        # Get user info from ID token
        request_session = google_requests.Request()
        id_info = id_token.verify_oauth2_token(
            credentials.id_token, request_session, settings.GOOGLE_CLIENT_ID)

        # Extract user information
        email = id_info.get('email', '')

        if not email:
            messages.error(request, "Could not retrieve email from Google.")
            return redirect('login')

        # Find or create user
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Create new user
            username = email.split('@')[0]
            # Ensure username is unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=id_info.get('given_name', ''),
                last_name=id_info.get('family_name', '')
            )

        # Get or create user profile
        profile, created = UserProfile.objects.get_or_create(user=user)

        # Save tokens
        profile.google_token = credentials.token
        profile.google_refresh_token = credentials.refresh_token
        profile.save()

        # Log user in
        auth_login(request, user)

        # Add success message
        messages.success(request, f"Successfully logged in as {email}")

        # Redirect to dashboard
        return redirect('dashboard')

    except Exception as e:
        messages.error(
            request, f"Error during Google authentication: {str(e)}")
        return redirect('login')


@login_required
def chat_list(request):
    """View for listing all chats for the user"""
    chats = Chat.objects.filter(user=request.user)

    # If there's at least one chat, redirect to the most recent
    if chats.exists():
        return redirect('chat_detail', chat_id=chats.first().id)

    # Otherwise just show the empty list page
    return render(request, 'chat.html', {'chats': chats})


@login_required
def chat_new(request):
    """Create a new chat and redirect to it"""
    chat = Chat.objects.create(
        user=request.user,
        title="New Chat"
    )

    # Add system message to initialize the chat
    ChatMessage.objects.create(
        chat=chat,
        role="system",
        content="I'm your financial advisor assistant. I can help you find information about your clients using data from emails and HubSpot."
    )

    return redirect('chat_detail', chat_id=chat.id)


@login_required
def chat_detail(request, chat_id):
    """View for a specific chat"""
    chat = get_object_or_404(Chat, id=chat_id, user=request.user)
    chats = Chat.objects.filter(user=request.user)

    return render(request, 'chat.html', {
        'chat': chat,
        'chats': chats
    })


@login_required
def chat_message(request, chat_id):
    """Handle new messages in a chat"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    chat = get_object_or_404(Chat, id=chat_id, user=request.user)
    message_text = request.POST.get('message', '').strip()

    if not message_text:
        return JsonResponse({'error': 'Message cannot be empty'}, status=400)

    # Save user message
    ChatMessage.objects.create(
        chat=chat,
        role='user',
        content=message_text
    )

    # Update chat details
    if chat.title == "New Chat":
        # Use first few words of first message as title
        words = message_text.split()
        title = " ".join(words[:4])
        if len(words) > 4:
            title += "..."
        chat.title = title
        chat.save()

    # Process message with RAG to get answer
    try:
        profile = UserProfile.objects.get(user=request.user)
        if not profile.openai_api_key:
            return JsonResponse({
                'message': "Please add your OpenAI API key in settings to use the chat feature.",
                'title': chat.title
            })

        # Initialize RAG service
        rag_service = RAGService(api_key=profile.openai_api_key)

        # Get email data for the user
        email_data = []
        contacts = HubspotContact.objects.filter(user=request.user)
        for contact in contacts:
            emails = EmailInteraction.objects.filter(contact=contact)
            for email in emails:
                email_data.append(email.serialize_for_vector_db())

        # Process emails
        print("Processing emails for RAG...")
        print(f"Found {len(email_data)} emails to process.")
        if email_data:
            rag_service.process_emails(email_data)

        # Get chat history
        history = [{
            'role': msg.role,
            'content': msg.content
        } for msg in chat.messages.all()]

        # Check if the message is asking about a specific person with ambiguous reference
        contact_name_match = None
        contact_id = None

        # Check for contact references in the message
        name_matches = extract_name_from_query2(message_text)
        print(f"Extracted name matches2: {name_matches}")
        name_matches = extract_name_from_query(
            message_text, history, profile.openai_api_key)
        print(f"Extracted name matches: {name_matches}")
        if name_matches:
            # Find matching contacts
            potential_contacts = find_matching_contacts(
                request.user, name_matches)

            if len(potential_contacts) == 0:
                answer = f"I couldn't find any contacts matching '{name_matches}'. Please try another name or check the spelling."
            elif len(potential_contacts) == 1:
                # Single match, use this contact's ID for filtering
                contact_id = potential_contacts[0].contact_id
                contact_name_match = potential_contacts[0].name
                answer = rag_service.answer_question(
                    message_text, history, contact_id)
            else:
                # Multiple matches, ask for clarification
                contact_options = ", ".join(
                    [f"{c.name} ({c.email})" for c in potential_contacts[:5]])
                answer = f"I found multiple contacts matching '{name_matches}'. Which one do you mean? {contact_options}"

                # Create a ChatMessage linking to potential contacts for follow-up
                for contact in potential_contacts[:5]:
                    chat_msg = ChatMessage.objects.create(
                        chat=chat,
                        role='system',
                        content=f"Potential contact: {contact.name}",
                        contact=HubspotContact.objects.get(
                            user=request.user, contact_id=contact.contact_id)
                    )
        else:
            # No specific person mentioned, process normally
            answer = rag_service.answer_question(message_text, history)

        # Save assistant response
        ChatMessage.objects.create(
            chat=chat,
            role='assistant',
            content=answer
        )

        # Touch chat to update last_modified
        chat.save()

        return JsonResponse({
            'message': answer,
            'title': chat.title
        })

    except Exception as e:
        print(f"Error processing message: {str(e)}")

        # Save error as assistant response
        ChatMessage.objects.create(
            chat=chat,
            role='assistant',
            content=f"I'm sorry, I encountered an error while processing your question. Please try again."
        )

        return JsonResponse({
            'message': f"I'm sorry, I encountered an error while processing your question. Technical details: {str(e)}",
            'title': chat.title
        })


def extract_name_from_query(query, history, openai_api_key):

    client = OpenAI()
    message_text = 'extract the name or names of people referred to in this following message "' + query + \
        ' "if you find a name then ignore the there is no names in that then use this history of messages "' + str(history) + \
        ' "your reply should be just the list of names separated by commas'
    # answer = rag_service.answer_question(message_text, history)
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=message_text
    )
    # print(f"OpenAI Query: {message_text}")
    answer = response.output_text.lower()
    # Check if we received any names
    if not answer:
        return None

    # Remove any whitespace and split by commas
    names = [name.strip() for name in answer.split(',') if name.strip()]

    # Return None if no valid names found
    if not names:
        return None

    # Return first name found (or could return all names if needed)
    return names


def extract_name_from_query2(query):
    """
    Extract potential person name from a query with improved pattern matching.
    Returns the name or None if no clear name is found.
    """
    query = query.lower()

    # Common patterns for asking about specific people
    patterns = [
        r"why did ([a-z]+) say",
        r"what did ([a-z]+) say about",
        r"when did ([a-z]+) mention",
        r"how did ([a-z]+) feel about",
        r"where is ([a-z]+) from",
        r"did ([a-z]+) mention",
        r"has ([a-z]+) talked about",
        r"([a-z]+)'s email",
        r"email from ([a-z]+)",
        r"([a-z]+) said",
        r"([a-z]+) mentioned",
        r"about ([a-z]+)'s",
    ]

    for pattern in patterns:
        import re
        match = re.search(pattern, query)
        if match:
            return match.group(1)

    # Look for capitalized words that might be names
    words = query.split()
    for word in words:
        if word[0].isupper() and len(word) > 1:
            # Check if this might be a name (not a common English word)
            common_words = ["the", "and", "but", "why", "what", "when",
                            "where", "how", "did", "do", "done", "has", "have", "had"]
            if word.lower() not in common_words:
                return word.lower()

    return None


def find_matching_contacts(user, name_query):
    """
    Find contacts matching a name query.
    Returns a list of matching contact objects.
    """
    query = Q()
    for name in name_query:
        query |= Q(name__icontains=name)
    # First try exact matches on first name
    contacts = HubspotContact.objects.filter(user=user).filter(query)
    #     name__icontains=query
    # )
    print(f"Found {contacts.count()} contacts matching '{name_query}'")
    return contacts


@login_required
def user_settings(request):
    """View for user to manage their API keys and settings"""
    profile = get_object_or_404(UserProfile, user=request.user)

    if request.method == 'POST':
        openai_api_key = request.POST.get('openai_api_key', '').strip()
        if openai_api_key:
            # Validate API key format (basic check)
            if openai_api_key.startswith('sk-') and len(openai_api_key) > 20:
                profile.openai_api_key = openai_api_key
                profile.save()
                messages.success(
                    request, "OpenAI API key updated successfully.")
            else:
                messages.error(request, "Invalid OpenAI API key format.")

        return redirect('user_settings')

    return render(request, 'user_settings.html', {
        'profile': profile,
        'has_openai_key': bool(profile.openai_api_key)
    })


# Agent API endpoints

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def agent_tasks(request):
    """List all tasks or create a new task"""
    if request.method == 'GET':
        tasks = AgentTask.objects.filter(user=request.user)
        serializer = AgentTaskSerializer(tasks, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = AgentTaskCreateSerializer(data=request.data)
        if serializer.is_valid():
            # Create task using the agent service
            agent_service = AgentService(request.user.id)
            task = agent_service.create_task(
                title=serializer.validated_data['title'],
                description=serializer.validated_data['description'],
                priority=serializer.validated_data.get('priority', 'medium'),
                due_date=serializer.validated_data.get('due_date')
            )

            if task:
                return Response(AgentTaskSerializer(task).data, status=status.HTTP_201_CREATED)
            else:
                return Response(
                    {"error": "Failed to create task"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def agent_task_detail(request, task_id):
    """Retrieve, update or delete a task"""
    # Check if task exists and belongs to the user
    try:
        task = AgentTask.objects.get(id=task_id, user=request.user)
    except AgentTask.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    # Initialize agent service
    agent_service = AgentService(request.user.id)

    if request.method == 'GET':
        serializer = AgentTaskSerializer(task)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = AgentTaskSerializer(task, data=request.data, partial=True)
        if serializer.is_valid():
            if 'status' in serializer.validated_data:
                # Use the agent service to update status
                new_status = serializer.validated_data['status']
                next_action = serializer.validated_data.get('next_action')

                result = agent_service.update_task_status(
                    task_id, new_status, next_action)
                if not result:
                    return Response(
                        {"error": "Failed to update task status"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            # For other fields, just save directly
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_task(request, task_id):
    """Mark a task as completed"""
    result = request.data.get('result', '')

    agent_service = AgentService(request.user.id)
    success = agent_service.complete_task(task_id, result)

    if success:
        # Get the updated task
        task = AgentTask.objects.get(id=task_id, user=request.user)
        serializer = AgentTaskSerializer(task)
        return Response(serializer.data)
    else:
        return Response(
            {"error": "Failed to complete task"},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def suggested_tasks(request):
    """Get AI-suggested tasks for the user"""
    agent_service = AgentService(request.user.id)
    tasks = agent_service.get_suggested_tasks()

    serializer = AgentTaskSerializer(tasks, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_task_suggestions(request):
    """Generate new AI task suggestions"""
    agent_service = AgentService(request.user.id)

    # Check if OpenAI API key is available
    if not agent_service.has_openai:
        return Response(
            {"error": "OpenAI API key is required to generate suggestions"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Generate suggestions
    suggested_tasks = agent_service.analyze_and_suggest_tasks()

    if suggested_tasks:
        serializer = AgentTaskSerializer(suggested_tasks, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    else:
        return Response(
            {"message": "No task suggestions were generated"},
            status=status.HTTP_200_OK
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_task_suggestion(request, task_id):
    """Approve an AI-suggested task"""
    agent_service = AgentService(request.user.id)

    # Approve the suggestion
    success = agent_service.approve_suggested_task(task_id)

    if success:
        # Get the updated task
        task = AgentTask.objects.get(id=task_id, user=request.user)
        serializer = AgentTaskSerializer(task)
        return Response(serializer.data)
    else:
        return Response(
            {"error": "Failed to approve task suggestion"},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST', 'GET'])
@permission_classes([IsAuthenticated])
def ongoing_instructions(request):
    """List all instructions or create a new instruction"""
    if request.method == 'GET':
        instructions = OngoingInstruction.objects.filter(user=request.user)
        serializer = OngoingInstructionSerializer(instructions, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        # Extract data from request
        name = request.data.get('name')
        instruction = request.data.get('instruction')
        triggers = request.data.get('triggers', [])

        if not name or not instruction:
            return Response(
                {"error": "Name and instruction are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create using agent service
        agent_service = AgentService(request.user.id)
        instruction_obj = agent_service.create_instruction(
            name, instruction, triggers)

        if instruction_obj:
            serializer = OngoingInstructionSerializer(instruction_obj)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(
                {"error": "Failed to create instruction"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def ongoing_instruction_detail(request, instruction_id):
    """Retrieve, update or delete an instruction"""
    try:
        instruction = OngoingInstruction.objects.get(
            id=instruction_id, user=request.user)
    except OngoingInstruction.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = OngoingInstructionSerializer(instruction)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = OngoingInstructionSerializer(
            instruction, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        instruction.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST', 'GET'])
def webhook_receiver(request, source):
    """Handle incoming webhooks from external services

    This endpoint handles both verification requests (GET) and actual webhook events (POST)
    from Gmail, Google Calendar, and HubSpot.
    """
    # Validate source is one of our supported types
    if source not in ['gmail', 'calendar', 'hubspot']:
        return Response(
            {"error": f"Unsupported webhook source: {source}"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Handle verification requests (GET)
    if request.method == 'GET':
        # For Gmail and Calendar verification
        if source in ['gmail', 'calendar'] and 'hub.challenge' in request.GET:
            challenge = request.GET.get('hub.challenge')
            return Response(challenge, content_type='text/plain')

        # For HubSpot verification
        elif source == 'hubspot' and 'hub.verify' in request.GET:
            verify_token = request.GET.get('hub.verify')
            expected_token = getattr(
                settings, 'HUBSPOT_WEBHOOK_VERIFY_TOKEN', None)
            if verify_token and expected_token and verify_token == expected_token:
                return Response("OK", content_type='text/plain')
            return Response("Verification failed", status=status.HTTP_403_FORBIDDEN)

        # Default verification response
        return Response("OK", content_type='text/plain')

    # Parse the payload
    try:
        payload = request.data        # Extract user identifier from the payload
        # This will vary depending on your webhook integration
        # For example, with Gmail push notifications, you might have a userEmail
        user_email = None
        user = None

        if source == 'gmail':
            # Gmail webhook might have a userEmail field
            user_email = payload.get('emailAddress')
            # For testing purposes, if no emailAddress provided, use the first user
            if not user_email and User.objects.exists():
                user = User.objects.first()
        elif source == 'calendar':
            # Calendar webhook might have an organizer email
            if 'organizer' in payload:
                user_email = payload['organizer'].get('email')
        elif source == 'hubspot':
            # HubSpot integration might need to use an API key to identify the user
            user_id = payload.get('userId')  # Just a placeholder

        # Find the user from the email if we have one
        if user_email and not user:
            try:
                user = User.objects.get(email=user_email)
            except User.DoesNotExist:
                return Response(
                    {"error": f"No matching user found for {user_email}"},
                    status=status.HTTP_404_NOT_FOUND
                )

        if user:            # Identify the event type from the payload
            event_type = 'default'
            if source == 'gmail':
                event_type = payload.get('historyId', 'message')
                # Process Gmail-specific webhook data
                gmail_result = _process_gmail_webhook(payload)
            elif source == 'calendar':
                event_type = payload.get('status', 'updated')
            elif source == 'hubspot':
                event_type = payload.get('eventType', 'change')

            # Record the webhook event
            agent_service = AgentService(user.id)
            event = agent_service.record_webhook_event(
                source, event_type, payload)

            if event:
                # Process the event (or queue it for processing)
                agent_service.process_webhook_event(event.id)
                return Response({"status": "success", "event_id": event.id})
            else:
                return Response(
                    {"error": "Failed to record webhook event"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            return Response(
                {"error": "Could not identify user from webhook payload"},
                status=status.HTTP_400_BAD_REQUEST
            )

    except Exception as e:
        return Response(
            {"error": f"Error processing webhook: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _process_gmail_webhook(payload):
    """Process Gmail webhook data and extract relevant information

    Args:
        payload: The webhook payload from Gmail

    Returns:
        dict: Processed webhook data
    """
    import base64
    import json

    try:
        # Gmail webhooks typically come with a message object containing base64 encoded data
        if 'message' in payload and 'data' in payload['message']:
            # Decode the base64 data
            encoded_data = payload['message']['data']
            decoded_data = base64.b64decode(encoded_data).decode('utf-8')

            # Parse the JSON data
            email_data = json.loads(decoded_data)

            return {
                'status': 'success',
                'data': email_data,
                'message_id': payload['message'].get('messageId'),
                'type': 'gmail_notification'
            }
        else:
            # If no encoded data, return the payload as-is
            return {
                'status': 'success',
                'data': payload,
                'type': 'gmail_webhook'
            }

    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'type': 'gmail_webhook'
        }


@login_required
def agent_dashboard(request):
    """View for the agent task dashboard"""
    tasks = AgentTask.objects.filter(user=request.user)
    active_tasks = tasks.exclude(
        status__in=['completed', 'cancelled', 'failed', 'draft'])
    completed_tasks = tasks.filter(status='completed')

    # Get suggestions (tasks with is_suggestion=True)
    suggested_tasks = tasks.filter(is_suggestion=True)

    instructions = OngoingInstruction.objects.filter(
        user=request.user, status='active')

    context = {
        'active_tasks': active_tasks,
        'completed_tasks': completed_tasks,
        'suggested_tasks': suggested_tasks,
        'instructions': instructions
    }

    return render(request, 'agent_dashboard.html', context)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_instruction(request, instruction_id):
    """Test an instruction with sample data to see if it matches and is actionable"""
    try:
        instruction = OngoingInstruction.objects.get(
            id=instruction_id, user=request.user)
    except OngoingInstruction.DoesNotExist:
        return Response(
            {"error": "Instruction not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    # Get test data from request if provided
    test_data = request.data.get('test_data')

    # Use the agent service to test the instruction
    agent_service = AgentService(request.user.id)
    result = agent_service.test_instruction(instruction_id, test_data)

    return Response(result)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def task_steps(request, task_id):
    """List all steps for a task or create a new step"""
    # Check if task exists and belongs to the user
    try:
        task = AgentTask.objects.get(id=task_id, user=request.user)
    except AgentTask.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    # Initialize agent service
    agent_service = AgentService(request.user.id)

    if request.method == 'GET':
        steps = TaskStep.objects.filter(task=task).order_by('step_number')
        serializer = TaskStepSerializer(steps, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        # Extract data
        description = request.data.get('description', '')
        step_number = request.data.get('step_number')

        if not description:
            return Response(
                {"error": "Description is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create new step using agent service
        step = agent_service.add_task_step(
            task_id=task_id,
            description=description,
            step_number=step_number
        )

        if step:
            serializer = TaskStepSerializer(step)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(
                {"error": "Failed to create step"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_step(request, task_id, step_number):
    """Mark a step as completed"""
    result = request.data.get('result', '')

    agent_service = AgentService(request.user.id)
    success = agent_service.complete_task_step(task_id, step_number, result)

    if success:
        try:
            step = TaskStep.objects.get(
                task__id=task_id, step_number=step_number)
            serializer = TaskStepSerializer(step)
            return Response(serializer.data)
        except TaskStep.DoesNotExist:
            return Response(
                {"error": "Step not found"},
                status=status.HTTP_404_NOT_FOUND
            )
    else:
        return Response(
            {"error": "Failed to complete step"},
            status=status.HTTP_404_NOT_FOUND
        )
