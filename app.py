from flask import Flask, render_template, request, redirect, session, flash, make_response, jsonify, url_for
from flask_mail import Message
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail as SGMail
import psycopg2
import psycopg2.extras
import bcrypt
import random
import config
import os
from werkzeug.utils import secure_filename
import requests

# Telegram settings (can be set via config or environment)
BOT_TOKEN = getattr(config, 'TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')   
DEFAULT_TELEGRAM_CHAT_ID = getattr(config, 'TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID')

def send_telegram_message(chat_id_or_none, message):
    chat_id = chat_id_or_none or DEFAULT_TELEGRAM_CHAT_ID
    if not chat_id or chat_id in ('YOUR_CHAT_ID', ''):
        app.logger.warning('send_telegram_message: no valid chat_id, skipping')
        return
    if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN':
        app.logger.warning('send_telegram_message: BOT_TOKEN not configured, skipping')
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=5)
        app.logger.info('Telegram response: %s %s', resp.status_code, resp.text)
    except Exception as e:
        app.logger.exception('Failed to send Telegram message: %s', e)
import razorpay
import traceback
import uuid
from utils.pdf_generator import generate_pdf
from datetime import datetime
import cloudinary
import cloudinary.uploader
from authlib.integrations.flask_client import OAuth
from authlib.jose.errors import InvalidClaimError
import requests
import pyotp
import qrcode
import base64
import io


app = Flask(__name__)
if config.CLOUDINARY_URL:
    try:
        cloudinary.config(cloudinary_url=config.CLOUDINARY_URL)
    except Exception:
        app.logger.warning('Invalid CLOUDINARY_URL provided; falling back to individual vars')
else:
    # use explicit parts if present
    try:
        cloudinary.config(
            cloud_name=config.CLOUDINARY.get('cloud_name'),
            api_key=config.CLOUDINARY.get('api_key'),
            api_secret=config.CLOUDINARY.get('api_secret')
        )
    except Exception:
        app.logger.warning('Cloudinary not configured via env vars')

# Template helpers to resolve image URLs stored in DB. If the stored value is
# already a full URL (Cloudinary), return it. Otherwise, return a static URL
# under `uploads/<folder>/`.
def resolve_image_url(img, folder='product_images'):
    if not img:
        return ''
    try:
        # normalize to str
        if not isinstance(img, str):
            try:
                img = img.decode() if isinstance(img, (bytes, bytearray)) else str(img)
            except Exception:
                img = str(img)

        # strip surrounding whitespace and quotes/brackets
        img = img.strip()
        if (img.startswith('"') and img.endswith('"')) or (img.startswith("'") and img.endswith("'")):
            img = img[1:-1].strip()
        # if stored as a JSON-like list or joined with ||, pick first candidate
        if img.startswith('[') and 'http' in img:
            # attempt to find the first http URL inside
            import re
            m = re.search(r'(https?://[^\]\",\']+)', img)
            if m:
                return m.group(1)
        # handle values joined by '||'
        if '||' in img:
            img_candidate = img.split('||')[0].strip()
            if img_candidate:
                img = img_candidate

        if img.startswith('http'):
            return img
        # handle cases where a dict-like string contains secure_url
        if 'secure_url' in img and 'http' in img:
            import re
            m = re.search(r'https?://[^\s\'\"]+', img)
            if m:
                return m.group(0)
    except Exception:
        pass
    # fallback to local static uploads path
    return url_for('static', filename=f'uploads/{folder}/' + img)

def resolve_admin_image(img):
    return resolve_image_url(img, folder='admin_profiles')

app.jinja_env.globals['resolve_image_url'] = resolve_image_url
app.jinja_env.globals['resolve_admin_image'] = resolve_admin_image


@app.template_filter('fdate')
def fdate_filter(value, fmt='%d %b %Y'):
    if not value:
        return '-'
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:19], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return value
    return value.strftime(fmt)

app.secret_key = config.SECRET_KEY
if not app.secret_key:
    app.logger.warning('SECRET_KEY is not set — session cookies may not be persistent across processes')

# --- OAuth setup (Google, Facebook)
oauth = OAuth(app)

# Register Google using OIDC discovery
if getattr(config, 'GOOGLE_CLIENT_ID', None) and getattr(config, 'GOOGLE_CLIENT_SECRET', None):
    oauth.register(
        name='google',
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

    # Register Microsoft (Azure AD / Microsoft Account)
if getattr(config, 'MICROSOFT_CLIENT_ID', None) and getattr(config, 'MICROSOFT_CLIENT_SECRET', None):
    # Prefer tenant-specific discovery when MICROSOFT_TENANT_ID is set to avoid
    # issuer (iss) mismatch errors from Azure AD. Fall back to `common` otherwise.
    tenant = getattr(config, 'MICROSOFT_TENANT_ID', None)
    if tenant:
        server_metadata = f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"
    else:
        server_metadata = 'https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration'

    oauth.register(
        name='microsoft',
        client_id=config.MICROSOFT_CLIENT_ID,
        client_secret=config.MICROSOFT_CLIENT_SECRET,
        server_metadata_url=server_metadata,
        client_kwargs={'scope': 'openid email public_profile'}
    )
# Register Facebook (Graph API)
if getattr(config, 'FACEBOOK_CLIENT_ID', None) and getattr(config, 'FACEBOOK_CLIENT_SECRET', None):
    oauth.register(
        name='facebook',
        client_id=config.FACEBOOK_CLIENT_ID,
        client_secret=config.FACEBOOK_CLIENT_SECRET,
        api_base_url='https://graph.facebook.com/',
        access_token_url='https://graph.facebook.com/v12.0/oauth/access_token',
        authorize_url='https://www.facebook.com/v12.0/dialog/oauth',
        # Request valid Facebook scopes. Use space-separated scopes for FB.
        client_kwargs={'scope': 'email public_profile'},
    )

razorpay_client = razorpay.Client(
    auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET)
)

app.config['MAIL_SERVER'] = config.MAIL_SERVER
app.config['MAIL_PORT'] = config.MAIL_PORT
app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
app.config['MAIL_USE_SSL'] = config.MAIL_USE_SSL
app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD
if getattr(config, 'MAIL_USERNAME', None):
    app.config['MAIL_DEFAULT_SENDER'] = config.MAIL_USERNAME

import threading

def send_email(msg):
    def _send():
        with app.app_context():
            try:
                sg_api_key = getattr(config, 'SENDGRID_API_KEY', None)

                if not sg_api_key:
                    print("No SendGrid API key")
                    return

                if isinstance(msg, Message):
                    subject = msg.subject
                    recipients = msg.recipients
                    body = msg.body
                    sender = app.config.get('MAIL_DEFAULT_SENDER')

                print("Sending email to:", recipients)

                sg = SendGridAPIClient(sg_api_key)

                email = SGMail(
                    from_email=sender,
                    to_emails=recipients,
                    subject=subject,
                    plain_text_content=body
                )

                response = sg.send(email)
                print("Email sent:", response.status_code)

            except Exception as e:
                print("Error sending email:", e)

    threading.Thread(target=_send).start()

@app.route('/debug/admin-pw/<email>')
def debug_admin_pw(email):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT email, password FROM admin WHERE email=%s", (email,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'not found'})
    pw = row['password']
    return jsonify({
        'email': row['email'],
        'type': str(type(pw)),
        'repr': repr(pw[:30] if pw else None),
        'starts_with_2b': str(pw).startswith('$2b$') if pw else False,
        'length': len(pw) if pw else 0
    })

@app.route('/_email-test', methods=['GET'])
def email_test():
    """Quick test route: /_email-test?to=you@example.com&subject=hi"""
    to = request.args.get('to')
    subject = request.args.get('subject', 'Test email from ShopCart')
    body = request.args.get('body', 'This is a test email. If you receive this, SMTP works.')
    if not to:
        return jsonify({'ok': False, 'error': 'missing `to` param'}), 400
    try:
        msg = Message(subject, sender=app.config.get('MAIL_DEFAULT_SENDER', app.config.get('MAIL_USERNAME')), recipients=[to])
        msg.body = body
        # use SendGrid wrapper (async)
        send_email(msg)
        return jsonify({'ok': True, 'message': 'sent'})
    except Exception as e:
        app.logger.exception('Test email failed')
        return jsonify({'ok': False, 'error': str(e)}), 500

UPLOAD_FOLDER = 'static/uploads/product_images'
ADMIN_UPLOAD_FOLDER = 'static/uploads/admin_profiles'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ADMIN_UPLOAD_FOLDER'] = ADMIN_UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ADMIN_UPLOAD_FOLDER, exist_ok=True)

# MySQL connection is configured in config.py
def get_db_connection():

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        # Ensure sslmode is set for Neon/managed Postgres providers
        dsn = database_url
        if 'sslmode' not in dsn:
            if '?' in dsn:
                dsn = dsn + '&sslmode=require'
            else:
                dsn = dsn + '?sslmode=require'
        conn = psycopg2.connect(
            dsn,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
    else:
        conn = psycopg2.connect(
            host=config.DB_HOST,
            database=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            port=config.DB_PORT,
            cursor_factory=psycopg2.extras.RealDictCursor
        )

    conn.set_client_encoding('UTF8')
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    ddls = [
        """
        CREATE TABLE IF NOT EXISTS admin (
            admin_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password TEXT NOT NULL,
            profile_image VARCHAR(255),
            phone VARCHAR(50),
            is_approved BOOLEAN DEFAULT FALSE,
            is_super_admin BOOLEAN DEFAULT FALSE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_requests (
            request_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password TEXT NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone VARCHAR(50),
            address TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(255),
            price DECIMAL(10,2) NOT NULL,
            image VARCHAR(255),
            quantity INT DEFAULT 0,
            added_by_admin INT,
            FOREIGN KEY (added_by_admin) REFERENCES admin(admin_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            razorpay_order_id VARCHAR(255),
            razorpay_payment_id VARCHAR(255),
            amount DECIMAL(10,2) NOT NULL,
            payment_status VARCHAR(50) DEFAULT 'pending',
            delivery_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS order_items (
            item_id SERIAL PRIMARY KEY,
            order_id INT NOT NULL,
            product_id INT,
            product_name VARCHAR(255) NOT NULL,
            quantity INT NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        );
        """,
    ]

    for ddl in ddls:
        try:
            cursor.execute(ddl)
        except Exception:
            pass

    for col_sql in [
        "ALTER TABLE admin ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT FALSE",
        "ALTER TABLE admin ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS quantity INT DEFAULT 0",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS added_by_admin INT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_image TEXT",
        "ALTER TABLE admin_requests ADD COLUMN IF NOT EXISTS phone VARCHAR(50)",
        "ALTER TABLE admin ADD COLUMN IF NOT EXISTS phone VARCHAR(50)",
        "ALTER TABLE admin_requests ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(255)",
        "ALTER TABLE admin ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(255)",
        "ALTER TABLE admin_requests ADD COLUMN IF NOT EXISTS telegram_token VARCHAR(255)",
    ]:
        try:
            cursor.execute(col_sql)
        except Exception:
            pass

    try:
        cursor.execute("ALTER TABLE products ALTER COLUMN image TYPE TEXT")
        cursor.execute("ALTER TABLE admin ALTER COLUMN profile_image TYPE TEXT")
        try:
            cursor.execute("ALTER TABLE users ALTER COLUMN profile_image TYPE TEXT")
        except Exception:
            pass
    except Exception as e:
        print("Column update error:", e)

    conn.commit()
    conn.close()



# ================================================================
# HOME
# ================================================================
@app.route('/')
def home():
    return render_template('landing.html')


# ================================================================
# ADMIN SIGNUP — sends OTP, stores as pending request
# ================================================================
@app.route('/admin-signup', methods=['GET', 'POST'])
def admin_signup():
    if request.method == 'GET':
        # Clear any stale signup/session state to avoid using previous email values
        for k in ['signup_name', 'signup_email', 'signup_phone', 'signup_telegram', 'mfa_secret', 'mfa_purpose', 'mfa_provisioning_uri']:
            session.pop(k, None)
        return render_template('admin/admin_signup.html')

    name  = request.form['name'].strip()
    email = request.form['email'].strip().lower()
    phone = request.form.get('phone', '').strip()

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT admin_id FROM admin WHERE email=%s", (email,))
    if cursor.fetchone():
        conn.close()
        flash("Email already registered. Please login.", "danger")
        return redirect('/admin-signup')
    cursor.execute(
        "SELECT request_id FROM admin_requests WHERE email=%s AND status IN ('pending','approved')",
        (email,)
    )
    if cursor.fetchone():
        conn.close()
        flash("A request with this email already exists and is pending approval.", "warning")
        return redirect('/admin-signup')
    conn.close()

    # Use Microsoft Authenticator (TOTP) flow: generate a secret and show a QR
    session['signup_name']  = name
    session['signup_email'] = email
    session['signup_phone'] = phone
    # generate TOTP secret and provisioning URI for authenticator apps
    secret = pyotp.random_base32()
    session['mfa_secret'] = secret
    session['mfa_purpose'] = 'admin_signup'
    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name="ShopCart Admin")
    session['mfa_provisioning_uri'] = provisioning_uri
    flash("Scan the QR with Microsoft Authenticator and enter the 6-digit code.", "info")
    return redirect('/verify-otp')


# ================================================================
# VERIFY OTP — saves request as pending (not approved yet)
# ================================================================
@app.route('/verify-otp', methods=['GET'])
def verify_otp_get():
    qr_data = None
    telegram_qr = None
    try:
        prov = session.get('mfa_provisioning_uri')
        if prov:
            qr = qrcode.make(prov)
            buffered = io.BytesIO()
            qr.save(buffered, format="PNG")
            qr_b64 = base64.b64encode(buffered.getvalue()).decode()
            qr_data = f"data:image/png;base64,{qr_b64}"
        # also prepare a Telegram deep-link QR so the user can quickly open the bot
        try:
            bot_link = getattr(config, 'TELEGRAM_BOT_LINK', None)
            if not bot_link:
                bot_username = getattr(config, 'TELEGRAM_BOT_USERNAME', 'ShopCart_admin_bot')
                bot_link = f'https://t.me/{bot_username}'
            tlink = bot_link
            tqr = qrcode.make(tlink)
            tbuff = io.BytesIO()
            tqr.save(tbuff, format="PNG")
            t_b64 = base64.b64encode(tbuff.getvalue()).decode()
            telegram_qr = f"data:image/png;base64,{t_b64}"
        except Exception:
            telegram_qr = None
    except Exception:
        qr_data = None
    return render_template('admin/verify_otp.html', qr_data=qr_data, telegram_qr=telegram_qr)


@app.route('/verify-otp', methods=['POST'])
def verify_otp_post():
    user_otp = request.form['otp']
    password = request.form['password']
    telegram_chat_id = request.form.get('telegram_chat_id', '').strip()

    # If TOTP flow is active, verify using the shared secret
    if session.get('mfa_secret'):
        try:
            totp = pyotp.TOTP(session.get('mfa_secret'))
            if not totp.verify(str(user_otp), valid_window=1):
                flash("Invalid authenticator code. Try again!", "danger")
                return redirect('/verify-otp')
        except Exception as e:
            app.logger.exception('TOTP verification failed: %s', e)
            flash("Invalid authenticator code. Try again!", "danger")
            return redirect('/verify-otp')
    else:
        if str(session.get('otp')) != str(user_otp):
            flash("Invalid OTP. Try again!", "danger")
            return redirect('/verify-otp')

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    requester_name  = session.get('signup_name', '')
    requester_email = (session.get('signup_email', '') or '').strip().lower()
    requester_phone = session.get('signup_phone', '')
    requester_telegram = telegram_chat_id or session.get('signup_telegram', '')

    conn   = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt FROM admin")
    admin_count = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) as cnt FROM admin_requests")
    req_count = cursor.fetchone()['cnt']

    # Basic validation: ensure we have an email to work with
    if not requester_email:
        conn.close()
        flash("Email missing. Please start signup again.", "danger")
        return redirect('/admin-signup')

    # Prevent duplicate requests or already-registered emails
    cursor.execute("SELECT admin_id FROM admin WHERE email=%s", (requester_email,))
    if cursor.fetchone():
        conn.close()
        flash("Email already registered. Please login.", "warning")
        return redirect('/admin-signup')

    cursor.execute("SELECT request_id FROM admin_requests WHERE email=%s AND status IN ('pending','approved')", (requester_email,))
    if cursor.fetchone():
        conn.close()
        flash("A request with this email already exists.", "warning")
        return redirect('/admin-signup')

    if admin_count == 0 and req_count == 0:
        cursor.execute(
            "INSERT INTO admin (name, email, password, is_approved, is_super_admin) VALUES (%s,%s,%s,True,True)",
            (requester_name, requester_email, hashed)
        )
        conn.commit()
        conn.close()
        for k in ['otp', 'signup_name', 'signup_email', 'otp_purpose']:
            session.pop(k, None)
        flash("Super Admin registered! Please login.", "success")
        return redirect('/admin-login')

    else:
        try:
            cursor.execute(
                "SELECT request_id FROM admin_requests WHERE email=%s AND status='rejected'",
                (requester_email,)
            )
            existing_rejected = cursor.fetchone()

            # generate a stable token for Telegram deep-linking
            token = uuid.uuid4().hex

            if existing_rejected:
                cursor.execute(
                    "UPDATE admin_requests SET name=%s, password=%s, phone=%s, telegram_chat_id=%s, telegram_token=%s, status='pending', created_at=CURRENT_TIMESTAMP WHERE email=%s",
                    (requester_name, hashed, requester_phone, requester_telegram, token, requester_email)
                )
            else:
                cursor.execute(
                    "INSERT INTO admin_requests (name, email, password, phone, telegram_chat_id, telegram_token) VALUES (%s,%s,%s,%s,%s,%s)",
                    (requester_name, requester_email, hashed, requester_phone, requester_telegram, token)
                )
            conn.commit()
            req_token = token
        except psycopg2.IntegrityError as ie:
            conn.rollback()
            conn.close()
            # Detect duplicate-email unique constraint and show friendlier message
            constraint = ''
            try:
                constraint = ie.diag.constraint_name or ''
            except Exception:
                constraint = ''
            if 'admin_requests_email_key' in constraint or 'duplicate key' in str(ie).lower() or 'admin_requests_email_key' in str(ie).lower():
                flash("A request with this email already exists.", "warning")
                return redirect('/admin-signup')
            flash(f"Error saving request: {ie}", "danger")
            return redirect('/verify-otp')
        except Exception as e:
            conn.close()
            flash(f"Error saving request: {e}", "danger")
            return redirect('/verify-otp')

        try:
            cursor.execute(
                "SELECT email FROM admin WHERE is_super_admin=True AND is_approved=True"
            )
            super_admins = cursor.fetchall()
            conn.close()

            if super_admins:
                for sa in super_admins:
                    msg = Message(
                            subject="ShopCart — New Admin Registration Request",
                            sender="ghanashyamgudela@gmail.com",
                            recipients=[sa['email']]
                        )
                    msg.body = (
                            f"Hello Super Admin,\n\n"
                            f"A new admin registration request is awaiting your approval.\n\n"
                            f"Name  : {requester_name}\n"
                            f"Email : {requester_email}\n\n"
                            f"Phone : {requester_phone or 'N/A'}\n\n"
                            f"Please log in to the ShopCart Admin Panel and go to\n"
                            f"'Admin Requests' to approve or reject this request.\n\n"
                            f"Login URL : {url_for('admin_login', _external=True)}\n\n"
                            f"Regards,\nShopCart System"
                        )
                    send_email(msg)
        except Exception as mail_err:
            app.logger.error("Failed to notify super admin(s): %s", mail_err)
            try:
                conn.close()
            except Exception:
                pass

        # clear temporary session state
        for k in ['otp', 'signup_name', 'signup_email', 'signup_phone', 'signup_telegram', 'otp_purpose']:
            session.pop(k, None)

        # If we generated a request token, show the confirmation page with the bot deep-link
        if 'req_token' in locals():
            try:
                conn.close()
            except Exception:
                pass
            return redirect(url_for('request_submitted', token=req_token))

        flash("Registration request submitted! Please wait for super admin approval.", "info")
        return redirect('/admin-login')


# ================================================================
# ADMIN LOGIN
# ================================================================
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        return render_template('admin/admin_login.html')

    email    = request.form['email']
    password = request.form['password']

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin WHERE email=%s", (email,))
    admin = cursor.fetchone()
    conn.close()

    if not admin:
        flash("Email not found! Please register first.", "danger")
        return redirect('/admin-login')

    if not admin['is_approved']:
        flash("Your account is pending approval by the super admin.", "warning")
        return redirect('/admin-login')

    stored_pw = admin['password']
app.logger.info('LOGIN DEBUG: type=%s repr=%r', type(stored_pw), stored_pw[:20] if stored_pw else None)

try:
    if isinstance(stored_pw, memoryview):
        stored_pw = bytes(stored_pw)
    if isinstance(stored_pw, str):
        stored_pw = stored_pw.encode('utf-8')
    
    app.logger.info('LOGIN DEBUG after encode: type=%s starts_with=%s', type(stored_pw), stored_pw[:4])
    
    result = bcrypt.checkpw(password.encode('utf-8'), stored_pw)
    app.logger.info('LOGIN DEBUG bcrypt result=%s', result)
    
    if not result:
        flash("Incorrect password!", "danger")
        return redirect('/admin-login')
        
except (ValueError, TypeError) as pw_err:
    app.logger.exception('LOGIN DEBUG error: %s', pw_err)
    flash('Account password is corrupted or unsupported. Contact support.', 'danger')
    return redirect('/admin-login')
    

    

    session['admin_id']       = admin['admin_id']
    session['admin_name']     = admin['name']
    session['admin_email']    = admin['email']
    # store profile image in session so navbar can display it
    session['admin_profile_image'] = admin.get('profile_image') or ''
    session['is_super_admin'] = bool(admin['is_super_admin'])

    flash("Login Successful!", "success")
    return redirect('/admin-dashboard')


# ================================================================
# ADMIN FORGOT / RESET PASSWORD
# ================================================================
@app.route('/admin-forgot-password', methods=['GET', 'POST'])
def admin_forgot_password():
    if request.method == 'GET':
        return render_template('admin/admin_forgot_password.html')

    email  = request.form['email']
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin WHERE email=%s", (email,))
    admin = cursor.fetchone()
    conn.close()

    if not admin:
        flash("Email not found!", "danger")
        return redirect('/admin-forgot-password')

    otp = random.randint(100000, 999999)
    session['reset_otp']   = otp
    session['reset_email'] = email
    session['reset_role']  = 'admin'

    try:
        msg = Message("ShopCart Password Reset OTP", sender=app.config.get('MAIL_DEFAULT_SENDER', app.config.get('MAIL_USERNAME')), recipients=[email])
        msg.body = f"Your OTP for ShopCart Admin Password Reset is: {otp}\n\nThis OTP is valid for 10 minutes."
        send_email(msg)
        flash("OTP sent to your email!", "success")
    except Exception as e:
        flash(f"Error sending email: {str(e)}", "danger")
        return redirect('/admin-forgot-password')

    return redirect('/admin-reset-password')


# -----------------------------
# Social login routes
# -----------------------------
@app.route('/login/google')
def login_google():
    if not oauth._registry.get('google'):
        flash('Google OAuth not configured.', 'danger')
        return redirect('/user-login')
    # Prefer explicit config redirect URI if provided, else use OAUTH_REDIRECT_BASE fallback,
    # otherwise use url_for to compute external URI.
    redirect_uri = None
    if getattr(config, 'GOOGLE_REDIRECT_URI', None):
        redirect_uri = config.GOOGLE_REDIRECT_URI
    else:
        redirect_uri = url_for('auth_google', _external=True)
    try:
        app.logger.debug('session before google authorize: %s', {k: str(v)[:200] for k, v in session.items()})
    except Exception:
        app.logger.debug('session before google authorize: <unserializable>')
    app.logger.info('Google OAuth redirect_uri=%s', redirect_uri)
    return oauth.google.authorize_redirect(redirect_uri=redirect_uri)


@app.route('/auth/google')
def auth_google():
    try:
        app.logger.info('auth_google: starting token exchange')
        token = oauth.google.authorize_access_token()
        app.logger.info('auth_google: token received keys=%s', list(token.keys()) if isinstance(token, dict) else str(type(token)))
        userinfo = None
        try:
            # prefer ID token parsing
            userinfo = oauth.google.parse_id_token(token)
            app.logger.info('auth_google: parsed ID token')
        except Exception as parse_err:
            app.logger.info('auth_google: ID token parse failed: %s', parse_err)
            # fallback to userinfo endpoint; prefer endpoint from server metadata if available
            userinfo_endpoint = None
            try:
                metadata = getattr(oauth.google, 'server_metadata', None)
                if isinstance(metadata, dict):
                    userinfo_endpoint = metadata.get('userinfo_endpoint')
            except Exception:
                userinfo_endpoint = None
            if not userinfo_endpoint:
                userinfo_endpoint = 'https://openidconnect.googleapis.com/v1/userinfo'
            app.logger.info('auth_google: fetching userinfo from %s', userinfo_endpoint)
            resp = oauth.google.get(userinfo_endpoint)
            app.logger.info('auth_google: userinfo endpoint status=%s', getattr(resp, 'status_code', None))
            userinfo = resp.json()
        app.logger.info('auth_google: request args=%s', dict(request.args))
        email = userinfo.get('email')
        name = userinfo.get('name') or userinfo.get('given_name') or ''
        if not email:
            flash('Google account has no email, cannot continue.', 'danger')
            return redirect('/user-login')

        # find or create user
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
        user = cursor.fetchone()
        if not user:
            # create minimal user; use ON CONFLICT to avoid duplicate-key issues
            random_pw = uuid.uuid4().hex
            hashed = bcrypt.hashpw(random_pw.encode(), bcrypt.gensalt())
            try:
                cursor.execute(
                    """
                    INSERT INTO users (name, email, password)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
                    RETURNING user_id
                    """,
                    (name, email, hashed)
                )
                user_id = cursor.fetchone()['user_id']
                conn.commit()
            except Exception as db_err:
                conn.rollback()
                app.logger.exception('User insert failed, attempting select: %s', db_err)
                cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
                user = cursor.fetchone()
                if user:
                    user_id = user['user_id']
                else:
                    conn.close()
                    flash('Account creation failed. Try again later.', 'danger')
                    return redirect('/user-login')
            session['user_id'] = user_id
            session['user_name'] = name
            session['user_email'] = email
            session['user_profile_image'] = None
        else:
            session['user_id'] = user['user_id']
            session['user_name'] = user.get('name') or name
            session['user_email'] = user.get('email')
            session['user_profile_image'] = user.get('profile_image') or ''
        conn.close()
        flash('Logged in with Google successfully!', 'success')
        return redirect('/user-dashboard')
    except Exception as e:
        app.logger.exception('Google login failed: %s', e)
        flash(f'Google login failed: {str(e)}', 'danger')
        return redirect('/user-login')


# Callback wrapper to support external OAuth redirect URI
@app.route('/login/google/callback')
def auth_google_callback():
    return auth_google()


@app.route('/login/facebook')
def login_facebook():
    if not oauth._registry.get('facebook'):
        flash('Facebook OAuth not configured.', 'danger')
        return redirect('/user-login')
    redirect_uri = None
    if getattr(config, 'FACEBOOK_REDIRECT_URI', None):
        redirect_uri = config.FACEBOOK_REDIRECT_URI
    else:
        redirect_uri = url_for('auth_facebook', _external=True)
    try:
        app.logger.debug('session before facebook authorize: %s', {k: str(v)[:200] for k, v in session.items()})
    except Exception:
        app.logger.debug('session before facebook authorize: <unserializable>')
    app.logger.info('Facebook OAuth redirect_uri=%s', redirect_uri)
    return oauth.facebook.authorize_redirect(redirect_uri=redirect_uri)


@app.route('/admin/login/microsoft')
def admin_login_microsoft():
    if not oauth._registry.get('microsoft'):
        flash('Microsoft OAuth not configured.', 'danger')
        return redirect('/admin-login')
    # mark intent so callback knows to create an admin request
    session['oauth_intent'] = 'admin_request'
    redirect_uri = config.MICROSOFT_REDIRECT_URI if getattr(config, 'MICROSOFT_REDIRECT_URI', None) else url_for('auth_microsoft', _external=True)
    try:
        app.logger.debug('session before microsoft authorize: %s', {k: str(v)[:200] for k, v in session.items()})
    except Exception:
        app.logger.debug('session before microsoft authorize: <unserializable>')
    app.logger.info('Microsoft OAuth redirect_uri=%s', redirect_uri)
    return oauth.microsoft.authorize_redirect(redirect_uri=redirect_uri)


@app.route('/login/microsoft')
def login_microsoft():
    if not oauth._registry.get('microsoft'):
        flash('Microsoft OAuth not configured.', 'danger')
        return redirect('/user-login')
    # mark intent so callback knows this is a normal user login
    session['oauth_intent'] = 'user_login'
    redirect_uri = config.MICROSOFT_REDIRECT_URI if getattr(config, 'MICROSOFT_REDIRECT_URI', None) else url_for('auth_microsoft', _external=True)
    try:
        app.logger.debug('session before microsoft authorize (user): %s', {k: str(v)[:200] for k, v in session.items()})
    except Exception:
        app.logger.debug('session before microsoft authorize (user): <unserializable>')
    app.logger.info('Microsoft OAuth redirect_uri=%s', redirect_uri)
    return oauth.microsoft.authorize_redirect(redirect_uri=redirect_uri)


@app.route('/auth/microsoft')
def auth_microsoft():
    try:
        app.logger.info('auth_microsoft: starting token exchange')
        manual_profile = None
        # First try manual token exchange to avoid Authlib parsing/iss validation
        manual_profile = None
        token = None
        try:
            code = request.args.get('code')
            redirect_uri = config.MICROSOFT_REDIRECT_URI if getattr(config, 'MICROSOFT_REDIRECT_URI', None) else url_for('auth_microsoft', _external=True)
            metadata = getattr(oauth.microsoft, 'server_metadata', None) or {}
            token_endpoint = metadata.get('token_endpoint') or 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
            code_verifier = None
            for k in ('code_verifier', 'oauth_code_verifier', 'microsoft_code_verifier', 'authlib_code_verifier'):
                if session.get(k):
                    code_verifier = session.get(k)
                    break
            data = {
                'client_id': config.MICROSOFT_CLIENT_ID,
                'client_secret': config.MICROSOFT_CLIENT_SECRET,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
            }
            if code_verifier:
                data['code_verifier'] = code_verifier
                app.logger.info('auth_microsoft: using stored code_verifier for manual token exchange')
            app.logger.info('auth_microsoft: performing manual token exchange at %s', token_endpoint)
            resp = requests.post(token_endpoint, data=data, headers={'Accept': 'application/json'})
            try:
                resp.raise_for_status()
            except requests.HTTPError:
                app.logger.error('auth_microsoft: token endpoint returned error: %s', resp.text)
                raise
            token = resp.json()
            access_token = token.get('access_token')
            if access_token:
                g = requests.get('https://graph.microsoft.com/v1.0/me', headers={'Authorization': f'Bearer {access_token}'})
                if g.status_code == 200:
                    manual_profile = g.json()
                    app.logger.info('auth_microsoft: fetched profile via Graph after manual token exchange')
        except Exception as manual_exc:
            app.logger.warning('auth_microsoft: manual token exchange failed: %s', manual_exc)
            # Fallback to Authlib's convenience method (may raise InvalidClaimError)
            try:
                token = oauth.microsoft.authorize_access_token()
            except InvalidClaimError as ice:
                app.logger.warning('auth_microsoft: ID token iss validation failed: %s', ice)
                # Try parsing with relaxed iss requirement (may raise mismatching_state)
                try:
                    token = oauth.microsoft.authorize_access_token(claims_options={'iss': {'essential': False}})
                    app.logger.info('auth_microsoft: parsed token with relaxed iss validation')
                except Exception as retry_err:
                    app.logger.exception('auth_microsoft: authorize_access_token retry failed: %s', retry_err)
                    raise
        app.logger.info('auth_microsoft: token keys=%s', list(token.keys()) if isinstance(token, dict) else str(type(token)))
        # fetch profile using OIDC userinfo endpoint (preferred)
        profile = None
        if manual_profile is not None:
            profile = manual_profile
        else:
            try:
                resp = oauth.microsoft.get('userinfo')
                app.logger.info('auth_microsoft: userinfo status=%s', getattr(resp, 'status_code', None))
                profile = resp.json()
            except Exception as e:
                app.logger.info('auth_microsoft: userinfo fetch failed, falling back to Graph /me: %s', e)
                try:
                    resp = oauth.microsoft.get('https://graph.microsoft.com/v1.0/me')
                    app.logger.info('auth_microsoft: graph /me status=%s', getattr(resp, 'status_code', None))
                    profile = resp.json()
                except Exception as e2:
                    app.logger.exception('auth_microsoft: failed to fetch profile from Microsoft: %s', e2)
                    profile = {}
        # email may be in 'mail' or 'userPrincipalName'
        email = profile.get('mail') or profile.get('userPrincipalName')
        name = profile.get('displayName') or ''

        if not email:
            flash('Microsoft account has no email, cannot continue.', 'danger')
            return redirect('/admin-signup')

        intent = session.pop('oauth_intent', None)
        if intent == 'admin_request':
            # create admin_requests entry (if not exists) and notify super admins
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT request_id FROM admin_requests WHERE email=%s', (email,))
            existing = cursor.fetchone()
            if existing:
                flash('An admin request for this email already exists.', 'info')
                conn.close()
                return redirect('/admin-login')
            try:
                # store a placeholder password (random) since admin will be approved and set later
                random_pw = uuid.uuid4().hex
                hashed = bcrypt.hashpw(random_pw.encode(), bcrypt.gensalt())
                token = uuid.uuid4().hex
                cursor.execute('INSERT INTO admin_requests (name, email, password, status, phone, telegram_chat_id, telegram_token) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING request_id', (name, email, hashed, 'pending', None, None, token))
                req_id = cursor.fetchone()['request_id']
                conn.commit()
                # notify super admins
                try:
                    cursor.execute("SELECT email FROM admin WHERE is_super_admin=True AND is_approved=True")
                    super_admins = cursor.fetchall()
                    if super_admins:
                        for sa in super_admins:
                            msg = Message(
                                subject="ShopCart — New Admin Registration Request (Microsoft Auth)",
                                sender=app.config.get('MAIL_DEFAULT_SENDER', app.config.get('MAIL_USERNAME')),
                                recipients=[sa['email']]
                            )
                            msg.body = (
                                f"Hello Super Admin,\n\nA new admin registration request via Microsoft Sign-in is awaiting your approval.\n\nName  : {name}\nEmail : {email}\nPhone : N/A\n\nPlease log in and approve or reject this request: {url_for('admin_login', _external=True)}\n\nRegards,\nShopCart System"
                            )
                            send_email(msg)
                except Exception as mail_err:
                    app.logger.error('Failed to notify super admin(s): %s', mail_err)
                try:
                    conn.close()
                except Exception:
                    pass
                return redirect(url_for('request_submitted', token=token))
            except psycopg2.IntegrityError as ie:
                conn.rollback()
                conn.close()
                constraint = ''
                try:
                    constraint = ie.diag.constraint_name or ''
                except Exception:
                    constraint = ''
                if 'admin_requests_email_key' in constraint or 'duplicate key' in str(ie).lower() or 'admin_requests_email_key' in str(ie).lower():
                    flash('A request with this email already exists.', 'warning')
                    return redirect('/admin-signup')
                app.logger.exception('Failed to save admin request: %s', ie)
                flash('Failed to submit admin request. Try again later.', 'danger')
                return redirect('/admin-signup')
            except Exception as e:
                conn.rollback()
                conn.close()
                app.logger.exception('Failed to save admin request: %s', e)
                flash('Failed to submit admin request. Try again later.', 'danger')
                return redirect('/admin-signup')
        else:
            # default behavior: create/login as normal user
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
            user = cursor.fetchone()
            if not user:
                random_pw = uuid.uuid4().hex
                hashed = bcrypt.hashpw(random_pw.encode(), bcrypt.gensalt())
                try:
                    cursor.execute(
                        """
                        INSERT INTO users (name, email, password)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
                        RETURNING user_id
                        """,
                        (name, email, hashed)
                    )
                    user_id = cursor.fetchone()['user_id']
                    conn.commit()
                except Exception as db_err:
                    conn.rollback()
                    app.logger.exception('User insert failed, attempting select: %s', db_err)
                    cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
                    user = cursor.fetchone()
                    if user:
                        user_id = user['user_id']
                    else:
                        conn.close()
                        flash('Account creation failed. Try again later.', 'danger')
                        return redirect('/user-login')
                session['user_id'] = user_id
                session['user_name'] = name
                session['user_email'] = email
                session['user_profile_image'] = None
            else:
                session['user_id'] = user['user_id']
                session['user_name'] = user.get('name') or name
                session['user_email'] = user.get('email')
                session['user_profile_image'] = user.get('profile_image') or ''
            conn.close()
            flash('Logged in with Microsoft successfully!', 'success')
            return redirect('/user-dashboard')
    except Exception as e:
        app.logger.exception('Microsoft login failed: %s', e)
        flash(f'Microsoft login failed: {str(e)}', 'danger')
        # Redirect according to original intent (admin_request vs user_login).
        intent = session.pop('oauth_intent', None) or session.get('oauth_intent')
        if intent == 'admin_request':
            return redirect('/admin-login')
        else:
            return redirect('/user-login')


@app.route('/login/microsoft/callback')
def auth_microsoft_callback():
    return auth_microsoft()


@app.route('/auth/facebook')
def auth_facebook():
    try:
        app.logger.info('auth_facebook: starting token exchange')
        # Facebook may return an error in the callback (e.g. invalid scopes).
        # If so, handle it gracefully instead of calling authorize_access_token().
        if 'error' in request.args or 'error_code' in request.args or 'error_message' in request.args:
            app.logger.error('auth_facebook: callback error params=%s', dict(request.args))
            err_msg = request.args.get('error_description') or request.args.get('error_message') or request.args.get('error') or request.args.get('error_code')
            flash(f'Facebook login failed: {err_msg}', 'danger')
            return redirect('/user-login')
        token = oauth.facebook.authorize_access_token()
        app.logger.info('auth_facebook: token received keys=%s', list(token.keys()) if isinstance(token, dict) else str(type(token)))
        try:
            has_at = bool(token.get('access_token')) if isinstance(token, dict) else False
        except Exception:
            has_at = False
        app.logger.info('auth_facebook: has_access_token=%s', has_at)
        resp = oauth.facebook.get('me?fields=id,name,email')
        app.logger.info('auth_facebook: profile fetch status=%s', getattr(resp, 'status_code', None))
        if getattr(resp, 'status_code', None) != 200:
            try:
                app.logger.error('auth_facebook: profile fetch body=%s', resp.text)
            except Exception:
                pass
            flash('Facebook profile fetch failed. Check app permissions or logs.', 'danger')
            return redirect('/user-login')
        profile = resp.json()
        email = profile.get('email')
        name = profile.get('name') or ''
        if not email:
            flash('Facebook account did not provide email. Use another sign-in method.', 'danger')
            return redirect('/user-login')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
        user = cursor.fetchone()
        if not user:
            random_pw = uuid.uuid4().hex
            hashed = bcrypt.hashpw(random_pw.encode(), bcrypt.gensalt())
            try:
                cursor.execute(
                    """
                    INSERT INTO users (name, email, password)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
                    RETURNING user_id
                    """,
                    (name, email, hashed)
                )
                user_id = cursor.fetchone()['user_id']
                conn.commit()
            except Exception as db_err:
                conn.rollback()
                app.logger.exception('User insert failed, attempting select: %s', db_err)
                cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
                user = cursor.fetchone()
                if user:
                    user_id = user['user_id']
                else:
                    conn.close()
                    flash('Account creation failed. Try again later.', 'danger')
                    return redirect('/user-login')
            session['user_id'] = user_id
            session['user_name'] = name
            session['user_email'] = email
            session['user_profile_image'] = None
        else:
            session['user_id'] = user['user_id']
            session['user_name'] = user.get('name') or name
            session['user_email'] = user.get('email')
            session['user_profile_image'] = user.get('profile_image') or ''
        conn.close()
        flash('Logged in with Facebook successfully!', 'success')
        return redirect('/user-dashboard')
    except Exception as e:
        app.logger.exception('Facebook login failed: %s', e)
        flash(f'Facebook login failed: {str(e)}', 'danger')
        return redirect('/user-login')


@app.route('/debug/oauth')
def debug_oauth():
    try:
        data = {
            'GOOGLE_REDIRECT_URI': getattr(config, 'GOOGLE_REDIRECT_URI', None),
            'FACEBOOK_REDIRECT_URI': getattr(config, 'FACEBOOK_REDIRECT_URI', None),
            'computed_google_callback': url_for('auth_google', _external=True),
            'computed_facebook_callback': url_for('auth_facebook', _external=True),
            'google_client_id': getattr(config, 'GOOGLE_CLIENT_ID', None),
            'facebook_client_id': getattr(config, 'FACEBOOK_CLIENT_ID', None)
        }
        return jsonify(data)
    except Exception as e:
        app.logger.exception('debug_oauth failed: %s', e)
        return jsonify({'error': str(e)}), 500


@app.route('/debug/products')
def debug_products():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT product_id, name, image FROM products ORDER BY product_id DESC LIMIT 20")
        rows = cursor.fetchall()
        conn.close()
        out = []
        for r in rows:
            out.append({
                'product_id': r.get('product_id'),
                'name': r.get('name'),
                'image_raw': r.get('image')
            })
        return jsonify({'count': len(out), 'products': out})
    except Exception as e:
        app.logger.exception('debug_products failed: %s', e)
        return jsonify({'error': str(e)}), 500


# Callback wrapper to support external OAuth redirect URI
@app.route('/login/facebook/callback')
def auth_facebook_callback():
    return auth_facebook()



@app.route('/admin-reset-password', methods=['GET', 'POST'])
def admin_reset_password():
    if request.method == 'GET':
        return render_template('admin/admin_reset_password.html')

    user_otp         = request.form['otp']
    new_password     = request.form['password']
    confirm_password = request.form['confirm_password']

    if str(session.get('reset_otp')) != str(user_otp):
        flash("Invalid OTP.", "danger")
        return redirect('/admin-reset-password')
    if new_password != confirm_password:
        flash("Passwords do not match!", "danger")
        return redirect('/admin-reset-password')

    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
    email  = session.get('reset_email')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE admin SET password=%s WHERE email=%s", (hashed, email))
    conn.commit()
    conn.close()

    for k in ['reset_otp', 'reset_email', 'reset_role']:
        session.pop(k, None)

    flash("Password reset successfully!", "success")
    return redirect('/admin-login')


@app.route('/admin/request-submitted/<token>')
def request_submitted(token):
    # show a confirmation page with the bot deep-link QR for the provided token
    try:
        bot_base = getattr(config, 'TELEGRAM_BOT_LINK', None)
        if not bot_base:
            bot_username = getattr(config, 'TELEGRAM_BOT_USERNAME', 'ShopCart_admin_bot')
            bot_base = f'https://t.me/{bot_username}'
        deep_link = f"{bot_base}?start={token}"
        qr = qrcode.make(deep_link)
        buffered = io.BytesIO()
        qr.save(buffered, format="PNG")
        qr_b64 = base64.b64encode(buffered.getvalue()).decode()
        qr_data = f"data:image/png;base64,{qr_b64}"
        return render_template('admin/request_submitted.html', deep_link=deep_link, qr_data=qr_data)
    except Exception as e:
        app.logger.exception('request_submitted render failed: %s', e)
        flash('Request submitted. Open the bot to link your Telegram chat.', 'info')
        return redirect('/admin-login')


@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    # Telegram will POST updates here. We look for /start <token> messages and link chat_id.
    try:
        data = request.get_json(force=True)
        message = data.get('message') or data.get('edited_message') or {}
        text = message.get('text', '')
        chat = message.get('chat') or {}
        chat_id = chat.get('id')
        if text and text.strip().startswith('/start') and chat_id:
            parts = text.strip().split()
            token = parts[1] if len(parts) > 1 else None
            if token:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT request_id FROM admin_requests WHERE telegram_token=%s", (token,))
                row = cursor.fetchone()
                if row:
                    cursor.execute("UPDATE admin_requests SET telegram_chat_id=%s WHERE telegram_token=%s", (str(chat_id), token))
                    conn.commit()
                    try:
                        send_telegram_message(str(chat_id), "✅ Your Telegram is now linked to your ShopCart admin request. You'll receive a notification once it's approved.")
                    except Exception:
                        pass
                conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        app.logger.exception('telegram webhook failed: %s', e)
        return jsonify({'ok': False}), 500


# ================================================================
# ADMIN DASHBOARD
# ================================================================
@app.route('/admin-dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        flash("Please login!", "danger")
        return redirect('/admin-login')

    conn   = get_db_connection()
    cursor = conn.cursor()

    if session.get('is_super_admin'):
        cursor.execute("SELECT COUNT(*) as c FROM products")
    else:
        cursor.execute("SELECT COUNT(*) as c FROM products WHERE added_by_admin=%s", (session['admin_id'],))
    total_products = cursor.fetchone()['c']

    cursor.execute("SELECT COUNT(*) as c FROM orders")
    total_orders = cursor.fetchone()['c']

    cursor.execute("SELECT COALESCE(SUM(amount),0) as c FROM orders WHERE payment_status='paid'")
    total_revenue = cursor.fetchone()['c']

    cursor.execute("SELECT COUNT(*) as c FROM users")
    total_users = cursor.fetchone()['c']

    cursor.execute("""
        SELECT o.order_id, o.amount, o.payment_status, o.created_at, u.name as user_name
        FROM orders o JOIN users u ON o.user_id=u.user_id
        ORDER BY o.created_at DESC LIMIT 5
    """)
    recent_orders = cursor.fetchall()

    pending_requests = 0
    if session.get('is_super_admin'):
        cursor.execute("SELECT COUNT(*) as c FROM admin_requests WHERE status='pending'")
        pending_requests = cursor.fetchone()['c']

    conn.close()

    return render_template('admin/dashboard.html',
                           admin_name=session['admin_name'],
                           total_products=total_products,
                           total_orders=total_orders,
                           total_revenue=total_revenue,
                           total_users=total_users,
                           recent_orders=recent_orders,
                           pending_requests=pending_requests)


# ================================================================
# ADMIN LOGOUT
# ================================================================
@app.route('/admin-logout')
def admin_logout():
    for k in ['admin_id', 'admin_name', 'admin_email', 'is_super_admin']:
        session.pop(k, None)
    flash("Logged out successfully.", "success")
    return redirect('/admin-login')


# ================================================================
# SUPER ADMIN: MANAGE REGISTRATION REQUESTS
# ================================================================
@app.route('/admin/requests')
def admin_requests():
    if 'admin_id' not in session or not session.get('is_super_admin'):
        flash("Access denied. Super admin only.", "danger")
        return redirect('/admin-dashboard')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin_requests ORDER BY created_at DESC")
    requests = cursor.fetchall()
    conn.close()

    return render_template('admin/admin_requests.html', requests=requests)


@app.route('/admin/approve-request/<int:req_id>')
def approve_request(req_id):
    if 'admin_id' not in session or not session.get('is_super_admin'):
        flash("Access denied.", "danger")
        return redirect('/admin-dashboard')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin_requests WHERE request_id=%s", (req_id,))
    req = cursor.fetchone()

    if not req:
        conn.close()
        flash("Request not found.", "danger")
        return redirect('/admin/requests')

    try:
    # normalize password bytes before inserting into admin table
        raw_pw = req['password']
        if isinstance(raw_pw, memoryview):
            raw_pw = raw_pw.tobytes()
        elif isinstance(raw_pw, str):
            raw_pw = raw_pw.encode()

        cursor.execute(
            "INSERT INTO admin (name, email, password, phone, telegram_chat_id, is_approved, is_super_admin) VALUES (%s,%s,%s,%s,%s, True,False)",
            (req['name'], req['email'], raw_pw.decode(), req.get('phone'), req.get('telegram_chat_id'))
        )
        cursor.execute("UPDATE admin_requests SET status='approved' WHERE request_id=%s", (req_id,))
        conn.commit()
        flash(f"Admin '{req['name']}' approved successfully!", "success")
        # send approval email to the newly approved admin (don't add another success flash)
        try:
            msg = Message("ShopCart Admin Account Approved", sender=app.config.get('MAIL_DEFAULT_SENDER', app.config.get('MAIL_USERNAME')), recipients=[req['email']])
            msg.body = (
                f"Hello {req['name']},\n\n"
                "Your ShopCart admin account request has been approved by the super admin.\n"
                f"You can now sign in here: {url_for('admin_login', _external=True)}\n\n"
                "If you did not request this account, please contact support.\n\n"
                "Regards,\nShopCart Team"
            )
            send_email(msg)
        except Exception as e:
            # don't block the flow on mail errors; notify the super admin
            flash(f"Approved but failed to send email: {str(e)}", "warning")
        # Send Telegram notification to the admin (uses DEFAULT_TELEGRAM_CHAT_ID if none provided)
        try:
            chat_id_to_use = req.get('telegram_chat_id') if isinstance(req, dict) else None
            if chat_id_to_use:
                telegram_msg = (
                    f"✅ Hello {req['name']},\n\n"
                    f"Your ShopCart admin account has been approved!\n"
                    f"Email: {req.get('email') or 'N/A'}\n"
                    f"Phone: {req.get('phone') or 'N/A'}\n\n"
                    f"👉 Login here: {url_for('admin_login', _external=True)}\n\n"
                    "Regards,\nShopCart Team"
                )
                send_telegram_message(chat_id_to_use, telegram_msg)
                app.logger.info('Telegram notification sent to chat_id=%s', chat_id_to_use)
            else:
                app.logger.warning('approve_request: no telegram_chat_id for request_id=%s, skipping Telegram notify', req_id)
                flash('Approved. Note: admin has not linked Telegram, so no Telegram notification was sent.', 'info')
        except Exception as te:
            app.logger.exception('Failed to send Telegram notification: %s', te)
            flash('Approved but failed to send Telegram notification.', 'warning')
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()

    return redirect('/admin/requests')


@app.route('/admin/edit-request/<int:req_id>', methods=['GET', 'POST'])
def edit_request(req_id):
    if 'admin_id' not in session or not session.get('is_super_admin'):
        flash("Access denied.", "danger")
        return redirect('/admin-dashboard')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin_requests WHERE request_id=%s", (req_id,))
    req = cursor.fetchone()

    if not req:
        conn.close()
        flash("Request not found.", "danger")
        return redirect('/admin/requests')

    original_status = req.get('status')
    original_email = req.get('email')

    if request.method == 'GET':
        conn.close()
        return render_template('admin/edit_request.html', req=req)

    # POST - update the request
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    new_password = request.form.get('password', '')

    try:
        hashed = None
        if new_password:
            hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
            cursor.execute(
                "UPDATE admin_requests SET name=%s, email=%s, password=%s, phone=%s WHERE request_id=%s",
                (name, email, hashed, phone, req_id)
            )
        else:
            cursor.execute(
                "UPDATE admin_requests SET name=%s, email=%s, phone=%s WHERE request_id=%s",
                (name, email, phone, req_id)
            )
        conn.commit()

        # If the request was already approved, reflect changes into the actual admin record
        if original_status == 'approved':
            try:
                if hashed:
                    cursor.execute(
                        "UPDATE admin SET name=%s, email=%s, password=%s, phone=%s WHERE email=%s",
                        (name, email, hashed, phone, original_email)
                    )
                else:
                    cursor.execute(
                        "UPDATE admin SET name=%s, email=%s, phone=%s WHERE email=%s",
                        (name, email, phone, original_email)
                    )
                conn.commit()
                flash("Request and approved admin record updated.", "success")
            except Exception as e:
                # Admin table update failed — keep request updated but notify
                flash(f"Request updated, but failed to update admin record: {e}", "warning")
    except Exception as e:
        flash(f"Error updating request: {e}", "danger")
    finally:
        conn.close()

    return redirect('/admin/requests')


@app.route('/admin/reject-request/<int:req_id>')
def reject_request(req_id):
    if 'admin_id' not in session or not session.get('is_super_admin'):
        flash("Access denied.", "danger")
        return redirect('/admin-dashboard')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE admin_requests SET status='rejected' WHERE request_id=%s", (req_id,))
    conn.commit()
    conn.close()

    flash("Request rejected.", "info")
    return redirect('/admin/requests')


@app.route('/admin/revoke-request/<int:req_id>')
def revoke_request(req_id):
    if 'admin_id' not in session or not session.get('is_super_admin'):
        flash("Access denied.", "danger")
        return redirect('/admin-dashboard')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admin_requests WHERE request_id=%s", (req_id,))
    req = cursor.fetchone()

    if not req:
        conn.close()
        flash("Request not found.", "danger")
        return redirect('/admin/requests')

    try:
        if req.get('status') != 'approved':
            # If not approved yet, mark as rejected
            cursor.execute("UPDATE admin_requests SET status='rejected' WHERE request_id=%s", (req_id,))
            conn.commit()
            flash("Request rejected.", "info")
        else:
            # revoke an already approved admin: remove from admin table and mark request revoked
            cursor.execute("UPDATE admin_requests SET status='revoked' WHERE request_id=%s", (req_id,))
            cursor.execute("DELETE FROM admin WHERE email=%s", (req['email'],))
            conn.commit()
            flash(f"Approved admin '{req['name']}' revoked and removed.", "success")
            # notify the affected admin
            try:
                msg = Message("ShopCart Admin Access Revoked", sender=app.config.get('MAIL_DEFAULT_SENDER', app.config.get('MAIL_USERNAME')), recipients=[req['email']])
                msg.body = (
                    f"Hello {req['name']},\n\n"
                    "Your ShopCart admin access has been revoked by the Super Admin.\n"
                    "If you believe this is a mistake, please contact the site administrator.\n\n"
                    "Regards,\nShopCart Team"
                )
                send_email(msg)
                flash("Revocation email sent to the admin.", "success")
            except Exception as e:
                flash(f"Revoked but failed to send email: {e}", "warning")
    except Exception as e:
        flash(f"Error processing revoke: {e}", "danger")
    finally:
        conn.close()

    return redirect('/admin/requests')


# ================================================================
# ADD PRODUCT — with quantity, tracks which admin added it
# ================================================================
@app.route('/admin/add-item', methods=['GET', 'POST'])
def add_item():
    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect('/admin-login')

    if request.method == 'GET':
        return render_template('admin/add_item.html')

    name        = request.form['name']
    description = request.form['description']
    category    = request.form['category']
    price       = request.form['price']
    quantity    = request.form.get('quantity', 0)

    # accept multiple images (1-3)
    uploaded_files = request.files.getlist('image')
    # filter out empty filenames
    images = [f for f in uploaded_files if f and f.filename]
    if not images or len(images) < 1:
        flash("Please upload at least one product image!", "danger")
        return redirect('/admin/add-item')
    if len(images) > 3:
        flash("You can upload a maximum of 3 images.", "danger")
        return redirect('/admin/add-item')

    saved_filenames = []
    for img in images:
        try:
            upload_result = cloudinary.uploader.upload(img)
            image_url = upload_result.get('secure_url')
            if not image_url:
                raise RuntimeError('Cloudinary upload did not return secure_url')
            saved_filenames.append(image_url)
        except Exception as e:
            app.logger.error('Cloudinary upload failed: %s', e)
            flash('Failed to upload images. Check Cloudinary configuration.', 'danger')
            return redirect('/admin/add-item')
    conn   = get_db_connection()
    cursor = conn.cursor()
    # store multiple filenames joined by '||' so existing DB schema stays unchanged
    images_field = '||'.join(saved_filenames)
    cursor.execute(
        "INSERT INTO products (name, description, category, price, image, quantity, added_by_admin) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (name, description, category, price, images_field, quantity, session['admin_id'])
    )
    conn.commit()
    conn.close()

    flash("Product added successfully!", "success")
    return redirect('/admin/item-list')


# ================================================================
# ITEM LIST — all admins see all products
# ================================================================
@app.route('/admin/item-list')
def item_list():
    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect('/admin-login')

    search          = request.args.get('search', '')
    category_filter = request.args.get('category', '')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM products")
    categories = cursor.fetchall()

    query  = """
        SELECT p.*, a.name as added_by_name
        FROM products p
        LEFT JOIN admin a ON p.added_by_admin = a.admin_id
        WHERE 1=1
    """
    params = []

    if not session.get('is_super_admin'):
        query  += " AND p.added_by_admin = %s"
        params.append(session['admin_id'])

    if search:
        query  += " AND p.name LIKE %s"
        params.append("%" + search + "%")
    if category_filter:
        query  += " AND p.category = %s"
        params.append(category_filter)

    query += " ORDER BY p.product_id DESC"
    cursor.execute(query, params)
    products = cursor.fetchall()
    conn.close()

    return render_template('admin/item_list.html', products=products, categories=categories)


# ================================================================
# VIEW / UPDATE / DELETE PRODUCT
# ================================================================
@app.route('/admin/view-item/<int:item_id>')
def view_item(item_id):
    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect('/admin-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, a.name as added_by_name
        FROM products p LEFT JOIN admin a ON p.added_by_admin=a.admin_id
        WHERE p.product_id=%s
    """, (item_id,))
    product = cursor.fetchone()
    conn.close()

    if not product:
        flash("Product not found!", "danger")
        return redirect('/admin/item-list')

    return render_template('admin/view_item.html', product=product)


@app.route('/admin/update-item/<int:item_id>', methods=['GET', 'POST'])
def update_item(item_id):
    if 'admin_id' not in session:
        flash("Please login!", "danger")
        return redirect('/admin-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE product_id=%s", (item_id,))
    product = cursor.fetchone()

    if not product:
        flash("Product not found!", "danger")
        conn.close()
        return redirect('/admin/item-list')

    if request.method == 'GET':
        conn.close()
        return render_template('admin/update_item.html', product=product)

    name            = request.form['name']
    description     = request.form['description']
    category        = request.form['category']
    price           = request.form['price']
    quantity        = request.form.get('quantity', product['quantity'])
    new_image       = request.files['image']
    old_image_name  = product['image']

    if new_image and new_image.filename != '':
        # Upload new image to Cloudinary and keep URL
        try:
            upload_result = cloudinary.uploader.upload(new_image)
            image_url = upload_result.get('secure_url')
        except Exception as e:
            app.logger.error('Cloudinary upload failed during product update: %s', e)
            flash('Failed to upload image to Cloudinary. Keeping existing image.', 'warning')
            image_url = None

        # remove local files for old images (if any and if they are local filenames)
        if old_image_name:
            for old in old_image_name.split('||'):
                if not old:
                    continue
                if not old.startswith('http'):
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], old)
                    try:
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    except Exception:
                        pass

        final_image = image_url or old_image_name
    else:
        final_image = old_image_name

    cursor.execute("""
        UPDATE products SET name=%s, description=%s, category=%s, price=%s, image=%s, quantity=%s
        WHERE product_id=%s
    """, (name, description, category, price, final_image, quantity, item_id))
    conn.commit()
    conn.close()

    flash("Product updated successfully!", "success")
    return redirect('/admin/item-list')


@app.route('/admin/delete-item/<int:item_id>')
def delete_item(item_id):
    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect('/admin-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT image FROM products WHERE product_id=%s", (item_id,))
    product = cursor.fetchone()

    if not product:
        flash("Product not found!", "danger")
        conn.close()
        return redirect('/admin/item-list')

    # product['image'] may contain multiple filenames joined by '||'
    if product.get('image'):
        for fname in product['image'].split('||'):
            if not fname:
                continue
            # only remove local files; Cloudinary URLs are left untouched
            if fname.startswith('http'):
                continue
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception:
                pass

    cursor.execute("DELETE FROM products WHERE product_id=%s", (item_id,))
    conn.commit()
    conn.close()

    flash("Product deleted successfully!", "success")
    return redirect('/admin/item-list')


# ================================================================
# ADMIN PROFILE
# ================================================================
@app.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    if 'admin_id' not in session:
        flash("Please login!", "danger")
        return redirect('/admin-login')

    admin_id = session['admin_id']
    conn     = get_db_connection()
    cursor   = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM admin WHERE admin_id=%s", (admin_id,))
        admin = cursor.fetchone()
        conn.close()
        return render_template('admin/admin_profile.html', admin=admin)

    name       = request.form['name']
    email      = request.form['email']
    new_pw     = request.form['password']
    new_image  = request.files['profile_image']

    cursor.execute("SELECT * FROM admin WHERE admin_id=%s", (admin_id,))
    admin = cursor.fetchone()
    old_image = admin['profile_image']

    hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()) if new_pw else admin['password']

    if new_image and new_image.filename != '':
        # upload admin profile image to Cloudinary
        try:
            upload_result = cloudinary.uploader.upload(new_image)
            final_image = upload_result.get('secure_url')
        except Exception as e:
            app.logger.error('Cloudinary upload failed for admin profile: %s', e)
            flash('Failed to upload profile image to Cloudinary. Keeping existing image.', 'warning')
            final_image = old_image
        # remove previous local profile image if it was a local file
        if old_image and not old_image.startswith('http'):
            old_p = os.path.join(app.root_path, app.config['ADMIN_UPLOAD_FOLDER'], old_image)
            try:
                if os.path.exists(old_p):
                    os.remove(old_p)
            except Exception:
                pass
    else:
        final_image = old_image

    cursor.execute(
        "UPDATE admin SET name=%s, email=%s, password=%s, profile_image=%s WHERE admin_id=%s",
        (name, email, hashed, final_image, admin_id)
    )
    conn.commit()
    conn.close()

    session['admin_name']  = name
    session['admin_email'] = email
    # update profile image in session so navbar updates immediately
    session['admin_profile_image'] = final_image or ''
    flash("Profile updated successfully!", "success")
    return redirect('/admin/profile')


# ================================================================
# ADMIN ORDERS
# ================================================================
@app.route('/admin/orders')
def admin_orders():
    if 'admin_id' not in session:
        flash("Please login!", "danger")
        return redirect('/admin-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, u.name as user_name, u.email as user_email
        FROM orders o JOIN users u ON o.user_id=u.user_id
        ORDER BY o.created_at DESC
    """)
    raw = cursor.fetchall()
    conn.close()

    orders = []
    for row in raw:
        o = dict(row)
        if o.get('created_at') and isinstance(o['created_at'], str):
            try:
                o['created_at'] = datetime.strptime(o['created_at'][:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                o['created_at'] = None
        orders.append(o)

    return render_template('admin/admin_orders.html', orders=orders)


@app.route('/admin/order/<int:order_id>')
def admin_view_order(order_id):
    if 'admin_id' not in session:
        flash("Please login!", "danger")
        return redirect('/admin-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, u.name as user_name, u.email as user_email, u.phone as user_phone
        FROM orders o JOIN users u ON o.user_id=u.user_id
        WHERE o.order_id=%s
    """, (order_id,))
    order = cursor.fetchone()
    cursor.execute("SELECT * FROM order_items WHERE order_id=%s", (order_id,))
    items = cursor.fetchall()
    conn.close()

    if not order:
        flash("Order not found!", "danger")
        return redirect('/admin/orders')

    order = dict(order)
    if order.get('created_at') and isinstance(order['created_at'], str):
        try:
            order['created_at'] = datetime.strptime(order['created_at'][:19], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            order['created_at'] = None

    return render_template('admin/admin_order_detail.html', order=order, items=items)


# ================================================================
# USER REGISTRATION / LOGIN / LOGOUT
# ================================================================
@app.route('/user-register', methods=['GET', 'POST'])
def user_register():
    if request.method == 'GET':
        return render_template('user/user_register.html')

    name     = request.form['name']
    email    = request.form['email']
    password = request.form['password']
    phone    = request.form.get('phone', '')
    address  = request.form.get('address', '')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
    if cursor.fetchone():
        flash("Email already registered!", "danger")
        conn.close()
        return redirect('/user-register')

    # handle optional profile image
    profile_image_url = None
    try:
        new_image = request.files.get('profile_image')
        if new_image and getattr(new_image, 'filename', '') != '':
            if config.CLOUDINARY_URL:
                try:
                    upload_result = cloudinary.uploader.upload(new_image)
                    profile_image_url = upload_result.get('secure_url')
                except Exception:
                    profile_image_url = None
            else:
                # save locally
                filename = secure_filename(new_image.filename)
                os.makedirs(app.config.get('UPLOAD_FOLDER', 'static/uploads/product_images'), exist_ok=True)
                save_path = os.path.join(app.config.get('UPLOAD_FOLDER', 'static/uploads/product_images'), filename)
                try:
                    new_image.save(save_path)
                    profile_image_url = url_for('static', filename=f'uploads/product_images/{filename}')
                except Exception:
                    profile_image_url = None
    except Exception:
        profile_image_url = None

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    cursor.execute(
        "INSERT INTO users (name, email, password, phone, address, profile_image) VALUES (%s,%s,%s,%s,%s,%s)",
        (name, email, hashed, phone, address, profile_image_url)
    )
    conn.commit()
    conn.close()

    flash("Registration successful! Please login.", "success")
    return redirect('/user-login')


@app.route('/user-login', methods=['GET', 'POST'])
def user_login():
    if request.method == 'GET':
        return render_template('user/user_login.html')

    email    = request.form['email']
    password = request.form['password']

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        flash("Email not found!", "danger")
        return redirect('/user-login')

    stored_pw = user['password']
    if isinstance(stored_pw, str):
        stored_pw = stored_pw.encode()

    if not bcrypt.checkpw(password.encode(), stored_pw):
        flash("Incorrect password!", "danger")
        return redirect('/user-login')

    session['user_id']    = user['user_id']
    session['user_name']  = user['name']
    session['user_email'] = user['email']
    # store profile image in session for navbar
    session['user_profile_image'] = user.get('profile_image') or ''

    flash("Login successful!", "success")
    return redirect('/user-dashboard')


@app.route('/user-logout')
def user_logout():
    for k in ['user_id', 'user_name', 'user_email', 'cart', 'user_profile_image']:
        session.pop(k, None)
    flash("Logged out successfully!", "success")
    return redirect('/user-login')


# ================================================================
# USER FORGOT / RESET PASSWORD
# ================================================================
@app.route('/user-forgot-password', methods=['GET', 'POST'])
def user_forgot_password():
    if request.method == 'GET':
        return render_template('user/user_forgot_password.html')

    email  = request.form['email']
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        flash("Email not found!", "danger")
        return redirect('/user-forgot-password')

    otp = random.randint(100000, 999999)
    session['user_reset_otp']   = otp
    session['user_reset_email'] = email

    try:
        msg = Message("ShopCart Password Reset OTP", sender=app.config.get('MAIL_DEFAULT_SENDER', app.config.get('MAIL_USERNAME')), recipients=[email])
        msg.body = f"Your OTP for ShopCart Password Reset is: {otp}\n\nThis OTP is valid for 10 minutes."
        send_email(msg)
        flash("OTP sent to your email!", "success")
    except Exception as e:
        flash(f"Error sending email: {str(e)}", "danger")
        return redirect('/user-forgot-password')

    return redirect('/user-reset-password')


@app.route('/user-reset-password', methods=['GET', 'POST'])
def user_reset_password():
    if request.method == 'GET':
        return render_template('user/user_reset_password.html')

    user_otp         = request.form['otp']
    new_password     = request.form['password']
    confirm_password = request.form['confirm_password']

    if str(session.get('user_reset_otp')) != str(user_otp):
        flash("Invalid OTP.", "danger")
        return redirect('/user-reset-password')
    if new_password != confirm_password:
        flash("Passwords do not match!", "danger")
        return redirect('/user-reset-password')

    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
    email  = session.get('user_reset_email')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET password=%s WHERE email=%s", (hashed, email))
    conn.commit()
    conn.close()

    for k in ['user_reset_otp', 'user_reset_email']:
        session.pop(k, None)

    flash("Password reset successfully!", "success")
    return redirect('/user-login')


# ================================================================
# USER DASHBOARD
# ================================================================
@app.route('/user-dashboard')
def user_dashboard():
    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect('/user-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE quantity > 0 ORDER BY product_id DESC")
    featured = cursor.fetchall()
    cursor.execute("SELECT DISTINCT category FROM products WHERE quantity > 0")
    categories = cursor.fetchall()
    conn.close()

    cart       = session.get('cart', {})
    cart_count = sum(i['quantity'] for i in cart.values())

    return render_template('user/user_home.html',
                           user_name=session['user_name'],
                           featured_products=featured,
                           categories=categories,
                           cart_count=cart_count)


# ================================================================
# USER PRODUCTS
# ================================================================
@app.route('/user/products')
def user_products():
    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    search   = request.args.get('search', '')
    category = request.args.get('category', '')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT category FROM products WHERE quantity > 0")
    categories = cursor.fetchall()

    query  = "SELECT * FROM products WHERE quantity > 0"
    params = []

    if search:
        query  += " AND name LIKE %s"
        params.append("%" + search + "%")
    if category:
        query  += " AND category = %s"
        params.append(category)

    query += " ORDER BY product_id DESC"
    cursor.execute(query, params)
    products = cursor.fetchall()
    conn.close()

    cart       = session.get('cart', {})
    cart_count = sum(i['quantity'] for i in cart.values())

    return render_template('user/user_products.html',
                           products=products, categories=categories, cart_count=cart_count)


# ================================================================
# USER PRODUCT DETAILS
# ================================================================
@app.route('/user/product/<int:product_id>')
def user_product_details(product_id):
    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE product_id=%s", (product_id,))
    product = cursor.fetchone()

    if not product:
        flash("Product not found!", "danger")
        conn.close()
        return redirect('/user/products')

    # Convert Decimal price (from DB) to float for template arithmetic
    try:
        if product.get('price') is not None:
            product['price'] = float(product['price'])
    except Exception:
        pass

    cursor.execute(
        "SELECT * FROM products WHERE category=%s AND product_id!=%s AND quantity>0 LIMIT 4",
        (product['category'], product_id)
    )
    related = cursor.fetchall()
    conn.close()

    # Convert prices for related products as well
    try:
        for r in related:
            if r.get('price') is not None:
                r['price'] = float(r['price'])
    except Exception:
        pass

    cart       = session.get('cart', {})
    cart_count = sum(i['quantity'] for i in cart.values())

    return render_template('user/product_details.html', product=product, related=related, cart_count=cart_count)


# ================================================================
# CART OPERATIONS
# ================================================================
@app.route('/user/add-to-cart/<int:product_id>')
def add_to_cart(product_id):
    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect('/user-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE product_id=%s AND quantity>0", (product_id,))
    product = cursor.fetchone()
    conn.close()

    if not product:
        flash("Product not available.", "danger")
        return redirect('/user/products')

    cart = session.get('cart', {})
    pid  = str(product_id)

    current_in_cart = cart[pid]['quantity'] if pid in cart else 0
    if current_in_cart >= product['quantity']:
        flash(f"Sorry, only {product['quantity']} unit(s) available in stock.", "warning")
        return redirect('/user/cart')

    if pid in cart:
        cart[pid]['quantity'] += 1
    else:
        cart[pid] = {
            'name':     product['name'],
            'price':    float(product['price']),
            'image':    product['image'],
            'quantity': 1,
            'stock':    product['quantity']
        }

    session['cart'] = cart
    flash(f"'{product['name']}' added to cart!", "success")
    return redirect('/user/cart')


@app.route('/user/cart')
def view_cart():
    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect('/user-login')

    cart        = session.get('cart', {})
    grand_total = sum(i['price'] * i['quantity'] for i in cart.values())
    cart_count  = sum(i['quantity'] for i in cart.values())

    return render_template('user/cart.html', cart=cart, grand_total=grand_total, cart_count=cart_count)


@app.route('/user/cart/increase/<pid>')
def increase_quantity(pid):
    cart = session.get('cart', {})
    if pid in cart:
        stock = cart[pid].get('stock', 999)
        if cart[pid]['quantity'] < stock:
            cart[pid]['quantity'] += 1
        else:
            flash("Cannot add more than available stock.", "warning")
    session['cart'] = cart
    return redirect('/user/cart')


@app.route('/user/cart/decrease/<pid>')
def decrease_quantity(pid):
    cart = session.get('cart', {})
    if pid in cart:
        cart[pid]['quantity'] -= 1
        if cart[pid]['quantity'] <= 0:
            cart.pop(pid)
    session['cart'] = cart
    return redirect('/user/cart')


@app.route('/user/cart/remove/<pid>')
def remove_from_cart(pid):
    cart = session.get('cart', {})
    if pid in cart:
        cart.pop(pid)
    session['cart'] = cart
    flash("Item removed!", "success")
    return redirect('/user/cart')


# ================================================================
# PAYMENT
# ================================================================
@app.route('/user/pay', methods=['GET', 'POST'])
def user_pay():
    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    cart = session.get('cart', {})
    if not cart:
        flash("Your cart is empty!", "danger")
        return redirect('/user/products')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=%s", (session['user_id'],))
    user = cursor.fetchone()
    conn.close()

    total_amount   = sum(i['price'] * i['quantity'] for i in cart.values())
    razorpay_amount = int(total_amount * 100)

    try:
        razorpay_order = razorpay_client.order.create({
            "amount":          razorpay_amount,
            "currency":        "INR",
            "payment_capture": "1"
        })
        session['razorpay_order_id'] = razorpay_order['id']
    except Exception as e:
        flash(f"Payment setup failed: {str(e)}", "danger")
        return redirect('/user/cart')

    cart_count = sum(i['quantity'] for i in cart.values())

    return render_template('user/payment.html',
                           amount=total_amount,
                           key_id=config.RAZORPAY_KEY_ID,
                           order_id=razorpay_order['id'],
                           user=user,
                           cart_count=cart_count)


@app.route('/verify-payment', methods=['POST'])
def verify_payment():

    if 'user_id' not in session:
        flash("Please login.", "danger")
        return redirect('/user-login')

    razorpay_payment_id = request.form.get('razorpay_payment_id')
    razorpay_order_id = request.form.get('razorpay_order_id')
    razorpay_signature = request.form.get('razorpay_signature')

    delivery_name = request.form.get('delivery_name', '')
    delivery_phone = request.form.get('delivery_phone', '')
    delivery_address = request.form.get('delivery_address', '')
    delivery_city = request.form.get('delivery_city', '')
    delivery_state = request.form.get('delivery_state', '')
    delivery_pincode = request.form.get('delivery_pincode', '')

    if not (razorpay_payment_id and razorpay_order_id and razorpay_signature):
        flash("Payment verification failed.", "danger")
        return redirect('/user/cart')

    try:

        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })

    except Exception as e:

        app.logger.error("Signature verification failed: %s", e)

        flash("Payment verification failed. Contact support.", "danger")

        return redirect('/user/cart')

    user_id = session['user_id']

    cart = session.get('cart', {})

    total_amount = sum(
        item['price'] * item['quantity']
        for item in cart.values()
    )

    full_address = (
        f"{delivery_name}, "
        f"{delivery_phone}, "
        f"{delivery_address}, "
        f"{delivery_city}, "
        f"{delivery_state} - {delivery_pincode}"
    )

    conn = get_db_connection()

    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO orders
            (
                user_id,
                razorpay_order_id,
                razorpay_payment_id,
                amount,
                payment_status,
                delivery_address
            )
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING order_id
        """, (
            user_id,
            razorpay_order_id,
            razorpay_payment_id,
            total_amount,
            'paid',
            full_address
        ))

        order_db_id = cursor.fetchone()['order_id']

        for pid_str, item in cart.items():

            product_id = int(pid_str)

            cursor.execute("""
                INSERT INTO order_items
                (
                    order_id,
                    product_id,
                    product_name,
                    quantity,
                    price
                )
                VALUES (%s,%s,%s,%s,%s)
            """, (
                order_db_id,
                product_id,
                item['name'],
                item['quantity'],
                item['price']
            ))

            cursor.execute("""
                UPDATE products
                SET quantity = GREATEST(quantity - %s, 0)
                WHERE product_id = %s
            """, (
                item['quantity'],
                product_id
            ))

        conn.commit()

        session.pop('cart', None)

        session.pop('razorpay_order_id', None)

        flash("Payment successful and order placed!", "success")

        return redirect(f"/user/order-success/{order_db_id}")

    except Exception as e:

        conn.rollback()

        app.logger.error(
            "Order storage failed: %s\n%s",
            str(e),
            traceback.format_exc()
        )

        flash("Error saving order. Contact support.", "danger")

        return redirect('/user/cart')

    finally:

        cursor.close()

        conn.close()


# ================================================================
# ORDER SUCCESS
# ================================================================
@app.route('/user/order-success/<int:order_db_id>')
def order_success(order_db_id):
    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, u.name as customer_name, u.email as customer_email, u.phone as customer_phone
        FROM orders o JOIN users u ON o.user_id=u.user_id
        WHERE o.order_id=%s AND o.user_id=%s
    """, (order_db_id, session['user_id']))
    order = cursor.fetchone()
    cursor.execute("SELECT * FROM order_items WHERE order_id=%s", (order_db_id,))
    items = cursor.fetchall()
    conn.close()

    if not order:
        flash("Order not found.", "danger")
        return redirect('/user/products')

    order = dict(order)
    if order.get('created_at') and isinstance(order['created_at'], str):
        try:
            order['created_at'] = datetime.strptime(order['created_at'][:19], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            order['created_at'] = None

    return render_template('user/order_success.html', order=order, items=items, cart_count=0)


# ================================================================
# MY ORDERS
# ================================================================
@app.route('/user/my-orders')
def my_orders():
    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE user_id=%s ORDER BY created_at DESC", (session['user_id'],))
    raw = cursor.fetchall()
    conn.close()

    orders = []
    for row in raw:
        o = dict(row)
        if o.get('created_at') and isinstance(o['created_at'], str):
            try:
                o['created_at'] = datetime.strptime(o['created_at'][:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                o['created_at'] = None
        orders.append(o)

    cart       = session.get('cart', {})
    cart_count = sum(i['quantity'] for i in cart.values())

    return render_template('user/my_orders.html', orders=orders, cart_count=cart_count)


# ================================================================
# DOWNLOAD INVOICE
# ================================================================
@app.route('/user/download-invoice/<int:order_id>')
def download_invoice(order_id):
    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, u.name as customer_name, u.email as customer_email,
               u.phone as customer_phone, u.address as customer_address
        FROM orders o JOIN users u ON o.user_id=u.user_id
        WHERE o.order_id=%s AND o.user_id=%s
    """, (order_id, session['user_id']))
    order = cursor.fetchone()
    cursor.execute("SELECT * FROM order_items WHERE order_id=%s", (order_id,))
    items = cursor.fetchall()
    conn.close()

    if not order:
        flash("Order not found.", "danger")
        return redirect('/user/my-orders')

    order = dict(order)
    if order.get('created_at') and isinstance(order['created_at'], str):
        try:
            order['created_at'] = datetime.strptime(order['created_at'][:19], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            order['created_at'] = None

    html = render_template('user/invoice.html', order=order, items=items)
    pdf  = generate_pdf(html)

    if not pdf:
        flash("Error generating PDF", "danger")
        return redirect('/user/my-orders')

    response = make_response(pdf.getvalue())
    response.headers['Content-Type']        = 'application/pdf'
    response.headers['Content-Disposition'] = f"attachment; filename=ShopCart_Invoice_{order_id}.pdf"
    return response


# ================================================================
# USER PROFILE
# ================================================================
@app.route('/user/profile', methods=['GET', 'POST'])
def user_profile():
    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    conn   = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (session['user_id'],))
        user = cursor.fetchone()
        conn.close()
        cart       = session.get('cart', {})
        cart_count = sum(i['quantity'] for i in cart.values())
        return render_template('user/user_profile.html', user=user, cart_count=cart_count)

    name    = request.form['name']
    phone   = request.form.get('phone', '')
    address = request.form.get('address', '')

    # handle profile image upload (optional)
    profile_image_url = None
    try:
        new_image = request.files.get('profile_image')
        if new_image and getattr(new_image, 'filename', '') != '':
            if config.CLOUDINARY_URL:
                try:
                    upload_result = cloudinary.uploader.upload(new_image)
                    profile_image_url = upload_result.get('secure_url')
                except Exception as e:
                    app.logger.error('Cloudinary upload failed for user profile: %s', e)
                    profile_image_url = None
            else:
                filename = secure_filename(new_image.filename)
                os.makedirs(app.config.get('ADMIN_UPLOAD_FOLDER', 'static/uploads/admin_profiles'), exist_ok=True)
                save_path = os.path.join(app.config.get('ADMIN_UPLOAD_FOLDER', 'static/uploads/admin_profiles'), filename)
                try:
                    new_image.save(save_path)
                    profile_image_url = url_for('static', filename=f'uploads/admin_profiles/{filename}')
                except Exception:
                    profile_image_url = None
    except Exception:
        profile_image_url = None

    if profile_image_url:
        cursor.execute("UPDATE users SET name=%s, phone=%s, address=%s, profile_image=%s WHERE user_id=%s",
                       (name, phone, address, profile_image_url, session['user_id']))
        session['user_profile_image'] = profile_image_url
    else:
        cursor.execute("UPDATE users SET name=%s, phone=%s, address=%s WHERE user_id=%s",
                       (name, phone, address, session['user_id']))

    conn.commit()
    conn.close()

    session['user_name'] = name
    flash("Profile updated successfully!", "success")
    return redirect('/user/profile')


# ========================
def seed_super_admin():
    """
    Hard-codes ghanashyam@gmail.com as the Super Admin.
    Safe to call multiple times — it only creates/upgrades, never deletes.
    """
    email    = 'ghana19183@gmail.com'
    name     = 'Ghana Shyam'
    password = 'Ghana@2003'

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    conn   = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT admin_id FROM admin WHERE email=%s", (email,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            "UPDATE admin SET name=%s, password=%s, is_approved=True, is_super_admin=True WHERE email=%s",
            (name, hashed, email)
        )
        print(f"[seed] Updated '{email}' → Super Admin.")
    else:
        cursor.execute(
            "INSERT INTO admin (name, email, password, is_approved, is_super_admin) VALUES (%s,%s,%s,True,True)",
            (name, email, hashed)
        )
        print(f"[seed] Created Super Admin '{email}'.")

    conn.commit()
    conn.close()

    
@app.context_processor
def inject_categories():
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM products WHERE quantity > 0 AND category IS NOT NULL ORDER BY category")
        cats = cursor.fetchall()
        conn.close()
        return {'categories': cats}
    except Exception:
        return {'categories': []}


if __name__ == '__main__':
    import sys
    with app.app_context():
        init_db()

    if '--create-super-admin' in sys.argv:
        seed_super_admin()
        print("Done. Login with ghanashyam@gmail.com / Ghana@2003")
    else:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM admin")
        count = cursor.fetchone()['c']
        conn.close()
        if count == 0:
            print("[startup] No admins found — seeding Super Admin...")
            seed_super_admin()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
