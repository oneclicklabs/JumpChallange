from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from datetime import datetime
from django.contrib.auth import login as auth_login
from django.contrib.auth.models import User

# Create your views here.
import os
import json
import requests
import google.oauth2.credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from .models import UserProfile, HubspotContact, EmailInteraction, CalendarEvent


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
        has_google = profile.google_token is not None
        has_hubspot = profile.hubspot_token is not None
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

            # Extract email details
            subject = next(
                (h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            from_email = next(
                (h['value'] for h in headers if h['name'] == 'From'), 'Unknown')

            # Extract email address only
            if '<' in from_email and '>' in from_email:
                from_email = from_email.split('<')[1].split('>')[0]

            # Check if this is from a contact we know
            contacts = HubspotContact.objects.filter(
                user=request.user, email=from_email)
            if contacts.exists():
                contact = contacts.first()

                # Create or update email interaction
            EmailInteraction.objects.update_or_create(
                contact=contact,
                subject=subject,
                defaults={
                    'snippet': message.get('snippet', ''),
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
