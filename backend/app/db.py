from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from backend.app.config import DATABASE_URL, LOG_LEVEL

engine = create_engine(DATABASE_URL, echo=(LOG_LEVEL == "DEBUG"))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
