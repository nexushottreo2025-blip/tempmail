from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, render_template_string, make_response
import requests
from bs4 import BeautifulSoup
import time
import json
import os
from datetime import datetime, timedelta
import hashlib
import secrets
from functools import wraps
from user_agents import parse

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)

# ============================================
# Database giả lập
# ============================================
class UserDB:
    def __init__(self, db_file="users.json"):
        self.db_file = db_file
        self._init_db()
    
    def _init_db(self):
        if not os.path.exists(self.db_file):
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)
    
    def _load_users(self):
        with open(self.db_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _save_users(self, users):
        with open(self.db_file, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
    
    def hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()
    
    def register(self, username, password):
        users = self._load_users()
        
        if username in users:
            return False, "Tên đăng nhập đã tồn tại!"
        
        users[username] = {
            'password': self.hash_password(password),
            'created_at': datetime.now().isoformat(),
            'last_login': None,
            'remember_me': False
        }
        
        self._save_users(users)
        return True, "Đăng ký thành công!"
    
    def login(self, username, password, remember_me=False):
        users = self._load_users()
        
        if username not in users:
            return False, "Tên đăng nhập không tồn tại!"
        
        if users[username]['password'] != self.hash_password(password):
            return False, "Sai mật khẩu!"
        
        users[username]['last_login'] = datetime.now().isoformat()
        users[username]['remember_me'] = remember_me
        self._save_users(users)
        
        return True, "Đăng nhập thành công!"

user_db = UserDB()

# ============================================
# Decorator yêu cầu đăng nhập
# ============================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': 'login_required', 'redirect': url_for('login_page')})
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# CLASS TempMailManager
# ============================================
class TempMailManager:
    def __init__(self, username):
        self.username = username
        safe_username = hashlib.md5(username.encode()).hexdigest()
        self.save_file = f"mails_{safe_username}.json"
        
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        self.email = None
        self.mail_data = None

    def _load_saved_mails(self):
        if os.path.exists(self.save_file):
            try:
                with open(self.save_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_mail_data(self, email, cookies, created_at=None):
        saved = self._load_saved_mails()
        cookies_dict = {k: v for k, v in cookies.items()}
        saved[email] = {
            "cookies": cookies_dict,
            "created_at": created_at or datetime.now().isoformat(),
            "last_used": datetime.now().isoformat()
        }
        with open(self.save_file, 'w', encoding='utf-8') as f:
            json.dump(saved, f, indent=2, ensure_ascii=False)
        return True

    def get_saved_emails_with_details(self):
        saved = self._load_saved_mails()
        result = []
        for email, data in saved.items():
            result.append({
                'email': email,
                'created_at': data.get('created_at', 'N/A'),
                'last_used': data.get('last_used', 'N/A')
            })
        return result

    def load_email_data(self, email):
        saved = self._load_saved_mails()
        data = saved.get(email)
        if data:
            self.session.cookies.clear()
            self.session.cookies.update(data["cookies"])
            self.email = email
            self.mail_data = data
            return True
        return False

    def get_new_email(self):
        url = "https://10minutemail.net/?lang=vi"
        response = self.session.get(url, headers=self.headers)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            email_input = soup.find("input", {"id": "fe_text"})
            
            if email_input and email_input.get("value"):
                self.email = email_input["value"]
                self._save_mail_data(self.email, self.session.cookies.get_dict())
                return self.email
        return None

    def recover_email(self, email):
        if self.load_email_data(email):
            url = "https://10minutemail.net/?lang=vi"
            response = self.session.get(url, headers=self.headers)
            if response.status_code == 200:
                saved = self._load_saved_mails()
                if email in saved:
                    saved[email]["last_used"] = datetime.now().isoformat()
                    with open(self.save_file, 'w', encoding='utf-8') as f:
                        json.dump(saved, f, indent=2, ensure_ascii=False)
                return True
        return False

    def delete_email(self, email):
        saved = self._load_saved_mails()
        if email in saved:
            del saved[email]
            with open(self.save_file, 'w', encoding='utf-8') as f:
                json.dump(saved, f, indent=2, ensure_ascii=False)
            return True
        return False

    def get_mail_content(self, mail_id):
        """Lấy nội dung chi tiết của một email"""
        if not self.email:
            return None
            
        url = f"https://10minutemail.net/mail.php?mid={mail_id}"
        response = self.session.get(url, headers=self.headers)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Tìm nội dung email
            content_div = soup.find("div", class_="mail-body") or soup.find("div", {"id": "mailbody"})
            if content_div:
                return str(content_div)
        return None

    def check_mailbox(self):
        if not self.email:
            return None

        url = "https://10minutemail.net/mailbox.ajax.php"
        params = {"_": int(time.time() * 1000)}
        
        response = self.session.get(url, headers=self.headers, params=params)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            mails = soup.find_all("tr", class_="mail_row") or soup.find_all("tr", attrs={"style": "font-weight: bold; cursor: pointer;"})
            
            mail_list = []
            for mail in mails:
                mail_id = None
                mail_link = mail.find("a", class_="row-link")
                if mail_link and mail_link.get('href'):
                    import re
                    match = re.search(r'mid=(\d+)', mail_link['href'])
                    if match:
                        mail_id = match.group(1)
                
                cells = mail.find_all("td")
                if len(cells) >= 3:
                    sender = cells[0].get_text(strip=True)
                    subject = cells[1].get_text(strip=True)
                    time_received = cells[2].get_text(strip=True)
                    mail_list.append({
                        'id': mail_id,
                        'sender': sender,
                        'subject': subject,
                        'time': time_received,
                        'has_content': mail_id is not None
                    })
                else:
                    links = mail.find_all("a", class_="row-link")
                    if len(links) >= 2:
                        sender = links[0].get_text(strip=True)
                        subject = links[1].get_text(strip=True)
                        mail_list.append({
                            'id': mail_id,
                            'sender': sender,
                            'subject': subject,
                            'time': 'N/A',
                            'has_content': mail_id is not None
                        })
            return mail_list
        return None


# ============================================
# Flask Routes
# ============================================

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember_me = request.form.get('remember_me') == 'on'
        
        success, message = user_db.login(username, password, remember_me)
        
        if success:
            session.permanent = remember_me
            session['username'] = username
            resp = make_response(redirect(url_for('dashboard')))
            if remember_me:
                resp.set_cookie('remember_me', username, max_age=30*24*60*60)
            return resp
        else:
            flash(message, 'error')
    
    return render_template_string(LOGIN_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register_page():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Mật khẩu xác nhận không khớp!', 'error')
        else:
            success, message = user_db.register(username, password)
            if success:
                flash(message, 'success')
                return redirect(url_for('login_page'))
            else:
                flash(message, 'error')
    
    return render_template_string(REGISTER_HTML)

@app.route('/logout')
def logout():
    session.pop('username', None)
    resp = make_response(redirect(url_for('login_page')))
    resp.delete_cookie('remember_me')
    return resp

@app.route('/dashboard')
@login_required
def dashboard():
    # Kiểm tra device
    user_agent_string = request.headers.get('User-Agent')
    user_agent = parse(user_agent_string)
    is_mobile = user_agent.is_mobile
    
    return render_template_string(DASHBOARD_HTML, 
                                 username=session['username'],
                                 is_mobile=is_mobile)

@app.route('/api/emails')
@login_required
def get_emails():
    manager = TempMailManager(session['username'])
    emails = manager.get_saved_emails_with_details()
    return jsonify({'success': True, 'emails': emails})

@app.route('/api/create_email', methods=['POST'])
@login_required
def create_email():
    manager = TempMailManager(session['username'])
    email = manager.get_new_email()
    if email:
        return jsonify({'success': True, 'email': email})
    return jsonify({'success': False, 'error': 'Không thể tạo email'})

@app.route('/api/recover_email', methods=['POST'])
@login_required
def recover_email():
    data = request.json
    email = data.get('email')
    manager = TempMailManager(session['username'])
    if manager.recover_email(email):
        return jsonify({'success': True, 'email': email})
    return jsonify({'success': False, 'error': 'Không thể khôi phục email'})

@app.route('/api/delete_email', methods=['POST'])
@login_required
def delete_email():
    data = request.json
    email = data.get('email')
    manager = TempMailManager(session['username'])
    if manager.delete_email(email):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Không thể xóa email'})

@app.route('/api/check_mailbox')
@login_required
def check_mailbox():
    email = request.args.get('email')
    if not email:
        return jsonify({'success': False, 'error': 'Chưa chọn email'})
    
    manager = TempMailManager(session['username'])
    if manager.load_email_data(email):
        mails = manager.check_mailbox()
        return jsonify({'success': True, 'mails': mails, 'email': email})
    return jsonify({'success': False, 'error': 'Không thể kiểm tra hộp thư'})

@app.route('/api/get_mail_content')
@login_required
def get_mail_content():
    mail_id = request.args.get('mail_id')
    email = request.args.get('email')
    
    if not mail_id or not email:
        return jsonify({'success': False, 'error': 'Thiếu thông tin'})
    
    manager = TempMailManager(session['username'])
    if manager.load_email_data(email):
        content = manager.get_mail_content(mail_id)
        if content:
            return jsonify({'success': True, 'content': content})
    
    return jsonify({'success': False, 'error': 'Không thể lấy nội dung'})

@app.route('/api/keep_alive')
@login_required
def keep_alive():
    """API để giữ session sống"""
    return jsonify({'success': True, 'time': datetime.now().isoformat()})


# ============================================
# HTML Templates - Theme tối như Worm GPT
# ============================================

LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Đăng nhập - TempMail</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #0a0a0a;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            color: #e0e0e0;
        }
        
        .container {
            background: #1a1a1a;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.05);
            width: 90%;
            max-width: 400px;
            padding: 40px;
            border: 1px solid #2a2a2a;
        }
        
        h2 {
            text-align: center;
            color: #fff;
            margin-bottom: 30px;
            font-size: 2em;
            font-weight: 500;
            letter-spacing: -0.5px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            color: #a0a0a0;
            font-weight: 400;
            font-size: 0.9em;
            letter-spacing: 0.3px;
        }
        
        input[type="text"], input[type="password"] {
            width: 100%;
            padding: 12px 16px;
            background: #0d0d0d;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
            font-size: 1em;
            transition: all 0.3s;
            color: #fff;
        }
        
        input:focus {
            outline: none;
            border-color: #10a37f;
            background: #000;
            box-shadow: 0 0 0 2px rgba(16, 163, 127, 0.2);
        }
        
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .checkbox-group input[type="checkbox"] {
            width: 18px;
            height: 18px;
            accent-color: #10a37f;
        }
        
        button {
            width: 100%;
            padding: 14px;
            background: #10a37f;
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 1.1em;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
            margin-top: 10px;
        }
        
        button:hover {
            background: #0d8b6c;
            transform: translateY(-1px);
            box-shadow: 0 10px 25px rgba(16, 163, 127, 0.3);
        }
        
        .links {
            text-align: center;
            margin-top: 25px;
        }
        
        .links a {
            color: #10a37f;
            text-decoration: none;
            font-size: 0.95em;
            transition: color 0.3s;
        }
        
        .links a:hover {
            color: #0d8b6c;
            text-decoration: underline;
        }
        
        .error {
            background: rgba(220, 38, 38, 0.1);
            color: #ef4444;
            padding: 12px;
            border-radius: 12px;
            margin-bottom: 20px;
            text-align: center;
            border: 1px solid rgba(239, 68, 68, 0.2);
            font-size: 0.95em;
        }
        
        .footer {
            margin-top: 20px;
            text-align: center;
            color: #404040;
            font-size: 0.9em;
        }
        
        .footer span {
            color: #10a37f;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>🔐 Đăng nhập</h2>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="error">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="POST" action="/login">
            <div class="form-group">
                <label>Tên đăng nhập</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>Mật khẩu</label>
                <input type="password" name="password" required>
            </div>
            <div class="form-group checkbox-group">
                <input type="checkbox" name="remember_me" id="remember_me">
                <label for="remember_me">Ghi nhớ đăng nhập (30 ngày)</label>
            </div>
            <button type="submit">Đăng nhập</button>
        </form>
        
        <div class="links">
            Chưa có tài khoản? <a href="/register">Đăng ký ngay</a>
        </div>
    </div>
    
    <div class="footer">
        by <span>Dinh Xuan Thang</span>
    </div>
</body>
</html>
'''

REGISTER_HTML = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Đăng ký - TempMail</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #0a0a0a;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            color: #e0e0e0;
        }
        
        .container {
            background: #1a1a1a;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.05);
            width: 90%;
            max-width: 400px;
            padding: 40px;
            border: 1px solid #2a2a2a;
        }
        
        h2 {
            text-align: center;
            color: #fff;
            margin-bottom: 30px;
            font-size: 2em;
            font-weight: 500;
            letter-spacing: -0.5px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            color: #a0a0a0;
            font-weight: 400;
            font-size: 0.9em;
            letter-spacing: 0.3px;
        }
        
        input {
            width: 100%;
            padding: 12px 16px;
            background: #0d0d0d;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
            font-size: 1em;
            transition: all 0.3s;
            color: #fff;
        }
        
        input:focus {
            outline: none;
            border-color: #10a37f;
            background: #000;
            box-shadow: 0 0 0 2px rgba(16, 163, 127, 0.2);
        }
        
        button {
            width: 100%;
            padding: 14px;
            background: #10a37f;
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 1.1em;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
            margin-top: 10px;
        }
        
        button:hover {
            background: #0d8b6c;
            transform: translateY(-1px);
            box-shadow: 0 10px 25px rgba(16, 163, 127, 0.3);
        }
        
        .links {
            text-align: center;
            margin-top: 25px;
        }
        
        .links a {
            color: #10a37f;
            text-decoration: none;
            font-size: 0.95em;
            transition: color 0.3s;
        }
        
        .links a:hover {
            color: #0d8b6c;
            text-decoration: underline;
        }
        
        .error {
            background: rgba(220, 38, 38, 0.1);
            color: #ef4444;
            padding: 12px;
            border-radius: 12px;
            margin-bottom: 20px;
            text-align: center;
            border: 1px solid rgba(239, 68, 68, 0.2);
            font-size: 0.95em;
        }
        
        .success {
            background: rgba(16, 163, 127, 0.1);
            color: #10a37f;
            padding: 12px;
            border-radius: 12px;
            margin-bottom: 20px;
            text-align: center;
            border: 1px solid rgba(16, 163, 127, 0.2);
            font-size: 0.95em;
        }
        
        .footer {
            margin-top: 20px;
            text-align: center;
            color: #404040;
            font-size: 0.9em;
        }
        
        .footer span {
            color: #10a37f;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>📝 Đăng ký</h2>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="{{ 'success' if category == 'success' else 'error' }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="POST" action="/register">
            <div class="form-group">
                <label>Tên đăng nhập</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>Mật khẩu</label>
                <input type="password" name="password" required>
            </div>
            <div class="form-group">
                <label>Xác nhận mật khẩu</label>
                <input type="password" name="confirm_password" required>
            </div>
            <button type="submit">Đăng ký</button>
        </form>
        
        <div class="links">
            Đã có tài khoản? <a href="/login">Đăng nhập</a>
        </div>
    </div>
    
    <div class="footer">
        by <span>Dinh Xuan Thang</span>
    </div>
</body>
</html>
'''

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>Dashboard - TempMail</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            min-height: 100vh;
        }
        
        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: #1a1a1a;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #3a3a3a;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #4a4a4a;
        }
        
        .navbar {
            background: #1a1a1a;
            padding: 16px 24px;
            color: white;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.5);
            border-bottom: 1px solid #2a2a2a;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .navbar-brand {
            font-size: 1.4em;
            font-weight: 600;
            background: linear-gradient(135deg, #10a37f, #0d8b6c);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }
        
        .navbar-user {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        .username {
            background: #2a2a2a;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.95em;
            color: #e0e0e0;
            border: 1px solid #3a3a3a;
        }
        
        .logout-btn {
            background: #2a2a2a;
            color: #ff6b6b;
            text-decoration: none;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.95em;
            transition: all 0.3s;
            border: 1px solid #3a3a3a;
        }
        
        .logout-btn:hover {
            background: #3a3a3a;
            color: #ff5252;
        }
        
        .container {
            max-width: 1600px;
            margin: 24px auto;
            padding: 0 20px;
            display: grid;
            grid-template-columns: 350px 1fr;
            gap: 24px;
        }
        
        /* Mobile styles */
        {% if is_mobile %}
        .container {
            grid-template-columns: 1fr;
        }
        
        .sidebar {
            position: fixed;
            left: -100%;
            top: 70px;
            width: 85%;
            height: calc(100vh - 70px);
            transition: left 0.3s ease;
            z-index: 99;
            border-radius: 0 20px 20px 0;
        }
        
        .sidebar.show {
            left: 0;
        }
        
        .menu-toggle {
            display: block;
            background: #2a2a2a;
            border: 1px solid #3a3a3a;
            color: #10a37f;
            font-size: 1.5em;
            padding: 8px 15px;
            border-radius: 12px;
            margin-right: 15px;
            cursor: pointer;
        }
        {% else %}
        .menu-toggle {
            display: none;
        }
        {% endif %}
        
        .sidebar {
            background: #1a1a1a;
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            border: 1px solid #2a2a2a;
            height: fit-content;
            backdrop-filter: blur(10px);
        }
        
        .main-content {
            background: #1a1a1a;
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            border: 1px solid #2a2a2a;
            min-height: 600px;
        }
        
        .section-title {
            color: #fff;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid #2a2a2a;
            font-size: 1.3em;
            font-weight: 500;
            letter-spacing: -0.3px;
        }
        
        .section-title::before {
            content: '▍';
            color: #10a37f;
            margin-right: 8px;
        }
        
        .btn {
            padding: 12px 20px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.3s;
            width: 100%;
            margin-bottom: 12px;
            font-size: 1em;
            letter-spacing: 0.3px;
        }
        
        .btn-primary {
            background: #10a37f;
            color: white;
        }
        
        .btn-primary:hover {
            background: #0d8b6c;
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(16, 163, 127, 0.3);
        }
        
        .btn-danger {
            background: #2a2a2a;
            color: #ff6b6b;
            border: 1px solid #3a3a3a;
        }
        
        .btn-danger:hover {
            background: #3a3a3a;
            color: #ff5252;
        }
        
        .btn-secondary {
            background: #2a2a2a;
            color: #a0a0a0;
            border: 1px solid #3a3a3a;
        }
        
        .email-list {
            list-style: none;
            max-height: 500px;
            overflow-y: auto;
            padding-right: 5px;
        }
        
        .email-item {
            padding: 16px;
            background: #0d0d0d;
            border: 1px solid #2a2a2a;
            border-radius: 16px;
            margin-bottom: 12px;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .email-item:hover {
            border-color: #10a37f;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(16, 163, 127, 0.1);
        }
        
        .email-item.active {
            border-color: #10a37f;
            background: #0f0f0f;
            box-shadow: 0 0 0 1px #10a37f;
        }
        
        .email-address {
            font-weight: 600;
            color: #fff;
            word-break: break-all;
            font-size: 0.95em;
            margin-bottom: 8px;
        }
        
        .email-meta {
            font-size: 0.85em;
            color: #808080;
            margin-top: 8px;
            line-height: 1.5;
        }
        
        .mailbox {
            min-height: 500px;
        }
        
        .mail-item {
            padding: 16px;
            background: #0d0d0d;
            border: 1px solid #2a2a2a;
            border-radius: 16px;
            margin-bottom: 12px;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .mail-item:hover {
            border-color: #10a37f;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(16, 163, 127, 0.1);
        }
        
        .mail-item:last-child {
            margin-bottom: 0;
        }
        
        .mail-sender {
            font-weight: 600;
            color: #10a37f;
            font-size: 1em;
            margin-bottom: 6px;
        }
        
        .mail-subject {
            color: #e0e0e0;
            margin: 8px 0;
            font-size: 0.95em;
            line-height: 1.5;
        }
        
        .mail-time {
            font-size: 0.8em;
            color: #808080;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .mail-time::before {
            content: '⏱️';
            opacity: 0.7;
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #505050;
            font-size: 1.1em;
        }
        
        .empty-state::before {
            content: '📭';
            display: block;
            font-size: 3em;
            margin-bottom: 15px;
            opacity: 0.5;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #10a37f;
        }
        
        .loading::after {
            content: '...';
            animation: dots 1.5s steps(4, end) infinite;
        }
        
        @keyframes dots {
            0%, 20% { content: '.'; }
            40% { content: '..'; }
            60%, 100% { content: '...'; }
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            backdrop-filter: blur(5px);
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        
        .modal-content {
            background: #1a1a1a;
            padding: 30px;
            border-radius: 24px;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
            border: 1px solid #2a2a2a;
            box-shadow: 0 25px 50px rgba(0,0,0,0.5);
        }
        
        .modal-title {
            font-size: 1.3em;
            font-weight: 600;
            color: #fff;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid #2a2a2a;
        }
        
        .modal-title::before {
            content: '📧';
            margin-right: 10px;
        }
        
        .modal-body {
            margin-bottom: 25px;
            color: #e0e0e0;
            line-height: 1.6;
        }
        
        .modal-buttons {
            display: flex;
            gap: 12px;
            margin-top: 25px;
        }
        
        .modal-btn {
            flex: 1;
            padding: 12px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-weight: 500;
            font-size: 0.95em;
            transition: all 0.3s;
        }
        
        .close-btn {
            background: #2a2a2a;
            color: #e0e0e0;
            border: 1px solid #3a3a3a;
        }
        
        .close-btn:hover {
            background: #3a3a3a;
        }
        
        .confirm-btn {
            background: #ef4444;
            color: white;
        }
        
        .confirm-btn:hover {
            background: #dc2626;
        }
        
        .cancel-btn {
            background: #2a2a2a;
            color: #e0e0e0;
            border: 1px solid #3a3a3a;
        }
        
        .cancel-btn:hover {
            background: #3a3a3a;
        }
        
        .refresh-btn {
            background: #2a2a2a;
            color: #10a37f;
            padding: 8px 16px;
            border: 1px solid #3a3a3a;
            border-radius: 20px;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.3s;
        }
        
        .refresh-btn:hover {
            background: #3a3a3a;
            border-color: #10a37f;
        }
        
        .header-actions {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .current-email-badge {
            background: #0d0d0d;
            padding: 8px 16px;
            border-radius: 20px;
            color: #10a37f;
            font-weight: 500;
            font-size: 0.95em;
            word-break: break-all;
            border: 1px solid #2a2a2a;
        }
        
        .current-email-badge::before {
            content: '📬 ';
            opacity: 0.7;
        }
        
        .mail-content {
            font-family: inherit;
            line-height: 1.6;
        }
        
        .mail-content img {
            max-width: 100%;
            height: auto;
            border-radius: 8px;
        }
        
        .mail-content table {
            max-width: 100%;
            overflow-x: auto;
            display: block;
            border-collapse: collapse;
        }
        
        .mail-content a {
            color: #10a37f;
            text-decoration: none;
        }
        
        .mail-content a:hover {
            text-decoration: underline;
        }
        
        .status-bar {
            background: #0d0d0d;
            padding: 12px 24px;
            margin: 0 20px 20px;
            border-radius: 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.95em;
            border: 1px solid #2a2a2a;
            max-width: 1600px;
            margin: 0 auto 20px;
        }
        
        .online-status {
            color: #10a37f;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .online-status::before {
            content: '●';
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .footer {
            text-align: center;
            padding: 20px;
            color: #404040;
            font-size: 0.9em;
            border-top: 1px solid #2a2a2a;
            margin-top: 30px;
        }
        
        .footer span {
            color: #10a37f;
        }
        
        @media (max-width: 768px) {
            .status-bar {
                margin: 0 15px 15px;
                padding: 10px 15px;
                font-size: 0.85em;
            }
            
            .current-email-badge {
                max-width: 100%;
                font-size: 0.85em;
            }
            
            .header-actions {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .modal-content {
                padding: 20px;
                width: 95%;
            }
        }
    </style>
</head>
<body>
    <div class="navbar">
        <div style="display: flex; align-items: center;">
            {% if is_mobile %}
            <button class="menu-toggle" onclick="toggleSidebar()">☰</button>
            {% endif %}
            <div class="navbar-brand">⚡ TempMail</div>
        </div>
        <div class="navbar-user">
            <span class="username">👤 {{ username }}</span>
            <a href="/logout" class="logout-btn">Đăng xuất</a>
        </div>
    </div>
    
    <div class="status-bar">
        <span>🔐 <strong>{{ username }}</strong></span>
        <span class="online-status">Online</span>
    </div>
    
    <div class="container">
        <!-- Sidebar - Danh sách email -->
        <div class="sidebar" id="sidebar">
            <h3 class="section-title">Email của tôi</h3>
            <button class="btn btn-primary" onclick="createNewEmail()">
                ✨ Tạo email mới
            </button>
            
            <div style="margin-top: 20px;">
                <h4 style="color: #a0a0a0; margin-bottom: 15px; font-size: 0.95em;">Danh sách đã lưu</h4>
                <ul class="email-list" id="emailList">
                    <li class="loading">Đang tải</li>
                </ul>
            </div>
        </div>
        
        <!-- Main - Hộp thư -->
        <div class="main-content">
            <div class="header-actions">
                <h3 class="section-title" style="margin-bottom: 0;">Hộp thư đến</h3>
                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <span class="current-email-badge" id="currentEmailDisplay">Chưa chọn email</span>
                    <button class="refresh-btn" onclick="checkMailbox()">⟳ Làm mới</button>
                </div>
            </div>
            
            <div class="mailbox" id="mailbox">
                <div class="empty-state">
                    Chọn email từ danh sách
                </div>
            </div>
        </div>
    </div>
    
    <!-- Modal xem nội dung email -->
    <div class="modal" id="mailContentModal">
        <div class="modal-content">
            <div class="modal-title" id="mailModalTitle">Nội dung email</div>
            <div class="modal-body" id="mailModalBody">
                <div class="loading">Đang tải</div>
            </div>
            <div class="modal-buttons">
                <button class="modal-btn close-btn" onclick="closeMailModal()">Đóng</button>
            </div>
        </div>
    </div>
    
    <!-- Modal xác nhận xóa -->
    <div class="modal" id="deleteModal">
        <div class="modal-content">
            <div class="modal-title">Xác nhận xóa</div>
            <p style="color: #e0e0e0; line-height: 1.6;">Bạn có chắc muốn xóa email này khỏi danh sách lưu trữ?</p>
            <div class="modal-buttons">
                <button class="modal-btn cancel-btn" onclick="closeDeleteModal()">Hủy</button>
                <button class="modal-btn confirm-btn" id="confirmDeleteBtn">Xóa</button>
            </div>
        </div>
    </div>
    
    <!-- Footer -->
    <div class="footer">
        by <span>Dinh Xuan Thang</span>
    </div>
    
    <script>
        let currentEmail = null;
        let emailToDelete = null;
        let keepAliveInterval = null;
        
        // Tải danh sách email khi trang load
        loadEmails();
        
        // Giữ session sống
        startKeepAlive();
        
        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('show');
        }
        
        function startKeepAlive() {
            keepAliveInterval = setInterval(async () => {
                try {
                    await fetch('/api/keep_alive');
                } catch (error) {
                    console.log('Keep alive error:', error);
                }
            }, 5 * 60 * 1000);
        }
        
        async function loadEmails() {
            try {
                const response = await fetch('/api/emails');
                const data = await response.json();
                
                if (data.success) {
                    renderEmailList(data.emails);
                } else if (data.error === 'login_required') {
                    window.location.href = data.redirect;
                }
            } catch (error) {
                console.error('Lỗi:', error);
            }
        }
        
        function renderEmailList(emails) {
            const emailList = document.getElementById('emailList');
            
            if (emails.length === 0) {
                emailList.innerHTML = '<li class="empty-state">Chưa có email</li>';
                return;
            }
            
            emailList.innerHTML = emails.map(email => {
                const created = new Date(email.created_at).toLocaleString('vi-VN');
                const lastUsed = new Date(email.last_used).toLocaleString('vi-VN');
                return `
                    <li class="email-item ${currentEmail === email.email ? 'active' : ''}" 
                        onclick="selectEmail('${email.email}')">
                        <div class="email-address">${email.email}</div>
                        <div class="email-meta">
                            <div>📅 Tạo: ${created}</div>
                            <div>⏰ Dùng: ${lastUsed}</div>
                        </div>
                        <button class="btn btn-danger" style="margin-top: 12px;" 
                                onclick="event.stopPropagation(); showDeleteModal('${email.email}')">
                            🗑️ Xóa
                        </button>
                    </li>
                `;
            }).join('');
        }
        
        async function createNewEmail() {
            try {
                const response = await fetch('/api/create_email', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'}
                });
                const data = await response.json();
                
                if (data.success) {
                    alert('✅ Tạo email thành công: ' + data.email);
                    loadEmails();
                    selectEmail(data.email);
                } else {
                    alert('❌ ' + data.error);
                }
            } catch (error) {
                alert('❌ Lỗi kết nối');
            }
        }
        
        async function selectEmail(email) {
            currentEmail = email;
            document.getElementById('currentEmailDisplay').textContent = email;
            
            document.querySelectorAll('.email-item').forEach(item => {
                item.classList.remove('active');
            });
            event.currentTarget.classList.add('active');
            
            if (window.innerWidth <= 768) {
                document.getElementById('sidebar').classList.remove('show');
            }
            
            await checkMailbox();
        }
        
        async function checkMailbox() {
            if (!currentEmail) {
                alert('Vui lòng chọn email!');
                return;
            }
            
            const mailbox = document.getElementById('mailbox');
            mailbox.innerHTML = '<div class="loading">Đang kiểm tra</div>';
            
            try {
                const response = await fetch(`/api/check_mailbox?email=${encodeURIComponent(currentEmail)}`);
                const data = await response.json();
                
                if (data.success) {
                    if (data.mails && data.mails.length > 0) {
                        mailbox.innerHTML = data.mails.map(mail => `
                            <div class="mail-item" onclick="showMailContent('${mail.id}', '${currentEmail}')">
                                <div class="mail-sender">📧 ${mail.sender}</div>
                                <div class="mail-subject">📝 ${mail.subject}</div>
                                <div class="mail-time">${mail.time}</div>
                            </div>
                        `).join('');
                    } else {
                        mailbox.innerHTML = '<div class="empty-state">Hộp thư trống</div>';
                    }
                } else {
                    mailbox.innerHTML = `<div class="empty-state">❌ ${data.error}</div>`;
                }
            } catch (error) {
                mailbox.innerHTML = '<div class="empty-state">❌ Lỗi kết nối</div>';
            }
        }
        
        async function showMailContent(mailId, email) {
            if (!mailId) {
                alert('Không thể đọc nội dung email này');
                return;
            }
            
            document.getElementById('mailModalTitle').textContent = 'Đang tải...';
            document.getElementById('mailModalBody').innerHTML = '<div class="loading">Đang tải</div>';
            document.getElementById('mailContentModal').style.display = 'flex';
            
            try {
                const response = await fetch(`/api/get_mail_content?mail_id=${mailId}&email=${encodeURIComponent(email)}`);
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('mailModalTitle').textContent = 'Nội dung email';
                    document.getElementById('mailModalBody').innerHTML = `<div class="mail-content">${data.content}</div>`;
                } else {
                    document.getElementById('mailModalBody').innerHTML = `<div class="empty-state">❌ ${data.error}</div>`;
                }
            } catch (error) {
                document.getElementById('mailModalBody').innerHTML = '<div class="empty-state">❌ Lỗi kết nối</div>';
            }
        }
        
        function closeMailModal() {
            document.getElementById('mailContentModal').style.display = 'none';
        }
        
        function showDeleteModal(email) {
            emailToDelete = email;
            document.getElementById('deleteModal').style.display = 'flex';
        }
        
        function closeDeleteModal() {
            document.getElementById('deleteModal').style.display = 'none';
            emailToDelete = null;
        }
        
        document.getElementById('confirmDeleteBtn').onclick = async function() {
            if (!emailToDelete) return;
            
            try {
                const response = await fetch('/api/delete_email', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email: emailToDelete})
                });
                const data = await response.json();
                
                if (data.success) {
                    alert('✅ Xóa email thành công');
                    if (currentEmail === emailToDelete) {
                        currentEmail = null;
                        document.getElementById('currentEmailDisplay').textContent = 'Chưa chọn email';
                        document.getElementById('mailbox').innerHTML = '<div class="empty-state">Chọn email từ danh sách</div>';
                    }
                    loadEmails();
                } else {
                    alert('❌ ' + data.error);
                }
            } catch (error) {
                alert('❌ Lỗi kết nối');
            }
            
            closeDeleteModal();
        };
        
        setInterval(() => {
            if (currentEmail) {
                checkMailbox();
            }
        }, 30000);
        
        window.onclick = function(event) {
            const mailModal = document.getElementById('mailContentModal');
            const deleteModal = document.getElementById('deleteModal');
            
            if (event.target === mailModal) {
                mailModal.style.display = 'none';
            }
            if (event.target === deleteModal) {
                deleteModal.style.display = 'none';
            }
        };
        
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeMailModal();
                closeDeleteModal();
            }
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    try:
        from user_agents import parse
    except ImportError:
        os.system('pip install user-agents')
        from user_agents import parse
    
    print("""
    ╔══════════════════════════════════════╗
    ║     TempMail - by Dinh Xuan Thang    ║
    ║         Đang chạy tại:               ║
    ║     http://localhost:5000            ║
    ╚══════════════════════════════════════╝
    """)
    
    app.run(debug=True, host='0.0.0.0', port=5000)