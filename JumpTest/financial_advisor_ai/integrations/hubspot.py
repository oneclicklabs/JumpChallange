"""
HubSpot API integration for managing contacts and CRM data
"""
import os
import json
import logging
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
from django.contrib.auth.models import User
from django.conf import settings
from ..models import HubspotContact, EmailInteraction, UserProfile

logger = logging.getLogger(__name__)


class HubspotAPI:
    """HubSpot API wrapper for CRM operations"""

    def __init__(self, user_id):
        """Initialize the HubSpot API client

        Args:
            user_id: ID of the Django user
        """
        self.user = User.objects.get(id=user_id)
        self.profile = None
        self.access_token = None
        self.initialized = False
        self.error = None
        self.base_url = "https://api.hubapi.com"

        try:
            self.profile = self.user.userprofile
            if not self.profile.hubspot_token:
                self.error = "HubSpot access token not available"
                return

            # Get access token from stored token
            self.access_token = self.profile.hubspot_token
            self.initialized = True

        except Exception as e:
            logger.error(f"Error initializing HubSpot API: {str(e)}")
            self.error = str(e)

    def get_contacts(self, limit=50, properties=None) -> List[Dict]:
        """Get contacts from HubSpot CRM

        Args:
            limit: Maximum number of contacts to return
            properties: List of properties to include

        Returns:
            List of contact dictionaries
        """
        if not self.initialized:
            logger.error("HubSpot API not initialized")
            return []

        # Default properties to retrieve
        if properties is None:
            properties = ["email", "firstname", "lastname", "phone",
                          "company", "website", "lastmodifieddate"]

        try:
            url = f"{self.base_url}/crm/v3/objects/contacts"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            params = {
                "limit": limit,
                "properties": ",".join(properties)
            }

            response = requests.get(url, headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                contacts = []

                for result in data.get("results", []):
                    contact_id = result.get("id")
                    props = result.get("properties", {})

                    contact = {
                        "id": contact_id,
                        "email": props.get("email", ""),
                        "firstName": props.get("firstname", ""),
                        "lastName": props.get("lastname", ""),
                        "fullName": f"{props.get('firstname', '')} {props.get('lastname', '')}".strip(),
                        "phone": props.get("phone", ""),
                        "company": props.get("company", ""),
                        "website": props.get("website", ""),
                        "createdAt": result.get("createdAt", ""),
                        "updatedAt": result.get("updatedAt", ""),
                    }

                    contacts.append(contact)

                return contacts
            else:
                logger.error(
                    f"Error fetching HubSpot contacts: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            logger.error(f"Error getting HubSpot contacts: {str(e)}")
            return []

    def create_contact(self, email: str, first_name: str = None, last_name: str = None,
                       phone: str = None, company: str = None) -> Optional[str]:
        """Create a new contact in HubSpot

        Args:
            email: Contact email address
            first_name: First name
            last_name: Last name
            phone: Phone number
            company: Company name

        Returns:
            Contact ID if created successfully, None otherwise
        """
        if not self.initialized:
            logger.error("HubSpot API not initialized")
            return None

        try:
            url = f"{self.base_url}/crm/v3/objects/contacts"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            # Build properties dictionary
            properties = {
                "email": email
            }

            if first_name:
                properties["firstname"] = first_name

            if last_name:
                properties["lastname"] = last_name

            if phone:
                properties["phone"] = phone

            if company:
                properties["company"] = company

            data = {
                "properties": properties
            }

            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 201:
                result = response.json()
                contact_id = result.get("id")

                if contact_id:
                    # Create contact in our database
                    full_name = f"{first_name or ''} {last_name or ''}".strip()
                    contact = HubspotContact.objects.create(
                        user=self.user,
                        contact_id=contact_id,
                        name=full_name or "Unknown",
                        email=email
                    )

                    logger.info(
                        f"Created HubSpot contact: {contact_id} - {email}")
                    return contact_id
                else:
                    logger.error("HubSpot contact created but no ID returned")
                    return None
            else:
                logger.error(
                    f"Error creating HubSpot contact: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error creating HubSpot contact: {str(e)}")
            return None

    def update_contact(self, contact_id: str, properties: Dict) -> bool:
        """Update a contact in HubSpot

        Args:
            contact_id: HubSpot contact ID
            properties: Dictionary of properties to update

        Returns:
            True if updated successfully, False otherwise
        """
        if not self.initialized:
            logger.error("HubSpot API not initialized")
            return False

        try:
            url = f"{self.base_url}/crm/v3/objects/contacts/{contact_id}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            data = {
                "properties": properties
            }

            response = requests.patch(url, headers=headers, json=data)

            if response.status_code == 200:
                # Update local contact if exists
                try:
                    contact = HubspotContact.objects.get(
                        user=self.user,
                        contact_id=contact_id
                    )

                    # Update name if provided
                    if 'firstname' in properties or 'lastname' in properties:
                        first_name = properties.get('firstname')
                        last_name = properties.get('lastname')

                        if first_name and last_name:
                            contact.name = f"{first_name} {last_name}"
                        elif first_name:
                            contact.name = first_name
                        elif last_name:
                            contact.name = last_name

                    # Update email if provided
                    if 'email' in properties:
                        contact.email = properties['email']

                    contact.save()
                except HubspotContact.DoesNotExist:
                    pass

                logger.info(f"Updated HubSpot contact: {contact_id}")
                return True
            else:
                logger.error(
                    f"Error updating HubSpot contact: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error updating HubSpot contact: {str(e)}")
            return False

    def get_contact_by_email(self, email: str) -> Optional[Dict]:
        """Get a contact by email address

        Args:
            email: Contact email address

        Returns:
            Contact dictionary if found, None otherwise
        """
        if not self.initialized:
            logger.error("HubSpot API not initialized")
            return None

        try:
            # Filter by email
            url = f"{self.base_url}/crm/v3/objects/contacts/search"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            data = {
                "filterGroups": [{
                    "filters": [{
                        "propertyName": "email",
                        "operator": "EQ",
                        "value": email
                    }]
                }],
                "properties": ["email", "firstname", "lastname", "phone", "company"]
            }

            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()
                contacts = result.get("results", [])

                if contacts:
                    # Return the first matching contact
                    contact_data = contacts[0]
                    contact_id = contact_data.get("id")
                    props = contact_data.get("properties", {})

                    contact = {
                        "id": contact_id,
                        "email": props.get("email", ""),
                        "firstName": props.get("firstname", ""),
                        "lastName": props.get("lastname", ""),
                        "fullName": f"{props.get('firstname', '')} {props.get('lastname', '')}".strip(),
                        "phone": props.get("phone", ""),
                        "company": props.get("company", "")
                    }

                    return contact
                else:
                    logger.info(
                        f"No HubSpot contact found with email: {email}")
                    return None
            else:
                logger.error(
                    f"Error searching for HubSpot contact: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error getting HubSpot contact by email: {str(e)}")
            return None

    def add_note_to_contact(self, contact_id: str, note_body: str) -> Optional[str]:
        """Add a note to a contact

        Args:
            contact_id: HubSpot contact ID
            note_body: Text content of the note

        Returns:
            Note ID if created successfully, None otherwise
        """
        if not self.initialized:
            logger.error("HubSpot API not initialized")
            return None

        try:
            url = f"{self.base_url}/crm/v3/objects/notes"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            data = {
                "properties": {
                    "hs_note_body": note_body
                },
                "associations": [
                    {
                        "to": {
                            "id": contact_id
                        },
                        "types": [{
                            "category": "HUBSPOT_DEFINED",
                            "typeId": 1
                        }]
                    }
                ]
            }

            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 201:
                result = response.json()
                note_id = result.get("id")

                logger.info(
                    f"Created note for contact {contact_id}: {note_id}")
                return note_id
            else:
                logger.error(
                    f"Error adding note to contact: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error adding note to HubSpot contact: {str(e)}")
            return None

    def create_meeting(self, contact_id: str, title: str, description: str,
                       start_time: datetime, end_time: datetime, location: str = None) -> Optional[str]:
        """Create a meeting and associate it with a contact

        Args:
            contact_id: HubSpot contact ID
            title: Meeting title
            description: Meeting description
            start_time: Meeting start datetime
            end_time: Meeting end datetime
            location: Optional meeting location

        Returns:
            Meeting ID if created successfully, None otherwise
        """
        if not self.initialized:
            logger.error("HubSpot API not initialized")
            return None

        try:
            url = f"{self.base_url}/crm/v3/objects/meetings"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            # Format start and end times
            start_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            # Prepare properties
            properties = {
                "hs_meeting_title": title,
                "hs_meeting_body": description,
                "hs_meeting_start_time": start_str,
                "hs_meeting_end_time": end_str
            }

            if location:
                properties["hs_meeting_location"] = location

            data = {
                "properties": properties,
                "associations": [
                    {
                        "to": {
                            "id": contact_id
                        },
                        "types": [{
                            "category": "HUBSPOT_DEFINED",
                            "typeId": 1
                        }]
                    }
                ]
            }

            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 201:
                result = response.json()
                meeting_id = result.get("id")

                logger.info(
                    f"Created meeting with contact {contact_id}: {meeting_id}")
                return meeting_id
            else:
                logger.error(
                    f"Error creating meeting: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error creating HubSpot meeting: {str(e)}")
            return None

    def sync_contacts_to_db(self) -> int:
        """Sync HubSpot contacts to database

        Returns:
            Number of contacts processed
        """
        if not self.initialized:
            logger.error("HubSpot API not initialized")
            return 0

        try:
            # Get contacts from HubSpot
            contacts = self.get_contacts(limit=100)

            count = 0
            for contact in contacts:
                contact_id = contact.get("id")
                email = contact.get("email")

                if not email:
                    continue

                # Check if contact exists in our database
                existing = HubspotContact.objects.filter(
                    user=self.user,
                    contact_id=contact_id
                )

                if not existing.exists():
                    # Create new contact record
                    HubspotContact.objects.create(
                        user=self.user,
                        contact_id=contact_id,
                        name=contact.get("fullName", "Unknown"),
                        email=email,
                    )

                    count += 1
                else:
                    # Update existing contact
                    existing_contact = existing.first()
                    existing_contact.name = contact.get("fullName", "Unknown")
                    existing_contact.email = email
                    existing_contact.save()

            return count

        except Exception as e:
            logger.error(f"Error syncing HubSpot contacts to DB: {str(e)}")
            return 0

# Module-level functions for compatibility with tests


def get_hubspot_contacts(user):
    """Get HubSpot contacts for a user

    Args:
        user: Django User object

    Returns:
        List of contact dictionaries
    """
    try:
        hubspot_api = HubspotAPI(user.id)
        if hubspot_api.initialized:
            return hubspot_api.get_contacts()
        else:
            logger.error(
                f"Failed to initialize HubSpot API for user {user.id}: {hubspot_api.error}")
            return []
    except Exception as e:
        logger.error(
            f"Error getting HubSpot contacts for user {user.id}: {str(e)}")
        return []


def sync_hubspot_contacts(user):
    """Sync HubSpot contacts to the database

    Args:
        user: Django User object

    Returns:
        Number of contacts synced
    """
    try:
        hubspot_api = HubspotAPI(user.id)
        if hubspot_api.initialized:
            return hubspot_api.sync_contacts_to_db()
        else:
            logger.error(
                f"Failed to sync HubSpot contacts for user {user.id}: {hubspot_api.error}")
            return 0
    except Exception as e:
        logger.error(
            f"Error syncing HubSpot contacts for user {user.id}: {str(e)}")
        return 0


def create_hubspot_contact(user, contact_data):
    """Create a new contact in HubSpot

    Args:
        user: Django User object
        contact_data: Dictionary containing contact information

    Returns:
        Dictionary with contact info if created successfully, None otherwise
    """
    try:
        hubspot_api = HubspotAPI(user.id)
        if hubspot_api.initialized:
            contact_id = hubspot_api.create_contact(
                email=contact_data.get('email'),
                first_name=contact_data.get('first_name'),
                last_name=contact_data.get('last_name'),
                phone=contact_data.get('phone'),
                company=contact_data.get('company')
            )
            
            # Return dictionary format expected by tests
            if contact_id:
                return {
                    'id': contact_id,
                    'email': contact_data.get('email'),
                    'first_name': contact_data.get('first_name'),
                    'last_name': contact_data.get('last_name'),
                    'phone': contact_data.get('phone'),
                    'company': contact_data.get('company')
                }
            return None
        else:
            logger.error(
                f"Failed to create HubSpot contact for user {user.id}: {hubspot_api.error}")
            return None
    except Exception as e:
        logger.error(
            f"Error creating HubSpot contact for user {user.id}: {str(e)}")
        return None
