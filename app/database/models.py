# ## path: app/database/models.py
import uuid
from sqlalchemy import (Column, String, Integer, DateTime, ForeignKey, Boolean,
                          Enum, Text, Interval)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database.database import Base
import app.constants as const

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    google_credentials_json = Column(Text, nullable=True)

class TaskDefinition(Base):
    __tablename__ = "task_definitions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    category = Column(String, nullable=False)
    reproduction_period = Column(Interval, nullable=False)
    pass_over_period = Column(Interval, nullable=False)
    actors = Column(String, nullable=False)  # Comma-separated names
    overdue_behavior = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

class TaskInstance(Base):
    __tablename__ = "task_instances"
    id = Column(Integer, primary_key=True, index=True)
    instance_uuid = Column(UUID(as_uuid=True), unique=True, default=uuid.uuid4, nullable=False)
    task_definition_id = Column(Integer, ForeignKey("task_definitions.id"), nullable=False)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    gtasks_task_id = Column(String, nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=False)
    deadline_repeat = Column(DateTime, nullable=False)
    deadline_final = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String, default=const.STATUS_ACTIVE, nullable=False)
    allow_reassignment = Column(Boolean, default=True)

    definition = relationship("TaskDefinition")
    assigned_user = relationship("User")

class TaskCompletionHistory(Base):
    __tablename__ = "task_completion_history"
    id = Column(Integer, primary_key=True, index=True)
    task_instance_id = Column(Integer, ForeignKey("task_instances.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    completed_at = Column(DateTime, nullable=False)
    trigger_type = Column(String, nullable=False)

    instance = relationship("TaskInstance")
    user = relationship("User")