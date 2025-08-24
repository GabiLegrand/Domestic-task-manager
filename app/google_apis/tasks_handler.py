# ## path: app/google_apis/tasks_handler.py
import re
import logging
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from app.database.models import TaskInstance
from app.dtos import TaskUpdateDTO
from datetime import datetime, timezone
import app.constants as const

logger = logging.getLogger(__name__)
def days_and_hours_between(date1: datetime, date2: datetime):
    """
    Calculate the difference between two dates in days and hours.
    
    Args:
        date1 (datetime): First datetime object.
        date2 (datetime): Second datetime object.
    
    Returns:
        tuple: (days, hours) where
               days = full days between the two dates
               hours = remaining hours if less than a full day difference
    """
    delta = abs(date2.replace(tzinfo=timezone.utc) - date1.replace(tzinfo=timezone.utc))  # absolute difference
    days = delta.days
    seconds_remaining = delta.seconds
    
    # convert seconds to hours if difference is less than a full day
    hours = seconds_remaining // 3600 if days == 0 else 0
    
    return days, hours


class GoogleTasksHandler:
    def __init__(self, credentials: Credentials):
        if not credentials:
            raise ValueError("Credentials are required for GoogleTasksHandler.")
        try:
            self.service = build('tasks', 'v1', credentials=credentials)
        except Exception as e:
            logger.error(f"Failed to build Google Tasks service: {e}")
            self.service = None

    def _get_or_create_tasklist(self, category_name: str) -> str | None:
        """Finds a task list by name or creates it. Returns the task list ID."""
        try:
            tasklists_result = self.service.tasklists().list().execute()
            items = tasklists_result.get('items', [])
            for item in items:
                if item['title'].lower() == category_name.lower():
                    return item['id']
            # If not found, create it
            new_list = self.service.tasklists().insert(body={'title': category_name}).execute()
            logger.info(f"Created new task list: '{category_name}'")
            return new_list['id']
        except HttpError as e:
            logger.error(f"API error getting/creating tasklist '{category_name}': {e}")
            return None

    def get_all_tasks_with_sync_id(self, tasklist_id: str) -> dict:
        """Fetches all tasks from a tasklist and returns a dict mapping sync_id to task object."""
        tasks_map = {}
        try:
            tasks_result = self.service.tasks().list(tasklist=tasklist_id, showCompleted=True, showHidden=True).execute()
            for task in tasks_result.get('items', []):
                notes = task.get('notes', '')
                match = re.search(r"\[" + const.TASK_ID_MARKER + r"::(.*?)\]", notes)
                if match:
                    sync_id = match.group(1)
                    tasks_map[sync_id] = task
        except HttpError as e:
            logger.error(f"API error fetching tasks from list '{tasklist_id}': {e}")
        return tasks_map

    def create_task(self, instance: TaskInstance) -> str | None:
        """Creates a new task in Google Tasks. Returns the Google Task ID."""
        tasklist_id = self._get_or_create_tasklist(instance.definition.category)
        if not tasklist_id:
            return None
        now = datetime.now(timezone.utc)
        remainings = days_and_hours_between(now, min(instance.deadline_final, instance.deadline_repeat))
        remain_str  = f"{remainings[0]}J" if remainings[0] > 0 else f"{remainings[1]}H"
        body = {
            'title': f"{instance.definition.name} - [{remain_str}]",
            'notes': const.TASK_ID_FORMAT.format(instance_uuid=instance.instance_uuid),
            # 'due': instance.deadline_final.isoformat() + "Z", # RFC 3339 format
            'status': 'needsAction'
        }
        try:
            new_task = self.service.tasks().insert(tasklist=tasklist_id, body=body).execute()
            logger.info(f"Created task '{new_task['title']}' for user {instance.assigned_user.email}")
            return new_task['id']
        except HttpError as e:
            logger.error(f"API error creating task '{body['title']}': {e}")
            return None
    
    def refresh_title(self, instance : TaskInstance, tasklist_id: str):
        now = datetime.now(timezone.utc)
        remainings = days_and_hours_between(now, min(instance.deadline_final, instance.deadline_repeat))
        remain_str  = f"{remainings[0]}J" if remainings[0] > 0 else f"{remainings[1]}H"
        body = {
            'title': f"{instance.definition.name} - [{remain_str}]",
            'notes': const.TASK_ID_FORMAT.format(instance_uuid=instance.instance_uuid),
            'status': 'needsAction'
        }
        gtasks_id = instance.gtasks_task_id
        try:
            self.service.tasks().patch(tasklist=tasklist_id, task=gtasks_id, body=body).execute()
            logger.info(f"Updated task ID {gtasks_id}.")
        except HttpError as e:
            logger.error(f"API error updating task {gtasks_id}: {e}")

    def update_task(self, tasklist_id: str, gtasks_id: str, updates: TaskUpdateDTO):
        """Updates an existing Google Task."""
        try:
            self.service.tasks().patch(tasklist=tasklist_id, task=gtasks_id, body=updates.to_dict()).execute()
            logger.info(f"Updated task ID {gtasks_id}.")
        except HttpError as e:
            logger.error(f"API error updating task {gtasks_id}: {e}")

    def delete_task(self, tasklist_id: str, gtasks_id: str):
        """Deletes a Google Task."""
        try:
            self.service.tasks().delete(tasklist=tasklist_id, task=gtasks_id).execute()
            logger.info(f"Deleted task ID {gtasks_id}.")
        except HttpError as e:
            # Ignore 404 not found errors, as the task may have been deleted manually
            if e.resp.status == 404:
                logger.warning(f"Task ID {gtasks_id} not found for deletion, probably already deleted.")
            else:
                logger.error(f"API error deleting task {gtasks_id}: {e}")