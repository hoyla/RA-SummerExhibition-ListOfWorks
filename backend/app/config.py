import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost/catalogue_tool"
)