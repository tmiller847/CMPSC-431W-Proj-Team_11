import os
from pathlib import Path
import sqlite3 as sql

from flask import Flask, render_template, request

app = Flask(__name__)

host = 'http://127.0.0.1:5000/'
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent.parent
DEFAULT_DATASET_DB_PATH = (
    PROJECT_DIR / "NittanyAuctionDataset_v1" / "NittanyAuctionDataset_v1" / "NittanyAuction.db"
)
DB_PATH = Path(os.getenv("NITTANY_AUCTION_DB_PATH", str(DEFAULT_DATASET_DB_PATH)))
SCHEMA_PATH = BASE_DIR.parent.parent / "backup console.txt"


def get_connection():
    connection = sql.connect(DB_PATH)
    connection.row_factory = sql.Row
    return connection


def initialize_schema_if_needed(connection):
    user_table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='User'"
    ).fetchone()
    if user_table:
        return

    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"Schema file not found at {SCHEMA_PATH}. Cannot initialize database."
        )

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    connection.commit()


@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        normalized_email = email.lower()
        password = request.form.get('password', '').strip()
        if not email or not password:
            error = 'Please enter both email and password.'
        else:
            try:
                with get_connection() as connection:
                    initialize_schema_if_needed(connection)
                    user = connection.execute(
                        "SELECT email FROM User WHERE LOWER(email) = ? AND password = ?",
                        (normalized_email, password),
                    ).fetchone()
            except (sql.Error, FileNotFoundError):
                error = "Database error. Please verify schema/data setup."
            else:
                if user:
                    return render_template('role_home.html', email=user["email"])
                error = "Invalid email or password."
    return render_template('login.html', error=error)



if __name__ == "__main__":
    app.run()


