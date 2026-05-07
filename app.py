from flask import Flask, render_template, request, redirect, session, flash, make_response, jsonify, url_for
from flask_mail import Mail, Message
import psycopg2
import psycopg2.extras
import bcrypt
import random
import config
import os
from werkzeug.utils import secure_filename
import razorpay
import traceback
import uuid
from utils.pdf_generator import generate_pdf
from datetime import datetime


app = Flask(__name__)


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

razorpay_client = razorpay.Client(
    auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET)
)

app.config['MAIL_SERVER'] = config.MAIL_SERVER
app.config['MAIL_PORT'] = config.MAIL_PORT
app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD

mail = Mail(app)

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
        conn = psycopg2.connect(
            database_url,
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
    ]:
        try:
            cursor.execute(col_sql)
        except Exception:
            pass

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
        return render_template('admin/admin_signup.html')

    name  = request.form['name']
    email = request.form['email']

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

    session['signup_name']  = name
    session['signup_email'] = email
    otp = random.randint(100000, 999999)
    session['otp'] = otp
    session['otp_purpose'] = 'admin_signup'

    try:
        msg = Message("ShopCart Admin OTP", sender=config.MAIL_USERNAME, recipients=[email])
        msg.body = f"Your OTP for ShopCart Admin Registration is: {otp}\n\nThis OTP is valid for 10 minutes."
        mail.send(msg)
        flash("OTP sent to your email!", "success")
    except Exception as e:
        flash(f"Error sending email: {str(e)}", "danger")

    return redirect('/verify-otp')


# ================================================================
# VERIFY OTP — saves request as pending (not approved yet)
# ================================================================
@app.route('/verify-otp', methods=['GET'])
def verify_otp_get():
    return render_template('admin/verify_otp.html')


@app.route('/verify-otp', methods=['POST'])
def verify_otp_post():
    user_otp = request.form['otp']
    password = request.form['password']

    if str(session.get('otp')) != str(user_otp):
        flash("Invalid OTP. Try again!", "danger")
        return redirect('/verify-otp')

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    requester_name  = session.get('signup_name', '')
    requester_email = session.get('signup_email', '')

    conn   = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt FROM admin")
    admin_count = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) as cnt FROM admin_requests")
    req_count = cursor.fetchone()['cnt']

    if admin_count == 0 and req_count == 0:
        cursor.execute(
            "INSERT INTO admin (name, email, password, is_approved, is_super_admin) VALUES (%s,%s,%s,1,1)",
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

            if existing_rejected:
                cursor.execute(
                    "UPDATE admin_requests SET name=%s, password=%s, status='pending', created_at=CURRENT_TIMESTAMP WHERE email=%s",
                    (requester_name, hashed, requester_email)
                )
            else:
                cursor.execute(
                    "INSERT INTO admin_requests (name, email, password) VALUES (%s,%s,%s)",
                    (requester_name, requester_email, hashed)
                )
            conn.commit()
        except Exception as e:
            conn.close()
            flash(f"Error saving request: {e}", "danger")
            return redirect('/verify-otp')

        try:
            cursor.execute(
                "SELECT email FROM admin WHERE is_super_admin=1 AND is_approved=1"
            )
            super_admins = cursor.fetchall()
            conn.close()

            if super_admins:
                for sa in super_admins:
                    msg = Message(
                            subject="ShopCart — New Admin Registration Request",
                            sender=config.MAIL_USERNAME,
                            recipients=[sa['email']]
                        )
                    msg.body = (
                            f"Hello Super Admin,\n\n"
                            f"A new admin registration request is awaiting your approval.\n\n"
                            f"Name  : {requester_name}\n"
                            f"Email : {requester_email}\n\n"
                            f"Please log in to the ShopCart Admin Panel and go to\n"
                            f"'Admin Requests' to approve or reject this request.\n\n"
                            f"Login URL : {url_for('admin_login', _external=True)}\n\n"
                            f"Regards,\nShopCart System"
                        )
                    mail.send(msg)
        except Exception as mail_err:
            app.logger.error("Failed to notify super admin(s): %s", mail_err)
            try:
                conn.close()
            except Exception:
                pass

        for k in ['otp', 'signup_name', 'signup_email', 'otp_purpose']:
            session.pop(k, None)
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
    if isinstance(stored_pw, str):
        stored_pw = stored_pw.encode()

    if not bcrypt.checkpw(password.encode(), stored_pw):
        flash("Incorrect password!", "danger")
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
        msg = Message("ShopCart Password Reset OTP", sender=config.MAIL_USERNAME, recipients=[email])
        msg.body = f"Your OTP for ShopCart Admin Password Reset is: {otp}\n\nThis OTP is valid for 10 minutes."
        mail.send(msg)
        flash("OTP sent to your email!", "success")
    except Exception as e:
        flash(f"Error sending email: {str(e)}", "danger")
        return redirect('/admin-forgot-password')

    return redirect('/admin-reset-password')


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
        cursor.execute(
            "INSERT INTO admin (name, email, password, is_approved, is_super_admin) VALUES (%s,%s,%s,1,0)",
            (req['name'], req['email'], req['password'])
        )
        cursor.execute("UPDATE admin_requests SET status='approved' WHERE request_id=%s", (req_id,))
        conn.commit()
        flash(f"Admin '{req['name']}' approved successfully!", "success")
        # send approval email to the newly approved admin
        try:
            msg = Message("ShopCart Admin Account Approved", sender=config.MAIL_USERNAME, recipients=[req['email']])
            msg.body = (
                f"Hello {req['name']},\n\n"
                "Your ShopCart admin account request has been approved by the super admin.\n"
                f"You can now sign in here: {url_for('admin_login', _external=True)}\n\n"
                "If you did not request this account, please contact support.\n\n"
                "Regards,\nShopCart Team"
            )
            mail.send(msg)
            flash("Approval email sent to the admin.", "success")
        except Exception as e:
            # don't block the flow on mail errors; notify the super admin
            flash(f"Approved but failed to send email: {str(e)}", "warning")
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
    new_password = request.form.get('password', '')

    try:
        hashed = None
        if new_password:
            hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
            cursor.execute(
                "UPDATE admin_requests SET name=%s, email=%s, password=%s WHERE request_id=%s",
                (name, email, hashed, req_id)
            )
        else:
            cursor.execute(
                "UPDATE admin_requests SET name=%s, email=%s WHERE request_id=%s",
                (name, email, req_id)
            )
        conn.commit()

        # If the request was already approved, reflect changes into the actual admin record
        if original_status == 'approved':
            try:
                if hashed:
                    cursor.execute(
                        "UPDATE admin SET name=%s, email=%s, password=%s WHERE email=%s",
                        (name, email, hashed, original_email)
                    )
                else:
                    cursor.execute(
                        "UPDATE admin SET name=%s, email=%s WHERE email=%s",
                        (name, email, original_email)
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
                msg = Message("ShopCart Admin Access Revoked", sender=config.MAIL_USERNAME, recipients=[req['email']])
                msg.body = (
                    f"Hello {req['name']},\n\n"
                    "Your ShopCart admin access has been revoked by the Super Admin.\n"
                    "If you believe this is a mistake, please contact the site administrator.\n\n"
                    "Regards,\nShopCart Team"
                )
                mail.send(msg)
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
        filename = secure_filename(img.filename)
        # make filename reasonably unique to avoid clashes
        unique_name = f"{str(uuid.uuid4())[:8]}_{filename}"
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        img.save(image_path)
        saved_filenames.append(unique_name)
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
        new_filename = secure_filename(new_image.filename)
        unique_name = f"{str(uuid.uuid4())[:8]}_{new_filename}"
        new_image.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
        # remove all old images if multiple were stored
        if old_image_name:
            for old in old_image_name.split('||'):
                if not old:
                    continue
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], old)
                try:
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception:
                    pass
        final_image = unique_name
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
        new_fn = secure_filename(new_image.filename)
        # prefix with uuid to avoid name collisions
        new_fn = f"{uuid.uuid4().hex}_{new_fn}"
        # save using absolute path to ensure correct location
        save_path = os.path.join(app.root_path, app.config['ADMIN_UPLOAD_FOLDER'], new_fn)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        new_image.save(save_path)
        if old_image:
            old_p = os.path.join(app.root_path, app.config['ADMIN_UPLOAD_FOLDER'], old_image)
            if os.path.exists(old_p):
                os.remove(old_p)
        final_image = new_fn
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

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    cursor.execute(
        "INSERT INTO users (name, email, password, phone, address) VALUES (%s,%s,%s,%s,%s)",
        (name, email, hashed, phone, address)
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

    flash("Login successful!", "success")
    return redirect('/user-dashboard')


@app.route('/user-logout')
def user_logout():
    for k in ['user_id', 'user_name', 'user_email', 'cart']:
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
        msg = Message("ShopCart Password Reset OTP", sender=config.MAIL_USERNAME, recipients=[email])
        msg.body = f"Your OTP for ShopCart Password Reset is: {otp}\n\nThis OTP is valid for 10 minutes."
        mail.send(msg)
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
            "UPDATE admin SET name=%s, password=%s, is_approved=1, is_super_admin=1 WHERE email=%s",
            (name, hashed, email)
        )
        print(f"[seed] Updated '{email}' → Super Admin.")
    else:
        cursor.execute(
            "INSERT INTO admin (name, email, password, is_approved, is_super_admin) VALUES (%s,%s,%s,1,1)",
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
