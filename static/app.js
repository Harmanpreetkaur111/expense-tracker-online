// FRONTEND (v2): adds search, date filters and edit.
// Flow: user action -> API call -> backend changes database -> reload data -> render()

const CATEGORIES = [
  { name: "Food",          color: "#e8833a" },
  { name: "Transport",     color: "#3b82c4" },
  { name: "Shopping",      color: "#a15bd0" },
  { name: "Bills",         color: "#d6455d" },
  { name: "Entertainment", color: "#2ea66f" },
  { name: "Other",         color: "#7a8a96" }
];

const $ = id => document.getElementById(id);
const money = n => "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const colorOf = name => (CATEGORIES.find(c => c.name === name) || CATEGORIES[5]).color;
const todayStr = () => new Date().toISOString().slice(0, 10);
const escapeHtml = s => s.replace(/[&<>"']/g, ch =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

let editingId = null;   // null = adding, a number = editing that expense
let shown = [];         // the expenses currently on screen

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

// Build the URL with the current filters, e.g. /api/expenses?category=Food&q=bus
function listUrl() {
  const p = new URLSearchParams();
  p.set("category", $("filter").value);
  if ($("search").value.trim()) p.set("q", $("search").value.trim());
  if ($("from").value) p.set("start", $("from").value);
  if ($("to").value) p.set("end", $("to").value);
  return "/api/expenses?" + p.toString();
}
const filtersActive = () =>
  $("filter").value !== "All" || $("search").value.trim() || $("from").value || $("to").value;

async function render() {
  try {
    const [list, sum] = await Promise.all([api(listUrl()), api("/api/summary")]);
    shown = list;

    $("totalAll").textContent = money(sum.total);
    $("totalMonth").textContent = money(sum.month_total);
    $("count").textContent = sum.count;

    $("showing").textContent = filtersActive()
      ? `Showing ${list.length} of ${sum.count} expenses · ${money(list.reduce((s, e) => s + e.amount, 0))}`
      : "";

    $("list").innerHTML = list.length
      ? list.map(e => `
        <li class="item">
          <span class="dot" style="background:${colorOf(e.category)}"></span>
          <div class="info"><b>${escapeHtml(e.description)}</b><small>${e.category} · ${e.date}</small></div>
          <span class="amt">${money(e.amount)}</span>
          <button class="del edit" data-edit="${e.id}" aria-label="Edit ${escapeHtml(e.description)}">✎</button>
          <button class="del" data-id="${e.id}" aria-label="Delete ${escapeHtml(e.description)}">✕</button>
        </li>`).join("")
      : `<li class="empty">${sum.count ? "No expenses match your filters." : "No expenses yet. Add your first one."}</li>`;

    $("bars").innerHTML = sum.by_category.length
      ? "<h2>By category</h2>" + sum.by_category.map(c => `
        <div class="bar-row">
          <div><span>${c.category}</span><span>${money(c.total)} (${Math.round(c.total / sum.total * 100)}%)</span></div>
          <div class="track"><div class="fill" style="width:${c.total / sum.total * 100}%;background:${colorOf(c.category)}"></div></div>
        </div>`).join("")
      : "";
  } catch (err) {
    $("error").textContent = "Can’t reach the server. Is app.py running?";
  }
}

// Add a new expense, or save changes to the one being edited
async function submitForm() {
  const body = JSON.stringify({
    description: $("desc").value,
    amount: $("amount").value,
    category: $("category").value,
    date: $("date").value
  });
  try {
    if (editingId) await api("/api/expenses/" + editingId, { method: "PUT", body });
    else await api("/api/expenses", { method: "POST", body });
    $("error").textContent = "";
    exitEdit();
    $("desc").focus();
    render();
  } catch (err) {
    $("error").textContent = err.message;
  }
}

function startEdit(id) {
  const e = shown.find(x => x.id === id);
  if (!e) return;
  editingId = id;
  $("desc").value = e.description;
  $("amount").value = e.amount;
  $("category").value = e.category;
  $("date").value = e.date;
  $("formTitle").textContent = "Edit expense";
  $("addBtn").textContent = "Save changes";
  $("cancelBtn").hidden = false;
  $("error").textContent = "";
  $("desc").scrollIntoView({ behavior: "smooth", block: "center" });
  $("desc").focus();
}

function exitEdit() {
  editingId = null;
  $("desc").value = ""; $("amount").value = ""; $("date").value = todayStr();
  $("formTitle").textContent = "Add an expense";
  $("addBtn").textContent = "Add expense";
  $("cancelBtn").hidden = true;
}

async function deleteExpense(id) {
  await api("/api/expenses/" + id, { method: "DELETE" });
  if (editingId === id) exitEdit();
  render();
}

async function clearAll() {
  if (confirm("Delete all expenses? This can’t be undone.")) {
    await api("/api/expenses", { method: "DELETE" });
    exitEdit();
    render();
  }
}

function resetFilters() {
  $("search").value = ""; $("filter").value = "All"; $("from").value = ""; $("to").value = "";
  render();
}

// Wait until the person stops typing before searching (saves requests)
let timer;
function debouncedRender() { clearTimeout(timer); timer = setTimeout(render, 250); }

// Setup
$("category").innerHTML = CATEGORIES.map(c => `<option>${c.name}</option>`).join("");
$("filter").innerHTML = '<option value="All">All categories</option>' +
  CATEGORIES.map(c => `<option>${c.name}</option>`).join("");
$("date").value = todayStr();

$("addBtn").addEventListener("click", submitForm);
$("cancelBtn").addEventListener("click", exitEdit);
$("clearBtn").addEventListener("click", clearAll);
$("resetBtn").addEventListener("click", resetFilters);
$("search").addEventListener("input", debouncedRender);
["filter", "from", "to"].forEach(id => $(id).addEventListener("change", render));
$("amount").addEventListener("keydown", e => { if (e.key === "Enter") submitForm(); });
$("list").addEventListener("click", e => {
  const del = e.target.closest("[data-id]");
  if (del) return deleteExpense(Number(del.dataset.id));
  const ed = e.target.closest("[data-edit]");
  if (ed) startEdit(Number(ed.dataset.edit));
});
$("themeBtn").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark"
                                  : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
});

render();
