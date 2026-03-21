from flask import Flask, render_template, request
import sqlite3 as sql

app = Flask(__name__)

host = 'http://127.0.0.1:5000/'


@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        if not email or not password:
            error = 'Please enter both email and password.'
        else:
            return render_template('role_home.html', email=email)
    return render_template('login.html', error=error)



if __name__ == "__main__":
    app.run()


