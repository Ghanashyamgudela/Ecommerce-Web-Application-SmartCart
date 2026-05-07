import os

# =========================================================
# APP SECRET
# =========================================================
SECRET_KEY = os.environ.get("SECRET_KEY")

# =========================================================
# RAZORPAY
# =========================================================
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

# =========================================================
# POSTGRESQL / NEON DATABASE
# =========================================================
DATABASE_URL = os.environ.get("DATABASE_URL")

# =========================================================
# MAIL CONFIG
# =========================================================
MAIL_SERVER = os.environ.get("MAIL_SERVER")

MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD =  os.environ.get("MAIL_PASSWORD")

# =========================================================
# SUPER ADMIN
# =========================================================
SUPER_ADMIN_EMAIL = 'ghana19183@gmail.com'
