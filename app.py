"""
BACKEND: Flask server.
Database: PostgreSQL when DATABASE_URL is set (online, e.g. Neon),
          otherwise a local SQLite file (so it still runs on your laptop with no setup).

Local:   python app.py            -> http://127.0.0.1:5000
Online:  gunicorn app:app         (Render runs this command)
"""
import os
import sqlite3
from datetime import date

from flask import Flask, g, jsonify, render_template, request

app = Flask(__name__)
CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Other"]

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_PG = bool(DATABASE_URL)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db")

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row


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
    run(db, f"""CREATE TABLE IF NOT EXISTS expenses (
                    id          {id_col},
                    description TEXT NOT NULL,
                    amount      {amount_type} NOT NULL CHECK (amount > 0),
                    category    TEXT NOT NULL,
                    date        TEXT NOT NULL
                )""")
    db.commit()
    db.close()


# ---------- PAGE ----------
@app.route("/")
def index():
    return render_template("index.html")


# ---------- API (JSON) ----------
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
def list_expenses():
    """Optional filters: ?category=Food&q=bus&start=2026-11-01&end=2026-11-30"""
    category = request.args.get("category", "All")
    q = request.args.get("q", "").strip()
    start = request.args.get("start", "")
    end = request.args.get("end", "")

    where, params = [], []
    if category != "All":
        where.append("category = ?")
        params.append(category)
    if q:
        where.append("LOWER(description) LIKE ?")
        params.append("%" + q.lower() + "%")
    if start:
        where.append("date >= ?")      # dates are ISO text, so text comparison works
        params.append(start)
    if end:
        where.append("date <= ?")
        params.append(end)

    sql = "SELECT * FROM expenses"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date DESC, id DESC"
    rows = run(get_db(), sql, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/expenses")
def add_expense():
    values, error = parse_expense(request.get_json(silent=True) or {})
    if error:
        return error
    db = get_db()
    sql = "INSERT INTO expenses (description, amount, category, date) VALUES (?, ?, ?, ?)"
    if USE_PG:
        new_id = run(db, sql + " RETURNING id", values).fetchone()["id"]
    else:
        new_id = run(db, sql, values).lastrowid
    db.commit()
    return jsonify(id=new_id), 201


@app.put("/api/expenses/<int:expense_id>")
def update_expense(expense_id):
    """NEW: edit an existing expense."""
    values, error = parse_expense(request.get_json(silent=True) or {})
    if error:
        return error
    db = get_db()
    cur = run(
        db,
        "UPDATE expenses SET description = ?, amount = ?, category = ?, date = ? WHERE id = ?",
        (*values, expense_id),
    )
    db.commit()
    if cur.rowcount == 0:
        return jsonify(error="Expense not found."), 404
    return jsonify(ok=True)


@app.delete("/api/expenses/<int:expense_id>")
def delete_expense(expense_id):
    db = get_db()
    run(db, "DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()
    return jsonify(ok=True)


@app.delete("/api/expenses")
def clear_expenses():
    db = get_db()
    run(db, "DELETE FROM expenses")
    db.commit()
    return jsonify(ok=True)


@app.get("/api/summary")
def summary():
    db = get_db()
    month = date.today().strftime("%Y-%m")
    row = run(db, "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS n FROM expenses").fetchone()
    month_total = run(
        db,
        "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE substr(date, 1, 7) = ?",
        (month,),
    ).fetchone()["total"]
    by_category = run(
        db,
        "SELECT category, SUM(amount) AS total FROM expenses GROUP BY category ORDER BY total DESC",
    ).fetchall()
    return jsonify(
        total=row["total"],
        month_total=month_total,
        count=row["n"],
        by_category=[dict(r) for r in by_category],
    )


# Create the table on startup (works under gunicorn too, not only `python app.py`)
init_db()

if __name__ == "__main__":
    app.run(debug=True)
