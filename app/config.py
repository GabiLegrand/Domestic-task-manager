# ## path: app/config.py
import os
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

class Settings:
    """Application configuration settings."""
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID")
    CREDENTIALS_FILE_PATH: str = os.getenv("CREDENTIALS_FILE_PATH")
    TOKEN_CACHE_DIR: str = os.getenv("TOKEN_CACHE_DIR")
    LOOP_INTERVAL_SECONDS: int = int(os.getenv("LOOP_INTERVAL_SECONDS", 300))

# Create a single settings instance to be imported by other modules
settings = Settings()