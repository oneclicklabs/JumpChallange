"""
Google Calendar API integration for managing calendar events
"""
import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from django.contrib.auth.models import User
from django.conf import settings
from ..models import HubspotContact, CalendarEvent, UserProfile

logger = logging.getLogger(__name__)

class CalendarAPI:
    """Google Calendar API wrapper for calendar operations"""
    
    def __init__(self, user_id):
        """Initialize the Calendar API client
        
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
                scopes=["https://www.googleapis.com/auth/calendar"]
            )
            
            # Create Calendar API service
            self.service = build('calendar', 'v3', credentials=credentials)
            self.initialized = True
            
        except Exception as e:
            logger.error(f"Error initializing Calendar API: {str(e)}")
            self.error = str(e)
    
    def get_events(self, days: int = 7, calendar_id: str = 'primary') -> List[Dict]:
        """Get upcoming calendar events
        
        Args:
            days: Number of days to look ahead
            calendar_id: Calendar ID to use (default: primary)
            
        Returns:
            List of calendar event dictionaries
        """
        if not self.initialized:
            logger.error("Calendar API not initialized")
            return []
            
        try:
            # Calculate time range
            now = datetime.utcnow()
            time_min = now.isoformat() + 'Z'  # 'Z' indicates UTC time
            time_max = (now + timedelta(days=days)).isoformat() + 'Z'
            
            # Get calendar events
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=100,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Format events
            formatted_events = []
            for event in events:
                start = event.get('start', {})
                end = event.get('end', {})
                
                # Get start and end times
                start_datetime = start.get('dateTime', start.get('date'))
                end_datetime = end.get('dateTime', end.get('date'))
                
                # Get attendees
                attendees = []
                for attendee in event.get('attendees', []):
                    attendees.append({
                        'email': attendee.get('email'),
                        'name': attendee.get('displayName', ''),
                        'status': attendee.get('responseStatus', 'needsAction')
                    })
                
                # Format event
                formatted_events.append({
                    'id': event.get('id'),
                    'summary': event.get('summary', 'Untitled Event'),
                    'description': event.get('description', ''),
                    'location': event.get('location', ''),
                    'start_datetime': start_datetime,
                    'end_datetime': end_datetime,
                    'attendees': attendees,
                    'status': event.get('status', 'confirmed'),
                    'html_link': event.get('htmlLink', '')
                })
            
            return formatted_events
            
        except Exception as e:
            logger.error(f"Error getting calendar events: {str(e)}")
            return []
    
    def create_event(self, summary: str, description: str, start_time: datetime, 
                     end_time: datetime, attendees: List[str] = None, 
                     calendar_id: str = 'primary', location: str = None) -> Optional[str]:
        """Create a new calendar event
        
        Args:
            summary: Event title/summary
            description: Event description
            start_time: Event start datetime
            end_time: Event end datetime
            attendees: List of attendee email addresses
            calendar_id: Calendar ID to use (default: primary)
            location: Optional location string
            
        Returns:
            Event ID if created successfully, None otherwise
        """
        if not self.initialized:
            logger.error("Calendar API not initialized")
            return None
            
        try:
            # Format attendees
            formatted_attendees = []
            if attendees:
                formatted_attendees = [{'email': email} for email in attendees]
            
            # Create event body
            event = {
                'summary': summary,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'UTC',
                },
                'attendees': formatted_attendees,
            }
            
            # Add location if provided
            if location:
                event['location'] = location
            
            # Create the event
            created_event = self.service.events().insert(
                calendarId=calendar_id,
                body=event,
                sendUpdates='all'
            ).execute()
            
            logger.info(f"Event created: {created_event.get('id')}")
            return created_event.get('id')
            
        except Exception as e:
            logger.error(f"Error creating calendar event: {str(e)}")
            return None
    
    def check_availability(self, start_time: datetime, end_time: datetime, 
                          calendar_id: str = 'primary') -> bool:
        """Check if a time slot is available
        
        Args:
            start_time: Start datetime to check
            end_time: End datetime to check
            calendar_id: Calendar ID to use (default: primary)
            
        Returns:
            True if the slot is available, False otherwise
        """
        if not self.initialized:
            logger.error("Calendar API not initialized")
            return False
            
        try:
            # Format time range
            time_min = start_time.isoformat() + 'Z'
            time_max = end_time.isoformat() + 'Z'
            
            # Get events in the time range
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True
            ).execute()
            
            events = events_result.get('items', [])
            
            # If there are any events, the slot is not available
            return len(events) == 0
            
        except Exception as e:
            logger.error(f"Error checking availability: {str(e)}")
            return False
    
    def find_available_slots(self, date: datetime, duration_minutes: int = 30, 
                            start_hour: int = 9, end_hour: int = 17, 
                            calendar_id: str = 'primary') -> List[Dict]:
        """Find available time slots on a given day
        
        Args:
            date: Date to check
            duration_minutes: Duration of desired slot in minutes
            start_hour: Start hour of the workday (24-hour format)
            end_hour: End hour of the workday (24-hour format)
            calendar_id: Calendar ID to use (default: primary)
            
        Returns:
            List of available time slots as {start, end} dictionaries
        """
        if not self.initialized:
            logger.error("Calendar API not initialized")
            return []
            
        try:
            # Set up the day's boundaries
            start_of_day = datetime(date.year, date.month, date.day, start_hour, 0, 0)
            end_of_day = datetime(date.year, date.month, date.day, end_hour, 0, 0)
            
            # Get all events for that day
            time_min = start_of_day.isoformat() + 'Z'
            time_max = end_of_day.isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Convert events to time blocks
            busy_blocks = []
            for event in events:
                start = event.get('start', {})
                end = event.get('end', {})
                
                # Parse start and end times
                start_datetime = start.get('dateTime')
                end_datetime = end.get('dateTime')
                
                if start_datetime and end_datetime:
                    start_dt = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
                    
                    busy_blocks.append({
                        'start': start_dt,
                        'end': end_dt
                    })
            
            # Find available slots
            available_slots = []
            slot_duration = timedelta(minutes=duration_minutes)
            
            # Start with the full day
            if not busy_blocks:
                # If no events, the whole day is available
                current = start_of_day
                while current + slot_duration <= end_of_day:
                    available_slots.append({
                        'start': current,
                        'end': current + slot_duration
                    })
                    current += timedelta(minutes=30)  # Advance by 30 minute increments
            else:
                # Sort busy blocks by start time
                busy_blocks.sort(key=lambda x: x['start'])
                
                # Check slot before first meeting
                current = start_of_day
                while current + slot_duration <= busy_blocks[0]['start']:
                    available_slots.append({
                        'start': current,
                        'end': current + slot_duration
                    })
                    current += timedelta(minutes=30)
                
                # Check slots between meetings
                for i in range(len(busy_blocks) - 1):
                    current = busy_blocks[i]['end']
                    while current + slot_duration <= busy_blocks[i+1]['start']:
                        available_slots.append({
                            'start': current,
                            'end': current + slot_duration
                        })
                        current += timedelta(minutes=30)
                
                # Check slot after last meeting
                current = busy_blocks[-1]['end']
                while current + slot_duration <= end_of_day:
                    available_slots.append({
                        'start': current,
                        'end': current + slot_duration
                    })
                    current += timedelta(minutes=30)
            
            return available_slots
            
        except Exception as e:
            logger.error(f"Error finding available slots: {str(e)}")
            return []
    
    def setup_watch(self, channel_id: str, address: str) -> bool:
        """Set up push notifications for calendar changes
        
        Args:
            channel_id: A unique channel ID
            address: Webhook URL to receive notifications
            
        Returns:
            True if watch was set up successfully, False otherwise
        """
        if not self.initialized:
            logger.error("Calendar API not initialized")
            return False
            
        try:
            # Set up notification for calendar changes
            result = self.service.events().watch(
                calendarId='primary',
                body={
                    'id': channel_id,
                    'type': 'web_hook',
                    'address': address
                }
            ).execute()
            
            logger.info(f"Calendar watch set up: {result}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up Calendar watch: {str(e)}")
            return False
    
    def sync_events_to_db(self, days=30) -> int:
        """Sync upcoming calendar events to database
        
        Args:
            days: Number of days to look ahead
            
        Returns:
            Number of events processed
        """
        if not self.initialized:
            logger.error("Calendar API not initialized")
            return 0
            
        try:
            # Get upcoming events
            events = self.get_events(days=days)
            
            count = 0
            for event in events:
                event_id = event.get('id')
                
                # Check if event already exists in DB
                existing = CalendarEvent.objects.filter(
                    user=self.user,
                    event_id=event_id
                )
                
                if not existing.exists():
                    # Parse start and end times
                    start_datetime = event.get('start_datetime')
                    end_datetime = event.get('end_datetime')
                    
                    start_time = datetime.fromisoformat(start_datetime.replace('Z', '+00:00')) if 'T' in start_datetime else datetime.strptime(start_datetime, '%Y-%m-%d')
                    end_time = datetime.fromisoformat(end_datetime.replace('Z', '+00:00')) if 'T' in end_datetime else datetime.strptime(end_datetime, '%Y-%m-%d')
                    
                    # Look for contact match in attendees
                    contact = None
                    for attendee in event.get('attendees', []):
                        attendee_email = attendee.get('email')
                        if attendee_email:
                            contacts = HubspotContact.objects.filter(
                                user=self.user,
                                email__iexact=attendee_email
                            )
                            if contacts.exists():
                                contact = contacts.first()
                                break
                    
                    # Create calendar event record
                    CalendarEvent.objects.create(
                        user=self.user,
                        contact=contact,
                        event_id=event_id,
                        title=event.get('summary', 'Untitled Event'),
                        description=event.get('description', ''),
                        start_time=start_time,
                        end_time=end_time,
                        status=event.get('status', 'confirmed')
                    )
                    
                    count += 1
            
            return count
            
        except Exception as e:
            logger.error(f"Error syncing events to DB: {str(e)}")
            return 0
