# Google OAuth Integration

This document explains the implementation of Google OAuth in the Financial Advisor AI project.

## Overview

We've implemented Google OAuth using Google's official client libraries, following best practices. This implementation allows:

1. Users to log in with their Google accounts
2. The application to access Gmail and Calendar data (with permission)
3. Secure handling of authentication tokens

## Implementation Details

### Key Components

1. **Authentication Flow:**
   - Uses Google's OAuth 2.0 flow via `google_auth_oauthlib.flow.Flow`
   - Handles authorization code exchange for access tokens
   - Validates ID tokens to verify user identity
   - Creates or updates user accounts based on Google profile information

2. **Token Management:**
   - Securely stores access and refresh tokens in the UserProfile model
   - Uses refresh tokens to maintain long-term access
   - Handles token expiration gracefully

3. **API Services:**
   - Gmail API integration for email analysis
   - Calendar API integration for event management

### Configuration

1. **Google Cloud Console Setup:**
   - Create a project in Google Cloud Console
   - Enable Gmail and Calendar APIs
   - Configure OAuth consent screen (add test user: webshookeng@gmail.com)
   - Create OAuth client credentials (Web application type)
   - Add authorized redirect URI: http://127.0.0.1:8000/google/callback/

2. **Django Settings:**
   - `GOOGLE_CLIENT_ID`: Your Google OAuth client ID
   - `GOOGLE_CLIENT_SECRET`: Your Google OAuth client secret
   - `GOOGLE_REDIRECT_URI`: The callback URL (http://127.0.0.1:8000/google/callback/)
   - `GOOGLE_AUTH_SCOPES`: List of required API scopes

## How It Works

1. User clicks "Login with Google" button
2. User is redirected to Google's consent page
3. After consent, Google redirects to our callback URL with an authorization code
4. Our application exchanges the code for access and refresh tokens
5. User information is extracted from ID token
6. User is created or authenticated in our system
7. Tokens are saved for later API access

## Benefits Over social-auth-app-django

1. **Direct Control:** We have complete control over the authentication flow
2. **Custom Integration:** We can customize user creation and token storage
3. **Better Error Handling:** We can handle edge cases like URL malformation
4. **Simplified Dependencies:** We only use Google's official libraries
5. **Modern Approach:** Follow's Google's recommended integration patterns

## Security Considerations

1. Tokens are stored securely in the database
2. ID tokens are validated before use
3. State parameter prevents CSRF attacks
4. Refresh tokens enable long-term access without requiring re-authentication
