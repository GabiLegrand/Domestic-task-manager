# ## path: app/main.py
import json
import os
import time
import logging
import sys
from urllib.parse import urlparse, parse_qs

from app.config import settings
from app import constants as const
from app.database.database import init_db, get_db
from app.database.models import *
from app.google_apis import auth, sheets_handler, tasks_handler
from app.logic.task_manager import TaskManager
import app.database.crud as crud
from app.dtos import UserDTO

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def load_email_json(folder_path: str, email: str):
    """
    Look in a specific folder for <email>.json.
    If found, load and return the JSON content; otherwise return None.
    """
    file_path = os.path.join(folder_path, f"{email}.json")
    
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON in file: {file_path}")
    return None

def initial_auth_flow(db_session, user_dto: UserDTO) -> bool:
    """Handles the initial authentication for a single user."""

    saved_credential_json = load_email_json(settings.TOKEN_CACHE_DIR, user_dto.email)
    if saved_credential_json is not None :
        user_in_db = crud.get_or_create_user(db_session, user_dto)
        crud.update_user_credentials(db_session, user_in_db.email, json.dumps(saved_credential_json))
        logger.info(f"User credentials already existed for {user_dto.email} in a json cache file.")
        return True
        
    flow, auth_url = auth.generate_consent_url()
    if not auth_url:
        return False

    # Update sheet with consent URL
    # This requires an authenticated GSheet handler, assuming one is available
    # For simplicity, we'll just log it. The main loop will handle the sheet update.
    logger.warning(f"ACTION REQUIRED for {user_dto.email}:")
    logger.warning(f"1. Visit this URL: {auth_url}")
    logger.warning("2. Authenticate and you will be redirected to a page (likely an error page).")
    logger.warning("3. Copy the ENTIRE address from your browser's address bar.")
    
    try:
        redirected_url = input(f"4. Paste the full redirect URL for {user_dto.email} here and press Enter: ")
        
        parsed_url = urlparse(redirected_url)
        query_params = parse_qs(parsed_url.query)
        auth_code = query_params.get('code', [None])[0]

        if not auth_code:
            logger.error("Could not find 'code' in the provided URL.")
            return False

        creds = auth.fetch_token_from_code(flow, auth_code)
        if creds:
            auth.save_user_credentials(user_dto.email, creds)
            user_in_db = crud.get_or_create_user(db_session, user_dto)
            crud.update_user_credentials(db_session, user_in_db.email, creds.to_json())
            logger.info(f"Successfully fetched and saved token for {user_dto.email}.")
            return True
        else:
            logger.error(f"Failed to fetch token for {user_dto.email}.")
            return False
            
    except Exception as e:
        logger.error(f"An error occurred during auth flow: {e}")
        return False


def main_loop():
    """The main application loop."""
    db_session = next(get_db())
    
    # We need an admin/primary user to read the sheet first.
    # The first user in the sheet will be our admin.
    logger.info("--- Starting main loop ---")
    
    # 1. Get user configs from sheet. This needs an authenticated user.
    # We'll use the first user who gets authenticated as the 'admin' for sheet access.
    admin_creds = None
    all_users = crud.get_all_users(db_session)
    for user in all_users:
        if user.google_credentials_json:
            admin_creds = auth.Credentials.from_authorized_user_info(
                info=eval(user.google_credentials_json), scopes=auth.SCOPES
            )
            if admin_creds and admin_creds.valid:
                logger.info(f"Using credentials from {user.email} to manage Google Sheet.")
                break
    if not admin_creds:
        logger.warning("No authenticated user found to manage the Google Sheet.")
        logger.warning("Attempting to authenticate the first user listed in the DB or from a manual prompt if DB is empty.")
        # This is a chicken-and-egg problem. Let's assume the first run requires manual intervention.
        # A helper script or manual DB entry for the first user's token is the most robust solution.
        # For now, we will prompt for the first user from the sheet.
        logger.info("Please provide the email of the 'admin' user who will read the sheet:")
        # admin_email = input("Admin Email: ")
        # admin_name = input("Admin Name (must match sheet): ")
        admin_email = "gabriel.ludel@gmail.com"
        admin_name = "Gabriel"
        admin_dto = UserDTO(name=admin_name, email=admin_email, row_index=0) # row_index doesn't matter here
        
        if initial_auth_flow(db_session, admin_dto):
            logger.info("Admin user authenticated. The app will restart the loop.")
            return # Restart loop
        else:
            logger.error("Could not authenticate admin user. Exiting loop.")
            return

    # With admin creds, we can now interact with the sheet
    gsheet_handler = sheets_handler.GSheetHandler(admin_creds)
    user_configs = gsheet_handler.get_user_configs()
    
    # 2. Sync users and handle auth for others
    for user_dto in user_configs:
        if user_dto.email == "alicepeyrolviale@gmail.com":
            logger.warning(f"User {user_dto.email} -- SKIPING DEBUG")
            continue
        user_in_db = crud.get_or_create_user(db_session, user_dto)
        if not user_in_db.google_credentials_json:
             # This flow would be better handled by generating the URL, putting it in the sheet,
             # and then checking for a pasted code on the next run.
             # For now, the console-interactive flow will be used.
             logger.warning(f"User {user_dto.email} is not authenticated.")
             if initial_auth_flow(db_session, user_dto):
                 gsheet_handler.update_cell(user_dto.row_index, const.USER_SHEET_COL_HAS_TOKEN, "TRUE")
             else:
                 _, url = auth.generate_consent_url()
                 gsheet_handler.update_cell(user_dto.row_index, const.USER_SHEET_COL_CONSENT_URL, url)
                 gsheet_handler.update_cell(user_dto.row_index, const.USER_SHEET_COL_HAS_TOKEN, "FALSE")

    # 3. Sync Task Definitions
    task_manager = TaskManager(db_session)
    task_defs_from_sheet = gsheet_handler.get_task_definitions()
    task_manager.sync_task_definitions(task_defs_from_sheet)

    # 4. Process all tasks based on DB state
    task_manager.process_all_tasks(crud.get_all_users(db_session))
    
    # 5. Sync state back to Google Tasks for each user
    users_with_creds = [u for u in crud.get_all_users(db_session) if u.google_credentials_json]
    for user in users_with_creds:
        creds = auth.Credentials.from_authorized_user_info(eval(user.google_credentials_json), scopes=auth.SCOPES)
        if creds and creds.valid:
            tasks_api = tasks_handler.GoogleTasksHandler(creds)
            task_manager.sync_gtasks_state(user, tasks_api)
        else:
            logger.warning(f"Credentials for {user.email} are invalid or expired. Trying to refresh")
            refreshed_creds = auth.refresh_auth_token(user.email)
            if refreshed_creds is not None:
                auth.save_user_credentials(user.email, refreshed_creds)
                user_in_db = crud.get_or_create_user(db_session, user)
                crud.update_user_credentials(db_session, user_in_db.email, refreshed_creds.to_json())
                logger.info(f"Successfully refreshed and saved token for {user.email}.")
    db_session.close()
    logger.info("--- Main loop finished ---")

def main():
    logger.info("Application starting...")
    init_db()
    while True:
        try:
            main_loop()
        except Exception as e:
            logger.critical(f"An unhandled error occurred in the main loop: {e}", exc_info=True)
        
        logger.info(f"Sleeping for {settings.LOOP_INTERVAL_SECONDS} seconds...")
        time.sleep(settings.LOOP_INTERVAL_SECONDS)   

if __name__ == "__main__":
    main()