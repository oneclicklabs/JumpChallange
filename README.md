# Financial Advisor AI Integration

This Django project provides an AI agent for Financial Advisors that integrates with Gmail, Google Calendar and Hubspot.

## Features

- Google OAuth integration (Gmail and Calendar access)
- HubSpot CRM integration
- Dashboard with AI-powered insights
- Email communication analysis
- Calendar event management

## Setup Instructions

### 1. Install Dependencies

```bash
pip install social-auth-app-django django-rest-framework google-auth google-auth-oauthlib google-api-python-client
```

### 2. Configure OAuth Credentials

#### Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the Gmail API and Google Calendar API
4. Create OAuth credentials
   - Application type: Web application
   - Authorized JavaScript origins: `http://localhost:8000`
   - Authorized redirect URIs: `http://127.0.0.1:8000/oauth/complete/google-oauth2/`
5. Add webshookeng@gmail.com as a test user
6. Update settings.py with your CLIENT_ID and CLIENT_SECRET

#### HubSpot OAuth

1. Go to [HubSpot Developer Portal](https://developers.hubspot.com/)
2. Create a new app
3. Add redirect URL: `http://localhost:8000/hubspot-callback/`
4. Update settings.py with your CLIENT_ID and CLIENT_SECRET

### 3. Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 4. Run Server

```bash
python manage.py runserver
```

## Known Issues and Solutions

### Google OAuth Redirect Issue

Google OAuth may redirect with malformed URLs containing spaces and extra parameters:
```
/oauth/complete/google-oauth2/ flowName=GeneralOAuthFlow
```

We handle this with a custom middleware (`GoogleOAuthFixMiddleware`) that intercepts and fixes these URLs before they're processed by Django's URL resolver.

## Project Structure

- `financial_advisor_ai/`: Main app
  - `middleware.py`: Contains custom middleware for handling OAuth issues
  - `models.py`: Data models for user profiles, contacts, and interactions
  - `signals.py`: Signal handlers for OAuth token management
  - `views.py`: View controllers
  - `urls.py`: URL routing
- `templates/`: HTML templates
- `static/`: Static assets (CSS, JS)
