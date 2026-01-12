import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    SQLALCHEMY_DATABASE_URI = (os.getenv("DATABASE_URL"))

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

    SMSAPI_TOKEN = os.getenv("SMSAPI_TOKEN")
    SMSAPI_SENDER = os.getenv("SMSAPI_SENDER")
    BASE_URL = os.getenv("BASE_URL")


