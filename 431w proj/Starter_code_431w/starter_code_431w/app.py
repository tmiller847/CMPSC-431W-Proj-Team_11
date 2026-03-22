import os
from pathlib import Path
import sqlite3 as sql
import hashlib

from flask import Flask, render_template, request, session

app = Flask(__name__)
app.secret_key = "phase2-demo-key"

host = 'http://127.0.0.1:5000/'
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent.parent
DEFAULT_DATASET_DB_PATH = (
    PROJECT_DIR / "NittanyAuctionDataset_v1" / "NittanyAuctionDataset_v1" / "NittanyAuction.db"
)
DB_PATH = Path(os.getenv("NITTANY_AUCTION_DB_PATH", str(DEFAULT_DATASET_DB_PATH)))
SCHEMA_PATH = BASE_DIR.parent.parent / "backup console.txt"

# When users are stored, their passwords are hashed using sha-256 and saved in the User table.
# During login, the entered password is hashed again and compared with the stored hash
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

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
        normalized_email = email.strip().lower()
        password = request.form.get('password', '').strip()

        if not email or not password:
            error = 'Please enter both email and password.'
        else:
            try:
                with get_connection() as connection:
                    initialize_schema_if_needed(connection)
                    hashed_pw = hash_password(password)

                    user = connection.execute(
                        "SELECT email FROM User WHERE LOWER(TRIM(email)) = ? AND password = ?",
                        (normalized_email, hashed_pw),
                    ).fetchone()

                    if user:
                        email = user["email"]
                        roles = []

                        seller = connection.execute(
                            "SELECT email FROM Seller WHERE LOWER(TRIM(email)) = ?",
                            (normalized_email,)
                        ).fetchone()

                        bidder = connection.execute(
                            "SELECT email FROM Bidder WHERE LOWER(TRIM(email)) = ?",
                            (normalized_email,)
                        ).fetchone()

                        helpdesk = connection.execute(
                            "SELECT email FROM Helpdesk WHERE LOWER(TRIM(email)) = ?",
                            (normalized_email,)
                        ).fetchone()

                        if seller:
                            roles.append("Seller")
                        if bidder:
                            roles.append("Buyer")
                        if helpdesk:
                            roles.append("HelpDesk")

                        if len(roles) == 1:
                            if roles[0] == "Seller":
                                return render_template("seller_home.html", email=email)
                            elif roles[0] == "Buyer":
                                return render_template("buyer_home.html", email=email)
                            elif roles[0] == "HelpDesk":
                                return render_template("helpdesk_home.html", email=email)

                        elif len(roles) > 1:
                            session["email"] = email
                            return render_template("select_role.html", email=email, roles=roles)

                        else:
                            error = "User authenticated, but role was not found."
                    else:
                        error = "Invalid email or password."

            except (sql.Error, FileNotFoundError) as e:
                print("Database error:", e)
                error = "Database error. Please verify schema/data setup."

    return render_template('login.html', error=error)

@app.route('/choose_role', methods=['POST'])
def choose_role():
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "").strip()

    if not email or not role:
        return render_template("login.html", error="Role selection failed.")

    if role == "Seller":
        return render_template("seller_home.html", email=email)
    elif role == "Buyer":
        return render_template("buyer_home.html", email=email)
    elif role == "HelpDesk":
        return render_template("helpdesk_home.html", email=email)

    return render_template("login.html", error="Invalid role selected.")

if __name__ == "__main__":
    app.run()


