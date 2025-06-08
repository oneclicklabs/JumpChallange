"""
Agent Service Module - Handles agent tasks, tool calling, and persistent memory
"""
import json
from datetime import datetime
import logging
import traceback
import re
from typing import Dict, List, Any, Optional, Union, Callable
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from .models import (
    AgentTask, TaskStep, OngoingInstruction, AgentMemory,
    WebhookEvent, HubspotContact, EmailInteraction, CalendarEvent
)
from .utils import RAGService

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for available tools that the agent can call"""

    def __init__(self):
        self.tools = {}
        self.tool_schemas = {}

    def register_tool(self, name: str, func: Callable, schema: Dict):
        """Register a new tool with the registry"""
        self.tools[name] = func
        self.tool_schemas[name] = schema

    def get_tool(self, name: str) -> Optional[Callable]:
        """Get a tool by name"""
        return self.tools.get(name)

    def get_tool_schema(self, name: str) -> Optional[Dict]:
        """Get a tool's schema by name"""
        return self.tool_schemas.get(name)

    def get_all_tool_schemas(self) -> List[Dict]:
        """Get all tool schemas for LLM function calling"""
        return list(self.tool_schemas.values())

    def execute_tool(self, name: str, **kwargs) -> Any:
        """Execute a tool by name with provided arguments"""
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found in registry")

        try:
            return tool(**kwargs)
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {str(e)}")
            logger.error(traceback.format_exc())
            raise


# Create global tool registry
tool_registry = ToolRegistry()


class AgentService:
    """Main service for handling agent tasks and tool calling"""

    def __init__(self, user_id):
        self.user = User.objects.get(id=user_id)
        try:
            self.profile = self.user.userprofile
            self.openai_api_key = self.profile.openai_api_key
            self.has_openai = bool(self.openai_api_key)

            # Initialize RAG service if OpenAI key is available
            if self.has_openai:
                self.rag_service = RAGService(api_key=self.openai_api_key)
            else:
                self.rag_service = None

        except Exception as e:
            logger.error(f"Error initializing AgentService: {str(e)}")
            self.profile = None
            self.openai_api_key = None
            self.has_openai = False
            self.rag_service = None

    def create_task(self, title, description, priority='medium', due_date=None, contact=None, calendar_event=None):
        """Create a new agent task"""
        try:
            task = AgentTask.objects.create(
                user=self.user,
                title=title,
                description=description,
                priority=priority,
                due_date=due_date,
                contact=contact,
                calendar_event=calendar_event,
                status='pending'
            )
            logger.info(f"Created new task: {task.id} - {task.title}")
            return task
        except Exception as e:
            logger.error(f"Error creating task: {str(e)}")
            return None

    def get_task(self, task_id):
        """Get a specific task by ID"""
        try:
            return AgentTask.objects.get(id=task_id, user=self.user)
        except AgentTask.DoesNotExist:
            logger.warning(f"Task {task_id} not found")
            return None

    def update_task_status(self, task_id, status, next_action=None):
        """Update a task's status and next action"""
        task = self.get_task(task_id)
        if not task:
            return False

        task.advance_status(status, next_action)
        return True

    def complete_task(self, task_id, result=None):
        """Mark a task as completed"""
        task = self.get_task(task_id)
        if not task:
            return False

        task.status = 'completed'
        task.completed_at = datetime.now()
        task.progress = 100

        if result:
            task.update_state({"result": result})

        task.save()
        logger.info(f"Task {task_id} marked as completed")
        return True

    def add_task_step(self, task_id, description, step_number=None):
        """Add a step to a multi-step task"""
        task = self.get_task(task_id)
        if not task:
            return None

        # Auto-determine step number if not provided
        if step_number is None:
            current_steps = TaskStep.objects.filter(task=task).count()
            step_number = current_steps + 1

        step = TaskStep.objects.create(
            task=task,
            step_number=step_number,
            description=description,
            status='pending'
        )

        logger.info(f"Added step {step_number} to task {task_id}")
        return step

    def complete_task_step(self, task_id, step_number, result=None):
        """Mark a task step as completed"""
        task = self.get_task(task_id)
        if not task:
            return False

        try:
            step = TaskStep.objects.get(task=task, step_number=step_number)
            step.status = 'completed'
            step.completed_at = datetime.now()

            if result:
                step.result = result

            step.save()

            # Update task progress
            total_steps = TaskStep.objects.filter(task=task).count()
            completed_steps = TaskStep.objects.filter(
                task=task, status='completed').count()

            if total_steps > 0:
                task.progress = int((completed_steps / total_steps) * 100)
                task.save()

            logger.info(f"Completed step {step_number} of task {task_id}")
            return True

        except TaskStep.DoesNotExist:
            logger.warning(f"Step {step_number} for task {task_id} not found")
            return False

    def save_memory(self, key, value, context=None, expires_at=None):
        """Save a piece of information to agent memory"""
        try:
            memory, created = AgentMemory.objects.update_or_create(
                user=self.user,
                key=key,
                defaults={
                    'value': value,
                    'context': context or '',
                    'expires_at': expires_at
                }
            )
            action = "Created" if created else "Updated"
            logger.info(f"{action} memory: {key}")
            return memory
        except Exception as e:
            logger.error(f"Error saving memory: {str(e)}")
            return None

    def get_memory(self, key):
        """Retrieve a piece of information from agent memory"""
        try:
            memory = AgentMemory.objects.get(user=self.user, key=key)

            # Check if memory has expired
            if memory.expires_at and memory.expires_at < datetime.now():
                memory.delete()
                logger.info(f"Memory {key} has expired and was deleted")
                return None

            return memory.value
        except AgentMemory.DoesNotExist:
            return None

    # New methods for tool calling and LLM integration

    def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a registered tool"""
        return tool_registry.execute_tool(tool_name, user=self.user, **kwargs)

    def get_tool_schemas(self) -> List[Dict]:
        """Get all tool schemas for LLM function calling"""
        return tool_registry.get_all_tool_schemas()

    def process_task(self, task_id: int) -> bool:
        """Process a task using LLM and tool calling"""
        task = self.get_task(task_id)
        if not task:
            return False

        if not self.has_openai:
            logger.error(f"Cannot process task: No OpenAI API key available")
            task.update_state({"error": "No OpenAI API key available"})
            task.advance_status("failed", "Set up OpenAI API key in settings")
            return False

        # Import OpenAI here to avoid circular imports
        try:
            from openai import OpenAI

            # Initialize OpenAI client
            client = OpenAI(api_key=self.openai_api_key)

            # Get task context
            context = self._build_task_context(task)

            # Get tool schemas
            tools = self.get_tool_schemas()

            # Define system message
            system_message = {
                "role": "system",
                "content": """You are an autonomous agent for a financial advisor. Your goal is to help financial advisors automate tasks 
                such as scheduling appointments, following up with clients, retrieving information, and managing contacts.
                You have access to various tools that you can call to accomplish these tasks.
                Think step by step and break down complex tasks into manageable steps.
                Always use the available tools rather than asking the user to perform actions manually.
                
                Important guidelines:
                1. When you need to complete a task with multiple steps, create a plan first
                2. When sending emails, be professional and courteous
                3. When scheduling appointments, check for conflicts first
                4. Always update task status and store important information in memory
                5. Be proactive in identifying and resolving issues
                """
            }

            # Define user message with task details
            user_message = {
                "role": "user",
                "content": f"""
                Task: {task.title}
                Description: {task.description}
                
                Context information:
                {context}
                
                Please help me complete this task using the available tools.
                Think step by step and create a plan before taking actions.
                """
            }

            # Update task status
            task.advance_status("in_progress", "Processing with AI assistant")

            # Make API call to GPT
            response = client.chat.completions.create(
                model="gpt-4-turbo",  # Use appropriate model based on your needs
                messages=[system_message, user_message],
                tools=tools,
                temperature=0.2
            )

            # Handle the response
            assistant_message = response.choices[0].message

            # Extract tool calls if any
            if hasattr(assistant_message, 'tool_calls') and assistant_message.tool_calls:
                # There are tool calls to execute
                tool_results = []

                for tool_call in assistant_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    # Log the tool call
                    logger.info(
                        f"Tool call: {function_name} with args: {function_args}")

                    # Execute the tool
                    try:
                        result = self.execute_tool(
                            function_name, **function_args)
                        tool_results.append({
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "result": result
                        })
                    except Exception as e:
                        error_message = f"Error executing {function_name}: {str(e)}"
                        logger.error(error_message)
                        tool_results.append({
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "error": error_message
                        })

                # Update task state with the results
                task.update_state({
                    "tool_results": tool_results,
                    "assistant_message": assistant_message.content
                })

                # Set next action based on assistant message
                next_action = assistant_message.content or "Processing tool results"
                task.advance_status("in_progress", next_action)

                # Create a task step for this action
                self.add_task_step(
                    task_id=task.id,
                    description=f"Executed tools: {', '.join([r['name'] for r in tool_results])}"
                )

                # Return indicating that follow-up processing is needed
                return True

            else:
                # No tool calls, just text response
                task.update_state({
                    "assistant_response": assistant_message.content
                })

                # Create a task step for the response
                self.add_task_step(
                    task_id=task.id,
                    description=f"AI Response: {assistant_message.content[:100]}..."
                )

                # If the assistant indicates task is complete, mark it as such
                if re.search(r'task (is )?complete', assistant_message.content.lower()):
                    self.complete_task(task_id, assistant_message.content)
                else:
                    # Otherwise, update next action
                    task.advance_status("waiting_response",
                                        "Awaiting next action")

                return True

        except Exception as e:
            logger.error(f"Error processing task with LLM: {str(e)}")
            logger.error(traceback.format_exc())

            # Update task with error
            task.update_state({"error": str(e)})
            task.advance_status("failed", f"Error: {str(e)[:100]}")
            return False

    def _build_task_context(self, task) -> str:
        """Build context for the task to send to LLM"""
        context_parts = []

        # Add task state if available
        if task.current_state:
            context_parts.append("Current task state:")
            for key, value in task.current_state.items():
                context_parts.append(f"- {key}: {value}")

        # Add task steps if any
        steps = TaskStep.objects.filter(task=task).order_by('step_number')
        if steps.exists():
            context_parts.append("\nTask steps so far:")
            for step in steps:
                status = f"[{step.status}]"
                context_parts.append(
                    f"- Step {step.step_number} {status}: {step.description}")
                if step.result:
                    context_parts.append(f"  Result: {step.result}")

        # Add related contact information if available
        if task.contact:
            context_parts.append(
                f"\nRelated contact: {task.contact.name} ({task.contact.email})")

            # Add recent emails from this contact
            recent_emails = EmailInteraction.objects.filter(
                contact=task.contact
            ).order_by('-received_at')[:3]

            if recent_emails.exists():
                context_parts.append(
                    f"\nRecent emails from {task.contact.name}:")
                for email in recent_emails:
                    context_parts.append(f"- Subject: {email.subject}")
                    context_parts.append(f"  Date: {email.received_at}")
                    context_parts.append(f"  Snippet: {email.snippet}")

        # Add related calendar event if available
        if task.calendar_event:
            event = task.calendar_event
            context_parts.append(f"\nRelated calendar event:")
            context_parts.append(f"- Title: {event.title}")
            context_parts.append(
                f"- Time: {event.start_time} to {event.end_time}")
            if event.description:
                context_parts.append(f"- Description: {event.description}")

        # Add relevant agent memories
        memories = AgentMemory.objects.filter(
            user=self.user).order_by('-updated_at')[:5]
        if memories.exists():
            context_parts.append("\nRecent agent memories:")
            for memory in memories:
                context_parts.append(f"- {memory.key}: {memory.value}")

        return "\n".join(context_parts)

    def process_instruction(self, instruction_id: int, trigger_event_id: Optional[int] = None) -> Optional[int]:
        """Process an ongoing instruction using LLM and potentially create tasks"""
        try:
            instruction = OngoingInstruction.objects.get(
                id=instruction_id, user=self.user)
        except OngoingInstruction.DoesNotExist:
            logger.warning(f"Instruction {instruction_id} not found")
            return None

        if instruction.status != 'active':
            logger.info(
                f"Instruction {instruction_id} is not active, skipping processing")
            return None

        # Create a task for this instruction
        task_description = f"Process ongoing instruction: {instruction.instruction}"
        if trigger_event_id:
            try:
                event = WebhookEvent.objects.get(id=trigger_event_id)
                source_info = f"Triggered by {event.source} event ({event.event_type})"
                task_description += f"\n\n{source_info}"
            except WebhookEvent.DoesNotExist:
                pass

        task = self.create_task(
            title=f"Auto: {instruction.name}",
            description=task_description,
            priority='medium'
        )

        if task:
            # Update task state with instruction details
            task.update_state({
                "instruction_id": instruction.id,
                "instruction_text": instruction.instruction,
                "trigger_event_id": trigger_event_id
            })

            # Update last triggered timestamp
            instruction.last_triggered = datetime.now()
            instruction.save()

            # Process the task
            self.process_task(task.id)

            return task.id

        return None

    def record_webhook_event(self, source: str, event_type: str, payload: Dict) -> Optional[WebhookEvent]:
        """Record an incoming webhook event in the database

        Args:
            source: Source of the webhook (gmail, calendar, hubspot)
            event_type: Type of event from the source
            payload: Raw webhook payload data

        Returns:
            WebhookEvent object if successful, None otherwise
        """
        try:
            # Convert payload to JSON string for storage
            payload_json = json.dumps(payload)

            # Extract a summary for easier viewing in logs/admin
            summary = self._generate_webhook_summary(
                source, event_type, payload)

            # Create the webhook event record
            event = WebhookEvent.objects.create(
                user=self.user,
                source=source,
                event_type=event_type,
                payload=payload_json,
                summary=summary,
                status='received',
                received_at=timezone.now()
            )

            logger.info(
                f"Recorded webhook event: {event.id} from {source} ({event_type}): {summary}")
            return event

        except Exception as e:
            logger.error(f"Error recording webhook event: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def _generate_webhook_summary(self, source: str, event_type: str, payload: Dict) -> str:
        """Generate a readable summary of a webhook event

        Args:
            source: Source of the webhook (gmail, calendar, hubspot)
            event_type: Type of event from the source
            payload: Raw webhook payload data

        Returns:
            A string summary of the event
        """
        summary_parts = []

        try:
            if source == 'gmail':
                if 'message' in payload:
                    message = payload['message']
                    if 'from' in message:
                        summary_parts.append(f"From: {message['from']}")
                    if 'subject' in message:
                        summary_parts.append(f"Subject: {message['subject']}")
                elif 'emailAddress' in payload:
                    summary_parts.append(f"Email: {payload['emailAddress']}")
                elif 'historyId' in payload:
                    summary_parts.append(f"History ID: {payload['historyId']}")

            elif source == 'calendar':
                if 'summary' in payload:
                    summary_parts.append(f"Event: {payload['summary']}")
                if 'start' in payload and 'dateTime' in payload['start']:
                    summary_parts.append(
                        f"Start: {payload['start']['dateTime']}")
                if 'attendees' in payload:
                    attendees = [a.get('email') for a in payload['attendees']]
                    summary_parts.append(
                        f"Attendees: {', '.join(attendees[:3])}")
                    if len(attendees) > 3:
                        summary_parts[-1] += f" and {len(attendees) - 3} more"

            elif source == 'hubspot':
                if 'objectType' in payload:
                    summary_parts.append(
                        f"{payload['objectType'].capitalize()}")
                if 'objectId' in payload:
                    summary_parts.append(f"ID: {payload['objectId']}")
                if 'propertyName' in payload and 'propertyValue' in payload:
                    summary_parts.append(
                        f"{payload['propertyName']}: {payload['propertyValue']}")
                elif 'contact' in payload and 'email' in payload['contact']:
                    summary_parts.append(
                        f"Email: {payload['contact']['email']}")
        except Exception as e:
            logger.error(f"Error generating webhook summary: {str(e)}")
            return f"{source} {event_type} event"

        if summary_parts:
            return " | ".join(summary_parts)
        else:
            return f"{source} {event_type} event"

    def process_webhook_event(self, event_id: int) -> bool:
        """Process a webhook event and match it with ongoing instructions

        Args:
            event_id: ID of the WebhookEvent to process

        Returns:
            True if processed successfully, False otherwise
        """
        try:
            # Get the event
            event = WebhookEvent.objects.get(id=event_id)

            # Only process received events
            if event.status != 'received':
                logger.warning(
                    f"Webhook event {event.id} has already been processed (status: {event.status})")
                return False

            # Update status to processing
            event.status = 'processing'
            event.save()

            # Parse the payload
            payload = json.loads(event.payload)

            # Extract relevant data based on the source
            extracted_data = self._extract_data_from_webhook(
                event.source, event.event_type, payload)

            # Find matching instructions
            matching_instructions = self._find_matching_instructions(event)

            # Process each matching instruction
            for instruction in matching_instructions:
                self.execute_instruction(instruction, event.id)

            # Update the event status
            event.status = 'processed'
            event.processed_at = timezone.now()
            event.save()

            logger.info(
                f"Processed webhook event {event.id} with {len(matching_instructions)} matching instructions")
            return True

        except WebhookEvent.DoesNotExist:
            logger.error(f"Webhook event {event_id} not found")
            return False
        except Exception as e:
            logger.error(
                f"Error processing webhook event {event_id}: {str(e)}")
            logger.error(traceback.format_exc())

            # Update status to failed
            try:
                event = WebhookEvent.objects.get(id=event_id)
                event.status = 'failed'
                event.save()
            except:
                pass

            return False

    def _extract_data_from_webhook(self, source: str, event_type: str, payload: Dict) -> Dict:
        """Extract relevant data from a webhook payload based on source and type

        Args:
            source: Source of the webhook (gmail, calendar, hubspot)
            event_type: Type of event from the source
            payload: Raw webhook payload data

        Returns:
            Dictionary of extracted data
        """
        extracted = {
            'source': source,
            'event_type': event_type,
            'timestamp': timezone.now().isoformat(),
        }

        try:
            if source == 'gmail':
                # Gmail webhook - extract email details
                if 'emailAddress' in payload:
                    extracted['email'] = payload['emailAddress']
                if 'historyId' in payload:
                    extracted['history_id'] = payload['historyId']

                # For a new message event, we might have message details
                if 'message' in payload:
                    message = payload['message']
                    if 'id' in message:
                        extracted['message_id'] = message['id']
                    if 'threadId' in message:
                        extracted['thread_id'] = message['threadId']
                    if 'from' in message:
                        extracted['from'] = message['from']
                    if 'subject' in message:
                        extracted['subject'] = message['subject']

            elif source == 'calendar':
                # Calendar webhook - extract event details
                if 'id' in payload:
                    extracted['event_id'] = payload['id']
                if 'summary' in payload:
                    extracted['title'] = payload['summary']
                if 'description' in payload:
                    extracted['description'] = payload['description']
                if 'start' in payload:
                    extracted['start_time'] = payload['start'].get(
                        'dateTime', payload['start'].get('date', ''))
                if 'end' in payload:
                    extracted['end_time'] = payload['end'].get(
                        'dateTime', payload['end'].get('date', ''))
                if 'attendees' in payload:
                    extracted['attendees'] = [
                        a.get('email') for a in payload.get('attendees', [])]

            elif source == 'hubspot':
                # HubSpot webhook - extract contact or deal details
                if 'objectId' in payload:
                    extracted['object_id'] = payload['objectId']
                if 'objectType' in payload:
                    extracted['object_type'] = payload['objectType']
                if 'propertyName' in payload:
                    extracted['property_name'] = payload['propertyName']
                if 'propertyValue' in payload:
                    extracted['property_value'] = payload['propertyValue']

                # For contact events, extract contact details
                if payload.get('objectType') == 'contact':
                    if 'contact' in payload:
                        contact_data = payload['contact']
                        if 'email' in contact_data:
                            extracted['email'] = contact_data['email']
                        if 'firstName' in contact_data:
                            extracted['first_name'] = contact_data['firstName']
                        if 'lastName' in contact_data:
                            extracted['last_name'] = contact_data['lastName']
        except Exception as e:
            logger.error(f"Error extracting data from webhook: {str(e)}")

        return extracted

    def _find_matching_instructions(self, event: WebhookEvent) -> List[OngoingInstruction]:
        """Find ongoing instructions that match a webhook event

        Args:
            event: WebhookEvent to match against instructions

        Returns:
            List of matching OngoingInstruction objects
        """        # Get all active ongoing instructions for this user
        instructions = OngoingInstruction.objects.filter(
            user=self.user,
            status='active'
        )

        matching_instructions = []
        payload = json.loads(event.payload)

        for instruction in instructions:
            # Check if this instruction has trigger conditions for this event source
            if instruction.trigger_conditions:
                trigger_conditions = instruction.trigger_conditions

                # Check if the source matches
                if event.source in trigger_conditions.get('sources', []):
                    # For Gmail events
                    if event.source == 'gmail' and trigger_conditions.get('email_conditions'):
                        email_conditions = trigger_conditions['email_conditions']

                        # Check new email conditions
                        if event.event_type == 'message' and email_conditions.get('new_email'):
                            # Extract email details from payload
                            # This is simplified, in practice you'd need to make an API call
                            # to get the full email details from Gmail
                            if 'from' in payload and any(
                                sender_pattern in payload['from']
                                for sender_pattern in email_conditions.get('from_patterns', [])
                            ):
                                matching_instructions.append(instruction)
                            elif 'subject' in payload and any(
                                subject_pattern in payload['subject']
                                for subject_pattern in email_conditions.get('subject_patterns', [])
                            ):
                                matching_instructions.append(instruction)

                    # For Calendar events
                    elif event.source == 'calendar' and trigger_conditions.get('calendar_conditions'):
                        calendar_conditions = trigger_conditions['calendar_conditions']

                        # Check new event conditions
                        if event.event_type == 'created' and calendar_conditions.get('new_event'):
                            matching_instructions.append(instruction)

                        # Check updated event conditions
                        elif event.event_type == 'updated' and calendar_conditions.get('updated_event'):
                            matching_instructions.append(instruction)

                    # For HubSpot events
                    elif event.source == 'hubspot' and trigger_conditions.get('hubspot_conditions'):
                        hubspot_conditions = trigger_conditions['hubspot_conditions']

                        # Check object type conditions
                        object_type = payload.get('objectType')
                        if object_type and object_type in hubspot_conditions.get('object_types', []):
                            matching_instructions.append(instruction)

                        # Check property change conditions
                        property_name = payload.get('propertyName')
                        if property_name and property_name in hubspot_conditions.get('property_changes', []):
                            matching_instructions.append(instruction)

            # Also check instructions without specific trigger conditions but with the correct source
            # This allows for general instructions like "When I receive an email, do X"
            elif not instruction.trigger_conditions and instruction.instruction.lower().find(event.source) >= 0:
                matching_instructions.append(instruction)

        return matching_instructions

    def execute_instruction(self, instruction: OngoingInstruction, webhook_event_id: Optional[int] = None) -> Optional[int]:
        """Execute an ongoing instruction, potentially creating a task

        Args:
            instruction: The OngoingInstruction object to execute
            webhook_event_id: ID of the WebhookEvent that triggered this execution, if any

        Returns:
            Task ID if a task was created, None otherwise
        """
        try:
            logger.info(
                f"Executing instruction {instruction.id}: {instruction.name}")

            # Update the last triggered timestamp
            instruction.last_triggered = timezone.now()
            instruction.save()

            # Get webhook event details if available
            event_context = ""
            if webhook_event_id:
                try:
                    event = WebhookEvent.objects.get(id=webhook_event_id)
                    event_data = self._extract_data_from_webhook(
                        event.source,
                        event.event_type,
                        json.loads(event.payload)
                    )
                    event_context = f"Triggered by {event.source} event ({event.event_type})\n"
                    event_context += "Event data:\n" + \
                        "\n".join(
                            [f"- {k}: {v}" for k, v in event_data.items()])
                except WebhookEvent.DoesNotExist:
                    logger.warning(
                        f"Webhook event {webhook_event_id} not found")

            # Create a task for this instruction
            task = self.create_task(
                title=f"Auto: {instruction.name}",
                description=f"Execute ongoing instruction: {instruction.instruction}\n\n{event_context}",
                priority="medium"
            )

            if not task:
                logger.error(
                    f"Failed to create task for instruction {instruction.id}")
                return None

            # Store instruction and event context in the task state
            task_context = {
                "instruction_id": instruction.id,
                "instruction_text": instruction.instruction,
            }

            if webhook_event_id:
                task_context["webhook_event_id"] = webhook_event_id

            task.update_state(task_context)

            # Process the task automatically if we have OpenAI capabilities
            if self.has_openai:
                self.process_task(task.id)

            logger.info(
                f"Created task {task.id} from instruction {instruction.id}")
            return task.id

        except Exception as e:
            logger.error(
                f"Error executing instruction {instruction.id}: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def create_instruction(self, name: str, instruction_text: str, triggers: List[str] = None) -> Optional[OngoingInstruction]:
        """Create a new ongoing instruction and parse trigger conditions

        Args:
            name: Name of the instruction
            instruction_text: Natural language instruction text
            triggers: Optional list of trigger types

        Returns:
            Created OngoingInstruction object or None if failed
        """
        try:
            # Parse the instruction to extract trigger conditions
            trigger_conditions = self._parse_instruction_triggers(
                instruction_text)

            # Create instruction object
            instruction = OngoingInstruction.objects.create(
                user=self.user,
                name=name,
                instruction=instruction_text,
                triggers=triggers or [],
                trigger_conditions=trigger_conditions,
                status='active'
            )

            logger.info(f"Created instruction {instruction.id}: {name}")
            return instruction

        except Exception as e:
            logger.error(f"Error creating instruction: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def _parse_instruction_triggers(self, instruction_text: str) -> Dict:
        """Parse trigger conditions from natural language instruction

        This function analyzes the instruction text to extract trigger conditions
        such as email patterns, calendar conditions, or hubspot conditions.

        Args:
            instruction_text: Natural language instruction text

        Returns:
            Dictionary of trigger conditions
        """
        trigger_conditions = {
            'sources': []
        }

        # Convert to lowercase for case-insensitive matching
        text = instruction_text.lower()

        # Check for email-related triggers
        if any(term in text for term in ['email', 'gmail', 'message', 'inbox']):
            trigger_conditions['sources'].append('gmail')

            # Initialize email conditions
            trigger_conditions['email_conditions'] = {
                'new_email': True,
                'from_patterns': [],
                'subject_patterns': []
            }

            # Check for sender patterns
            if 'from' in text:
                # Try to extract email domains or senders
                from_match = re.search(r'from\s+([^\s,;]+(\.[^\s,;]+)+)', text)
                if from_match:
                    trigger_conditions['email_conditions']['from_patterns'].append(
                        from_match.group(1))

            # Check for subject patterns
            if 'subject' in text:
                # Try to extract subject keywords
                subject_match = re.search(
                    r'subject\s+(?:contains|with)\s+["\']([^"\']+)["\']', text)
                if subject_match:
                    trigger_conditions['email_conditions']['subject_patterns'].append(
                        subject_match.group(1))

        # Check for calendar-related triggers
        if any(term in text for term in ['calendar', 'event', 'meeting', 'appointment']):
            trigger_conditions['sources'].append('calendar')

            # Initialize calendar conditions
            trigger_conditions['calendar_conditions'] = {
                'new_event': 'new' in text or 'create' in text,
                'updated_event': 'update' in text or 'change' in text
            }

        # Check for HubSpot-related triggers
        if any(term in text for term in ['hubspot', 'crm', 'contact', 'deal', 'lead']):
            trigger_conditions['sources'].append('hubspot')

            # Initialize hubspot conditions
            trigger_conditions['hubspot_conditions'] = {
                'object_types': [],
                'property_changes': []
            }

            # Check for object types
            if 'contact' in text:
                trigger_conditions['hubspot_conditions']['object_types'].append(
                    'contact')
            if 'deal' in text:
                trigger_conditions['hubspot_conditions']['object_types'].append(
                    'deal')

            # Check for property changes
            if 'property' in text or 'field' in text:
                property_match = re.search(
                    r'(?:property|field)\s+["\']([^"\']+)["\']', text)
                if property_match:
                    trigger_conditions['hubspot_conditions']['property_changes'].append(
                        property_match.group(1))

        # If we have OpenAI capabilities, use it to enhance the parsing
        if self.has_openai:
            try:
                enhanced_conditions = self._enhance_trigger_parsing_with_llm(
                    instruction_text, trigger_conditions)
                if enhanced_conditions:
                    trigger_conditions = enhanced_conditions
            except Exception as e:
                logger.warning(
                    f"Error enhancing trigger parsing with LLM: {str(e)}")

        return trigger_conditions

    def _enhance_trigger_parsing_with_llm(self, instruction_text: str, initial_conditions: Dict) -> Optional[Dict]:
        """Use LLM to enhance trigger condition parsing

        Args:
            instruction_text: Natural language instruction text
            initial_conditions: Initial parsed conditions

        Returns:
            Enhanced trigger conditions or None if failed
        """
        if not self.has_openai:
            return None

        try:
            from openai import OpenAI

            # Initialize OpenAI client
            client = OpenAI(api_key=self.openai_api_key)

            # Prepare the prompt
            prompt = f"""
            Analyze this instruction for an AI agent and extract the trigger conditions:
            
            "{instruction_text}"
            
            Current extracted conditions: {json.dumps(initial_conditions, indent=2)}
            
            Improve these conditions by identifying:
            1. Sources (gmail, calendar, hubspot)
            2. Email conditions (from patterns, subject patterns)
            3. Calendar conditions (new events, updated events)
            4. HubSpot conditions (object types, property changes)
            
            Return a JSON object with the improved conditions, maintaining the same structure.
            Only include valid JSON in your response.
            """

            # Call OpenAI API
            response = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that extracts structured information from natural language instructions."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )

            # Extract the JSON from the response
            content = response.choices[0].message.content

            # Try to find and parse JSON in the response
            try:
                # Look for JSON block
                json_match = re.search(
                    r'```(?:json)?\s*([\s\S]+?)```', content)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = content

                # Parse the JSON
                enhanced_conditions = json.loads(json_str)
                return enhanced_conditions

            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON from LLM response")
                return initial_conditions

        except Exception as e:
            logger.error(f"Error using LLM for trigger parsing: {str(e)}")
            return initial_conditions

    def analyze_and_suggest_tasks(self):
        """Analyze user data and suggest proactive tasks
        
        This method analyzes emails, calendar events, and contacts to identify
        potential tasks that would be valuable for the financial advisor.
        
        Returns:
            List of suggested tasks
        """
        if not self.has_openai:
            logger.warning("Cannot suggest tasks without OpenAI API key")
            return []
            
        try:
            from openai import OpenAI
            
            # Initialize OpenAI client
            client = OpenAI(api_key=self.openai_api_key)
            
            # Gather data for analysis
            data = self._gather_analysis_data()
            
            # Prepare a prompt for the LLM
            system_message = {
                "role": "system",
                "content": """You are an AI assistant for financial advisors. Your job is to analyze client data and identify 
                opportunities for the financial advisor to take action. Focus on identifying:
                
                1. Follow-ups needed for clients who haven't been contacted recently
                2. Preparation needed for upcoming meetings
                3. Potential issues or opportunities based on client communications
                4. Administrative tasks that might be overlooked
                
                For each suggestion, provide:
                - A clear title 
                - A description explaining what should be done and why
                - A priority level (low, medium, high)
                
                Format your response as a JSON array of task objects with the fields: 
                title, description, priority, due_date (ISO format or null)
                """
            }
            
            user_message = {
                "role": "user",
                "content": f"""
                Here is the data to analyze:
                
                UPCOMING CALENDAR EVENTS:
                {data['calendar_events']}
                
                RECENT EMAILS:
                {data['recent_emails']}
                
                CONTACTS WITHOUT RECENT INTERACTIONS:
                {data['inactive_contacts']}
                
                TODAY'S DATE: {timezone.now().strftime('%Y-%m-%d')}
                
                Based on this data, suggest up to 3 tasks the financial advisor should consider.
                """
            }
            
            # Call OpenAI to generate suggestions
            response = client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[system_message, user_message],
                response_format={"type": "json_object"},
                temperature=0.7
            )
              # Parse the response
            content = response.choices[0].message.content
            try:
                # Try to parse as an object with 'tasks' field first
                suggested_tasks = json.loads(content).get('tasks', [])
                # If it's empty, maybe the response is a direct array
                if not suggested_tasks and isinstance(json.loads(content), list):
                    suggested_tasks = json.loads(content)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse LLM response: {content}")
                return []
            
            # Create draft tasks from suggestions
            created_tasks = []
            for task in suggested_tasks:
                # Parse due_date if it exists and is not null
                due_date = None
                if task.get('due_date'):
                    try:
                        due_date = datetime.fromisoformat(task['due_date'].replace('Z', '+00:00'))
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid due_date format: {task.get('due_date')}")
                
                new_task = AgentTask.objects.create(
                    user=self.user,
                    title=task['title'],
                    description=task['description'],
                    priority=task.get('priority', 'medium'),
                    due_date=due_date,
                    status='draft',  # These are suggestions until approved
                    is_suggestion=True  # Mark as AI suggested
                )
                created_tasks.append(new_task)
                
            logger.info(f"Created {len(created_tasks)} task suggestions for user {self.user.username}")
            return created_tasks
            
        except Exception as e:
            logger.error(f"Error generating task suggestions: {str(e)}")
            logger.error(traceback.format_exc())
            return []
            
    def _gather_analysis_data(self):
        """Gather data for analysis to suggest tasks
        
        Returns:
            Dictionary of data for analysis
        """
        data = {
            'calendar_events': '',
            'recent_emails': '',
            'inactive_contacts': ''
        }
        
        # Get upcoming calendar events
        try:
            events = CalendarEvent.objects.filter(
                user=self.user, 
                start_time__gte=timezone.now()
            ).order_by('start_time')[:10]
            
            if events:
                events_text = []
                for event in events:
                    contact_info = f" with {event.contact.name}" if event.contact else ""
                    events_text.append(
                        f"{event.start_time.strftime('%Y-%m-%d %H:%M')} - {event.title}{contact_info}"
                    )
                data['calendar_events'] = "\n".join(events_text)
        except Exception as e:
            logger.warning(f"Error getting calendar events: {str(e)}")
            
        # Get recent emails
        try:
            emails = EmailInteraction.objects.filter(
                contact__user=self.user
            ).order_by('-received_at')[:20]
            
            if emails:
                emails_text = []
                for email in emails:
                    emails_text.append(
                        f"From: {email.contact.name} ({email.received_at.strftime('%Y-%m-%d')})\n"
                        f"Subject: {email.subject}\n"
                        f"Snippet: {email.snippet}\n"
                    )
                data['recent_emails'] = "\n\n".join(emails_text)
        except Exception as e:
            logger.warning(f"Error getting recent emails: {str(e)}")
            
        # Get contacts without recent interactions
        try:
            from django.db.models import Q, Max
            
            # Get contacts with no recent emails in the last 30 days
            thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
            
            contacts = HubspotContact.objects.filter(
                user=self.user
            ).annotate(
                last_email=Max('emails__received_at')
            ).filter(
                Q(last_email__lt=thirty_days_ago) | Q(last_email__isnull=True)
            )[:10]
            
            if contacts:
                contacts_text = []
                for contact in contacts:
                    last_contact = "Never" if not contact.last_interaction else contact.last_interaction.strftime('%Y-%m-%d')
                    contacts_text.append(f"{contact.name} ({contact.email}) - Last contact: {last_contact}")
                data['inactive_contacts'] = "\n".join(contacts_text)
        except Exception as e:
            logger.warning(f"Error getting inactive contacts: {str(e)}")
            
        return data
    
    def approve_suggested_task(self, task_id: int) -> bool:
        """Approve an AI-suggested task
        
        This method converts a suggested task (draft) into an active task.
        
        Args:
            task_id: The ID of the suggested task to approve
            
        Returns:
            bool: Whether the task was successfully approved
        """
        try:
            task = AgentTask.objects.get(id=task_id, user=self.user, is_suggestion=True)
            
            # Convert from suggestion to actual task
            task.is_suggestion = False
            task.status = 'pending'  # Change from draft to pending
            task.save()
            
            logger.info(f"Approved suggested task {task_id} for user {self.user.username}")
            return True
            
        except AgentTask.DoesNotExist:
            logger.warning(f"Suggested task {task_id} not found for user {self.user.username}")
            return False
        except Exception as e:
            logger.error(f"Error approving suggested task {task_id}: {str(e)}")
            return False
            
    def get_suggested_tasks(self) -> list:
        """Get all AI-suggested tasks for the user
        
        Returns:
            List of suggested tasks
        """
        try:
            return list(AgentTask.objects.filter(user=self.user, is_suggestion=True).order_by('-created_at'))
        except Exception as e:
            logger.error(f"Error getting suggested tasks: {str(e)}")
            return []
