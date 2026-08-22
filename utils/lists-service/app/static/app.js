const state = {
  selectedListId: null,
  listFilter: "",
  itemFilter: "",
};

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

function showError(error) {
  alert(error.message || String(error));
}

function setView(view) {
  document.getElementById("lists-view").classList.toggle("hidden", view !== "lists");
  document.getElementById("audit-view").classList.toggle("hidden", view !== "audit");
  document.getElementById("nav-lists").classList.toggle("active", view === "lists");
  document.getElementById("nav-audit").classList.toggle("active", view === "audit");
}

async function loadLists() {
  const query = new URLSearchParams();
  if (state.listFilter) query.set("query", state.listFilter);
  const data = await api(`/lists?${query.toString()}`);
  const listEl = document.getElementById("lists");
  listEl.innerHTML = "";

  for (const list of data.lists) {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${list.name}</strong><br/>${list.description || ""}`;

    const actions = document.createElement("div");
    actions.className = "actions";

    const details = document.createElement("button");
    details.textContent = "Details";
    details.onclick = () => {
      state.selectedListId = list.id;
      document.getElementById("detail-title").textContent = list.name;
      document.getElementById("detail-description").textContent = list.description || "";
      document.getElementById("list-details-empty").classList.add("hidden");
      document.getElementById("list-details").classList.remove("hidden");
      loadItems();
    };

    const remove = document.createElement("button");
    remove.textContent = "Delete";
    remove.onclick = async () => {
      if (!confirm("Delete this list?")) return;
      try {
        await api(`/lists/${list.id}?actor=web`, { method: "DELETE" });
        if (state.selectedListId === list.id) {
          state.selectedListId = null;
          document.getElementById("list-details").classList.add("hidden");
          document.getElementById("list-details-empty").classList.remove("hidden");
        }
        await Promise.all([loadLists(), loadAudit()]);
      } catch (error) {
        showError(error);
      }
    };

    actions.append(details, remove);
    li.appendChild(actions);
    listEl.appendChild(li);
  }
}

async function loadItems() {
  if (!state.selectedListId) return;
  const query = new URLSearchParams();
  if (state.itemFilter) query.set("query", state.itemFilter);
  const data = await api(`/lists/${state.selectedListId}/items?${query.toString()}`);
  const listEl = document.getElementById("items");
  listEl.innerHTML = "";

  for (const item of data.items) {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${item.title}</strong> [${item.status}]<br/>${item.notes || ""}`;

    const actions = document.createElement("div");
    actions.className = "actions";

    const edit = document.createElement("button");
    edit.textContent = "Edit";
    edit.onclick = async () => {
      const title = prompt("Title", item.title);
      if (title === null) return;
      const notes = prompt("Notes", item.notes || "");
      if (notes === null) return;
      const status = prompt("Status", item.status);
      if (status === null) return;
      try {
        await api(`/items/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ title, notes, status, actor: "web" }),
        });
        await Promise.all([loadItems(), loadAudit()]);
      } catch (error) {
        showError(error);
      }
    };

    const remove = document.createElement("button");
    remove.textContent = "Delete";
    remove.onclick = async () => {
      if (!confirm("Delete this item?")) return;
      try {
        await api(`/items/${item.id}?actor=web`, { method: "DELETE" });
        await Promise.all([loadItems(), loadAudit()]);
      } catch (error) {
        showError(error);
      }
    };

    actions.append(edit, remove);
    li.appendChild(actions);
    listEl.appendChild(li);
  }
}

async function loadAudit() {
  const data = await api("/audit?limit=100");
  const listEl = document.getElementById("audit");
  listEl.innerHTML = "";

  for (const entry of data.entries) {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${entry.operation}</strong> (${entry.target_type})<br/>${entry.created_at}`;

    if (entry.operation !== "audit.revert" && !entry.reverted_by_audit_id) {
      const actions = document.createElement("div");
      actions.className = "actions";
      const revert = document.createElement("button");
      revert.textContent = "Revert";
      revert.onclick = async () => {
        try {
          await api(`/audit/${entry.id}/revert`, {
            method: "POST",
            body: JSON.stringify({ actor: "web" }),
          });
          await Promise.all([loadAudit(), loadLists(), loadItems()]);
        } catch (error) {
          showError(error);
        }
      };
      actions.appendChild(revert);
      li.appendChild(actions);
    }

    listEl.appendChild(li);
  }
}

async function addList() {
  const name = prompt("List name");
  if (!name) return;
  const description = prompt("Description") || "";
  try {
    await api("/lists", {
      method: "POST",
      body: JSON.stringify({ name, description, actor: "web" }),
    });
    await Promise.all([loadLists(), loadAudit()]);
  } catch (error) {
    showError(error);
  }
}

async function addItem() {
  if (!state.selectedListId) {
    alert("Select a list first.");
    return;
  }
  const title = prompt("Item title");
  if (!title) return;
  const notes = prompt("Notes") || "";
  const status = prompt("Status", "open") || "open";
  try {
    await api(`/lists/${state.selectedListId}/items`, {
      method: "POST",
      body: JSON.stringify({ title, notes, status, actor: "web" }),
    });
    await Promise.all([loadItems(), loadAudit()]);
  } catch (error) {
    showError(error);
  }
}

function setup() {
  document.getElementById("nav-lists").onclick = () => setView("lists");
  document.getElementById("nav-audit").onclick = () => {
    setView("audit");
    loadAudit().catch(showError);
  };

  document.getElementById("list-filter-btn").onclick = () => {
    state.listFilter = document.getElementById("list-filter").value.trim();
    loadLists().catch(showError);
  };
  document.getElementById("list-add-btn").onclick = () => addList();

  document.getElementById("item-filter-btn").onclick = () => {
    state.itemFilter = document.getElementById("item-filter").value.trim();
    loadItems().catch(showError);
  };
  document.getElementById("item-add-btn").onclick = () => addItem();

  document.getElementById("audit-refresh-btn").onclick = () => loadAudit().catch(showError);
}

setup();
loadLists().catch(showError);
