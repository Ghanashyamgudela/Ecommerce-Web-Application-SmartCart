import os

# =========================================================
# APP SECRET
# =========================================================
SECRET_KEY = os.getenv("SECRET_KEY", "abe123")

# =========================================================
# RAZORPAY
# =========================================================
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

# =========================================================
# POSTGRESQL / NEON DATABASE
# =========================================================
DATABASE_URL = os.getenv("DATABASE_URL")

# =========================================================
# MAIL CONFIG
# =========================================================
MAIL_SERVER = 'smtp.gmail.com'
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")

# =========================================================
# SUPER ADMIN
# =========================================================
SUPER_ADMIN_EMAIL = 'ghana19183@gmail.com'
