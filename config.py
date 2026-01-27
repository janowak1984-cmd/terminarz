import os


def _fix_database_url(url: str | None) -> str | None:
    """
    Railway często ustawia DATABASE_URL jako mysql://...
    SQLAlchemy + PyMySQL WYMAGA mysql+pymysql://
    """
    if not url:
        return None

    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+pymysql://", 1)

    return url


class Config:
    # ─────────────────────────
    # CORE
    # ─────────────────────────
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    # ─────────────────────────
    # DATABASE (RAILWAY SAFE)
    # ─────────────────────────
    SQLALCHEMY_DATABASE_URI = _fix_database_url(
        os.getenv("DATABASE_URL")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ─────────────────────────
    # GOOGLE CALENDAR
    # ─────────────────────────
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

    # ─────────────────────────
    # SMS
    # ─────────────────────────
    SMSAPI_TOKEN = os.getenv("SMSAPI_TOKEN")
    SMSAPI_SENDER = os.getenv("SMSAPI_SENDER")

    # ─────────────────────────
    # EMAIL (SMTP)
    # ─────────────────────────
    MAIL_HOST = os.getenv("MAIL_HOST")
    MAIL_PORT = int(os.getenv("MAIL_PORT") or 587)
    MAIL_USER = os.getenv("MAIL_USER")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")

    # np. "Rejestracja wizyt <bobinska@kingabobinska.pl>"
    MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USER)

    # ─────────────────────────
    # SENDGRID (EMAIL API)
    # ─────────────────────────
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

    # 📬 ADRES DO FORMULARZA KONTAKTOWEGO
    CONTACT_FORM_TO = os.getenv(
        "CONTACT_FORM_TO",
        "bobinskagabinet@gmail.com"
    )

    # ─────────────────────────
    # APP
    # ─────────────────────────
    BASE_URL = os.getenv(
        "BASE_URL",
        "http://127.0.0.1:5000"
    ).rstrip("/")
