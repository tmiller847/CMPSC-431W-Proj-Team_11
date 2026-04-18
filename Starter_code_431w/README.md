# NittanyAuction Flask Backend

## Startup Steps

1. Open a terminal in this folder:
   - `Starter_code_431w`
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Run the backend:
   - `python app.py`
4. Open in browser:
   - `http://127.0.0.1:5000/`

## Database Path

By default, the app reads from:

- `NittanyAuctionDataset_v1/NittanyAuction.db`

Optional override (PowerShell):

- `$env:NITTANY_AUCTION_DB_PATH="C:\full\path\to\NittanyAuction.db"`
- `python app.py`

## Authentication
- User passwords are stored in the User table in hashed form using SHA-256. 
- During login, the entered password is hashed using SHA-256 and is compared with the stored value in the database.
- Plain-text passwords are never stored.

## Login Handling
After successful authentication, the system determines the user's role by checking the email field in the Seller, Bidder, and Helpdesk databases. 

If the user has one role, it redirects to the corresponding page.
If the user has multiple roles, it displays a role selection page allowing the user to choose which role to continue as. 

## Quick Integration Test

1. Open the login page.
2. Enter a valid user email/password from the `User` table.
3. Expected result:
   - success
     - single role -> redirected to role-specific dashboard
     - multiple roles -> redirected to role selection page
   - failure -> `Invalid email or password.`

