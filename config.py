import os


class Config:
    # ─────────────────────────
    # CORE
    # ─────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # ─────────────────────────
    # DATABASE
    # ─────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ─────────────────────────
    # GOOGLE CALENDAR
    # ─────────────────────────
    GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    GOOGLE_CALENDAR_ID = os.environ.get(
        "GOOGLE_CALENDAR_ID",
        "janowak1984@gmail.com"
    )

    # ─────────────────────────
    # SMS
    # ─────────────────────────
    SMSAPI_TOKEN = os.environ.get("SMSAPI_TOKEN")
    SMSAPI_SENDER = os.environ.get("SMSAPI_SENDER")

    # ─────────────────────────
    # EMAIL (SMTP)
    # ─────────────────────────
    MAIL_HOST = os.environ.get("MAIL_HOST")
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or 587)
    MAIL_USER = os.environ.get("MAIL_USER")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

    MAIL_FROM = os.environ.get("MAIL_FROM", MAIL_USER)

    # ─────────────────────────
    # URL APLIKACJI (PUBLICZNY)
    # ─────────────────────────
    BASE_URL = os.environ.get(
        "BASE_URL",
        "https://www.kingabobinska.pl"
    )

    # ─────────────────────────
    # RESEND (EMAIL API)
    # ─────────────────────────
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY")

    # 📬 ADRES DO FORMULARZA KONTAKTOWEGO
    CONTACT_FORM_TO = os.environ.get(
        "CONTACT_FORM_TO",
        "bobinskagabinet@gmail.com"
    )

   # ─────────────────────────
    # PRZELEWY24 – PRODUKCJA
    # ─────────────────────────
    P24_MERCHANT_ID = int(os.getenv("P24_MERCHANT_ID"))
    P24_POS_ID = int(os.getenv("P24_POS_ID"))      # zwykle = merchantId
    P24_CRC = os.getenv("P24_CRC")
    P24_API_KEY = os.getenv("P24_API_KEY")

    P24_API_URL = "https://secure.przelewy24.pl/api/v1"
    P24_REGISTER_URL = f"{P24_API_URL}/transaction/register"
    P24_VERIFY_URL = f"{P24_API_URL}/transaction/verify"

    P24_REDIRECT_URL = "https://secure.przelewy24.pl/trnRequest"

    P24_RETURN_URL = os.getenv(
        "P24_RETURN_URL",
        f"{BASE_URL}/payments/return"
    )

    P24_STATUS_URL = os.getenv(
        "P24_STATUS_URL",
        f"{BASE_URL}/payments/status"
    )

    P24_CURRENCY = "PLN"
    P24_COUNTRY = "PL"
    P24_LANGUAGE = "pl"

