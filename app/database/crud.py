# ## path: app/database/crud.py
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.database import models
from app.dtos import TaskDefinitionDTO, UserDTO
import app.constants as const
import logging

logger = logging.getLogger(__name__)

# User CRUD
def get_or_create_user(db: Session, user_dto: UserDTO) -> models.User:
    user = db.query(models.User).filter(models.User.email == user_dto.email).first()
    if not user:
        user = models.User(name=user_dto.name, email=user_dto.email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def get_user_by_name(db: Session, name: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.name == name).first()

def get_all_users(db: Session) -> List[models.User]:
    return db.query(models.User).all()

def update_user_credentials(db: Session, email: str, creds_json: str):
    db.query(models.User).filter(models.User.email == email).update({"google_credentials_json": creds_json})
    db.commit()

# Task Definition CRUD
def upsert_task_definition(db: Session, task_def_dto: TaskDefinitionDTO) -> models.TaskDefinition:
    task_def : models.TaskDefinition= db.query(models.TaskDefinition).filter(models.TaskDefinition.name == task_def_dto.name).first()
    if task_def:
        # Update existing definition
        task_def.category = task_def_dto.category
        task_def.reproduction_period = task_def_dto.reproduction_period
        task_def.pass_over_period = task_def_dto.pass_over_period
        task_def.actors = ",".join(task_def_dto.actors)
        task_def.overdue_behavior = task_def_dto.overdue_behavior
        task_def.start_preferences = ",".join(task_def_dto.start_preferences)
        task_def.task_days = task_def_dto.task_days
        task_def.is_active = True
    else:
        # Create new definition
        task_def = models.TaskDefinition(
            name=task_def_dto.name,
            category=task_def_dto.category,
            reproduction_period=task_def_dto.reproduction_period,
            pass_over_period=task_def_dto.pass_over_period,
            actors=",".join(task_def_dto.actors),
            overdue_behavior=task_def_dto.overdue_behavior,
            start_preferences = ",".join(task_def_dto.start_preferences),
            task_days = task_def_dto.task_days,
            is_active=True
        )
        db.add(task_def)
    logger.info(f"{task_def.name} - {task_def.start_preferences}")
    db.commit()
    db.refresh(task_def)
    return task_def

def get_active_task_definitions(db: Session) -> List[models.TaskDefinition]:
    return db.query(models.TaskDefinition).filter(models.TaskDefinition.is_active == True).all()

def deactivate_task_definitions(db: Session, active_names: List[str]):
    db.query(models.TaskDefinition).filter(models.TaskDefinition.name.notin_(active_names)).update({"is_active": False})
    db.commit()

# Task Instance CRUD
def get_active_task_instance_for_definition(db: Session, task_def_id: int) -> Optional[models.TaskInstance]:
    return db.query(models.TaskInstance).filter(
        models.TaskInstance.task_definition_id == task_def_id,
        models.TaskInstance.status != const.STATUS_TERMINATED
    ).all()


def get_active_task_instance_for_user(db: Session, task_def_id: int, user_id) -> Optional[models.TaskInstance]:
    return db.query(models.TaskInstance).filter(
        models.TaskInstance.task_definition_id == task_def_id,
        models.TaskInstance.status != const.STATUS_TERMINATED,
        models.TaskInstance.assigned_user_id == user_id,
    ).first()

def get_all_active_task_instances(db: Session) -> List[models.TaskInstance]:
    active_task_definitions = get_active_task_definitions(db)
    
    active_ids = [definition.id for definition in active_task_definitions]

    return db.query(models.TaskInstance).filter(
        models.TaskInstance.task_definition_id.in_(active_ids),
        models.TaskInstance.status != const.STATUS_TERMINATED
    ).all()


def create_task_instance(db: Session, **kwargs) -> models.TaskInstance:
    instance = models.TaskInstance(**kwargs)
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance

def update_task_instance(db: Session, instance_id: int, **kwargs):
    db.query(models.TaskInstance).filter(models.TaskInstance.id == instance_id).update(kwargs)
    db.commit()

# Task Completion History CRUD
def create_completion_log(db: Session, **kwargs):
    log = models.TaskCompletionHistory(**kwargs)
    db.add(log)
    db.commit()