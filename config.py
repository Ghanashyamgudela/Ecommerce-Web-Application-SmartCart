import os

# =========================================================
# APP SECRET
# =========================================================
SECRET_KEY = os.environ.get("SECRET_KEY")

# =========================================================
# RAZORPAY
# =========================================================
RAZORPAY_KEY_ID = os.environ.get("rzp_test_SlGbnJzNHYY2kL")
RAZORPAY_KEY_SECRET = os.environ.get("6v9njW4QuWqc95585eUo7xwr")

# =========================================================
# POSTGRESQL / NEON DATABASE
# =========================================================
DATABASE_URL = os.environ.get("DATABASE_URL")

# =========================================================
# MAIL CONFIG
# =========================================================
MAIL_SERVER = 'smtp-relay.brevo.com'
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD =  os.environ.get("MAIL_PASSWORD")

# =========================================================
# SUPER ADMIN
# =========================================================
SUPER_ADMIN_EMAIL = 'ghana19183@gmail.com'
