import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (two levels above this file)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost/catalogue_tool",
)

# Shared API key for all requests.
# If empty or unset, authentication is disabled (useful for local development).
API_KEY: str = os.getenv("API_KEY", "")

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# Directory where uploaded Excel files are stored.
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
