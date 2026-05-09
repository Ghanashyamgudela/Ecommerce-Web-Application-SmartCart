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
MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")

MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "False").lower() in ("1", "true", "yes")

MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "True").lower() in ("1", "true", "yes")
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")


CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")

# Optional explicit parts (used if CLOUDINARY_URL is not provided)
CLOUDINARY = {
	"cloud_name": os.getenv("CLOUDINARY_CLOUD_NAME"),
	"api_key": os.getenv("CLOUDINARY_API_KEY"),
	"api_secret": os.getenv("CLOUDINARY_API_SECRET"),
}
# =========================================================
# SUPER ADMIN
# =========================================================
SUPER_ADMIN_EMAIL = 'ghana19183@gmail.com'
