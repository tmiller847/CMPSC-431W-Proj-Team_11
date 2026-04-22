import os
from pathlib import Path
import sqlite3 as sql
import hashlib
from uuid import uuid4
from datetime import datetime, timedelta

from flask import Flask, render_template, request, session, redirect, url_for

app = Flask(__name__)
app.secret_key = "phase2-demo-key"

host = 'http://127.0.0.1:5000/'
HELPDESK_QUEUE_EMAIL = "helpdeskteam@lsu.edu"
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
        0: "Unassigned",
        1: "In Progress",
        2: "Completed",
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


def current_db_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalized_email(value):
    return (value or "").strip().lower()


def mark_helpdesk_active(connection, helpdesk_email):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS Helpdesk_Active_Session (
            email TEXT PRIMARY KEY,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO Helpdesk_Active_Session (email, last_seen_at)
        VALUES (?, ?)
        ON CONFLICT(email) DO UPDATE SET last_seen_at = excluded.last_seen_at
        """,
        (normalized_email(helpdesk_email), current_db_timestamp()),
    )


def get_active_helpdesk_emails(connection, minutes=10):
    cutoff = (datetime.now() - timedelta(minutes=int(minutes))).strftime("%Y-%m-%d %H:%M:%S")
    return [
        row["email"]
        for row in connection.execute(
            """
            SELECT email
            FROM Helpdesk_Active_Session
            WHERE last_seen_at >= ?
            """,
            (cutoff,),
        ).fetchall()
    ]


def create_helpdesk_notifications_for_request(connection, request_id, sender_email, request_type):
    active_helpdesk_emails = get_active_helpdesk_emails(connection, minutes=10)
    for helpdesk_email in active_helpdesk_emails:
        connection.execute(
            """
            INSERT INTO Helpdesk_Request_Notification
            (request_id, helpdesk_email, sender_email, request_type, message, is_read, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                request_id,
                normalized_email(helpdesk_email),
                normalized_email(sender_email),
                request_type,
                (
                    f"New help request #{request_id} from {normalized_email(sender_email)} "
                    f"({request_type})."
                ),
                current_db_timestamp(),
            ),
        )


def parse_datetime_local_input(value):
    try:
        parsed = datetime.fromisoformat(value.strip())
    except (TypeError, ValueError, AttributeError):
        return None
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def ensure_runtime_schema(connection):
    user_columns = {
        row["name"].strip().lower()
        for row in connection.execute("PRAGMA table_info(User)").fetchall()
    }
    if "is_active" not in user_columns:
        connection.execute("ALTER TABLE User ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    connection.execute("UPDATE User SET is_active = 1 WHERE is_active IS NULL")

    listing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(Auction_Listing)").fetchall()
    }
    if "start_time" not in listing_columns:
        connection.execute("ALTER TABLE Auction_Listing ADD COLUMN start_time TEXT")
    if "end_time" not in listing_columns:
        connection.execute("ALTER TABLE Auction_Listing ADD COLUMN end_time TEXT")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS Auction_Notification (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_ID INTEGER NOT NULL,
            bidder_email TEXT NOT NULL,
            seller_email TEXT NOT NULL,
            winner_email TEXT,
            highest_bid INTEGER,
            can_pay INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(listing_ID, bidder_email)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS Bidder_Notification (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_ID INTEGER NOT NULL,
            bidder_email TEXT NOT NULL,
            seller_email TEXT,
            winner_email TEXT,
            highest_bid INTEGER,
            can_pay INTEGER NOT NULL DEFAULT 0,
            notification_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS Wishlist (
            wishlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_ID INTEGER NOT NULL,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(listing_ID, email)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS Helpdesk_Approval_Request (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            applicant_email TEXT NOT NULL UNIQUE,
            applicant_name TEXT,
            request_status INTEGER NOT NULL DEFAULT 0,
            approver_email TEXT,
            requested_at TEXT NOT NULL,
            decided_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS Helpdesk_Active_Session (
            email TEXT PRIMARY KEY,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS Helpdesk_Request_Notification (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            helpdesk_email TEXT NOT NULL,
            sender_email TEXT NOT NULL,
            request_type TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def get_wishlist_email_column(connection):
    columns = {
        row["name"].strip().lower()
        for row in connection.execute("PRAGMA table_info(Wishlist)").fetchall()
    }
    if "bidder_email" in columns:
        return "bidder_email"
    if "email" in columns:
        return "email"
    return "email"


def wishlist_has_created_at(connection):
    columns = {
        row["name"].strip().lower()
        for row in connection.execute("PRAGMA table_info(Wishlist)").fetchall()
    }
    return "created_at" in columns


def create_bidder_notification(
    connection,
    listing_id,
    bidder_email,
    seller_email,
    winner_email,
    highest_bid,
    can_pay,
    notification_type,
    message,
    created_at=None,
):
    connection.execute(
        """
        INSERT INTO Bidder_Notification
        (listing_ID, bidder_email, seller_email, winner_email, highest_bid, can_pay, notification_type, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            bidder_email,
            seller_email,
            winner_email,
            highest_bid,
            can_pay,
            notification_type,
            message,
            created_at or current_db_timestamp(),
        ),
    )


def notify_wishlisters_on_bid(connection, listing_id, seller_email, bid_price, triggering_bidder):
    wishlist_email_col = get_wishlist_email_column(connection)
    wishlisters = connection.execute(
        f"""
        SELECT DISTINCT w.{wishlist_email_col} AS wishlist_email
        FROM Wishlist w
        WHERE w.listing_ID = ?
          AND LOWER(TRIM(w.{wishlist_email_col})) <> LOWER(TRIM(?))
          AND NOT EXISTS (
              SELECT 1
              FROM Bid b
              WHERE b.listing_ID = w.listing_ID
                AND LOWER(TRIM(b.bidder_email)) = LOWER(TRIM(w.{wishlist_email_col}))
          )
        """,
        (listing_id, triggering_bidder),
    ).fetchall()

    for row in wishlisters:
        create_bidder_notification(
            connection=connection,
            listing_id=listing_id,
            bidder_email=row["wishlist_email"],
            seller_email=seller_email,
            winner_email=None,
            highest_bid=int(bid_price),
            can_pay=0,
            notification_type="wishlist_bid",
            message=f"Wishlist update: Auction #{listing_id} has a new bid of ${float(bid_price):.2f}.",
        )


def notify_wishlisters_on_sale(connection, listing_id, seller_email, winner_email, highest_bid):
    wishlist_email_col = get_wishlist_email_column(connection)
    wishlisters = connection.execute(
        f"""
        SELECT DISTINCT w.{wishlist_email_col} AS wishlist_email
        FROM Wishlist w
        WHERE w.listing_ID = ?
          AND NOT EXISTS (
              SELECT 1
              FROM Bid b
              WHERE b.listing_ID = w.listing_ID
                AND LOWER(TRIM(b.bidder_email)) = LOWER(TRIM(w.{wishlist_email_col}))
          )
        """,
        (listing_id,),
    ).fetchall()

    amount_text = f"${float(highest_bid):.2f}" if highest_bid is not None else "N/A"
    for row in wishlisters:
        create_bidder_notification(
            connection=connection,
            listing_id=listing_id,
            bidder_email=row["wishlist_email"],
            seller_email=seller_email,
            winner_email=winner_email,
            highest_bid=highest_bid,
            can_pay=0,
            notification_type="wishlist_sold",
            message=f"Wishlist update: Auction #{listing_id} has been sold at {amount_text}.",
        )


def notify_bidders_auction_end(connection, listing_id, seller_email, winner_email, highest_bid, sold):
    bidder_rows = connection.execute(
        """
        SELECT DISTINCT bidder_email
        FROM Bid
        WHERE listing_ID = ?
        """,
        (listing_id,),
    ).fetchall()

    for bidder_row in bidder_rows:
        bidder_email = bidder_row["bidder_email"]
        bidder_is_winner = bool(
            sold
            and winner_email
            and bidder_email.strip().lower() == winner_email.strip().lower()
        )

        if sold:
            message = (
                f"Auction #{listing_id} ended. Highest bid: ${float(highest_bid):.2f}. "
                + (
                    "You won this auction. You may now complete payment."
                    if bidder_is_winner
                    else f"Winner: {winner_email}."
                )
            )
        else:
            highest_text = "No bids were placed."
            if highest_bid is not None:
                highest_text = f"Highest bid: ${float(highest_bid):.2f} (reserve not met)."
            message = (
                f"Auction #{listing_id} ended without a sale. "
                f"{highest_text} Seller decision is pending."
            )

        create_bidder_notification(
            connection=connection,
            listing_id=listing_id,
            bidder_email=bidder_email,
            seller_email=seller_email,
            winner_email=winner_email,
            highest_bid=highest_bid,
            can_pay=1 if bidder_is_winner else 0,
            notification_type="auction_end",
            message=message,
        )


def notify_bidders_seller_decision(
    connection,
    listing_id,
    seller_email,
    winner_email,
    highest_bid,
    accepted,
):
    bidder_rows = connection.execute(
        """
        SELECT DISTINCT bidder_email
        FROM Bid
        WHERE listing_ID = ?
        """,
        (listing_id,),
    ).fetchall()

    for bidder_row in bidder_rows:
        bidder_email = bidder_row["bidder_email"]
        bidder_is_winner = bool(
            accepted
            and winner_email
            and bidder_email.strip().lower() == winner_email.strip().lower()
        )
        if accepted:
            message = (
                f"Seller accepted a final offer for auction #{listing_id}. "
                f"Final price: ${float(highest_bid):.2f}. "
                + (
                    "You won this auction. You may now complete payment."
                    if bidder_is_winner
                    else f"Winner: {winner_email}."
                )
            )
        else:
            message = (
                f"Seller declined all bids for auction #{listing_id}. "
                "This auction ended without a sale."
            )

        create_bidder_notification(
            connection=connection,
            listing_id=listing_id,
            bidder_email=bidder_email,
            seller_email=seller_email,
            winner_email=winner_email if accepted else None,
            highest_bid=highest_bid,
            can_pay=1 if bidder_is_winner else 0,
            notification_type="seller_decision",
            message=message,
        )


def close_expired_auctions(connection):
    now_ts = current_db_timestamp()
    expired_rows = connection.execute(
        """
        SELECT listing_ID, seller_email, reserve_price
        FROM Auction_Listing
        WHERE status = 1
          AND end_time IS NOT NULL
          AND TRIM(end_time) <> ''
          AND end_time <= ?
        """,
        (now_ts,),
    ).fetchall()

    for row in expired_rows:
        listing_id = row["listing_ID"]
        reserve_price = parse_reserve_price(row["reserve_price"])

        top_bid = connection.execute(
            """
            SELECT bidder_email, bid_price
            FROM Bid
            WHERE listing_ID = ?
            ORDER BY bid_price DESC, bid_ID ASC
            LIMIT 1
            """,
            (listing_id,),
        ).fetchone()

        highest_bid = top_bid["bid_price"] if top_bid else None
        winner_email = top_bid["bidder_email"] if top_bid else None
        sold = highest_bid is not None and highest_bid >= reserve_price
        new_status = 2 if sold else 3

        connection.execute(
            "UPDATE Auction_Listing SET status = ? WHERE listing_ID = ? AND status = 1",
            (new_status, listing_id),
        )

        notify_bidders_auction_end(
            connection,
            listing_id,
            row["seller_email"],
            winner_email,
            highest_bid,
            sold,
        )

        if sold:
            notify_wishlisters_on_sale(
                connection,
                listing_id,
                row["seller_email"],
                winner_email,
                highest_bid,
            )

    if expired_rows:
        connection.commit()


def initialize_schema_if_needed(connection):
    user_table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='User'"
    ).fetchone()
    if not user_table:
        if not SCHEMA_PATH.exists():
            raise FileNotFoundError(
                f"Schema file not found at {SCHEMA_PATH}. Cannot initialize database."
            )

        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema_sql)
        connection.commit()

    ensure_runtime_schema(connection)
    close_expired_auctions(connection)


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
                        """
                        SELECT email, is_active
                        FROM User
                        WHERE LOWER(TRIM(email)) = ? AND password = ?
                        """,
                        (normalized_email, hashed_pw),
                    ).fetchone()

                    if user:
                        if user["is_active"] == 0:
                            error = "This account is inactive. Please sign up again to reactivate."
                            return render_template('login.html', error=error)
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
                            pending_helpdesk = connection.execute(
                                """
                                SELECT request_status
                                FROM Helpdesk_Approval_Request
                                WHERE LOWER(TRIM(applicant_email)) = ?
                                """,
                                (normalized_email,),
                            ).fetchone()
                            if pending_helpdesk and pending_helpdesk["request_status"] == 0:
                                error = "Your HelpDesk registration is pending approval."
                            elif pending_helpdesk and pending_helpdesk["request_status"] == 2:
                                error = "Your HelpDesk registration was denied."
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
        return redirect(url_for("seller_home"))
    elif role == "Bidder":
        return redirect(url_for("bidder_home"))
    elif role == "HelpDesk":
        return redirect(url_for("helpdesk_home"))

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
    notifications = []
    wishlist_items = []

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)
            wishlist_email_col = get_wishlist_email_column(con)
            auctions = con.execute("""
                SELECT al.listing_ID, al.auction_title, al.seller_email, al.end_time,
                       al.status, al.max_bids,
                       (
                           SELECT COUNT(*)
                           FROM Bid b_count
                           WHERE b_count.listing_ID = al.listing_ID
                       ) AS bid_count,
                       (
                           SELECT MAX(b_highest.bid_price)
                           FROM Bid b_highest
                           WHERE b_highest.listing_ID = al.listing_ID
                       ) AS highest_bid,
                       (
                           SELECT MAX(b_my.bid_price)
                           FROM Bid b_my
                           WHERE b_my.listing_ID = al.listing_ID
                             AND LOWER(TRIM(b_my.bidder_email)) = LOWER(TRIM(?))
                       ) AS my_highest_bid,
                    EXISTS (
                       SELECT 1
                       FROM Transact t
                       WHERE t.listing_ID = al.listing_ID
                         AND LOWER(TRIM(t.bidder_email)) = LOWER(TRIM(?))
                   ) AS has_paid,
                   EXISTS (
                       SELECT 1
                       FROM Rating r
                       WHERE r.listing_ID = al.listing_ID
                         AND LOWER(TRIM(r.bidder_email)) = LOWER(TRIM(?))
                   ) AS has_rated
                FROM Auction_Listing al
                WHERE EXISTS (
                    SELECT 1
                    FROM Bid b_exists
                    WHERE b_exists.listing_ID = al.listing_ID
                      AND LOWER(TRIM(b_exists.bidder_email)) = LOWER(TRIM(?))
                )
                ORDER BY al.status ASC, al.listing_ID DESC
            """, (email, email, email, email)).fetchall()

            notifications = con.execute(
                """
                SELECT bn.listing_ID, bn.message, bn.can_pay, bn.created_at
                FROM Bidder_Notification bn
                WHERE LOWER(TRIM(bn.bidder_email)) = LOWER(TRIM(?))
                  AND NOT (
                      bn.notification_type IN ('wishlist_bid', 'wishlist_sold')
                      AND EXISTS (
                          SELECT 1
                          FROM Bid b
                          WHERE b.listing_ID = bn.listing_ID
                            AND LOWER(TRIM(b.bidder_email)) = LOWER(TRIM(bn.bidder_email))
                      )
                  )
                ORDER BY notification_id DESC
                LIMIT 20
                """,
                (email,),
            ).fetchall()

            wishlist_items = con.execute(
                f"""
                SELECT al.listing_ID, al.auction_title, al.seller_email, al.status, al.end_time,
                       MAX(b.bid_price) AS highest_bid
                FROM Wishlist w
                JOIN Auction_Listing al ON al.listing_ID = w.listing_ID
                LEFT JOIN Bid b ON b.listing_ID = al.listing_ID
                WHERE LOWER(TRIM(w.{wishlist_email_col})) = LOWER(TRIM(?))
                GROUP BY al.listing_ID
                ORDER BY al.status ASC, al.listing_ID DESC
                """,
                (email,),
            ).fetchall()
    except sql.Error as e:
        print("DB error in bidder_home:", e)

    return render_template(
        "bidder_home.html",
        email=email,
        auctions=auctions,
        notifications=notifications,
        wishlist_items=wishlist_items,
    )


@app.route('/seller_home', methods=['GET', 'POST'])
def seller_home():
    if "email" not in session or session.get("role") != "Seller":
        session['login_error'] = 'You must be a Seller to access this feature. Please log in.'
        return redirect(url_for("login"))

    seller_email = session["email"]
    message = None
    error = None
    seller_updates = []

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)

            if request.method == "POST":
                action = request.form.get("action", "").strip().lower()
                listing_id_raw = request.form.get("listing_id", "").strip()
                if not listing_id_raw.isdigit():
                    error = "Invalid listing ID."
                else:
                    listing_id = int(listing_id_raw)
                    listing = con.execute(
                        """
                        SELECT listing_ID, seller_email, status
                        FROM Auction_Listing
                        WHERE listing_ID = ?
                          AND LOWER(TRIM(seller_email)) = LOWER(TRIM(?))
                        """,
                        (listing_id, seller_email),
                    ).fetchone()
                    if not listing:
                        error = "Listing not found or not owned by you."
                    elif listing["status"] != 3:
                        error = "This listing is not awaiting a decision."
                    else:
                        top_bid = con.execute(
                            """
                            SELECT bidder_email, bid_price
                            FROM Bid
                            WHERE listing_ID = ?
                            ORDER BY bid_price DESC, bid_ID ASC
                            LIMIT 1
                            """,
                            (listing_id,),
                        ).fetchone()
                        winner_email = top_bid["bidder_email"] if top_bid else None
                        highest_bid = top_bid["bid_price"] if top_bid else None

                        if action == "accept":
                            if not winner_email:
                                error = "No bids are available to accept."
                            else:
                                con.execute(
                                    "UPDATE Auction_Listing SET status = 2 WHERE listing_ID = ?",
                                    (listing_id,),
                                )
                                notify_bidders_seller_decision(
                                    con,
                                    listing_id,
                                    seller_email,
                                    winner_email,
                                    highest_bid,
                                    accepted=True,
                                )
                                con.commit()
                                message = "Offer accepted. Winner has been notified to complete payment."
                        elif action == "reject":
                            con.execute(
                                "UPDATE Auction_Listing SET status = 0 WHERE listing_ID = ?",
                                (listing_id,),
                            )
                            notify_bidders_seller_decision(
                                con,
                                listing_id,
                                seller_email,
                                winner_email,
                                highest_bid,
                                accepted=False,
                            )
                            con.commit()
                            message = "Offer rejected. Bidders have been notified."
                        else:
                            error = "Invalid seller action."

            seller_updates = con.execute(
                """
                SELECT al.listing_ID, al.auction_title, al.status, al.end_time,
                       MAX(b.bid_price) AS highest_bid
                FROM Auction_Listing al
                LEFT JOIN Bid b ON b.listing_ID = al.listing_ID
                WHERE LOWER(TRIM(al.seller_email)) = LOWER(TRIM(?))
                  AND al.status IN (2, 3)
                GROUP BY al.listing_ID
                ORDER BY al.status DESC, al.listing_ID DESC
                """,
                (seller_email,),
            ).fetchall()

    except sql.Error as e:
        print("DB error in seller_home:", e)
        error = "Database error while loading seller updates."

    return render_template(
        "seller_home.html",
        email=seller_email,
        updates=seller_updates,
        message=message,
        error=error,
    )


@app.route('/helpdesk_home', methods=['GET', 'POST'])
def helpdesk_home():
    if "email" not in session or session.get("role") != "HelpDesk":
        session['login_error'] = 'You must be a Helpdesk Member to access this feature. Please log in.'
        return redirect(url_for("login"))

    helpdesk_email = session["email"]
    error = session.pop("helpdesk_error", None)
    message = session.pop("helpdesk_message", None)
    pending_requests = []
    request_history = []
    unread_notifications = []
    unassigned_category_requests = []
    my_category_requests = []
    recently_completed_category_requests = []

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)
            mark_helpdesk_active(con, helpdesk_email)
            con.commit()

            if request.method == "POST":
                action = request.form.get("action", "").strip().lower()
                if action in {"approve", "deny"}:
                    applicant_email = request.form.get("applicant_email", "").strip().lower()
                    if not applicant_email:
                        error = "Invalid applicant email."
                    else:
                        request_row = con.execute(
                            """
                            SELECT request_id, applicant_email, request_status
                            FROM Helpdesk_Approval_Request
                            WHERE LOWER(TRIM(applicant_email)) = LOWER(TRIM(?))
                            """,
                            (applicant_email,),
                        ).fetchone()
                        if not request_row:
                            error = "Request not found."
                        elif request_row["request_status"] != 0:
                            error = "This request has already been decided."
                        elif action == "approve":
                            con.execute(
                                """
                                INSERT OR IGNORE INTO Helpdesk (email, position)
                                VALUES (?, ?)
                                """,
                                (applicant_email, None),
                            )
                            con.execute(
                                """
                                UPDATE Helpdesk_Approval_Request
                                SET request_status = 1, approver_email = ?, decided_at = ?
                                WHERE request_id = ?
                                """,
                                (helpdesk_email, current_db_timestamp(), request_row["request_id"]),
                            )
                            con.commit()
                            message = f"Approved helpdesk request for {applicant_email}."
                        else:
                            con.execute(
                                """
                                UPDATE Helpdesk_Approval_Request
                                SET request_status = 2, approver_email = ?, decided_at = ?
                                WHERE request_id = ?
                                """,
                                (helpdesk_email, current_db_timestamp(), request_row["request_id"]),
                            )
                            con.commit()
                            message = f"Denied helpdesk request for {applicant_email}."
                elif action == "claim_request":
                    request_id_raw = request.form.get("request_id", "").strip()
                    if not request_id_raw.isdigit():
                        error = "Invalid help request ID."
                    else:
                        request_id = int(request_id_raw)
                        user_request = con.execute(
                            """
                            SELECT request_id, request_status, helpdesk_staff_email, request_type
                            FROM Request
                            WHERE request_id = ?
                            """,
                            (request_id,),
                        ).fetchone()
                        if not user_request:
                            error = "Help request not found."
                        elif (user_request["request_type"] or "").strip().lower() != "add category":
                            error = "Only Add Category requests can be managed from this dashboard."
                        else:
                            assigned_to = normalized_email(user_request["helpdesk_staff_email"])
                            if assigned_to not in {"", normalized_email(HELPDESK_QUEUE_EMAIL)}:
                                error = "This request is already claimed by another HelpDesk staff member."
                            else:
                                con.execute(
                                    """
                                    UPDATE Request
                                    SET request_status = 1, helpdesk_staff_email = ?
                                    WHERE request_id = ?
                                    """,
                                    (helpdesk_email, request_id),
                                )
                                con.commit()
                                message = f"You claimed Add Category request #{request_id}."
                else:
                    error = "Invalid action."

            unread_notifications = con.execute(
                """
                SELECT notification_id, request_id, sender_email, request_type, message, created_at
                FROM Helpdesk_Request_Notification
                WHERE LOWER(TRIM(helpdesk_email)) = LOWER(TRIM(?))
                  AND is_read = 0
                ORDER BY notification_id DESC
                LIMIT 20
                """,
                (helpdesk_email,),
            ).fetchall()

            if unread_notifications:
                notification_ids = [
                    str(row["notification_id"])
                    for row in unread_notifications
                    if row["notification_id"] is not None
                ]
                if notification_ids:
                    placeholder = ",".join(["?"] * len(notification_ids))
                    con.execute(
                        f"""
                        UPDATE Helpdesk_Request_Notification
                        SET is_read = 1
                        WHERE notification_id IN ({placeholder})
                        """,
                        notification_ids,
                    )
                    con.commit()

            pending_requests = con.execute(
                """
                SELECT applicant_email, applicant_name, requested_at
                FROM Helpdesk_Approval_Request
                WHERE request_status = 0
                ORDER BY request_id DESC
                """,
            ).fetchall()

            request_history = con.execute(
                """
                SELECT applicant_email, applicant_name, request_status, approver_email, requested_at, decided_at
                FROM Helpdesk_Approval_Request
                WHERE request_status IN (1, 2)
                ORDER BY request_id DESC
                LIMIT 20
                """,
            ).fetchall()

            unassigned_category_requests = con.execute(
                """
                SELECT request_id, sender_email, request_type, request_desc, request_status, helpdesk_staff_email
                FROM Request
                WHERE LOWER(TRIM(request_type)) = 'add category'
                  AND request_status = 0
                  AND (
                      helpdesk_staff_email IS NULL
                      OR TRIM(helpdesk_staff_email) = ''
                      OR LOWER(TRIM(helpdesk_staff_email)) = LOWER(TRIM(?))
                  )
                ORDER BY request_id DESC
                LIMIT 30
                """,
                (HELPDESK_QUEUE_EMAIL,),
            ).fetchall()

            my_category_requests = con.execute(
                """
                SELECT request_id, sender_email, request_type, request_desc, request_status, helpdesk_staff_email
                FROM Request
                WHERE LOWER(TRIM(request_type)) = 'add category'
                  AND request_status = 1
                  AND LOWER(TRIM(helpdesk_staff_email)) = LOWER(TRIM(?))
                ORDER BY request_id DESC
                LIMIT 20
                """,
                (helpdesk_email,),
            ).fetchall()

            recently_completed_category_requests = con.execute(
                """
                SELECT request_id, sender_email, request_type, request_desc, request_status, helpdesk_staff_email
                FROM Request
                WHERE LOWER(TRIM(request_type)) = 'add category'
                  AND request_status IN (2, 3)
                ORDER BY request_id DESC
                LIMIT 20
                """
            ).fetchall()

    except sql.Error as e:
        print("DB error in helpdesk_home:", e)
        error = "Database error while loading helpdesk approvals."

    return render_template(
        "helpdesk_home.html",
        email=helpdesk_email,
        unread_notifications=unread_notifications,
        unassigned_category_requests=unassigned_category_requests,
        my_category_requests=my_category_requests,
        recently_completed_category_requests=recently_completed_category_requests,
        request_status_label=request_status_label,
        pending_requests=pending_requests,
        request_history=request_history,
        message=message,
        error=error,
    )


@app.route('/helpdesk_request/<int:request_id>', methods=['GET', 'POST'])
def manage_add_category_request(request_id):
    if "email" not in session or session.get("role") != "HelpDesk":
        session['login_error'] = 'You must be a Helpdesk Member to access this feature. Please log in.'
        return redirect(url_for("login"))

    helpdesk_email = session["email"]
    error = None
    request_row = None
    parent_categories = []
    selected_parent = "Root"

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)
            mark_helpdesk_active(con, helpdesk_email)
            con.commit()

            request_row = con.execute(
                """
                SELECT request_id, sender_email, helpdesk_staff_email, request_type, request_desc, request_status
                FROM Request
                WHERE request_id = ?
                  AND LOWER(TRIM(request_type)) = 'add category'
                """,
                (request_id,),
            ).fetchone()
            if not request_row:
                session["helpdesk_error"] = "Add Category request not found."
                return redirect(url_for("helpdesk_home"))

            if normalized_email(request_row["helpdesk_staff_email"]) != normalized_email(helpdesk_email):
                session["helpdesk_error"] = "You can only open Add Category requests assigned to your account."
                return redirect(url_for("helpdesk_home"))

            if request_row["request_status"] != 1:
                session["helpdesk_error"] = "Only in-progress Add Category requests can be managed."
                return redirect(url_for("helpdesk_home"))

            parent_categories = [
                row["category_name"]
                for row in con.execute(
                    """
                    SELECT category_name
                    FROM Category
                    ORDER BY category_name ASC
                    """
                ).fetchall()
            ]

            if request.method == "POST":
                action = request.form.get("action", "").strip().lower()
                selected_parent = request.form.get("parent_category", "Root").strip() or "Root"

                if action == "complete_category":
                    category_name = request.form.get("new_category_name", "").strip()
                    if not category_name:
                        error = "Please enter a category name."
                    else:
                        parent_exists = (
                            selected_parent == "Root"
                            or con.execute(
                                """
                                SELECT 1
                                FROM Category
                                WHERE LOWER(TRIM(category_name)) = LOWER(TRIM(?))
                                """,
                                (selected_parent,),
                            ).fetchone()
                        )
                        if not parent_exists:
                            error = "Selected parent category does not exist."
                        else:
                            duplicate = con.execute(
                                """
                                SELECT 1
                                FROM Category
                                WHERE LOWER(TRIM(category_name)) = LOWER(TRIM(?))
                                """,
                                (category_name,),
                            ).fetchone()
                            if duplicate:
                                error = "That category already exists."
                            else:
                                con.execute(
                                    """
                                    INSERT INTO Category (category_name, parent_category)
                                    VALUES (?, ?)
                                    """,
                                    (category_name, selected_parent),
                                )
                                con.execute(
                                    """
                                    UPDATE Request
                                    SET request_status = 2
                                    WHERE request_id = ?
                                    """,
                                    (request_id,),
                                )
                                con.commit()
                                session["helpdesk_message"] = (
                                    f'Added category "{category_name}" and completed request #{request_id}.'
                                )
                                return redirect(url_for("helpdesk_home"))
                elif action == "reject_category":
                    con.execute(
                        """
                        UPDATE Request
                        SET request_status = 3
                        WHERE request_id = ?
                        """,
                        (request_id,),
                    )
                    con.commit()
                    session["helpdesk_message"] = f"Rejected Add Category request #{request_id}."
                    return redirect(url_for("helpdesk_home"))
                else:
                    error = "Invalid action."

    except sql.Error as e:
        print("DB error in manage_add_category_request:", e)
        error = "Database error while managing Add Category request."

    return render_template(
        "helpdesk_category_request.html",
        request_row=request_row,
        parent_categories=parent_categories,
        selected_parent=selected_parent,
        error=error,
    )


@app.route('/search')
@app.route('/search/<path:category>')
def search(category=None):
    if "email" not in session:
        return render_template("login.html", error="Please log in first.")

    error = None
    subcategories = []
    products = []
    breadcrumb = [] # build breadcrumb to track user's path
    wishlist_feedback = session.pop("wishlist_feedback", None)
    keyword = request.args.get('keyword', '').strip()
    min_price = request.args.get('min_price', '').strip()
    max_price = request.args.get('max_price', '').strip()
    is_search = bool(keyword or min_price or max_price)
    current_email = session.get("email", "")

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)
            wishlist_email_col = get_wishlist_email_column(con)
            if category is None:
                subcategories = con.execute("""
                    SELECT category_name FROM Category
                    WHERE parent_category = 'Root'
                    ORDER BY category_name
                """).fetchall()
                breadcrumb = [("All", None)]

            else:

                breadcrumb = [("All", "/search")]
                crumb_cat = category
                crumb_trail = []
                while crumb_cat:
                    parent_row = con.execute(
                        "SELECT parent_category FROM Category WHERE category_name = ?",
                        (crumb_cat,)
                    ).fetchone()
                    crumb_trail.append(crumb_cat)
                    if parent_row and parent_row["parent_category"] != "Root":
                        crumb_cat = parent_row["parent_category"]
                    else:
                        break


                for name in reversed(crumb_trail):
                    breadcrumb.append((name, f"/search/{name}"))
                if breadcrumb:
                    last = breadcrumb[-1]
                    breadcrumb[-1] = (last[0], None)


                subcategories = con.execute("""
                    SELECT TRIM(category_name) AS category_name
                    FROM Category
                    WHERE LOWER(TRIM(parent_category)) = LOWER(TRIM(?))
                    ORDER BY TRIM(category_name)
                """, (category,)).fetchall()


            query = """
                SELECT al.listing_ID, al.auction_title, al.product_name,
                       al.seller_email, al.reserve_price, al.category,
                       COUNT(DISTINCT b.bid_ID) AS bid_count,
                       MAX(b.bid_price) AS highest_bid,
                       al.max_bids,
                       
                       ROUND(AVG(r.rating), 1) AS seller_rating,
                       COUNT(r.rating) AS rating_count,
                       
                       MAX(
                           CASE
                               WHEN LOWER(TRIM(w.{})) = LOWER(TRIM(?)) THEN 1
                               ELSE 0
                           END
                       ) AS wishlisted
                FROM Auction_Listing al
                LEFT JOIN Bid b ON al.listing_ID = b.listing_ID
                LEFT JOIN Wishlist w ON al.listing_ID = w.listing_ID
                LEFT JOIN Rating r
                    ON LOWER(TRIM(r.seller_email)) = LOWER(TRIM(al.seller_email))
                WHERE al.status = 1
            """.format(wishlist_email_col)
            params = [current_email]



            if category:
                query += " AND LOWER(TRIM(al.category)) = LOWER(TRIM(?))"
                params.append(category)

            if keyword:
                query += """
                    AND (
                        LOWER(al.auction_title) LIKE ?
                        OR LOWER(al.product_description) LIKE ?
                        OR LOWER(al.category) LIKE ?
                        OR LOWER(al.seller_email) LIKE ?
                    )
                """
                like = "%" + keyword.lower() + "%"
                params.extend([like, like, like, like])

            if min_price:
                query += " AND CAST(REPLACE(REPLACE(REPLACE(al.reserve_price, '$', ''), ',', ''), ' ', '') AS REAL) >= ?"
                params.append(float(str(min_price).replace('$', '').replace(',', '').strip()))

            if max_price:
                query += " AND CAST(REPLACE(REPLACE(REPLACE(al.reserve_price, '$', ''), ',', ''), ' ', '') AS REAL) <= ?"
                params.append(float(str(max_price).replace('$', '').replace(',', '').strip()))

            query += " GROUP BY al.listing_ID ORDER BY al.listing_ID DESC"
            products = con.execute(query, params).fetchall()

    except sql.Error as e:
        print("DB error in search:", e)
        error = "Database error while loading categories."

    return render_template(
        "search.html",
        category=category,
        subcategories=subcategories,
        products=products,
        breadcrumb=breadcrumb,
        error=error,
        role=session.get("role"),
        keyword=keyword,
        min_price=min_price,
        max_price=max_price,
        is_search=is_search,
        wishlist_feedback=wishlist_feedback,
        search_return_url=request.full_path,
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
    wishlisted = False
    wishlist_feedback = session.pop("wishlist_feedback", None)
    seller_rating = None
    rating_count = 0

    try:
        with get_connection() as connection:
            initialize_schema_if_needed(connection)
            wishlist_email_col = get_wishlist_email_column(connection)
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

            wishlisted_row = connection.execute(
                f"""
                SELECT 1
                FROM Wishlist
                WHERE listing_ID = ?
                  AND LOWER(TRIM({wishlist_email_col})) = LOWER(TRIM(?))
                """,
                (listing_id, session["email"]),
            ).fetchone()
            wishlisted = bool(wishlisted_row)

            rating_row = connection.execute("""
                SELECT ROUND(AVG(rating), 1) AS seller_rating,
                    COUNT(rating) AS rating_count
                FROM Rating
                WHERE LOWER(TRIM(seller_email)) = LOWER(TRIM(?))
            """, (product["seller_email"],)).fetchone()

            if rating_row:
                seller_rating = rating_row["seller_rating"]
                rating_count = rating_row["rating_count"]
    except sql.Error as e:
        print("Database error:", e)
        error = "Database error while loading product."

    return render_template(
        "product.html",
        product=product,
        bid_count=bid_count,
        highest_bid=highest_bid,
        remaining_bids=remaining_bids,
        error=error,
        wishlisted=wishlisted,
        wishlist_feedback=wishlist_feedback,
        seller_rating=seller_rating,
        rating_count=rating_count,
    )



@app.route('/wishlist/<int:listing_id>', methods=['POST'])
def toggle_wishlist(listing_id):
    if "email" not in session or session.get("role") != "Bidder":
        session['login_error'] = 'You must be a Bidder to use wishlist.'
        return redirect(url_for("login"))

    bidder_email = session["email"]
    action = request.form.get("action", "").strip().lower()
    next_url = request.form.get("next", "").strip()
    wishlist_feedback = None

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)
            wishlist_email_col = get_wishlist_email_column(con)
            listing = con.execute(
                "SELECT listing_ID FROM Auction_Listing WHERE listing_ID = ?",
                (listing_id,),
            ).fetchone()
            if not listing:
                wishlist_feedback = "Listing not found."
            elif action == "add":
                if wishlist_has_created_at(con):
                    con.execute(
                        f"""
                        INSERT OR IGNORE INTO Wishlist (listing_ID, {wishlist_email_col}, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (listing_id, bidder_email, current_db_timestamp()),
                    )
                else:
                    con.execute(
                        f"""
                        INSERT OR IGNORE INTO Wishlist (listing_ID, {wishlist_email_col})
                        VALUES (?, ?)
                        """,
                        (listing_id, bidder_email),
                    )
                con.commit()
                wishlist_feedback = "Added to wishlist."
            elif action == "remove":
                con.execute(
                    f"""
                    DELETE FROM Wishlist
                    WHERE listing_ID = ?
                      AND LOWER(TRIM({wishlist_email_col})) = LOWER(TRIM(?))
                    """,
                    (listing_id, bidder_email),
                )
                con.commit()
                wishlist_feedback = "Removed from wishlist."
            else:
                wishlist_feedback = "Invalid wishlist action."
    except sql.Error:
        wishlist_feedback = "Could not update wishlist due to a database error."

    session["wishlist_feedback"] = wishlist_feedback
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("product_page", listing_id=listing_id))



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
            initialize_schema_if_needed(con)
            listing = con.execute("""
                SELECT listing_ID, auction_title, product_name, seller_email,
                       reserve_price, max_bids, status, end_time
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

            previous_top_bidder_row = con.execute(
                """
                SELECT bidder_email, bid_price
                FROM Bid
                WHERE listing_ID = ?
                ORDER BY bid_price DESC, bid_ID DESC
                LIMIT 1
                """,
                (listing_id,),
            ).fetchone()
            previous_top_bidder = previous_top_bidder_row["bidder_email"] if previous_top_bidder_row else None

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
            if listing["end_time"] and listing["end_time"] <= current_db_timestamp():
                pre_errors.append("This auction has ended (end time reached).")
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

                            notify_wishlisters_on_bid(
                                con,
                                listing_id,
                                listing["seller_email"],
                                input_bid,
                                bidder_email,
                            )

                            # Notify prior highest bidder that they were outbid.
                            if previous_top_bidder and previous_top_bidder.strip().lower() != bidder_email.strip().lower():
                                create_bidder_notification(
                                    connection=con,
                                    listing_id=listing_id,
                                    bidder_email=previous_top_bidder,
                                    seller_email=listing["seller_email"],
                                    winner_email=None,
                                    highest_bid=int(input_bid),
                                    can_pay=0,
                                    notification_type="outbid",
                                    message=f"You were outbid on auction #{listing_id}. New highest bid is ${float(input_bid):.2f}.",
                                )

                            # If this bidder had wishlist notifications for this listing,
                            # remove them now that they are an active bidder.
                            con.execute(
                                """
                                DELETE FROM Bidder_Notification
                                WHERE listing_ID = ?
                                  AND LOWER(TRIM(bidder_email)) = LOWER(TRIM(?))
                                  AND notification_type IN ('wishlist_bid', 'wishlist_sold')
                                """,
                                (listing_id, bidder_email),
                            )
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
                                    notify_bidders_auction_end(
                                        con,
                                        listing_id,
                                        listing["seller_email"],
                                        bidder_email,
                                        highest_bid,
                                        True,
                                    )
                                    notify_wishlisters_on_sale(
                                        con,
                                        listing_id,
                                        listing["seller_email"],
                                        bidder_email,
                                        highest_bid,
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
                                    notify_bidders_auction_end(
                                        con,
                                        listing_id,
                                        listing["seller_email"],
                                        None,
                                        highest_bid,
                                        False,
                                    )
                                    con.commit()

                                    feedback = ("ended_no_sale",
                                        "Auction ended. The highest bid did not meet the reserve price. "
                                        "The seller will decide whether to accept or cancel.")
                            else:
                                feedback = ("accepted", f"Bid of ${highest_bid:.2f} placed successfully! {remaining_bids} bid(s) remaining.")


            listing = con.execute("""
                SELECT listing_ID, auction_title, product_name, seller_email,
                       reserve_price, max_bids, status, end_time
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
            initialize_schema_if_needed(con)
            listing = con.execute("""
                SELECT listing_ID, auction_title, seller_email, max_bids
                FROM Auction_Listing
                WHERE listing_ID = ? AND status = 2
            """, (listing_id,)).fetchone()

            if not listing:
                return render_template("payment.html", error="Listing not found or not yet sold.", listing=None)

            # confirm that bidder has the highest bid
            winner_row = con.execute("""
                SELECT bidder_email, MAX(bid_price) AS winning_price
                FROM Bid
                WHERE listing_ID = ?
            """, (listing_id,)).fetchone()

            if not winner_row or winner_row["bidder_email"].strip().lower() != bidder_email.strip().lower():
                return render_template("payment.html", error="You are not the winner of this auction.", listing=None)
            winning_price = winner_row["winning_price"]

            winner_notification = con.execute(
                """
                SELECT notification_id
                FROM Bidder_Notification
                WHERE listing_ID = ?
                  AND LOWER(TRIM(bidder_email)) = LOWER(TRIM(?))
                  AND can_pay = 1
                  AND notification_type = 'auction_end'
                """,
                (listing_id, bidder_email),
            ).fetchone()
            if not winner_notification:
                # Backfill a missing winner notification for legacy auctions so
                # the winner can still complete payment from the dashboard link.
                create_bidder_notification(
                    connection=con,
                    listing_id=listing_id,
                    bidder_email=bidder_email,
                    seller_email=listing["seller_email"],
                    winner_email=bidder_email,
                    highest_bid=winning_price,
                    can_pay=1,
                    notification_type="auction_end",
                    message=(
                        f"Auction #{listing_id} ended. Highest bid: ${float(winning_price):.2f}. "
                        "You won this auction. You may now complete payment."
                    ),
                )
                con.commit()

            # check if bidder already paid
            already_paid = con.execute("""
                SELECT transaction_ID FROM Transact WHERE listing_ID = ?
            """, (listing_id,)).fetchone()

            if already_paid:
                return render_template("payment.html", error="Payment already completed for this auction.", listing=None)
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
                    # Ensure listing remains sold once payment is submitted.
                    con.execute(
                        "UPDATE Auction_Listing SET status = 2 WHERE listing_ID = ?",
                        (listing_id,),
                    )
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
                            existing_helpdesk = con.execute(
                                "SELECT COUNT(*) AS count FROM Helpdesk"
                            ).fetchone()
                            has_helpdesk = existing_helpdesk and existing_helpdesk["count"] > 0

                            if has_helpdesk:
                                con.execute(
                                    """
                                    INSERT INTO Helpdesk_Approval_Request
                                    (applicant_email, applicant_name, request_status, approver_email, requested_at, decided_at)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        normalized_email,
                                        full_name,
                                        0,
                                        None,
                                        current_db_timestamp(),
                                        None,
                                    ),
                                )
                            else:
                                # Bootstrap path: if no helpdesk exists yet, allow first one immediately.
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
                        if role == "HelpDesk":
                            if has_helpdesk:
                                message = (
                                    "HelpDesk registration submitted. "
                                    "Please wait for approval from current HelpDesk staff."
                                )
                            else:
                                message = "HelpDesk account created successfully. Please log in."
                        else:
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
                action = request.form.get("action", "save_profile").strip().lower()
                if action == "inactivate_account":
                    con.execute(
                        """
                        UPDATE User
                        SET is_active = 0
                        WHERE LOWER(TRIM(email)) = ?
                        """,
                        (email,),
                    )

                    if "Seller" in roles:
                        con.execute(
                            """
                            UPDATE Auction_Listing
                            SET status = 0
                            WHERE LOWER(TRIM(seller_email)) = LOWER(TRIM(?))
                            """,
                            (email,),
                        )

                    if "HelpDesk" in roles:
                        con.execute(
                            """
                            UPDATE Request
                            SET request_status = 0, helpdesk_staff_email = ?
                            WHERE LOWER(TRIM(helpdesk_staff_email)) = LOWER(TRIM(?))
                              AND request_status IN (0, 1)
                            """,
                            (HELPDESK_QUEUE_EMAIL, email),
                        )
                        con.execute(
                            """
                            DELETE FROM Helpdesk_Active_Session
                            WHERE LOWER(TRIM(email)) = LOWER(TRIM(?))
                            """,
                            (email,),
                        )

                    con.commit()
                    session.clear()
                    session["login_error"] = (
                        "Account inactivated successfully. Please sign up again to reactivate."
                    )
                    return redirect(url_for("signup"))

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


@app.route("/seller/<path:seller_email>")
def seller_profile(seller_email):
    if "email" not in session:
        session["login_error"] = "Please log in first."
        return redirect(url_for("login"))

    error = None
    seller = None
    ratings = []

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)

            seller = con.execute("""
                SELECT
                    s.email,
                    ROUND(AVG(r.rating), 1) AS avg_rating,
                    COUNT(r.rating) AS rating_count
                FROM Seller s
                LEFT JOIN Rating r
                    ON LOWER(TRIM(r.seller_email)) = LOWER(TRIM(s.email))
                WHERE LOWER(TRIM(s.email)) = LOWER(TRIM(?))
                GROUP BY s.email
            """, (seller_email,)).fetchone()

            ratings = con.execute("""
                SELECT bidder_email, rating, rating_desc
                FROM Rating
                WHERE LOWER(TRIM(seller_email)) = LOWER(TRIM(?))
                ORDER BY rating DESC
            """, (seller_email,)).fetchall()

    except sql.Error as e:
        print("DB error in seller_profile:", e)
        error = "Database error while loading seller profile."

    return render_template(
        "seller_profile.html",
        seller=seller,
        ratings=ratings,
        error=error,
    )

@app.route("/rate/<int:listing_id>", methods=["GET", "POST"])
def rate_seller(listing_id):
    if "email" not in session or session.get("role") != "Bidder":
        session["login_error"] = "You must be logged in as a bidder to rate a seller."
        return redirect(url_for("login"))

    bidder_email = session["email"].strip().lower()
    error = None
    message = None
    listing = None

    try:
        with get_connection() as con:
            initialize_schema_if_needed(con)

            # checks transact table to make sure that bidder won and paid
            listing = con.execute("""
                SELECT
                    t.listing_ID,
                    t.bidder_email,
                    t.seller_email,
                    t.payment,
                    al.auction_title
                FROM Transact t
                JOIN Auction_Listing al
                    ON al.listing_ID = t.listing_ID
                WHERE t.listing_ID = ?
                  AND LOWER(TRIM(t.bidder_email)) = LOWER(TRIM(?))
            """, (listing_id, bidder_email)).fetchone()

            if not listing:
                error = "You can only rate sellers for auctions you won and paid for."
                return render_template("rate_seller.html", listing=None, error=error, message=message)


            # checks if user already created a rating
            existing_rating = con.execute("""
                SELECT 1
                FROM Rating
                WHERE listing_ID = ?
                  AND LOWER(TRIM(bidder_email)) = LOWER(TRIM(?))
            """, (listing_id, bidder_email)).fetchone()


            if existing_rating:
                error = "You have already rated this seller for this auction."
                return render_template("rate_seller.html", listing=listing, error=error, message=message)


            if request.method == "POST":
                rating_raw = request.form.get("rating", "").strip()
                rating_desc = request.form.get("rating_desc", "").strip()

                if not rating_raw:
                    error = "Please select a rating."
                else:
                    try:
                        rating_value = int(rating_raw)
                    except ValueError:
                        error = "Rating must be a number from 1 to 5."
                    else:
                        if rating_value < 1 or rating_value > 5:
                            error = "Rating must be between 1 and 5."
                        else: # insert rating into db
                            date = datetime.now().strftime("%m/%d/%Y")
                            con.execute("""
                                INSERT INTO Rating (listing_ID, bidder_email, seller_email, rating, rating_desc, date)
                                VALUES (?, ?, ?, ?, ?, ?) 
                            """, (
                                listing_id,
                                bidder_email,
                                listing["seller_email"],
                                rating_value,
                                rating_desc if rating_desc else None,
                                date
                            ))
                            con.commit()
                            message = "Rating submitted successfully."


    except sql.Error as e:
        print("DB error in rate_seller:", e)
        error = "Database error while submitting rating."

    return render_template("rate_seller.html", listing=listing, error=error, message=message)
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
                    end_time_raw = request.form.get("end_time", "").strip()

                    if not title or not description or not category or not reserve_price_raw or not max_bids_raw or not end_time_raw:
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
                                end_time_db = parse_datetime_local_input(end_time_raw)
                                if not end_time_db:
                                    error = "Invalid end date/time."
                                elif end_time_db <= current_db_timestamp():
                                    error = "End time must be in the future."

                            if not error:
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
                                         quantity, reserve_price, max_bids, status, start_time, end_time)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                                            current_db_timestamp(),
                                            end_time_db,
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
                SELECT listing_ID, auction_title, category, reserve_price, max_bids, status, end_time
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
                    "end_time": row["end_time"] or "",
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
                    request_result = con.execute(
                        """
                        INSERT INTO Request
                        (sender_email, helpdesk_staff_email, request_type, request_desc, request_status)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (sender_email, HELPDESK_QUEUE_EMAIL, request_type, description, 0),
                    )
                    create_helpdesk_notifications_for_request(
                        con,
                        request_result.lastrowid,
                        sender_email,
                        request_type,
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


