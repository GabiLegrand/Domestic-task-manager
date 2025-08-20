# ## path: app/dtos.py
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import timedelta, datetime

@dataclass
class UserDTO:
    """Data Transfer Object for a user's configuration."""
    name: str
    email: str
    row_index: int
    has_token: bool = False
    consent_url: Optional[str] = None

@dataclass
class TaskDefinitionDTO:
    """Data Transfer Object for a task definition from the spreadsheet."""
    name: str
    category: str
    reproduction_period: timedelta
    pass_over_period: timedelta
    actors: List[str]
    overdue_behavior: str
    start_preferences: List[str]
    task_days: Optional[int] = None
    is_active: bool = True