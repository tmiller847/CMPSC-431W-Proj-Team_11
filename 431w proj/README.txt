This README intends to explain the functions of this project.

OTHER .TXT FILES:
The "backup console.txt" file provides a plaintext script to be input into the PyCharm console, which correctly creates each table.

The "sample_import.txt" file contains the commands to be run via SQLite in the command line interface. These do not contain all datasets for all tables, but just the datasets which are directly used or listed as foreign keys for the necessary data for the progress review. This is simply included for completion. The database was populated using PyCharm's inbuilt import function, directly from the .csv files, ignoring the header row when necessary.

INTENDED FUNCTION:
Users are brought directly onto the login page, where they enter their username and password (the latter of which is securely stored). If details are correct, they will be directed to their respective login page (or choice of available login pages for non-bidders). If the email/password do not exist, or are wrong, the user will be denied. If they do exist, but have no role (which is possible with the provided dataset) they will also be denied.