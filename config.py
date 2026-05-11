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
MAIL_USE_SSL = False

MAIL_USE_TLS = True
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD =  os.environ.get("MAIL_PASSWORD")


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

# =========================================================
# SENDGRID
# =========================================================
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
# Optional default sender address for SendGrid (falls back to MAIL_USERNAME)
SENDGRID_SENDER = os.environ.get("SENDGRID_SENDER")

# =========================================================
# OAUTH / SOCIAL LOGIN (Google, Facebook)
# =========================================================
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

FACEBOOK_CLIENT_ID = os.environ.get("FACEBOOK_CLIENT_ID")
FACEBOOK_CLIENT_SECRET = os.environ.get("FACEBOOK_CLIENT_SECRET")

# Optional redirect hosts if you need to override
OAUTH_REDIRECT_BASE = os.environ.get("OAUTH_REDIRECT_BASE")

# Explicit OAuth redirect URIs (optional). If not set, they will be
# derived from `OAUTH_REDIRECT_BASE` when that is provided.
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI") or (OAUTH_REDIRECT_BASE.rstrip('/') + "/login/google/callback" if OAUTH_REDIRECT_BASE else None)
FACEBOOK_REDIRECT_URI = os.environ.get("FACEBOOK_REDIRECT_URI") or (OAUTH_REDIRECT_BASE.rstrip('/') + "/login/facebook/callback" if OAUTH_REDIRECT_BASE else None)

# =========================================================
# MICROSOFT (Azure AD / Microsoft Account)
# =========================================================
MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET")
MICROSOFT_REDIRECT_URI = os.environ.get("MICROSOFT_REDIRECT_URI") or (OAUTH_REDIRECT_BASE.rstrip('/') + "/login/microsoft/callback" if OAUTH_REDIRECT_BASE else None)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DEFAULT_TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


