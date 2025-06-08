"""
Tool implementations for the agent functionality.
These tools can be called by the LLM to perform various actions.
"""
import logging
import json
from datetime import datetime, timedelta
import re
from typing import Dict, List, Any, Optional, Union
from django.utils import timezone
from django.conf import settings
from django.contrib.auth.models import User

from .agent_service import register_tool
from .models import (
    HubspotContact, EmailInteraction, CalendarEvent, 
    AgentTask, AgentMemory
)
from .integrations.gmail import GmailAPI
from .integrations.calendar import CalendarAPI
from .integrations.hubspot import HubspotAPI

logger = logging.getLogger(__name__)

# Email tools
@register_tool(
    name="find_contact",
    description="Find a contact by name or email address in the system",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Name or email address to search for"
            }
        },
        "required": ["query"]
    }
)
def find_contact(user: User, query: str) -> Dict:
    """Find a contact by name or email address"""
    # Search by name (case-insensitive)
    name_matches = HubspotContact.objects.filter(
        user=user, 
        name__icontains=query
    )
    
    # Search by email (case-insensitive)
    email_matches = HubspotContact.objects.filter(
        user=user,
        email__icontains=query
    )
    
    # Combine results (avoiding duplicates)
    contacts = list(name_matches) + [c for c in email_matches if c not in name_matches]
    
    # Format the results
    results = []
    for contact in contacts:
        results.append({
            "id": contact.contact_id,
            "name": contact.name,
            "email": contact.email,
            "last_interaction": contact.last_interaction.isoformat() if contact.last_interaction else None
        })
        
    return {
        "found": len(results) > 0,
        "count": len(results),
        "contacts": results
    }


@register_tool(
    name="get_contact_emails",
    description="Get recent emails from a specific contact",
    parameters={
        "type": "object",
        "properties": {
            "contact_id": {
                "type": "string",
                "description": "ID of the contact"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of emails to retrieve (default: 5)"
            }
        },
        "required": ["contact_id"]
    }
)
def get_contact_emails(user: User, contact_id: str, limit: int = 5) -> Dict:
    """Get recent emails from a specific contact"""
    try:
        contact = HubspotContact.objects.get(user=user, contact_id=contact_id)
        
        # Get emails sorted by most recent first
        emails = EmailInteraction.objects.filter(
            contact=contact
        ).order_by('-received_at')[:limit]
        
        # Format the results
        results = []
        for email in emails:
            results.append({
                "id": email.id,
                "subject": email.subject,
                "snippet": email.snippet,
                "content": email.full_content,
                "date": email.received_at.isoformat()
            })
            
        return {
            "contact_name": contact.name,
            "contact_email": contact.email,
            "found": len(results) > 0,
            "count": len(results),
            "emails": results
        }
        
    except HubspotContact.DoesNotExist:
        return {
            "error": f"Contact with ID {contact_id} not found",
            "found": False,
            "count": 0,
            "emails": []
        }


@register_tool(
    name="send_email",
    description="Send an email to a contact",
    parameters={
        "type": "object",
        "properties": {
            "contact_id": {
                "type": "string",
                "description": "ID of the contact to email"
            },
            "subject": {
                "type": "string",
                "description": "Email subject line"
            },
            "body": {
                "type": "string",
                "description": "Email body content"
            },
            "html_body": {
                "type": "string",
                "description": "Optional HTML version of the email body"
            }
        },
        "required": ["contact_id", "subject", "body"]
    }
)
def send_email(user: User, contact_id: str, subject: str, body: str, html_body: str = None) -> Dict:
    """Send an email to a contact using Gmail API"""
    try:
        # Get the contact
        contact = HubspotContact.objects.get(user=user, contact_id=contact_id)
        
        # Initialize Gmail API
        gmail_api = GmailAPI(user.id)
        
        if not gmail_api.initialized:
            return {
                "success": False,
                "error": f"Gmail API not initialized: {gmail_api.error}"
            }
        
        # Send email using Gmail API
        success = gmail_api.send_email(
            to=contact.email,
            subject=subject,
            body=body,
            html_body=html_body
        )
        
        if success:
            # Log the email sending
            logger.info(f"Email sent to {contact.name} <{contact.email}>")
            
            # Record interaction (in a production system, you would do this via webhook)
            current_time = timezone.now()
            EmailInteraction.objects.create(
                contact=contact,
                subject=subject,
                snippet=body[:100] + ("..." if len(body) > 100 else ""),
                received_at=current_time,
                full_content=body
            )
            
            # Update last interaction time
            contact.last_interaction = current_time
            contact.save()
            
            return {
                "success": True,
                "to": contact.email,
                "subject": subject,
                "message": "Email sent successfully",
                "timestamp": current_time.isoformat()
            }
        else:
            return {
                "success": False,
                "error": "Failed to send email through Gmail API"
            }
        
    except HubspotContact.DoesNotExist:
        return {
            "success": False,
            "error": f"Contact with ID {contact_id} not found"
        }
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return {
            "success": False,
            "error": f"Error sending email: {str(e)}"
        }


# Calendar tools
@register_tool(
    name="get_calendar_events",
    description="Get upcoming calendar events",
    parameters={
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "Start date for events (ISO format, default: today)"
            },
            "end_date": {
                "type": "string",
                "description": "End date for events (ISO format, default: 7 days from start)"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of events to retrieve (default: 10)"
            }
        }
    }
)
def get_calendar_events(user: User, start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 10) -> Dict:
    """Get upcoming calendar events using the Calendar API"""
    try:
        # Initialize Calendar API
        calendar_api = CalendarAPI(user.id)
        
        if not calendar_api.initialized:
            return {
                "error": f"Calendar API not initialized: {calendar_api.error}",
                "found": False,
                "count": 0,
                "events": []
            }
            
        # Set default dates if not provided
        if start_date:
            start = datetime.fromisoformat(start_date)
        else:
            start = datetime.now()
            
        if end_date:
            end = datetime.fromisoformat(end_date)
        else:
            end = start + timedelta(days=7)
            
        # Calculate days between start and end
        days = (end - start).days + 1
        
        # Get events from Calendar API
        calendar_events = calendar_api.get_events(days=days)
        
        # Filter events to the requested date range
        filtered_events = []
        for event in calendar_events:
            event_start = event.get('start_datetime')
            if 'T' in event_start:
                event_start_dt = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
            else:
                event_start_dt = datetime.strptime(event_start, '%Y-%m-%d')
                
            # Only include events that start after our requested start date
            if start <= event_start_dt <= end:
                filtered_events.append(event)
                
        # Limit results
        filtered_events = filtered_events[:limit]
        
        # Format results
        results = []
        for event in filtered_events:
            # Try to find matching contact
            attendee_info = None
            attendees = event.get('attendees', [])
            if attendees:
                for attendee in attendees:
                    email = attendee.get('email')
                    if email:
                        contacts = HubspotContact.objects.filter(
                            user=user,
                            email__iexact=email
                        )
                        if contacts.exists():
                            contact = contacts.first()
                            attendee_info = {
                                "id": contact.contact_id,
                                "name": contact.name,
                                "email": contact.email
                            }
                            break
            
            # Format event
            results.append({
                "id": event.get('id'),
                "title": event.get('summary'),
                "description": event.get('description', ''),
                "start": event.get('start_datetime'),
                "end": event.get('end_datetime'),
                "status": event.get('status'),
                "location": event.get('location', ''),
                "attendee": attendee_info
            })
            
        # Also sync events to database in the background
        calendar_api.sync_events_to_db()
            
        return {
            "found": len(results) > 0,
            "count": len(results),
            "events": results
        }
        
    except Exception as e:
        logger.error(f"Error fetching calendar events: {str(e)}")
        return {
            "error": f"Error fetching calendar events: {str(e)}",
            "found": False,
            "count": 0,
            "events": []
        }


@register_tool(
    name="check_availability",
    description="Check calendar availability for a given time period",
    parameters={
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "Start date and time to check (ISO format)"
            },
            "end_date": {
                "type": "string",
                "description": "End date and time to check (ISO format)"
            }
        },
        "required": ["start_date", "end_date"]
    }
)
def check_availability(user: User, start_date: str, end_date: str) -> Dict:
    """Check if a time slot is available in the calendar using Calendar API"""
    try:
        # Initialize Calendar API
        calendar_api = CalendarAPI(user.id)
        
        if not calendar_api.initialized:
            return {
                "error": f"Calendar API not initialized: {calendar_api.error}",
                "is_available": False
            }
        
        # Parse dates
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        
        # Check availability with Calendar API
        is_available = calendar_api.check_availability(start, end)
        
        if is_available:
            return {
                "is_available": True,
                "conflicts": []
            }
            
        # If not available, get events for that time period to show conflicts
        days = 1  # Just get events for a single day
        events = calendar_api.get_events(days=days)
        
        # Filter to just events that conflict with the requested time
        conflict_list = []
        for event in events:
            event_start = event.get('start_datetime')
            event_end = event.get('end_datetime')
            
            if 'T' in event_start:
                event_start_dt = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
            else:
                event_start_dt = datetime.strptime(event_start, '%Y-%m-%d')
                
            if 'T' in event_end:
                event_end_dt = datetime.fromisoformat(event_end.replace('Z', '+00:00'))
            else:
                event_end_dt = datetime.strptime(event_end, '%Y-%m-%d')
            
            # Check if this event conflicts with our requested time
            if event_start_dt < end and event_end_dt > start:
                conflict_list.append({
                    "title": event.get('summary'),
                    "start": event_start,
                    "end": event_end
                })
        
        return {
            "is_available": False,
            "conflicts": conflict_list
        }
        
    except Exception as e:
        logger.error(f"Error checking availability: {str(e)}")
        return {
            "error": f"Error checking availability: {str(e)}",
            "is_available": False
        }


@register_tool(
    name="create_calendar_event",
    description="Create a new calendar event",
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Event title"
            },
            "description": {
                "type": "string",
                "description": "Event description"
            },
            "start_time": {
                "type": "string",
                "description": "Event start time (ISO format)"
            },
            "end_time": {
                "type": "string",
                "description": "Event end time (ISO format)"
            },
            "contact_id": {
                "type": "string",
                "description": "ID of the contact associated with the event (optional)"
            }
        },
        "required": ["title", "start_time", "end_time"]
    }
)
def create_calendar_event(user: User, title: str, start_time: str, end_time: str, description: str = "", contact_id: Optional[str] = None) -> Dict:
    """Create a new calendar event using Calendar API"""
    try:
        # Initialize Calendar API
        calendar_api = CalendarAPI(user.id)
        
        if not calendar_api.initialized:
            return {
                "success": False,
                "error": f"Calendar API not initialized: {calendar_api.error}"
            }
        
        # Parse times
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
        
        # Check if contact exists if provided
        contact = None
        attendees = []
        
        if contact_id:
            try:
                contact = HubspotContact.objects.get(user=user, contact_id=contact_id)
                attendees = [contact.email]
            except HubspotContact.DoesNotExist:
                return {
                    "success": False,
                    "error": f"Contact with ID {contact_id} not found"
                }
        
        # Create event with Calendar API
        event_id = calendar_api.create_event(
            summary=title,
            description=description,
            start_time=start,
            end_time=end,
            attendees=attendees if attendees else None
        )
        
        if event_id:
            # Store in our database as well
            event = CalendarEvent.objects.create(
                user=user,
                event_id=event_id,
                title=title,
                description=description,
                start_time=start,
                end_time=end,
                status='confirmed',
                contact=contact
            )
            
            # If we have a HubSpot contact, create a meeting there too
            if contact and contact_id:
                try:
                    hubspot_api = HubspotAPI(user.id)
                    if hubspot_api.initialized:
                        hubspot_api.create_meeting(
                            contact_id=contact_id,
                            title=title,
                            description=description,
                            start_time=start,
                            end_time=end
                        )
                except Exception as e:
                    logger.error(f"Error creating HubSpot meeting: {str(e)}")
            
            return {
                "success": True,
                "message": "Calendar event created successfully",
                "event_id": event_id,
                "title": title,
                "start": start.isoformat(),
                "end": end.isoformat()
            }
        else:
            return {
                "success": False,
                "error": "Failed to create calendar event through API"
            }
        
    except Exception as e:
        logger.error(f"Error creating calendar event: {str(e)}")
        return {
            "success": False,
            "error": f"Error creating calendar event: {str(e)}"
        }


# HubSpot tools
@register_tool(
    name="create_hubspot_contact",
    description="Create a new contact in HubSpot",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Contact's full name"
            },
            "email": {
                "type": "string",
                "description": "Contact's email address"
            },
            "phone": {
                "type": "string",
                "description": "Contact's phone number (optional)"
            },
            "company": {
                "type": "string",
                "description": "Contact's company (optional)"
            }
        },
        "required": ["name", "email"]
    }
)
def create_hubspot_contact(user: User, name: str, email: str, phone: Optional[str] = None, company: Optional[str] = None) -> Dict:
    """Create a new contact in HubSpot using HubSpot API"""
    try:
        # Check if contact with this email already exists
        existing = HubspotContact.objects.filter(user=user, email=email).first()
        if existing:
            return {
                "success": False,
                "error": f"Contact with email {email} already exists",
                "contact_id": existing.contact_id
            }
        
        # Initialize HubSpot API
        hubspot_api = HubspotAPI(user.id)
        
        if not hubspot_api.initialized:
            return {
                "success": False,
                "error": f"HubSpot API not initialized: {hubspot_api.error}"
            }
        
        # Parse name into first/last name
        name_parts = name.split()
        if len(name_parts) > 1:
            first_name = name_parts[0]
            last_name = " ".join(name_parts[1:])
        else:
            first_name = name
            last_name = ""
        
        # Create contact with HubSpot API
        contact_id = hubspot_api.create_contact(
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            company=company
        )
        
        if contact_id:
            # Get the newly created contact from database
            contact = HubspotContact.objects.get(user=user, contact_id=contact_id)
            
            return {
                "success": True,
                "message": "Contact created successfully in HubSpot",
                "contact_id": contact_id,
                "name": contact.name,
                "email": contact.email
            }
        else:
            return {
                "success": False,
                "error": "Failed to create contact through HubSpot API"
            }
        
    except Exception as e:
        logger.error(f"Error creating HubSpot contact: {str(e)}")
        return {
            "success": False,
            "error": f"Error creating contact: {str(e)}"
        }


@register_tool(
    name="add_hubspot_note",
    description="Add a note to a HubSpot contact",
    parameters={
        "type": "object",
        "properties": {
            "contact_id": {
                "type": "string",
                "description": "ID of the contact"
            },
            "content": {
                "type": "string",
                "description": "Note content"
            }
        },
        "required": ["contact_id", "content"]
    }
)
def add_hubspot_note(user: User, contact_id: str, content: str) -> Dict:
    """Add a note to a HubSpot contact using HubSpot API"""
    try:
        # Verify contact exists in our database
        contact = HubspotContact.objects.get(user=user, contact_id=contact_id)
        
        # Initialize HubSpot API
        hubspot_api = HubspotAPI(user.id)
        
        if not hubspot_api.initialized:
            return {
                "success": False,
                "error": f"HubSpot API not initialized: {hubspot_api.error}"
            }
        
        # Add note through HubSpot API
        note_id = hubspot_api.add_note_to_contact(contact_id, content)
        
        if note_id:
            # Update last interaction time in our database
            contact.last_interaction = timezone.now()
            contact.save()
            
            return {
                "success": True,
                "message": f"Note added to contact {contact.name}",
                "contact_id": contact.contact_id,
                "note_id": note_id,
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "success": False,
                "error": "Failed to add note through HubSpot API"
            }
        
    except HubspotContact.DoesNotExist:
        return {
            "success": False,
            "error": f"Contact with ID {contact_id} not found"
        }
    except Exception as e:
        logger.error(f"Error adding note to HubSpot contact: {str(e)}")
        return {
            "success": False,
            "error": f"Error adding note: {str(e)}"
        }


# Memory tools
@register_tool(
    name="save_memory",
    description="Save information to agent memory for later reference",
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key to identify this memory"
            },
            "value": {
                "type": "string",
                "description": "Information to save"
            },
            "context": {
                "type": "string",
                "description": "Additional context about this memory (optional)"
            }
        },
        "required": ["key", "value"]
    }
)
def save_memory_tool(user: User, key: str, value: str, context: Optional[str] = None) -> Dict:
    """Save information to agent memory for later reference"""
    try:
        # Create or update memory
        memory, created = AgentMemory.objects.update_or_create(
            user=user,
            key=key,
            defaults={
                'value': value,
                'context': context or ''
            }
        )
        
        action = "Created" if created else "Updated"
        
        return {
            "success": True,
            "message": f"{action} memory with key '{key}'",
            "key": key,
            "value": value
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Error saving memory: {str(e)}"
        }


@register_tool(
    name="get_memory",
    description="Retrieve information from agent memory",
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key of the memory to retrieve"
            }
        },
        "required": ["key"]
    }
)
def get_memory_tool(user: User, key: str) -> Dict:
    """Retrieve information from agent memory"""
    try:
        # Try to get memory
        try:
            memory = AgentMemory.objects.get(user=user, key=key)
            return {
                "found": True,
                "key": key,
                "value": memory.value,
                "context": memory.context,
                "updated_at": memory.updated_at.isoformat()
            }
        except AgentMemory.DoesNotExist:
            return {
                "found": False,
                "key": key,
                "message": f"No memory found with key '{key}'"
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Error retrieving memory: {str(e)}"
        }


@register_tool(
    name="list_memories",
    description="List all saved memories",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Optional pattern to filter memory keys (supports wildcards)"
            }
        }
    }
)
def list_memories(user: User, pattern: Optional[str] = None) -> Dict:
    """List all saved memories, optionally filtered by a pattern"""
    try:
        # Get all memories for the user
        memories = AgentMemory.objects.filter(user=user).order_by('key')
        
        # Filter by pattern if provided
        if pattern:
            # Convert wildcard pattern to regex
            regex_pattern = pattern.replace('*', '.*')
            filtered_memories = [m for m in memories if re.match(regex_pattern, m.key)]
        else:
            filtered_memories = memories
            
        # Format the results
        results = []
        for memory in filtered_memories:
            results.append({
                "key": memory.key,
                "value": memory.value,
                "updated_at": memory.updated_at.isoformat()
            })
            
        return {
            "count": len(results),
            "memories": results
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Error listing memories: {str(e)}"
        }


# Task management tools
@register_tool(
    name="complete_task",
    description="Mark the current task as completed",
    parameters={
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Final result or summary of the completed task"
            }
        },
        "required": ["result"]
    }
)
def complete_task_tool(user: User, result: str) -> Dict:
    """Mark the current task as completed"""
    # This tool implementation relies on the task_id being in the context
    # The AgentService will handle this when processing tool calls
    
    # In a real implementation, we'd get the task_id from context
    # For now, we'll return a message to be handled by the agent service
    
    return {
        "success": True,
        "message": "Task marked as completed",
        "result": result,
        "action": "complete_task"
    }


@register_tool(
    name="add_task_step",
    description="Add a step to the current task",
    parameters={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Description of the task step"
            }
        },
        "required": ["description"]
    }
)
def add_task_step_tool(user: User, description: str) -> Dict:
    """Add a step to the current task"""
    # Similar to complete_task_tool, this relies on task_id from context
    
    return {
        "success": True,
        "message": "Task step recorded",
        "description": description,
        "action": "add_step"
    }


@register_tool(
    name="set_next_action",
    description="Set the next action for the current task",
    parameters={
        "type": "object",
        "properties": {
            "next_action": {
                "type": "string",
                "description": "Description of the next action to take"
            }
        },
        "required": ["next_action"]
    }
)
def set_next_action_tool(user: User, next_action: str) -> Dict:
    """Set the next action for the current task"""
    # This will be handled by the agent service
    
    return {
        "success": True,
        "message": "Next action set",
        "next_action": next_action,
        "action": "set_next_action"
    }
