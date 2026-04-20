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

def parse_reserve_price(reserve_price_str):
    # reserve_price stored as '$50' in db, cast string into a float.
    try:
        return float(reserve_price_str.replace('$', '').strip())
    except (ValueError, AttributeError):
        return 0.0

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



@app.route('/bid/<int:listing_id>', methods=['GET', 'POST'])
def bid_page(listing_id):
    if "email" not in session:
        return render_template("login.html", error="Please log in first.")



    bidder_email = session["email"]
    feedback = None
    bid_accepted = False

    try:
        with get_connection() as con:
            listing = con.execute("""
                SELECT listing_ID, auction_title, product_name, seller_email,
                       reserve_price, max_bids, status
                FROM Auction_Listing
                WHERE listing_ID = ?
            """, (listing_id,)).fetchone()

            if not listing:
                return render_template("product.html", error="Listing not found.", product=None)

            bid_count = con.execute(
                "SELECT COUNT(*) FROM Bid WHERE listing_ID = ?", (listing_id,)
            ).fetchone()[0]

            highest_bid_row = con.execute(
                "SELECT MAX(bid_price) FROM Bid WHERE listing_ID = ?", (listing_id,)
            ).fetchone()
            highest_bid = highest_bid_row[0] if highest_bid_row[0] is not None else 0

            last_bidder_row = con.execute(
                "SELECT bidder_email FROM Bid WHERE listing_ID = ? ORDER BY bid_ID DESC LIMIT 1",
                (listing_id,)
            ).fetchone()
            last_bidder = last_bidder_row["bidder_email"] if last_bidder_row else None

            remaining_bids = listing["max_bids"] - bid_count
            reserve_price = parse_reserve_price(listing["reserve_price"])


            # validate all conditions
            pre_errors = []
            if listing["status"] != 1:
                pre_errors.append("This auction is not active.")
            if listing["seller_email"].strip().lower() == bidder_email.strip().lower():
                pre_errors.append("You cannot bid on your own listing.")
            if remaining_bids <= 0:
                pre_errors.append("This auction has ended (no bids remaining).")


            if request.method == 'POST' and not pre_errors:
                input_bid_str = request.form.get('bid_amount', '').strip()

                # reject if current bid belongs to bidder
                if last_bidder and last_bidder.strip().lower() == bidder_email.strip().lower():
                    feedback = ("rejected", "You placed the last bid. Wait for another bidder before bidding again.")
                elif not input_bid_str:
                    feedback = ("rejected", "Please enter a bid amount.")

                else:
                    try:
                        input_bid = float(input_bid_str)
                    except ValueError:
                        feedback = ("rejected", "Invalid bid amount.")
                        input_bid = None

                    if feedback is None:
                        min_required = highest_bid + 1
                        if input_bid < min_required:
                            feedback = ("rejected", f"Bid too low. Must be at least ${min_required:.2f} (current highest: ${highest_bid:.2f}).")
                        else:
                            # insert bid into db if all checks passed
                            con.execute("""
                                INSERT INTO Bid (seller_email, listing_ID, bidder_email, bid_price)
                                VALUES (?, ?, ?, ?)
                            """, (listing["seller_email"], listing_id, bidder_email, int(input_bid)))
                            con.commit()
                            bid_accepted = True
                            bid_count += 1
                            highest_bid = int(input_bid)
                            remaining_bids = listing["max_bids"] - bid_count
                            last_bidder = bidder_email

                            if bid_count >= listing["max_bids"]:
                                if highest_bid >= reserve_price:
                                    con.execute(
                                        "UPDATE Auction_Listing SET status = 2 WHERE listing_ID = ?",
                                        (listing_id,)
                                    )
                                    con.commit()

                                    feedback = ("winner",
                                        f"Auction ended! You won with a bid of ${highest_bid:.2f}. "
                                        f"Please complete payment.")
                                else:
                                    # highest bid did not meet reserve
                                    con.execute(
                                        "UPDATE Auction_Listing SET status = 3 WHERE listing_ID = ?",
                                        (listing_id,)
                                    )
                                    con.commit()

                                    feedback = ("ended_no_sale",
                                        "Auction ended. The highest bid did not meet the reserve price. "
                                        "The seller will decide whether to accept or cancel.")
                            else:
                                feedback = ("accepted", f"Bid of ${highest_bid:.2f} placed successfully! {remaining_bids} bid(s) remaining.")


            listing = con.execute("""
                SELECT listing_ID, auction_title, product_name, seller_email,
                       reserve_price, max_bids, status
                FROM Auction_Listing
                WHERE listing_ID = ?
            """, (listing_id,)).fetchone()

    except sql.Error as e:
        print("DB error in bid_page:", e)
        return render_template("bid.html", error="Database error.", listing=None)

    return render_template(
        "bid.html",
        listing=listing,
        bid_count=bid_count,
        highest_bid=highest_bid if highest_bid else 0,
        remaining_bids=remaining_bids,
        last_bidder=last_bidder,
        bidder_email=bidder_email,
        pre_errors=pre_errors,
        feedback=feedback,
        bid_accepted=bid_accepted,
    )

@app.route('/logout')
def logout():
    session.clear()
    return render_template("login.html", error="Logged out successfully.")

if __name__ == "__main__":
    app.run()


