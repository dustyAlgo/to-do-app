import httpx

from app import todo_routes

from .conftest import bearer


def test_health_needs_no_auth(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_requires_authentication(client):
    assert client.get("/api/todos").status_code == 401
    assert client.post("/api/todos", json={"title": "x"}).status_code == 401


def test_crud_happy_path(client):
    alice = bearer("alice-sub")
    assert client.get("/api/todos", headers=alice).json() == []

    created = client.post("/api/todos", json={"title": "  buy milk "}, headers=alice)
    assert created.status_code == 201
    todo = created.json()
    assert todo["title"] == "buy milk" and todo["done"] is False

    toggled = client.patch(f"/api/todos/{todo['id']}", json={"done": True}, headers=alice)
    assert toggled.json()["done"] is True

    renamed = client.patch(f"/api/todos/{todo['id']}", json={"title": "buy oat milk"}, headers=alice)
    assert renamed.json()["title"] == "buy oat milk"

    assert [t["id"] for t in client.get("/api/todos", headers=alice).json()] == [todo["id"]]

    assert client.delete(f"/api/todos/{todo['id']}", headers=alice).status_code == 204
    assert client.get("/api/todos", headers=alice).json() == []


def test_validation(client):
    alice = bearer("alice-sub")
    assert client.post("/api/todos", json={"title": ""}, headers=alice).status_code == 422
    assert client.post("/api/todos", json={"title": "x" * 256}, headers=alice).status_code == 422


def test_users_cannot_see_each_others_todos(client):
    alice, bob = bearer("alice-sub"), bearer("bob-sub")
    todo_id = client.post("/api/todos", json={"title": "alice only"}, headers=alice).json()["id"]

    assert client.get("/api/todos", headers=bob).json() == []
    assert client.patch(f"/api/todos/{todo_id}", json={"done": True}, headers=bob).status_code == 404
    assert client.delete(f"/api/todos/{todo_id}", headers=bob).status_code == 404
    # still intact for alice
    assert client.get("/api/todos", headers=alice).json()[0]["done"] is False


def test_rust_proxy(client, monkeypatch):
    def fake_get(url, timeout):
        return httpx.Response(200, json={"message": "hello rust api"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(todo_routes.httpx, "get", fake_get)
    resp = client.get("/api/rust", headers=bearer())
    assert resp.json() == {"message": "hello rust api"}
