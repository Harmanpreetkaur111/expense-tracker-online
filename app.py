"""
BACKEND (v3): Flask server with user accounts.
Database: PostgreSQL when DATABASE_URL is set (online, e.g. Neon),
          otherwise a local SQLite file (so it still runs on your laptop with no setup).

Local:   python app.py            -> http://127.0.0.1:5000
Online:  gunicorn app:app         (Render runs this command)
Online also needs an environment variable SECRET_KEY (a long random string).
"""
import os
import re
import secrets
import sqlite3
from datetime import date
from functools import wraps

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Other"]

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_PG = bool(DATABASE_URL)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db")

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row

app = Flask(__name__)
# SECRET_KEY signs the login cookie. Online you MUST set your own in Render.
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or ("local-dev-key" if not USE_PG else secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,    # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE="Lax",   # blocks most cross-site request tricks
    SESSION_COOKIE_SECURE=USE_PG,    # online (https) the cookie is only sent over https
)


# ---------- DATABASE ----------
def connect():
    if USE_PG:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def run(db, sql, params=()):
    """Run a query. SQLite uses ? placeholders, Postgres uses %s."""
    if USE_PG:
        sql = sql.replace("?", "%s")
    return db.execute(sql, params)


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    id_col = "SERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    amount_type = "DOUBLE PRECISION" if USE_PG else "REAL"
    db = connect()
    run(db, f"""CREATE TABLE IF NOT EXISTS users (
                    id            {id_col},
                    username      TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL
                )""")
    run(db, f"""CREATE TABLE IF NOT EXISTS expenses (
                    id          {id_col},
                    description TEXT NOT NULL,
                    amount      {amount_type} NOT NULL CHECK (amount > 0),
                    category    TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    user_id     INTEGER
                )""")
    # Upgrade an older table (from v1/v2) that has no user_id column yet
    if USE_PG:
        run(db, "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS user_id INTEGER")
    else:
        cols = [r[1] for r in run(db, "PRAGMA table_info(expenses)").fetchall()]
        if "user_id" not in cols:
            run(db, "ALTER TABLE expenses ADD COLUMN user_id INTEGER")
    run(db, "CREATE INDEX IF NOT EXISTS idx_expenses_user ON expenses (user_id, date)")
    db.commit()
    db.close()


# ---------- LOGIN HELPERS ----------
def login_required(view):
    """Put this under a route to make it private."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify(error="Please log in."), 401
        return view(*args, **kwargs)
    return wrapper


def start_session(user_id, username):
    session.clear()
    session["user_id"] = user_id
    session["username"] = username
    session.permanent = True


# ---------- PAGE ----------
@app.route("/")
def index():
    return render_template("index.html")


# ---------- AUTH API ----------
@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    if not re.fullmatch(r"[a-z0-9_]{3,30}", username):
        return jsonify(error="Username must be 3 to 30 letters, numbers or underscores."), 400
    if len(password) < 6:
        return jsonify(error="Password must be at least 6 characters."), 400

    db = get_db()
    if run(db, "SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify(error="That username is taken."), 409

    is_first_user = run(db, "SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
    sql = "INSERT INTO users (username, password_hash) VALUES (?, ?)"
    values = (username, generate_password_hash(password))   # never store the real password
    if USE_PG:
        user_id = run(db, sql + " RETURNING id", values).fetchone()["id"]
    else:
        user_id = run(db, sql, values).lastrowid
    if is_first_user:
        # Expenses saved before accounts existed go to the first person who signs up
        run(db, "UPDATE expenses SET user_id = ? WHERE user_id IS NULL", (user_id,))
    db.commit()
    start_session(user_id, username)
    return jsonify(username=username), 201


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    user = run(get_db(), "SELECT id, password_hash FROM users WHERE username = ?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Wrong username or password."), 401   # same message for both cases
    start_session(user["id"], username)
    return jsonify(username=username)


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    return jsonify(username=session.get("username"))


# ---------- EXPENSES API (all private to the logged-in user) ----------
def parse_expense(data):
    """Validate the JSON sent by the browser. Returns (values, error_response)."""
    description = str(data.get("description", "")).strip()
    category = data.get("category")
    expense_date = data.get("date") or date.today().isoformat()
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        amount = 0
    if not description:
        return None, (jsonify(error="Enter a description."), 400)
    if amount <= 0:
        return None, (jsonify(error="Enter an amount greater than 0."), 400)
    if category not in CATEGORIES:
        return None, (jsonify(error="Choose a valid category."), 400)
    return (description[:60], amount, category, expense_date), None


@app.get("/api/expenses")
@login_required
def list_expenses():
    """Optional filters: ?category=Food&q=bus&start=2026-11-01&end=2026-11-30"""
    category = request.args.get("category", "All")
    q = request.args.get("q", "").strip()
    start = request.args.get("start", "")
    end = request.args.get("end", "")

    where, params = ["user_id = ?"], [session["user_id"]]   # only MY expenses
    if category != "All":
        where.append("category = ?")
        params.append(category)
    if q:
        where.append("LOWER(description) LIKE ?")
        params.append("%" + q.lower() + "%")
    if start:
        where.append("date >= ?")
        params.append(start)
    if end:
        where.append("date <= ?")
        params.append(end)

    sql = "SELECT * FROM expenses WHERE " + " AND ".join(where) + " ORDER BY date DESC, id DESC"
    rows = run(get_db(), sql, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/expenses")
@login_required
def add_expense():
    values, error = parse_expense(request.get_json(silent=True) or {})
    if error:
        return error
    db = get_db()
    sql = "INSERT INTO expenses (description, amount, category, date, user_id) VALUES (?, ?, ?, ?, ?)"
    params = (*values, session["user_id"])
    if USE_PG:
        new_id = run(db, sql + " RETURNING id", params).fetchone()["id"]
    else:
        new_id = run(db, sql, params).lastrowid
    db.commit()
    return jsonify(id=new_id), 201


@app.put("/api/expenses/<int:expense_id>")
@login_required
def update_expense(expense_id):
    values, error = parse_expense(request.get_json(silent=True) or {})
    if error:
        return error
    db = get_db()
    cur = run(
        db,
        "UPDATE expenses SET description = ?, amount = ?, category = ?, date = ? WHERE id = ? AND user_id = ?",
        (*values, expense_id, session["user_id"]),
    )
    db.commit()
    if cur.rowcount == 0:
        return jsonify(error="Expense not found."), 404
    return jsonify(ok=True)


@app.delete("/api/expenses/<int:expense_id>")
@login_required
def delete_expense(expense_id):
    db = get_db()
    run(db, "DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, session["user_id"]))
    db.commit()
    return jsonify(ok=True)


@app.delete("/api/expenses")
@login_required
def clear_expenses():
    db = get_db()
    run(db, "DELETE FROM expenses WHERE user_id = ?", (session["user_id"],))
    db.commit()
    return jsonify(ok=True)


@app.get("/api/summary")
@login_required
def summary():
    db = get_db()
    uid = session["user_id"]
    month = date.today().strftime("%Y-%m")
    row = run(db, "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS n FROM expenses WHERE user_id = ?", (uid,)).fetchone()
    month_total = run(
        db,
        "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id = ? AND substr(date, 1, 7) = ?",
        (uid, month),
    ).fetchone()["total"]
    by_category = run(
        db,
        "SELECT category, SUM(amount) AS total FROM expenses WHERE user_id = ? GROUP BY category ORDER BY total DESC",
        (uid,),
    ).fetchall()
    return jsonify(
        total=row["total"],
        month_total=month_total,
        count=row["n"],
        by_category=[dict(r) for r in by_category],
    )


# Create/upgrade tables on startup (works under gunicorn too)
init_db()

if __name__ == "__main__":
    app.run(debug=True)
