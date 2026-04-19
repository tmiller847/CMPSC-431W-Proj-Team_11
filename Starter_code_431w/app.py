import os
from pathlib import Path
import sqlite3 as sql
import hashlib

from flask import Flask, render_template, request, session

app = Flask(__name__)
app.secret_key = "phase2-demo-key"

host = 'http://127.0.0.1:5000/'
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DEFAULT_DATASET_DB_PATH = (
    PROJECT_DIR / "NittanyAuctionDataset_v1" / "NittanyAuction.db"
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
                            roles.append("Bidder")
                        if helpdesk:
                            roles.append("HelpDesk")


                        if len(roles) == 1:
                            session["role"] = roles[0]
                            session["email"] = email
                            session["roles"] = roles
                            if roles[0] == "Seller":
                                return render_template("seller_home.html", email=email)
                            elif roles[0] == "Bidder":
                                return render_template("bidder_home.html", email=email)
                            elif roles[0] == "HelpDesk":
                                return render_template("helpdesk_home.html", email=email)

                        elif len(roles) > 1:
                            session["email"] = email
                            session["roles"] = roles
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
    email = session.get("email")
    roles = session.get("roles", [])
    role = request.form.get("role", "").strip()


    if not email or not role:
        return render_template("login.html", error="Role selection failed.")
    if role not in roles:
        return render_template("login.html", error="Invalid role selected.")
    session["role"] = role
    if role == "Seller":
        return render_template("seller_home.html", email=email)
    elif role == "Bidder":
        return render_template("bidder_home.html", email=email)
    elif role == "HelpDesk":
        return render_template("helpdesk_home.html", email=email)

    return render_template("login.html", error="Invalid role selected.")


@app.route('/search', methods=['GET'])
def search():
    error = None
    results = []

    keyword = request.args.get('keyword', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()

    try:
        with get_connection() as connection:
            query = """
                SELECT Listing_ID, Auction_Title, Product_Name, Product_Description,
                       Category, Seller_Email, Reserve_Price, Status
                FROM Auction_Listing
                WHERE Status = 1
            """
            params = []

            if keyword:
                query += """
                    AND (
                        LOWER(Auction_Title) LIKE ?
                        OR LOWER(Product_Description) LIKE ?
                        OR LOWER(Category) LIKE ?
                        OR LOWER(Seller_Email) LIKE ?
                    )
                """
                like_keyword = "%" + keyword.lower() + "%"
                params.extend([like_keyword, like_keyword, like_keyword, like_keyword])

            if min_price:
                query += " AND CAST(SUBSTR(Reserve_Price, 2) AS REAL) >= ?"
                params.append(min_price)

            if max_price:
                query += " AND CAST(SUBSTR(Reserve_Price, 2) AS REAL) <= ?"
                params.append(max_price)

            results = connection.execute(query, params).fetchall()

    except sql.Error as e:
        print("Database error:", e)
        error = "Database error while searching."

    return render_template(
        "search.html",
        results=results,
        error=error,
        keyword=keyword,
        min_price=min_price,
        max_price=max_price
    )

@app.route('/product/<int:listing_id>')
def product_page(listing_id):
    if "email" not in session:
        return render_template("login.html", error="Please log in first.")


    error = None
    product = None
    bid_count = 0
    highest_bid = None
    remaining_bids = 0

    try:
        with get_connection() as connection:
            product = connection.execute("""
                SELECT listing_ID, auction_title, product_name, product_description,
                       category, seller_email, quantity, reserve_price, max_bids, status
                FROM Auction_Listing
                WHERE listing_ID = ?
            """, (listing_id,)).fetchone()

            if not product:
                return render_template("product.html", error="Product not found.", product=None)

            bid_count_row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM Bid
                WHERE listing_ID = ?
            """, (listing_id,)).fetchone()

            highest_bid_row = connection.execute(
                """
                SELECT MAX(bid_price) AS highest_bid
                FROM Bid
                WHERE listing_ID = ?
                """, (listing_id,)).fetchone()

            bid_count = bid_count_row["count"] if bid_count_row else 0
            highest_bid = highest_bid_row["highest_bid"] if highest_bid_row else None
            remaining_bids = product["max_bids"] - bid_count

    except sql.Error as e:
        print("Database error:", e)
        error = "Database error while loading product."

    return render_template(
        "product.html",
        product=product,
        bid_count=bid_count,
        highest_bid=highest_bid,
        remaining_bids=remaining_bids,
        error=error
    )
@app.route('/logout')
def logout():
    session.clear()
    return render_template("login.html", error="Logged out successfully.")

if __name__ == "__main__":
    app.run()


