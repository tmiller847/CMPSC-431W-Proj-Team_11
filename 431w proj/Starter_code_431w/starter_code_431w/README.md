# NittanyAuction Flask Backend

## Startup Steps

1. Open a terminal in this folder:
   - `431w proj/Starter_code_431w/starter_code_431w`
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Run the backend:
   - `python app.py`
4. Open in browser:
   - `http://127.0.0.1:5000/`

## Database Path

By default, the app reads from:

- `431w proj/NittanyAuctionDataset_v1/NittanyAuctionDataset_v1/NittanyAuction.db`

Optional override (PowerShell):

- `$env:NITTANY_AUCTION_DB_PATH="C:\full\path\to\NittanyAuction.db"`
- `python app.py`

## Quick Integration Test

1. Open the login page.
2. Enter a valid user email/password from the `User` table.
3. Expected result:
   - success -> routed to `role_home.html`
   - failure -> `Invalid email or password.`

