import sqlite3
from flask import Flask, render_template, redirect, url_for, request, flash, g
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
import plotly.express as px
import json
import plotly
import os
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback_key_for_testing')
DATABASE = os.path.join(app.instance_path, 'finance.db')
os.makedirs(app.instance_path, exist_ok=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL, type TEXT NOT NULL, category TEXT NOT NULL, date TEXT NOT NULL, description TEXT, FOREIGN KEY (user_id) REFERENCES users (id))')
        db.commit()

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        return User(user['id'], user['username'])
    return None

@app.route('/')
def index():
    return redirect(url_for('login') if not current_user.is_authenticated else url_for('dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        if db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone():
            flash('Пользователь уже существует', 'danger')
            return render_template('register.html')
        db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, generate_password_hash(password)))
        db.commit()
        flash('Регистрация успешна. Войдите.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            login_user(User(user['id'], user['username']))
            return redirect(url_for('dashboard'))
        flash('Неверное имя пользователя или пароль', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_transaction():
    if request.method == 'POST':
        amount = float(request.form['amount'])
        trans_type = request.form['type']
        category = request.form['category']
        date = request.form['date']
        description = request.form.get('description', '')
        db = get_db()
        db.execute('INSERT INTO transactions (user_id, amount, type, category, date, description) VALUES (?, ?, ?, ?, ?, ?)',
                   (current_user.id, amount, trans_type, category, date, description))
        db.commit()
        flash('Транзакция добавлена', 'success')
        return redirect(url_for('dashboard'))
    return render_template('add_transaction.html')

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    transactions = db.execute('SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC', (current_user.id,)).fetchall()
    
    total_income = sum(float(t['amount']) for t in transactions if t['type'] == 'income')
    total_expense = sum(float(t['amount']) for t in transactions if t['type'] == 'expense')
    balance = total_income - total_expense
    
    forecast_html = None
    rows = db.execute('SELECT date, SUM(amount) as daily_expense FROM transactions WHERE user_id = ? AND type = "expense" GROUP BY date ORDER BY date DESC LIMIT 30', (current_user.id,)).fetchall()
    if len(rows) >= 7:
        df = pd.DataFrame([(row['date'], float(row['daily_expense'])) for row in rows], columns=['date', 'expense']).sort_values('date')
        X = np.arange(len(df)).reshape(-1, 1)
        y = df['expense'].values
        model = LinearRegression().fit(X, y)
        forecast = np.maximum(model.predict(np.arange(len(df), len(df) + 7).reshape(-1, 1)), 0).tolist()
        df_forecast = pd.DataFrame({'День': range(1, 8), 'Прогноз расходов (₽)': forecast})
        fig = px.line(df_forecast, x='День', y='Прогноз расходов (₽)', title='Прогноз расходов на следующую неделю')
        forecast_html = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    pie_html = None
    expense_rows = db.execute('SELECT category, SUM(amount) as total FROM transactions WHERE user_id = ? AND type = "expense" GROUP BY category', (current_user.id,)).fetchall()
    if expense_rows:
        pie_df = pd.DataFrame({'Категория': [r['category'] for r in expense_rows], 'Сумма': [float(r['total']) for r in expense_rows]})
        fig_pie = px.pie(pie_df, values='Сумма', names='Категория', title='Расходы по категориям')
        pie_html = json.dumps(fig_pie, cls=plotly.utils.PlotlyJSONEncoder)
    
    recent = list(transactions[:10])
    return render_template('dashboard.html', balance=balance, total_income=total_income, total_expense=total_expense, pie_html=pie_html, forecast_html=forecast_html, recent=recent, len=len)

def get_forecast(user_id, db):
    pass

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
