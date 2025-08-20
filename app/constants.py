# Google Sheets Configuration
CONFIG_SHEET_NAME = 'Configuration'
USER_SHEET_COL_NAME = 'name'
USER_SHEET_COL_EMAIL = 'email'
USER_SHEET_COL_CONSENT_URL = 'consent_url'
USER_SHEET_COL_HAS_TOKEN = 'has_token'

# Task Definition Columns from Sheets
TASK_COL_NAME = 'Nom'
TASK_COL_CATEGORY = 'Catégorie'
TASK_COL_REPRO_PERIOD = 'Durée reproduction'
TASK_COL_PASS_PERIOD = 'Durée avant passation'
TASK_COL_ACTORS = 'Acteurs'
TASK_COL_BEHAVIOR = 'Comportement non realisation'
TASK_COL_START_PREFS = 'Préférences début'
TASK_COL_TASK_DAYS = 'Nombre de jours pour la tâche'

# Behavior types
BEHAVIOR_KEEP = 'Garder'
BEHAVIOR_CHANGE = 'Changer'
BEHAVIOR_KEEP_AND_CHANGE = 'Garder et changer'

# Task Instance Status in DB
STATUS_ACTIVE = 'active'
STATUS_COMPLETED = 'completed'
STATUS_TERMINATED = 'terminated'

# Task identifier format in Google Tasks description
TASK_ID_MARKER = "sync_id"
TASK_ID_FORMAT = f"[{TASK_ID_MARKER}::{{instance_uuid}}]"

# Completion History Triggers
TRIGGER_API = 'api_completed'
TRIGGER_DELETED = 'deleted_in_app'
TRIGGER_PASSED_OVER = 'passed_over'