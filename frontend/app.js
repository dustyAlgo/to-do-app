// Plain JS client. Auth is entirely server-side: the browser only carries the
// HttpOnly session cookie set by FastAPI. No tokens are ever visible here.
"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    // no or expired session → start the OIDC login flow
    window.location.href = "/api/auth/login";
    throw new Error("redirecting to login");
  }
  if (!res.ok) {
    throw new Error(`${res.status}: ${await res.text()}`);
  }
  return res.status === 204 ? null : res.json();
}

function showError(err) {
  $("error").textContent = err ? String(err.message || err) : "";
  $("error").hidden = !err;
}

function renderTodos(todos) {
  const list = $("todos");
  list.replaceChildren();
  $("empty").hidden = todos.length > 0;

  for (const todo of todos) {
    const li = document.createElement("li");
    li.className = todo.done ? "done" : "";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = todo.done;
    checkbox.addEventListener("change", () => update(todo.id, { done: checkbox.checked }));

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = todo.title; // textContent only: user data is never parsed as HTML

    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "secondary small";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => {
      const next = prompt("Edit todo", todo.title);
      if (next !== null && next.trim()) update(todo.id, { title: next.trim() });
    });

    const del = document.createElement("button");
    del.type = "button";
    del.className = "danger small";
    del.textContent = "Delete";
    del.addEventListener("click", () => remove(todo.id));

    li.append(checkbox, title, edit, del);
    list.append(li);
  }
}

async function refresh() {
  renderTodos(await api("/api/todos"));
}

async function update(id, patch) {
  try {
    await api(`/api/todos/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
    showError(null);
  } catch (err) {
    showError(err);
  }
  await refresh();
}

async function remove(id) {
  try {
    await api(`/api/todos/${id}`, { method: "DELETE" });
    showError(null);
  } catch (err) {
    showError(err);
  }
  await refresh();
}

$("new-todo").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("title");
  const title = input.value.trim();
  if (!title) return;
  try {
    await api("/api/todos", { method: "POST", body: JSON.stringify({ title }) });
    input.value = "";
    showError(null);
    await refresh();
  } catch (err) {
    showError(err);
  }
});

$("call-rust").addEventListener("click", async () => {
  try {
    const data = await api("/api/rust");
    $("rust-out").textContent = data.message;
  } catch (err) {
    $("rust-out").textContent = "";
    showError(err);
  }
});

(async function init() {
  try {
    const me = await api("/api/me");
    $("username").textContent = me.username || me.sub;
    $("user").hidden = false;
    $("app").hidden = false;
    $("loading").hidden = true;
    await refresh();
  } catch (err) {
    if (err.message !== "redirecting to login") {
      $("loading").textContent = `Could not load: ${err.message}`;
    }
  }
})();
