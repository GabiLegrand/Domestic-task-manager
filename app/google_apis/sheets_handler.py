# ## path: app/google_apis/sheets_handler.py
import gspread
import pandas as pd
from google.oauth2.credentials import Credentials
from app.dtos import UserDTO, TaskDefinitionDTO
import app.constants as const
from app.config import settings
import logging
from isodate import parse_duration
import re

def human_to_iso_duration(human_str):
    # Extract number and unit from the human input
    match = re.match(r"(-?\d+)\s*(second|seconds|minute|minutes|heure|heures|jour|jours|semaine|semaines)", human_str.lower())
    if not match:
        raise ValueError("Invalid duration format. Try '1 minute', '2 heures', '-3 jours', etc.")
    
    value, unit = int(match.group(1)), match.group(2)
    
    # Map human unit to ISO 8601 duration component
    unit_map = {
        "second": "S", "seconds": "S",
        "minute": "M", "minutes": "M",
        "heure": "H", "heures": "H",
        "jour": "D", "jours": "D",
        "semaine": "W", "semaines": "W",
    }
    
    iso_unit = unit_map[unit]
    
    # Build ISO duration string
    if iso_unit in ["H", "M", "S"]:
        iso_str = f"PT{abs(value)}{iso_unit}"
    elif iso_unit == "W":
        iso_str = f"P{abs(value)}{iso_unit}"
    else:
        iso_str = f"P{abs(value)}{iso_unit}"
    
    # Add negative sign if needed
    if value < 0:
        iso_str = "-" + iso_str
    
    return iso_str


logger = logging.getLogger(__name__)

class GSheetHandler:
    def __init__(self, admin_credentials: Credentials):
        if not admin_credentials:
            raise ValueError("Admin credentials are required for GSheetHandler.")
        self.client = gspread.authorize(admin_credentials)
        self.spreadsheet = self.client.open_by_key(settings.GOOGLE_SHEET_ID)

    def _get_sheet_as_df(self, sheet_name: str) -> pd.DataFrame | None:
        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
            data = worksheet.get_all_records()
            return pd.DataFrame(data) if data else pd.DataFrame()
        except gspread.exceptions.WorksheetNotFound:
            logger.warning(f"Sheet '{sheet_name}' not found.")
            return None
        except Exception as e:
            logger.error(f"Failed to read sheet '{sheet_name}': {e}")
            return None

    def get_user_configs(self) -> list[UserDTO]:
        df = self._get_sheet_as_df(const.CONFIG_SHEET_NAME)
        if df is None or df.empty:
            return []

        users = []
        for index, row in df.iterrows():
            if row.get(const.USER_SHEET_COL_EMAIL):
                users.append(UserDTO(
                    name=row[const.USER_SHEET_COL_NAME],
                    email=row[const.USER_SHEET_COL_EMAIL],
                    row_index=index + 2, # 1-based index + header row
                    has_token=bool(row.get(const.USER_SHEET_COL_HAS_TOKEN)),
                    consent_url=row.get(const.USER_SHEET_COL_CONSENT_URL)
                ))
        return users

    def get_task_definitions(self) -> list[TaskDefinitionDTO]:
        all_tasks = []
        sheet_names = [s.title for s in self.spreadsheet.worksheets()]
        task_sheet_names = [name for name in sheet_names if name.lower() != const.CONFIG_SHEET_NAME.lower()]

        for sheet_name in task_sheet_names:
            df = self._get_sheet_as_df(sheet_name)
            if df is None or df.empty:
                continue

            for _, row in df.iterrows():
                try:
                    # Validate mandatory fields
                    if not all(k in row and row[k] for k in [const.TASK_COL_NAME, const.TASK_COL_CATEGORY, const.TASK_COL_REPRO_PERIOD, const.TASK_COL_PASS_PERIOD, const.TASK_COL_ACTORS, const.TASK_COL_BEHAVIOR]):
                        logger.warning(f"Skipping task '{row.get(const.TASK_COL_NAME)}' due to missing mandatory fields.")
                        continue
                    start_preferences = []
                    if const.TASK_COL_START_PREFS in row and row[const.TASK_COL_START_PREFS]:
                        start_preferences =[preference.strip() for preference in str(row[const.TASK_COL_START_PREFS]).split(',')]

                    task_days = None
                    if const.TASK_COL_TASK_DAYS in row and row[const.TASK_COL_TASK_DAYS]:
                        try:
                            days_str = str(row[const.TASK_COL_TASK_DAYS])
                            # Extract number from "X jour" or "X jours"
                            import re
                            match = re.search(r'(\d+)', days_str)
                            if match:
                                task_days = int(match.group(1))
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid task days format: {row[const.TASK_COL_TASK_DAYS]}")

                    task = TaskDefinitionDTO(
                        name=row[const.TASK_COL_NAME],
                        category=row[const.TASK_COL_CATEGORY],
                        reproduction_period=parse_duration(human_to_iso_duration(row[const.TASK_COL_REPRO_PERIOD])),
                        pass_over_period=parse_duration(human_to_iso_duration(row[const.TASK_COL_PASS_PERIOD])),
                        actors=[actor.strip() for actor in str(row[const.TASK_COL_ACTORS]).split(',')],
                        overdue_behavior=row[const.TASK_COL_BEHAVIOR],
                        start_preferences=start_preferences,
                        task_days=task_days
                    )
                    all_tasks.append(task)
                except Exception as e:
                    logger.error(f"Error parsing task row in sheet '{sheet_name}': {row}. Error: {e}")
        return all_tasks

    def update_cell(self, row: int, col_name: str, value: str):
        try:
            worksheet = self.spreadsheet.worksheet(const.CONFIG_SHEET_NAME)
            # Find column index by header name
            headers = worksheet.row_values(1)
            if col_name not in headers:
                logger.error(f"Column '{col_name}' not found in configuration sheet.")
                return
            col_index = headers.index(col_name) + 1
            worksheet.update_cell(row, col_index, value)
        except Exception as e:
            logger.error(f"Failed to update cell ({row}, {col_name}): {e}")