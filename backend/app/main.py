from fastapi import FastAPI
from sqlalchemy import text

from backend.app.db import engine, Base

from backend.app.models import import_model
from backend.app.models import section_model
from backend.app.models import work_model
from backend.app.models import override_model
from backend.app.models import ruleset_model
from backend.app.models import export_model

from backend.app.api import import_routes

app = FastAPI()

app.include_router(import_routes.router)


@app.get("/")
def root():
    return {"status": "Catalogue tool running"}


@app.get("/db-test")
def db_test():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        return {"db": "connected", "result": result.scalar()}
