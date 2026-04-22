This README intends to explain the functions of this project.


DESCRIPTION:
This project serves as a basic, functional website for sellers to auction off goods. Users are directed to the login page immediately, from which they would enter the role select page (for non-bidders) or the dashboard. The dashboard is the home for each type of user, containing quick links to other pages, as well as keeping track of user-specific data (like wishlisted products and helpdesk requests). From there, bidders will navigate to the product search + category hierarchy page, which makes it as easy as possible for bidders to place bids on offered products. 

Secure information is well-protected and users are not able to access pages they shouldn't (as all of them require an eligible logged-in user). Beyond security, this project is designed to be as user-friendly as possible.


FILE STRUCTURE:
Under the main folder is this file, some additional .txt files (see "PROJECT SETUP / OTHER .TXT FILES"), and the pdf submitted for phase 1.

All .csv files, and the .db file, can be found under "/NittanyAuctionDataset_v1/". The .csv files are unmodified from the given data, and no new .csv files were introduced. The .db file is already initialized.

Under "/Starter_code_431w/" is app.py, which contains all the python for this project (see "HOW TO RUN"). The "templates" folder is alongside it, which includes every .html file used for the running of the site, as well as some generic .html files to speed up development of new pages.


IMPLEMENTED FEATURES:
We have fully implemented...
- Login/Logout/Signup pages, where HelpDesk approval is required to create a new HelpDesk account.
- Dashboards for each user type
- [+ Extra Feature] A "Role View" feature, which allows non-Bidders to act as bidders without creating an entirely new account
- A banner for quick navigation to other pages
- A user page, where user data can be changed
- A search page, which lists all active products a Bidder might bid on
- Category hierarchy is seamlessly included into this page so as to ease navigation
- Product pages, where Bidders can bid on products
- Includes separate bidding and credit card info pages
- Created using a product creation page
- [+ Extra Feature] A wishlist feature, where a user can be notified of activities on given products
- A product library for sellers to look at everything they've ever published
- A help page to submit helpdesk requests
- A sleek user interface

All features should be completed to the satisfaction of the project guidelines


PROJECT SETUP / OTHER .TXT FILES:
The "backup console.txt" file provides a plaintext script to be input into SQLite, which creates every table for an empty database file located at "/NittanyAuctionDataset_v1/NittanyAuction.db".

The "sample_import.txt" file contains the commands to be run via SQLite in the command line interface. It includes an important disclaimer reminding the user to replace the .csv file name with the absolute path to that file. This is different for different systems, so it cannot be included in the script.

These files are NOT intended to be run on NittanyAuction.db as-is. They should only be used in the case of resetting and populating the database file.


HOW TO RUN:
The file app.py can be found under "/Starter_code_431w/app.py". Running this file with PyCharm (professional not required) boots up the server at the link "http://127.0.0.1:5000". This brings the user to the log-in page.