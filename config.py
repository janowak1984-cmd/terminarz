import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    SQLALCHEMY_DATABASE_URI = (
        os.getenv("DATABASE_URL")
        or (
            f"mysql+pymysql://{os.environ.get('MYSQLUSER')}:"
            f"{os.environ.get('MYSQLPASSWORD')}@"
            f"{os.environ.get('MYSQLHOST')}:"
            f"{os.environ.get('MYSQLPORT')}/"
            f"{os.environ.get('MYSQLDATABASE')}"
        )
        or "sqlite:///dev.db"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
