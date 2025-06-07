from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from datetime import datetime
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q

# Create your views here.
import os
import json
import requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from .models import UserProfile, HubspotContact, EmailInteraction, CalendarEvent, Chat, ChatMessage
from .utils import RAGService


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

    return render(request, 'dashboard.html', context)


@login_required
def hubspot_auth(request):
    # Initiate HubSpot OAuth flow
    auth_url = (
        f"https://app.hubspot.com/oauth/authorize"
        f"?client_id={settings.HUBSPOT_CLIENT_ID}"
        f"&redirect_uri={settings.HUBSPOT_REDIRECT_URI}"
        f"&scope=contacts%20timeline"
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


@login_required
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


def fetch_hubspot_contacts(user):
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
        name_matches = extract_name_from_query(message_text)
        
        if name_matches:
            # Find matching contacts
            potential_contacts = find_matching_contacts(request.user, name_matches)
            
            if len(potential_contacts) == 0:
                answer = f"I couldn't find any contacts matching '{name_matches}'. Please try another name or check the spelling."
            elif len(potential_contacts) == 1:
                # Single match, use this contact's ID for filtering
                contact_id = potential_contacts[0].contact_id
                contact_name_match = potential_contacts[0].name
                answer = rag_service.answer_question(message_text, history, contact_id)
            else:
                # Multiple matches, ask for clarification
                contact_options = ", ".join([f"{c.name} ({c.email})" for c in potential_contacts[:5]])
                answer = f"I found multiple contacts matching '{name_matches}'. Which one do you mean? {contact_options}"
                
                # Create a ChatMessage linking to potential contacts for follow-up
                for contact in potential_contacts[:5]:
                    chat_msg = ChatMessage.objects.create(
                        chat=chat,
                        role='system',
                        content=f"Potential contact: {contact.name}",
                        contact=HubspotContact.objects.get(user=request.user, contact_id=contact.contact_id)
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


def extract_name_from_query(query):
    """
    Extract potential person name from a query.
    Returns the name or None if no clear name is found.
    """
    # Very simple extraction for common question patterns
    # Could be improved with NLP in a production environment
    query = query.lower()
    
    # Patterns like "Why did [name] say..."
    patterns = [
        r"why did ([a-z]+) say",
        r"what did ([a-z]+) say about",
        r"when did ([a-z]+) mention",
        r"how did ([a-z]+) feel about",
        r"where is ([a-z]+) from"
    ]
    
    for pattern in patterns:
        import re
        match = re.search(pattern, query)
        if match:
            return match.group(1)
    
    return None


def find_matching_contacts(user, name_query):
    """
    Find contacts matching a name query.
    Returns a list of matching contact objects.
    """
    # First try exact matches on first name
    contacts = HubspotContact.objects.filter(
        user=user,
        name__icontains=name_query
    )
    
    return contacts


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
        name_matches = extract_name_from_query(message_text)

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


def extract_name_from_query(query):
    """
    Extract potential person name from a query.
    Returns the name or None if no clear name is found.
    """
    # Very simple extraction for common question patterns
    # Could be improved with NLP in a production environment
    query = query.lower()

    # Patterns like "Why did [name] say..."
    patterns = [
        r"why did ([a-z]+) say",
        r"what did ([a-z]+) say about",
        r"when did ([a-z]+) mention",
        r"how did ([a-z]+) feel about",
        r"where is ([a-z]+) from"
    ]

    for pattern in patterns:
        import re
        match = re.search(pattern, query)
        if match:
            return match.group(1)

    return None


def find_matching_contacts(user, name_query):
    """
    Find contacts matching a name query.
    Returns a list of matching contact objects.
    """
    # First try exact matches on first name
    contacts = HubspotContact.objects.filter(
        user=user,
        name__icontains=name_query
    )

    return contacts
