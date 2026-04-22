import os
from pathlib import Path
import sqlite3 as sql
import hashlib
from uuid import uuid4

from flask import Flask, render_template, request, session, redirect, url_for

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


def split_name(full_name):
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def parse_street(street):
    street = street.strip()
    if not street:
        return None, None
    parts = street.split(maxsplit=1)
    if parts[0].isdigit():
        street_num = int(parts[0])
        street_name = parts[1] if len(parts) > 1 else ""
    else:
        street_num = None
        street_name = street
    return street_num, street_name


def listing_status_label(status):
    mapping = {
        0: "Inactive",
        1: "Active",
        2: "Sold",
        3: "Awaiting Decision",
    }
    return mapping.get(status, "Unknown")


def request_status_label(status):
    mapping = {
        0: "Pending",
        1: "In Review",
        2: "Approved",
        3: "Rejected",
    }
    return mapping.get(status, "Unknown")


def build_profile_data(connection, email):
    profile = {
        "email": email,
        "name": "",
        "phone": "",
        "street": "",
        "city": "",
        "state": "",
        "zipcode": "",
        "first_name": "",
        "last_name": "",
        "age": "",
        "major": "",
        "bank_routing_number": "",
        "bank_account_number": "",
        "balance": "",
        "helpdesk_position": "",
    }
    roles = []

    bidder = connection.execute(
        """
        SELECT email, first_name, last_name, age, major, home_address_id
        FROM Bidder
        WHERE LOWER(TRIM(email)) = ?
        """,
        (email.strip().lower(),),
    ).fetchone()
    if bidder:
        roles.append("Bidder")
        profile["first_name"] = bidder["first_name"] or ""
        profile["last_name"] = bidder["last_name"] or ""
        profile["name"] = " ".join([profile["first_name"], profile["last_name"]]).strip()
        profile["age"] = "" if bidder["age"] is None else str(bidder["age"])
        profile["major"] = bidder["major"] or ""

        if bidder["home_address_id"]:
            address = connection.execute(
                """
                SELECT a.street_num, a.street_name, a.zipcode, z.city, z.state
                FROM Address a
                LEFT JOIN Zipcode z ON z.zipcode = a.zipcode
                WHERE a.address_id = ?
                """,
                (bidder["home_address_id"],),
            ).fetchone()
            if address:
                street_num = "" if address["street_num"] is None else str(address["street_num"])
                street_name = address["street_name"] or ""
                profile["street"] = " ".join([street_num, street_name]).strip()
                profile["zipcode"] = "" if address["zipcode"] is None else str(address["zipcode"])
                profile["city"] = address["city"] or ""
                profile["state"] = address["state"] or ""

    seller = connection.execute(
        """
        SELECT email, bank_routing_number, bank_account_number, balance
        FROM Seller
        WHERE LOWER(TRIM(email)) = ?
        """,
        (email.strip().lower(),),
    ).fetchone()
    if seller:
        roles.append("Seller")
        profile["bank_routing_number"] = seller["bank_routing_number"] or ""
        profile["bank_account_number"] = (
            "" if seller["bank_account_number"] is None else str(seller["bank_account_number"])
        )
        profile["balance"] = "" if seller["balance"] is None else str(seller["balance"])

    helpdesk = connection.execute(
        """
        SELECT email, position
        FROM Helpdesk
        WHERE LOWER(TRIM(email)) = ?
        """,
        (email.strip().lower(),),
    ).fetchone()
    if helpdesk:
        roles.append("HelpDesk")
        profile["helpdesk_position"] = helpdesk["position"] or ""

    local_vendor = connection.execute(
        """
        SELECT business_name, business_address_id, customer_service_phone_number
        FROM Local_Vendor
        WHERE LOWER(TRIM(email)) = ?
        """,
        (email.strip().lower(),),
    ).fetchone()
    if local_vendor and local_vendor["customer_service_phone_number"]:
        profile["name"] = local_vendor["business_name"]
        profile["phone"] = local_vendor["customer_service_phone_number"]

        if local_vendor["business_address_id"]:
            address = connection.execute(
                """
                SELECT a.street_num, a.street_name, a.zipcode, z.city, z.state
                FROM Address a
                LEFT JOIN Zipcode z ON z.zipcode = a.zipcode
                WHERE a.address_id = ?
                """,
                (local_vendor["business_address_id"],),
            ).fetchone()
            if address:
                street_num = "" if address["street_num"] is None else str(address["street_num"])
                street_name = address["street_name"] or ""
                profile["street"] = " ".join([street_num, street_name]).strip()
                profile["zipcode"] = "" if address["zipcode"] is None else str(address["zipcode"])
                profile["city"] = address["city"] or ""
                profile["state"] = address["state"] or ""

    return profile, roles

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
    temp_error = session.pop('login_error', None)
    error = None
    if error is None: error = temp_error
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
                                return redirect(url_for("seller_home"))
                            elif roles[0] == "Bidder":
                                return redirect(url_for("bidder_home"))
                            elif roles[0] == "HelpDesk":
                                return redirect(url_for("helpdesk_home"))

                        elif len(roles) > 1:
                            session["email"] = email
                            session["roles"] = roles
                            return redirect(url_for("choose_role_page"))

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
        session['login_error'] = 'Role selection failed.'
        return redirect(url_for("login"))
    if role not in roles:
        session['login_error'] = 'Invalid role selected.'
        return redirect(url_for("login"))
    session["role"] = role
    if role == "Seller":
        return render_template("seller_home.html", email=email)
    elif role == "Bidder":
        return render_template("bidder_home.html", email=email)
    elif role == "HelpDesk":
        return render_template("helpdesk_home.html", email=email)

    session['login_error'] = 'Invalid role selected.'
    return redirect(url_for("login"))

@app.route('/choose_role', methods=['GET'])
def choose_role_page():
    if "email" not in session:
        return redirect(url_for("login"))

    roles = session.get("roles", [])
    return render_template("select_role.html", roles=roles)

@app.route('/bidder_home')
def bidder_home():
    if "email" not in session or session.get("role") != "Bidder":
        session['login_error'] = 'You must be logged in to access this feature. Please log in.'
        return redirect(url_for("login"))

    email = session["email"]
    auctions = []

    try:
        with get_connection() as con:
            auctions = con.execute("""
                SELECT al.listing_ID, al.auction_title, al.seller_email,
                       al.status, al.max_bids,
                       COUNT(b.bid_ID) AS bid_count,
                       MAX(b.bid_price) AS highest_bid,
                       MAX(CASE WHEN LOWER(TRIM(b.bidder_email)) = LOWER(TRIM(?))
                                THEN b.bid_price END) AS my_highest_bid
                FROM Auction_Listing al
                JOIN Bid b ON al.listing_ID = b.listing_ID
                WHERE LOWER(TRIM(b.bidder_email)) = LOWER(TRIM(?))
                GROUP BY al.listing_ID
                ORDER BY al.status ASC, al.listing_ID DESC
            """, (email, email)).fetchall()
    except sql.Error as e:
        print("DB error in bidder_home:", e)

    return render_template("bidder_home.html", email=email, auctions=auctions)


@app.route('/seller_home')
def seller_home():
    if "email" not in session or session.get("role") != "Seller":
        session['login_error'] = 'You must be a Seller to access this feature. Please log in.'
        return redirect(url_for("login"))
    return render_template("seller_home.html", email=session["email"])


@app.route('/helpdesk_home')
def helpdesk_home():
    if "email" not in session or session.get("role") != "HelpDesk":
        session['login_error'] = 'You must be a Helpdesk Member to access this feature. Please log in.'
        return redirect(url_for("login"))
    return render_template("helpdesk_home.html", email=session["email"])
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
                clean_min = min_price.replace("$", "").replace(",", "").strip()
                query += " AND CAST(REPLACE(SUBSTR(Reserve_Price, 2), ',', '') AS REAL) >= ?"
                params.append(clean_min)

            if max_price:
                clean_max = max_price.replace("$", "").replace(",", "").strip()
                query += " AND CAST(REPLACE(SUBSTR(Reserve_Price, 2), ',', '') AS REAL) <= ?"
                params.append(clean_max)

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
        session['login_error'] = 'Please log in first.'
        return redirect(url_for("login"))


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
        session['login_error'] = 'Please log in first.'
        return redirect(url_for("login"))



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


@app.route('/pay/<int:listing_id>', methods=['GET', 'POST'])
def payment_page(listing_id):
    if "email" not in session:
        session['login_error'] = 'Please log in first.'
        return redirect(url_for("login"))

    bidder_email = session["email"]
    error = None
    success = False

    try:
        with get_connection() as con:
            listing = con.execute("""
                SELECT listing_ID, auction_title, seller_email, max_bids
                FROM Auction_Listing
                WHERE listing_ID = ? AND status = 2
            """, (listing_id,)).fetchone()

            if not listing:
                return render_template("pay.html", error="Listing not found or not yet sold.", listing=None)

            # confirm that bidder has the highest bid
            winner_row = con.execute("""
                SELECT bidder_email, MAX(bid_price) AS winning_price
                FROM Bid
                WHERE listing_ID = ?
            """, (listing_id,)).fetchone()

            if not winner_row or winner_row["bidder_email"].strip().lower() != bidder_email.strip().lower():
                return render_template("pay.html", error="You are not the winner of this auction.", listing=None)
            winning_price = winner_row["winning_price"]

            # check if bidder already paid
            already_paid = con.execute("""
                SELECT transaction_ID FROM Transact WHERE listing_ID = ?
            """, (listing_id,)).fetchone()

            if already_paid:
                return render_template("pay.html", error="Payment already completed for this auction.", listing=None)
            # load saved cards from credit_card table
            saved_cards = con.execute("""
                SELECT credit_card_num, card_type, expire_month, expire_year
                FROM Credit_Card
                WHERE LOWER(TRIM(owner_email)) = ?
            """, (bidder_email.strip().lower(),)).fetchall()

            if request.method == 'POST':
                use_saved = request.form.get('use_saved', '').strip()
                new_card_num = request.form.get('new_card_num', '').strip()
                card_type = request.form.get('card_type', '').strip()
                expire_month = request.form.get('expire_month', '').strip()
                expire_year = request.form.get('expire_year', '').strip()
                security_code = request.form.get('security_code', '').strip()

                chosen_card = None

                if use_saved:
                    chosen_card = con.execute("""
                        SELECT credit_card_num FROM Credit_Card
                        WHERE credit_card_num = ? AND LOWER(TRIM(owner_email)) = ?
                    """, (use_saved, bidder_email.strip().lower())).fetchone()
                    if not chosen_card:
                        error = "Invalid card selection."
                elif new_card_num:
                    if not card_type or not expire_month or not expire_year or not security_code:
                        error = "Please fill in all card fields."
                    else:
                        try:
                            expire_month = int(expire_month)
                            expire_year = int(expire_year)
                            security_code = int(security_code)
                        except ValueError:
                            error = "Invalid card details."

                        if not error:
                            con.execute("""
                                INSERT OR IGNORE INTO Credit_Card
                                (credit_card_num, card_type, expire_month, expire_year, security_code, owner_email)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (new_card_num, card_type, expire_month, expire_year, security_code, bidder_email))
                            con.commit()
                            chosen_card = {"credit_card_num": new_card_num}
                else:
                    error = "Please select or enter a credit card."

                if not error and chosen_card:
                    from datetime import date
                    today = date.today().strftime("%m/%d/%y")
                    con.execute("""
                        INSERT INTO Transact (seller_email, listing_ID, bidder_email, date, payment)
                        VALUES (?, ?, ?, ?, ?)
                    """, (listing["seller_email"], listing_id, bidder_email, today, winning_price))
                    con.commit()
                    success = True

    except sql.Error as e:
        print("DB error in payment_page:", e)
        error = "Database error during payment."

    return render_template(
        "payment.html",
        listing=listing if 'listing' in dir() else None,
        winning_price=winning_price if 'winning_price' in dir() else None,
        saved_cards=saved_cards if 'saved_cards' in dir() else [],
        error=error,
        success=success,
    )

@app.route('/logout')
def logout():
    session.clear()
    session['login_error'] = 'Logged out successfully.'
    return redirect(url_for("login"))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    message = None
    form_data = {"email": "", "name": "", "phone": "", "role": "Bidder"}

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        full_name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        role = request.form.get("role", "").strip()

        form_data = {"email": email, "name": full_name, "phone": phone, "role": role or "Bidder"}

        if not email or not password or not full_name:
            error = "Email, password, and name are required."
        elif role not in {"Bidder", "Seller", "HelpDesk"}:
            error = "Invalid role selected."
        else:
            normalized_email = email.lower()
            first_name, last_name = split_name(full_name)
            hashed_pw = hash_password(password)
            try:
                with get_connection() as con:
                    initialize_schema_if_needed(con)
                    existing_user = con.execute(
                        "SELECT email FROM User WHERE LOWER(TRIM(email)) = ?",
                        (normalized_email,),
                    ).fetchone()
                    if existing_user:
                        error = "An account with this email already exists."
                    else:
                        con.execute(
                            "INSERT INTO User (email, password) VALUES (?, ?)",
                            (normalized_email, hashed_pw),
                        )

                        if role == "Bidder":
                            con.execute(
                                """
                                INSERT INTO Bidder (email, first_name, last_name, age, home_address_id, major)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (normalized_email, first_name, last_name, None, None, None),
                            )
                        elif role == "Seller":
                            con.execute(
                                """
                                INSERT INTO Seller (email, bank_routing_number, bank_account_number, balance)
                                VALUES (?, ?, ?, ?)
                                """,
                                (normalized_email, None, None, 0),
                            )
                        elif role == "HelpDesk":
                            con.execute(
                                "INSERT INTO Helpdesk (email, position) VALUES (?, ?)",
                                (normalized_email, None),
                            )

                        if phone and role == "Seller":
                            con.execute(
                                """
                                INSERT OR IGNORE INTO Local_Vendor
                                (email, business_name, business_address_ID, customer_service_phone_number)
                                VALUES (?, ?, ?, ?)
                                """,
                                (normalized_email, None, None, phone),
                            )
                        con.commit()
                        message = "Account created successfully. Please log in."
                        form_data = {"email": "", "name": "", "phone": "", "role": "Bidder"}
            except sql.Error as e:
                print("DB error in signup:", e)
                error = "Could not create account due to a database error."

    return render_template("signup.html", error=error, message=message, form_data=form_data)

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "email" not in session:
        session['login_error'] = 'Please log in first.'
        return redirect(url_for("login"))

    email = session["email"].strip().lower()
    error = None
    message = None

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)
            profile_data, roles = build_profile_data(con, email)

            if request.method == "POST":
                password = request.form.get("password", "").strip()

                if "Bidder" in roles:
                    first_name, last_name = split_name(request.form.get("name", "").strip())
                    age_raw = request.form.get("age", "").strip()
                    major = request.form.get("major", "").strip()
                    street = request.form.get("street", "").strip()
                    city = request.form.get("city", "").strip()
                    state = request.form.get("state", "").strip()
                    zipcode = request.form.get("zipcode", "").strip()

                    age_value = None
                    if age_raw:
                        try:
                            age_value = int(age_raw)
                        except ValueError:
                            error = "Age must be a valid number."

                    home_address_id = con.execute(
                        """
                        SELECT home_address_id
                        FROM Bidder
                        WHERE LOWER(TRIM(email)) = ?
                        """,
                        (email,),
                    ).fetchone()["home_address_id"]

                    if not error:
                        con.execute(
                            """
                            UPDATE Bidder
                            SET first_name = ?, last_name = ?, age = ?, major = ?
                            WHERE LOWER(TRIM(email)) = ?
                            """,
                            (first_name, last_name, age_value, major or None, email),
                        )

                    if not error and (street or city or state or zipcode):
                        street_num, street_name = parse_street(street)
                        zip_value = None
                        if zipcode:
                            if not zipcode.isdigit():
                                error = "Zipcode must be numeric."
                            else:
                                zip_value = int(zipcode)
                                con.execute(
                                    """
                                    INSERT INTO Zipcode (zipcode, city, state)
                                    VALUES (?, ?, ?)
                                    ON CONFLICT(zipcode) DO UPDATE SET city = excluded.city, state = excluded.state
                                    """,
                                    (zip_value, city or None, state or None),
                                )

                        if not error:
                            if not home_address_id:
                                home_address_id = f"addr_{uuid4().hex[:10]}"
                                con.execute(
                                    """
                                    INSERT INTO Address (address_id, zipcode, street_num, street_name)
                                    VALUES (?, ?, ?, ?)
                                    """,
                                    (home_address_id, zip_value, street_num, street_name or None),
                                )
                                con.execute(
                                    """
                                    UPDATE Bidder
                                    SET home_address_id = ?
                                    WHERE LOWER(TRIM(email)) = ?
                                    """,
                                    (home_address_id, email),
                                )
                            else:
                                con.execute(
                                    """
                                    UPDATE Address
                                    SET zipcode = ?, street_num = ?, street_name = ?
                                    WHERE address_id = ?
                                    """,
                                    (zip_value, street_num, street_name or None, home_address_id),
                                )

                if not error and "Seller" in roles:
                    bank_routing = request.form.get("bank_routing_number", "").strip()
                    bank_account_raw = request.form.get("bank_account_number", "").strip()
                    balance_raw = request.form.get("balance", "").strip()
                    phone = request.form.get("phone", "").strip()

                    bank_account = None
                    if bank_account_raw:
                        if not bank_account_raw.isdigit():
                            error = "Bank account number must be numeric."
                        else:
                            bank_account = int(bank_account_raw)

                    balance = None
                    if not error and balance_raw:
                        try:
                            balance = int(float(balance_raw))
                        except ValueError:
                            error = "Balance must be numeric."

                    if not error:
                        con.execute(
                            """
                            UPDATE Seller
                            SET bank_routing_number = ?, bank_account_number = ?, balance = ?
                            WHERE LOWER(TRIM(email)) = ?
                            """,
                            (bank_routing or None, bank_account, balance, email),
                        )

                        if phone:
                            con.execute(
                                """
                                INSERT INTO Local_Vendor
                                (email, business_name, business_address_ID, customer_service_phone_number)
                                VALUES (?, ?, ?, ?)
                                ON CONFLICT(email) DO UPDATE SET
                                    customer_service_phone_number = excluded.customer_service_phone_number
                                """,
                                (email, None, None, phone),
                            )

                if not error and "HelpDesk" in roles:
                    position = request.form.get("helpdesk_position", "").strip()
                    con.execute(
                        """
                        UPDATE Helpdesk
                        SET position = ?
                        WHERE LOWER(TRIM(email)) = ?
                        """,
                        (position or None, email),
                    )

                if not error and password:
                    con.execute(
                        """
                        UPDATE User
                        SET password = ?
                        WHERE LOWER(TRIM(email)) = ?
                        """,
                        (hash_password(password), email),
                    )

                if not error:
                    con.commit()
                    message = "Profile updated successfully."
                else:
                    con.rollback()

                profile_data, roles = build_profile_data(con, email)

    except sql.Error as e:
        print("DB error in profile:", e)
        return render_template("profile.html", user={"email": email}, roles=[], error="Database error.")

    return render_template("profile.html", user=profile_data, roles=roles, message=message, error=error)

@app.route("/seller_products", methods=["GET", "POST"])
def seller_products():
    if "email" not in session or session.get("role") != "Seller":
        session['login_error'] = 'You must be a Seller to access this feature. Please log in.'
        return redirect(url_for("login"))

    seller_email = session["email"].strip().lower()
    message = None
    error = None
    products = []
    categories = []

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)

            if request.method == "POST":
                form_type = request.form.get("form_type", "").strip()

                if form_type == "create":
                    title = request.form.get("title", "").strip()
                    description = request.form.get("description", "").strip()
                    category = request.form.get("category", "").strip()
                    reserve_price_raw = request.form.get("reserve_price", "").strip()
                    max_bids_raw = request.form.get("max_bids", "").strip()

                    if not title or not description or not category or not reserve_price_raw or not max_bids_raw:
                        error = "Please fill in all listing fields."
                    else:
                        try:
                            reserve_price_value = float(reserve_price_raw)
                            max_bids_value = int(max_bids_raw)
                        except ValueError:
                            error = "Reserve price and max bids must be numeric."
                        else:
                            if reserve_price_value < 0:
                                error = "Reserve price must be non-negative."
                            elif max_bids_value <= 0:
                                error = "Max bids must be greater than zero."
                            else:
                                category_exists = con.execute(
                                    """
                                    SELECT category_name
                                    FROM Category
                                    WHERE LOWER(TRIM(category_name)) = ?
                                    """,
                                    (category.lower(),),
                                ).fetchone()
                                if not category_exists:
                                    error = "Selected category does not exist in the database."
                                else:
                                    con.execute(
                                        """
                                        INSERT INTO Auction_Listing
                                        (seller_email, category, auction_title, product_name, product_description,
                                         quantity, reserve_price, max_bids, status)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            seller_email,
                                            category_exists["category_name"],
                                            title,
                                            title,
                                            description,
                                            1,
                                            f"${reserve_price_value:.2f}",
                                            max_bids_value,
                                            1,
                                        ),
                                    )
                                    con.commit()
                                    message = "Listing created successfully."

                elif form_type == "delete":
                    listing_id_raw = request.form.get("product_id", "").strip()
                    if not listing_id_raw.isdigit():
                        error = "Invalid listing ID."
                    else:
                        listing_id = int(listing_id_raw)
                        result = con.execute(
                            """
                            UPDATE Auction_Listing
                            SET status = 0
                            WHERE listing_ID = ? AND LOWER(TRIM(seller_email)) = ?
                            """,
                            (listing_id, seller_email),
                        )
                        if result.rowcount == 0:
                            error = "Listing not found or not owned by you."
                        else:
                            con.commit()
                            message = "Listing marked as inactive."
                else:
                    error = "Invalid form action."

            category_rows = con.execute(
                "SELECT category_name FROM Category ORDER BY category_name ASC"
            ).fetchall()
            categories = [row["category_name"] for row in category_rows]

            rows = con.execute(
                """
                SELECT listing_ID, auction_title, category, reserve_price, max_bids, status
                FROM Auction_Listing
                WHERE LOWER(TRIM(seller_email)) = ?
                ORDER BY listing_ID DESC
                """,
                (seller_email,),
            ).fetchall()

            products = [
                {
                    "id": row["listing_ID"],
                    "title": row["auction_title"],
                    "category": row["category"],
                    "reserve_price": f"{parse_reserve_price(row['reserve_price']):.2f}",
                    "max_bids": row["max_bids"],
                    "status": listing_status_label(row["status"]),
                }
                for row in rows
            ]

    except sql.Error as e:
        print("DB error in seller_products:", e)
        error = "Database error while managing listings."

    return render_template(
        "seller_products.html",
        products=products,
        categories=categories,
        message=message,
        error=error,
    )

@app.route("/help_request", methods=["GET", "POST"])
def help_request():
    if "email" not in session:
        session['login_error'] = 'Please log in first.'
        return redirect(url_for("login"))

    sender_email = session["email"].strip().lower()
    message = None
    error = None
    requests_list = []

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)

            if request.method == "POST":
                request_type = request.form.get("request_type", "").strip()
                description = request.form.get("description", "").strip()

                if not request_type or not description:
                    error = "Please provide both request type and description."
                else:
                    con.execute(
                        """
                        INSERT INTO Request
                        (sender_email, helpdesk_staff_email, request_type, request_desc, request_status)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (sender_email, None, request_type, description, 0),
                    )
                    con.commit()
                    message = "Your request was sent successfully."

            request_rows = con.execute(
                """
                SELECT request_id, request_type, request_desc, request_status
                FROM Request
                WHERE LOWER(TRIM(sender_email)) = ?
                ORDER BY request_id DESC
                LIMIT 10
                """,
                (sender_email,),
            ).fetchall()

            requests_list = [
                {
                    "request_id": row["request_id"],
                    "request_type": row["request_type"],
                    "request_desc": row["request_desc"],
                    "request_status": request_status_label(row["request_status"]),
                }
                for row in request_rows
            ]

    except sql.Error as e:
        print("DB error in help_request:", e)
        error = "Database error while submitting request."

    return render_template("help_request.html", message=message, error=error, requests=requests_list)

if __name__ == "__main__":
    app.run()


