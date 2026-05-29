from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.app.config import DATABASE_URL, LOG_LEVEL

# pool_pre_ping issues a cheap SELECT 1 before handing out a pooled
# connection. Protects against stale connections when a firewall, NAT,
# or RDS itself silently drops the TCP socket after idle. Negligible
# cost; the alternative is sporadic 500s from "server closed the
# connection unexpectedly" on the first request after idle.
engine = create_engine(
    DATABASE_URL,
    echo=(LOG_LEVEL == "DEBUG"),
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
