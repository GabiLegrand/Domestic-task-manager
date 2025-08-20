# ## path: app/logic/task_manager.py
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

import app.database.crud as crud
from app.database.models import User, TaskDefinition, TaskInstance
from app.dtos import TaskDefinitionDTO
from app.google_apis.tasks_handler import GoogleTasksHandler
import app.constants as const
from app.logic.time_finder import TimePatternService
from app.config import settings
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

class TaskManager:
    def __init__(self, db: Session):
        self.db = db
        self.time_pattern = TimePatternService()

    def sync_task_definitions(self, task_defs_from_sheet: list[TaskDefinitionDTO]):
        """Synchronizes task definitions from the sheet with the database."""
        active_names = []
        for task_def_dto in task_defs_from_sheet:
            crud.upsert_task_definition(self.db, task_def_dto)
            active_names.append(task_def_dto.name)

        # Deactivate definitions no longer in the sheet
        crud.deactivate_task_definitions(self.db, active_names)
        logger.info(f"Synchronized {len(active_names)} task definitions. Deactivated obsolete ones.")

    def process_all_tasks(self, users_with_creds: list[User]):
        """Main processing function to handle all task logic."""
        self._assign_new_tasks()
        self._process_active_instances(users_with_creds)

    def _assign_new_tasks(self):
        """Assigns tasks that have no active instances."""
        active_defs = crud.get_active_task_definitions(self.db)
        for definition in active_defs:
            instances = crud.get_active_task_instance_for_definition(self.db, definition.id)
            if len(instances) == 0:
                logger.info(f"No active instance for '{definition.name}'. Creating new assignment.")
                self._assign_to_next_user(definition, None)
                continue

            has_assignable_instances = sum([instance.allow_reassignment for instance in instances])
            logger.info(f"assignable instances : {has_assignable_instances}, {definition.id}")
            if not has_assignable_instances > 0:
                # always have at least 1 instance that allow reassignment, otherwise task dissapear and assignment will reset on completion
                # We set the last valid instance to be assignable
                sorted_instances = sorted(instances, key=lambda x: x.deadline_final)
                instance = sorted_instances[-1]
                crud.update_task_instance(self.db, instance.id, allow_reassignment=True)

    def _process_active_instances(self, users_with_creds: list[User]):
        """Processes each active task instance, checking its state and applying logic."""
        active_instances = crud.get_all_active_task_instances(self.db)
        user_creds_map = {user.id: user.google_credentials_json for user in users_with_creds}

        for instance in active_instances:
            user_creds = user_creds_map.get(instance.assigned_user_id)
            if not user_creds:
                logger.warning(f"Skipping instance {instance.id} for user {instance.assigned_user.email} (no credentials).")
                continue

            try:
                self._check_and_update_instance_state(instance)
            except Exception as e:
                logger.error(f"Error processing instance {instance.instance_uuid}: {e}", exc_info=True)

    def _generate_start_date(self, instance: Optional[TaskInstance] = None, definition: Optional[TaskDefinition] = None):
        """
            Function should be run before assignment
        """
        now = datetime.now(timezone.utc)
        
        next_deadline = now + definition.reproduction_period
        if instance is None:
            deadline_final = now + definition.pass_over_period
        else :
            definition = instance.definition
            deadline_final = instance.deadline_final
    
        end_date = max(next_deadline.replace(tzinfo=timezone.utc), deadline_final.replace(tzinfo=timezone.utc))
        start_preferences = definition.start_preferences
        start_preferences = start_preferences.split(',') if start_preferences != "" else []
        
        nb_days = definition.task_days

        start_date = self.time_pattern.find_start_datetime(start_preferences, end_date, nb_days)

        return start_date

    def _reassign_to_user(self, instance: TaskInstance):
        """
            Reassign to user suppose that user now have the task assigned to him.
            Instance start now, but start date will be defined by the task definition logic
        """

        now = datetime.now(timezone.utc)
        definition = instance.definition

        crud.update_task_instance(self.db, instance.id,
            status=const.STATUS_ACTIVE,
            completed_at=None,
            assigned_at=now,
            deadline_repeat=now + definition.reproduction_period,
            start_date=self._generate_start_date(instance)
        )

    def _check_and_update_instance_state(self, instance: TaskInstance):
        """Checks a single instance against Google Tasks and updates its state."""
        definition = instance.definition
        logger.info(f'*******  Currently analysing : {definition.name} -- {instance.assigned_user.name}')
        
        now = datetime.now(timezone.utc)
        logger.info(f'Now time : {now} - repeat deadline {instance.deadline_repeat} - final deadline: {instance.deadline_final}')
        # If a task is completed, check if it's time to reactivate
        if instance.status == const.STATUS_COMPLETED:

            if now > instance.deadline_final.replace(tzinfo=timezone.utc):
                logger.info(f"Final deadline passed for task '{definition.name}' for user {instance.assigned_user.name}.  Passing to next user.")
                crud.update_task_instance(self.db, instance.id, status=const.STATUS_TERMINATED)
                crud.create_completion_log(self.db, task_instance_id=instance.id, user_id=instance.assigned_user_id, completed_at=now, trigger_type=const.TRIGGER_PASSED_OVER)
                if instance.allow_reassignment:
                    self._assign_to_next_user(definition, instance.assigned_user.name)
            else : 
                reactivation_time = instance.completed_at.replace(tzinfo=timezone.utc) + definition.reproduction_period
                if now > reactivation_time:
                    logger.info(f"Reactivating task '{definition.name}' for user {instance.assigned_user.name}.")
                    self._reassign_to_user(instance)
                else :
                    reactivation_time = reactivation_time.strftime("%d/%m/%Y, %H:%M:%S")
                    logger.info(f"Task '{definition.name}' for user {instance.assigned_user.name} is done, but waiting for reactivation at {reactivation_time}")
            
            return

        # If task is active, check for pass-over condition
        if instance.status == const.STATUS_ACTIVE and now > instance.deadline_final.replace(tzinfo=timezone.utc):
            logger.info(f"Final deadline passed for task '{definition.name}' for user {instance.assigned_user.name}.")
            behavior = definition.overdue_behavior

            if behavior == const.BEHAVIOR_CHANGE:
                logger.info(f"Behavior is '{const.BEHAVIOR_CHANGE}'. Passing to next user.")
                crud.update_task_instance(self.db, instance.id, status=const.STATUS_TERMINATED)
                crud.create_completion_log(self.db, task_instance_id=instance.id, user_id=instance.assigned_user_id, completed_at=now, trigger_type=const.TRIGGER_PASSED_OVER)
                if instance.allow_reassignment:
                    self._assign_to_next_user(definition, instance.assigned_user.name)

            elif behavior == const.BEHAVIOR_KEEP_AND_CHANGE:
                
                logger.info(f"Behavior is '{const.BEHAVIOR_KEEP_AND_CHANGE}'. Assigning to next user while keeping current.")
                # The current instance remains active, a new one is created for the next user
                if instance.allow_reassignment:
                    self._assign_to_next_user(definition, instance.assigned_user.name)
                # We extend the current user's deadline to prevent this from re-triggering every cycle
                new_final_deadline = now + definition.pass_over_period
                crud.update_task_instance(self.db, instance.id, deadline_final=new_final_deadline, allow_reassignment=False)

            elif behavior == const.BEHAVIOR_KEEP:
                logger.info(f"Behavior is '{const.BEHAVIOR_KEEP}'. User keeps the task.")
                # Extend the deadline to avoid re-processing this every loop
                new_final_deadline = now + definition.pass_over_period
                crud.update_task_instance(self.db, instance.id, deadline_final=new_final_deadline)

    def _assign_to_next_user(self, definition: TaskDefinition, current_user_name: str | None):
        """Assigns a task definition to the next user in the rotation."""
        actors = definition.actors.split(',')
        next_user_name = actors[0] # Default to first user
        if current_user_name in actors:
            current_index = actors.index(current_user_name)
            next_index = (current_index + 1) % len(actors)
            next_user_name = actors[next_index]

        next_user = crud.get_user_by_name(self.db, next_user_name)
        logger.info(f"Next user assignment fo task '{definition.name}' is '{next_user_name}'")

        if not next_user:
            logger.error(f"Cannot assign task '{definition.name}': Next user '{next_user_name}' not found in DB.")
            return
        

        now = datetime.now(timezone.utc)

        already_existing_instance = crud.get_active_task_instance_for_user(self.db, task_def_id=definition.id, user_id=next_user.id)
        if already_existing_instance is not None:
            # One active task definition is already assigned to this user
            crud.update_task_instance(self.db, already_existing_instance.id,
                assigned_user_id=next_user.id,
                assigned_at=now,
                deadline_repeat=now + definition.reproduction_period,
                deadline_final=now + definition.pass_over_period,
                status=const.STATUS_ACTIVE,
                start_date=self._generate_start_date(definition=definition),
                allow_reassignment=False
            )
            return
        new_instance = crud.create_task_instance(self.db,
            task_definition_id=definition.id,
            assigned_user_id=next_user.id,
            assigned_at=now,
            deadline_repeat=now + definition.reproduction_period,
            deadline_final=now + definition.pass_over_period,
            start_date=self._generate_start_date(definition=definition),
            status=const.STATUS_ACTIVE
        )
        logger.info(f"Created new instance {new_instance.instance_uuid} of '{definition.name}' for user '{next_user.name}'.")

    def sync_gtasks_state(self, user: User, tasks_handler: GoogleTasksHandler):
        """Synchronizes the state of DB instances with Google Tasks for a specific user."""
        logger.info(f"Syncing Google Tasks state for user {user.email}")
        now = datetime.now(ZoneInfo(settings.APP_TZ))
        user_instances = self.db.query(TaskInstance).filter(
            TaskInstance.assigned_user_id == user.id,
            TaskInstance.status == const.STATUS_ACTIVE
        ).all()

        # Organize instances by category to minimize API calls
        instances_by_category = {}
        for inst in user_instances:
            cat = inst.definition.category
            if cat not in instances_by_category:
                instances_by_category[cat] = []
            instances_by_category[cat].append(inst)

        for category, instances in instances_by_category.items():
            tasklist_id = tasks_handler._get_or_create_tasklist(category)
            if not tasklist_id:
                continue

            # Fetch all tasks from Google Tasks for this category once
            gtasks_map = tasks_handler.get_all_tasks_with_sync_id(tasklist_id)

            for instance in instances:
                instance_uuid_str = str(instance.instance_uuid)
                gtask = gtasks_map.get(instance_uuid_str)

                # Case 1: Task exists in DB but not in Google Tasks -> Create it
                if not gtask:
                    if instance.start_date < now:
                        gtasks_id = tasks_handler.create_task(instance)
                        if gtasks_id:
                            crud.update_task_instance(self.db, instance.id, gtasks_task_id=gtasks_id)
                    continue

                # Store gtask_id if it's missing in DB
                if not instance.gtasks_task_id:
                     crud.update_task_instance(self.db, instance.id, gtasks_task_id=gtask['id'])

                # Case 2: Task completed in Google Tasks
                if gtask['status'] == 'completed':
                    if instance.status == const.STATUS_ACTIVE:
                        logger.info(f"Task '{instance.definition.name}' marked as completed in Google Tasks for user {user.name}.")
                        completion_time = datetime.fromisoformat(gtask['completed'].replace('Z', '+00:00'))
                        crud.update_task_instance(self.db, instance.id, status=const.STATUS_COMPLETED, completed_at=completion_time)
                        crud.create_completion_log(self.db, task_instance_id=instance.id, user_id=user.id, completed_at=completion_time, trigger_type=const.TRIGGER_API)

        # Case 3: Task in DB is completed/terminated, but exists in Google -> Delete it
        inactive_instances = self.db.query(TaskInstance).filter(
            TaskInstance.assigned_user_id == user.id,
            TaskInstance.status != const.STATUS_ACTIVE,
            TaskInstance.gtasks_task_id != None
        ).all()
        for instance in inactive_instances:
            tasklist_id = tasks_handler._get_or_create_tasklist(instance.definition.category)
            if tasklist_id:
                tasks_handler.delete_task(tasklist_id, instance.gtasks_task_id)
                crud.update_task_instance(self.db, instance.id, gtasks_task_id=None) # Clear the ID after deletion