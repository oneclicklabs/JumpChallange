# Financial Advisor AI Integration Platform

A comprehensive Django-based AI agent platform designed for financial advisors to integrate with Gmail, Google Calendar, and HubSpot CRM. The platform provides intelligent chat capabilities using RAG (Retrieval-Augmented Generation) technology to analyze client communications and provide actionable insights.

## 🚀 Features

### Core Functionality
- **AI-Powered Chat Assistant**: Intelligent chatbot with RAG capabilities for client information retrieval
- **Multi-Platform Integration**: Seamless integration with Gmail, Google Calendar, and HubSpot CRM
- **Client Communication Analysis**: Automated email analysis and sentiment scoring
- **Task Management**: Agent-based task processing and automation
- **Dashboard Analytics**: Comprehensive dashboard with AI-generated insights

### Integration Capabilities
- **Google OAuth2 Authentication**: Secure login with Google accounts
- **Gmail API Integration**: Email synchronization and analysis
- **Google Calendar Integration**: Calendar event management and scheduling
- **HubSpot CRM Integration**: Contact management and CRM synchronization
- **OpenAI Integration**: Advanced AI capabilities for chat and analysis

### Advanced Features
- **RAG (Retrieval-Augmented Generation)**: Context-aware responses based on client data
- **Contact Name Extraction**: Intelligent parsing of client references in conversations
- **Multi-Contact Disambiguation**: Smart handling of ambiguous name references
- **Real-time Data Processing**: Live synchronization with external platforms
- **Webhook Support**: Event-driven updates and notifications

## 📋 Prerequisites

- Python 3.13+
- Django 5.2+
- Pipenv (recommended) or pip
- Google Cloud Console account
- HubSpot Developer account
- OpenAI API key

## 🛠️ Installation

### 1. Clone and Setup Environment

```bash
git clone <repository-url>
cd JumpChallange
pipenv install
pipenv shell
```

### 2. Configure OAuth Credentials

#### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the following APIs:
   - Gmail API
   - Google Calendar API
   - Google+ API (for user info)
4. Create OAuth 2.0 credentials:
   - Application type: **Web application**
   - Authorized JavaScript origins: `http://localhost:8000`
   - Authorized redirect URIs: `http://127.0.0.1:8000/google/callback/`
5. Add test users (if app is in testing mode):
   - Add your email address
   - Add `webshookeng@gmail.com` as a test user
6. Download credentials and note the Client ID and Client Secret

#### HubSpot OAuth Setup

1. Go to [HubSpot Developer Portal](https://developers.hubspot.com/)
2. Create a new app or select existing one
3. Configure OAuth settings:
   - Redirect URL: `http://localhost:8000/hubspot-callback/`
   - Scopes: `crm.objects.contacts.read`, `timeline`
4. Note your Client ID and Client Secret

#### OpenAI API Setup

1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Generate an API key
3. Save the API key for configuration

### 3. Environment Configuration

Update `JumpTest/JumpTest/settings.py` with your credentials:

```python
# Google OAuth Settings
GOOGLE_CLIENT_ID = 'your-google-client-id'
GOOGLE_CLIENT_SECRET = 'your-google-client-secret'
GOOGLE_REDIRECT_URI = 'http://127.0.0.1:8000/google/callback/'

# HubSpot OAuth Settings
HUBSPOT_CLIENT_ID = 'your-hubspot-client-id'
HUBSPOT_CLIENT_SECRET = 'your-hubspot-client-secret'
HUBSPOT_REDIRECT_URI = 'http://localhost:8000/hubspot-callback/'
```

### 4. Database Setup

```bash
cd JumpTest
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser  # Optional: create admin user
```

### 5. Run the Application

```bash
python manage.py runserver
```

Visit `http://localhost:8000` to access the application.

## 🏗️ Project Structure

```
JumpTest/
├── financial_advisor_ai/          # Main application
│   ├── models.py                  # Data models
│   ├── views.py                   # View controllers
│   ├── urls.py                    # URL routing
│   ├── middleware.py              # Custom middleware
│   ├── agent_service.py           # AI agent services
│   ├── agent_tools.py             # Agent automation tools
│   ├── task_processor.py          # Background task processing
│   ├── utils.py                   # RAG and utility functions
│   ├── serializers.py             # API serializers
│   ├── integrations/              # External API integrations
│   │   ├── gmail.py               # Gmail API wrapper
│   │   ├── calendar.py            # Google Calendar API wrapper
│   │   └── hubspot.py             # HubSpot CRM API wrapper
│   └── migrations/                # Database migrations
├── JumpTest/                      # Django project settings
│   ├── settings.py                # Configuration
│   ├── urls.py                    # Main URL routing
│   └── wsgi.py                    # WSGI configuration
├── templates/                     # HTML templates
│   ├── dashboard.html             # Main dashboard
│   ├── chat.html                  # Chat interface
│   ├── login.html                 # Authentication
│   └── user_settings.html         # User preferences
├── static/                        # Static assets
│   ├── style.css                  # Main styles
│   └── style2.css                 # Additional styles
└── manage.py                      # Django management script
```

## 📊 Data Models

### Core Models

- **UserProfile**: Extended user information with OAuth tokens
- **HubspotContact**: CRM contact information
- **EmailInteraction**: Email data with sentiment analysis
- **CalendarEvent**: Calendar event details
- **Chat**: Chat session management
- **ChatMessage**: Individual chat messages
- **AgentTask**: Automated task management

### Key Features

- **RAG Integration**: Email content serialization for vector database
- **Contact Linking**: Automatic association between emails and contacts
- **Task Automation**: Background processing for agent tasks
- **Sentiment Analysis**: Automated email sentiment scoring

## 🔧 API Endpoints

### Authentication
- `GET /google/login/` - Initiate Google OAuth
- `GET /google/callback/` - Handle Google OAuth callback
- `GET /hubspot-auth/` - Initiate HubSpot OAuth
- `GET /hubspot-callback/` - Handle HubSpot OAuth callback

### Core Features
- `GET /dashboard/` - Main dashboard
- `GET /chat/` - Chat interface
- `POST /chat/<chat_id>/message/` - Send chat message
- `GET /sync-gmail/` - Sync Gmail data
- `GET /sync-calendar/` - Sync calendar data
- `GET /ai-insights/` - Get AI insights

### Agent API
- `GET|POST /api/tasks/` - Task management
- `GET|PUT|DELETE /api/tasks/<id>/` - Task details
- `POST /api/tasks/<id>/complete/` - Complete task
- `GET /api/suggested-tasks/` - Get task suggestions

## 💡 Usage Guide

### 1. Initial Setup

1. **Login**: Use Google OAuth to authenticate
2. **Connect HubSpot**: Link your HubSpot CRM account
3. **Add OpenAI Key**: Configure OpenAI API key in user settings
4. **Sync Data**: Synchronize Gmail and Calendar data

### 2. Using the Chat Assistant

1. **Start a Chat**: Click "New Chat" on the dashboard
2. **Ask Questions**: Query about specific clients or general information
3. **Context-Aware Responses**: The AI uses your email and CRM data for answers
4. **Name Resolution**: Ask about clients by name - the system handles ambiguous references

Example queries:
- "What did John say about the investment proposal?"
- "When is my next meeting with Sarah?"
- "Show me recent emails from Microsoft clients"

### 3. Agent Tasks

1. **Automated Tasks**: The system can perform background tasks
2. **Task Suggestions**: AI suggests tasks based on your data
3. **Task Monitoring**: Track progress of automated actions

## 🔍 Advanced Features

### RAG (Retrieval-Augmented Generation)

The platform uses RAG technology to provide context-aware responses:

- **Email Indexing**: All emails are processed and indexed
- **Semantic Search**: Natural language queries across your data
- **Context Integration**: Responses include relevant email content
- **Contact Association**: Automatically links conversations to specific contacts

### Name Extraction and Disambiguation

- **Pattern Matching**: Identifies client names in queries
- **AI-Powered Extraction**: Uses OpenAI for complex name extraction
- **Multiple Match Handling**: Clarifies when multiple contacts match
- **Context History**: Uses conversation history for disambiguation

### Middleware and Error Handling

- **OAuth Fix Middleware**: Handles malformed Google OAuth redirects
- **Token Refresh**: Automatic refresh of expired tokens
- **Error Recovery**: Graceful handling of API failures
- **Comprehensive Logging**: Detailed logging for debugging

## 🛡️ Security Features

- **OAuth2 Implementation**: Secure authentication flow
- **Token Encryption**: Secure storage of access tokens
- **State Validation**: CSRF protection for OAuth flows
- **API Key Management**: Secure handling of third-party API keys
- **User Isolation**: Data segregation per user account

## 🐛 Known Issues and Solutions

### Google OAuth Redirect Issue

Google OAuth may redirect with malformed URLs containing extra parameters. This is handled by `GoogleOAuthFixMiddleware` which automatically fixes these URLs.

### Token Expiration

The platform automatically refreshes expired tokens for both Google and HubSpot services. If refresh fails, users are prompted to re-authenticate.

### Rate Limiting

API calls are optimized to stay within rate limits of external services. The system includes retry logic and exponential backoff.

## 🧪 Testing

Run the test suite:

```bash
python manage.py test
python run_tests.py  # Custom test runner
```

Test webhook functionality:
```bash
python test_webhooks.py
```

## 📦 Dependencies

Main packages (see `Pipfile` for complete list):

- **Django 5.2+**: Web framework
- **Django REST Framework**: API development
- **Google Auth Libraries**: OAuth and API access
- **Requests**: HTTP client for API calls
- **Social Auth**: Additional authentication support

## 🚀 Deployment

### Development
```bash
python manage.py runserver
```

### Production Considerations

1. **Environment Variables**: Move sensitive settings to environment variables
2. **Database**: Use PostgreSQL or MySQL for production
3. **Static Files**: Configure static file serving
4. **HTTPS**: Enable SSL/TLS in production
5. **Error Monitoring**: Implement error tracking (e.g., Sentry)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License. See the LICENSE file for details.

## 📞 Support

For issues and support:

1. Check existing issues in the repository
2. Create a new issue with detailed description
3. Include error logs and reproduction steps

## 🔮 Future Enhancements

- **Multi-language Support**: Internationalization
- **Advanced Analytics**: Enhanced reporting and insights
- **Mobile App**: React Native or Flutter mobile application
- **Webhook Integrations**: Real-time updates from external services
- **Advanced AI Features**: More sophisticated AI capabilities
- **Team Collaboration**: Multi-user features and permissions

---

**Note**: This platform is designed for financial advisors and contains features specific to client relationship management. Ensure compliance with financial industry regulations and data protection laws in your jurisdiction.
