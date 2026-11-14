// FRONTEND: talks to the Flask backend with fetch().
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

// Small helper for talking to the API
async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

async function render() {
  try {
    const f = $("filter").value;
    const [list, sum] = await Promise.all([
      api("/api/expenses?category=" + encodeURIComponent(f)),
      api("/api/summary")
    ]);

    $("totalAll").textContent = money(sum.total);
    $("totalMonth").textContent = money(sum.month_total);
    $("count").textContent = sum.count;

    $("list").innerHTML = list.length
      ? list.map(e => `
        <li class="item">
          <span class="dot" style="background:${colorOf(e.category)}"></span>
          <div class="info"><b>${escapeHtml(e.description)}</b><small>${e.category} · ${e.date}</small></div>
          <span class="amt">${money(e.amount)}</span>
          <button class="del" data-id="${e.id}" aria-label="Delete ${escapeHtml(e.description)}">✕</button>
        </li>`).join("")
      : `<li class="empty">${sum.count ? "No expenses in this category." : "No expenses yet. Add your first one."}</li>`;

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

async function addExpense() {
  try {
    await api("/api/expenses", {
      method: "POST",
      body: JSON.stringify({
        description: $("desc").value,
        amount: $("amount").value,
        category: $("category").value,
        date: $("date").value
      })
    });
    $("error").textContent = "";
    $("desc").value = ""; $("amount").value = "";
    $("desc").focus();
    render();
  } catch (err) {
    $("error").textContent = err.message;   // message comes from the backend
  }
}

async function deleteExpense(id) {
  await api("/api/expenses/" + id, { method: "DELETE" });
  render();
}

async function clearAll() {
  if (confirm("Delete all expenses? This can’t be undone.")) {
    await api("/api/expenses", { method: "DELETE" });
    render();
  }
}

// Setup
$("category").innerHTML = CATEGORIES.map(c => `<option>${c.name}</option>`).join("");
$("filter").innerHTML = '<option value="All">All categories</option>' +
  CATEGORIES.map(c => `<option>${c.name}</option>`).join("");
$("date").value = todayStr();

$("addBtn").addEventListener("click", addExpense);
$("clearBtn").addEventListener("click", clearAll);
$("filter").addEventListener("change", render);
$("amount").addEventListener("keydown", e => { if (e.key === "Enter") addExpense(); });
$("list").addEventListener("click", e => {
  const btn = e.target.closest(".del");
  if (btn) deleteExpense(Number(btn.dataset.id));
});
$("themeBtn").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark"
                                  : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
});

render();
