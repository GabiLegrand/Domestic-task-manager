# ## path: app/google_apis/auth.py
import os
import json
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/tasks', 'https://www.googleapis.com/auth/spreadsheets']
REDIRECT_URI = 'http://localhost:5000' # A dummy redirect for desktop app flow

def get_user_credentials(user_email: str) -> Credentials | None:
    """Loads a user's credentials from the cache if they exist."""
    token_path = os.path.join(settings.TOKEN_CACHE_DIR, f"{user_email}.json")
    if os.path.exists(token_path):
        try:
            return Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            logger.error(f"Failed to load credentials for {user_email}: {e}")
            return None
    return None

def save_user_credentials(user_email: str, creds: Credentials):
    """Saves a user's credentials to the cache."""
    token_path = os.path.join(settings.TOKEN_CACHE_DIR, f"{user_email}.json")
    with open(token_path, 'w') as token_file:
        token_file.write(creds.to_json())
    logger.info(f"Saved credentials for {user_email}")

def generate_consent_url() -> tuple[Flow, str]:
    """Generates a new OAuth consent URL for the user to visit."""
    try:
        flow = Flow.from_client_secrets_file(
            settings.CREDENTIALS_FILE_PATH,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        logger.info(f"Generated new consent URL: {auth_url}")
        return flow, auth_url
    except FileNotFoundError:
        logger.error(f"FATAL: credentials.json not found at '{settings.CREDENTIALS_FILE_PATH}'")
        raise
    except Exception as e:
        logger.error(f"Error generating consent URL: {e}")
        return None, None

def fetch_token_from_code(flow: Flow, auth_code: str) -> Credentials | None:
    """Fetches a token using the authorization code provided by the user."""
    try:
        flow.fetch_token(code=auth_code)
        return flow.credentials
    except Exception as e:
        logger.error(f"Failed to fetch token with code: {e}")
        return None
    



def refresh_auth_token(user_email: str) -> Credentials | None:
    """
    Refreshes an expired auth token for a user.

    This function should be called if an API call fails with an authentication error.
    It checks if the credentials exist and have a refresh token. If so, it
    attempts to refresh them and saves the updated credentials.

    Args:
        user_email: The email of the user whose token needs refreshing.

    Returns:
        The refreshed Credentials object, or None if refresh fails or is not possible.
    """
    creds = get_user_credentials(user_email)
    
    # Check if credentials exist and are invalid/expired but have a refresh token
    if creds and not creds.valid and creds.refresh_token:
        logger.info(f"Token for {user_email} has expired. Attempting to refresh...")
        try:
            creds.refresh(Request())
            # Save the newly refreshed credentials back to the user's cache
            save_user_credentials(user_email, creds)
            logger.info(f"Successfully refreshed and saved token for {user_email}.")
            return creds
        except Exception as e:
            # This can happen if the refresh token has been revoked by the user.
            logger.error(f"Failed to refresh token for {user_email}. Re-authentication is required. Error: {e}")
            # Optionally, you could delete the now-useless token file here.
            return None
            
    # If creds are still valid, no need to refresh
    elif creds and creds.valid:
        logger.debug(f"Token for {user_email} is still valid.")
        return creds

    # If creds don't exist or there's no refresh token, we can't do anything.
    else:
        logger.warning(f"Could not refresh token for {user_email}: No credentials or refresh token found.")
        return None