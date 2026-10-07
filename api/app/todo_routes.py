import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .deps import CurrentUser, get_current_user
from .models import Todo
from .schemas import Me, TodoCreate, TodoOut, TodoUpdate

router = APIRouter(prefix="/api", tags=["todos"])


def _get_owned(db: Session, todo_id: int, user: CurrentUser) -> Todo:
    # Ownership is part of the query: another user's todo is indistinguishable from a missing one (404).
    todo = db.scalar(select(Todo).where(Todo.id == todo_id, Todo.user_id == user.sub))
    if todo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "todo not found")
    return todo


@router.get("/me", response_model=Me)
def me(user: CurrentUser = Depends(get_current_user)):
    return Me(sub=user.sub, username=user.username)


@router.get("/todos", response_model=list[TodoOut])
def list_todos(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Todo).where(Todo.user_id == user.sub).order_by(Todo.id)).all()


@router.post("/todos", response_model=TodoOut, status_code=status.HTTP_201_CREATED)
def create_todo(body: TodoCreate, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    todo = Todo(user_id=user.sub, title=body.title.strip(), done=False)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


@router.patch("/todos/{todo_id}", response_model=TodoOut)
def update_todo(
    todo_id: int,
    body: TodoUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    todo = _get_owned(db, todo_id, user)
    if body.title is not None:
        todo.title = body.title.strip()
    if body.done is not None:
        todo.done = body.done
    db.commit()
    db.refresh(todo)
    return todo


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: int, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_get_owned(db, todo_id, user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/rust")
def call_rust(user: CurrentUser = Depends(get_current_user)):
    """Middleware → Rust API (internal only, so it is still behind auth)."""
    try:
        resp = httpx.get(f"{settings.rust_api_url}/hello", timeout=5)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"rust api unavailable: {exc}")
    return resp.json()
