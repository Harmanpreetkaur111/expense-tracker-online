# Expense Tracker (Full-Stack, deployable)

Frontend: HTML/CSS/JS | Backend: Flask | Database: PostgreSQL online, SQLite locally

## Run locally (no database setup needed)
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    python app.py

## Deploy: Neon (database) + Render (hosting)
1. Neon: create a project, copy the connection string.
2. Push this folder to GitHub.
3. Render: New > Web Service > pick the repo.
   Build command: pip install -r requirements.txt
   Start command: gunicorn app:app
   Environment variable: DATABASE_URL = your Neon connection string
