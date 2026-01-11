import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    DB_USER = os.environ.get("MYSQLUSER")
    DB_PASSWORD = os.environ.get("MYSQLPASSWORD")
    DB_HOST = os.environ.get("MYSQLHOST")
    DB_PORT = os.environ.get("MYSQLPORT")
    DB_NAME = os.environ.get("MYSQLDATABASE")

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+mysqldb://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")
