from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import auth_routes, todo_routes
from .db import Base, engine, get_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # No migrations in scope: create tables if missing. TODO: switch to Alembic if the schema evolves.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="To-Do API",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.include_router(auth_routes.router)
app.include_router(todo_routes.router)


@app.get("/api/health", tags=["ops"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
