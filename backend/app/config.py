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

# Shared API key for all requests (LEGACY – ignored when Cognito is configured).
# If empty or unset, authentication is disabled (useful for local development).
API_KEY: str = os.getenv("API_KEY", "")

# Cognito settings.  When COGNITO_USER_POOL_ID is set, JWT auth is used
# instead of the shared API key.
COGNITO_USER_POOL_ID: str = os.getenv("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID: str = os.getenv("COGNITO_CLIENT_ID", "")
COGNITO_REGION: str = os.getenv("COGNITO_REGION", os.getenv("AWS_REGION", "eu-north-1"))

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# Directory where uploaded Excel files are stored.
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")

# Storage backend: "local" (default) or "s3".
STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local").lower()

# S3 settings (only used when STORAGE_BACKEND=s3)
S3_BUCKET: str = os.getenv("S3_BUCKET", "")
AWS_REGION: str | None = os.getenv("AWS_REGION")

# Comma-separated list of allowed CORS origins.
# Leave empty to disallow cross-origin requests (same-origin only).
CORS_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]
