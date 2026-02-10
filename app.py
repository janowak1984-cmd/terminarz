import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, redirect, url_for, send_from_directory, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from extensions import db, login_manager
from models import Doctor
from settings_defaults import init_default_settings
from blueprints.patient_test import patient_test_bp


# ───────────────────────────────────────
# SCHEDULER
# ───────────────────────────────────────
from apscheduler.schedulers.background import BackgroundScheduler
from jobs.send_reminders import run as send_reminders_run


def create_app():

    app = Flask(__name__, static_folder="static")

    # =============================
    # BASE CONFIG
    # =============================
    app.config.from_object(Config)

    # 🔐 SESJA – KRYTYCZNE DLA GOOGLE OAUTH
    cookie_domain = None
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME") == "production":
        cookie_domain = ".kingabobinska.pl"

    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_DOMAIN=cookie_domain,
    )


    # =============================
    # PROXY (RAILWAY / HTTPS)
    # =============================
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1
    )

    # =============================
    # INIT EXTENSIONS
    # =============================
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # =============================
    # LOGIN MANAGER
    # =============================
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Doctor, int(user_id))

    # =============================
    # TEMPLATE FILTERS
    # =============================
    @app.template_filter("month_name")
    def month_name_filter(month):
        names = [
            "", "Styczeń", "Luty", "Marzec", "Kwiecień",
            "Maj", "Czerwiec", "Lipiec", "Sierpień",
            "Wrzesień", "Październik", "Listopad", "Grudzień"
        ]
        return names[month]

    # =============================
    # STRONA GŁÓWNA – STATIC HTML
    # =============================
    @app.route("/")
    def site():
        return send_from_directory("static/site", "index.html")

    # =============================
    # SITEMAP.XML
    # =============================
    @app.route("/sitemap.xml")
    def sitemap():
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.kingabobinska.pl/</loc>
  </url>
  <url>
    <loc>https://www.kingabobinska.pl/rejestracja</loc>
  </url>
</urlset>
"""
        return app.response_class(xml, mimetype="application/xml")

    # =============================
    # GLOBALNY KRÓTKI LINK CANCEL
    # =============================
    @app.route("/c/<token>")
    def cancel_short(token):
        return redirect(
            url_for("patient.cancel_by_token", token=token)
        )

    # =============================
    # 🔍 DEBUG OAUTH – GLOBALNY LOG
    # =============================
    @app.before_request
    def log_oauth_debug():
        if request.path.startswith("/doctor/google"):
            app.logger.warning(
                "[OAUTH DEBUG] path=%s scheme=%s host=%s args_state=%s session_state=%s",
                request.path,
                request.scheme,
                request.host,
                request.args.get("state"),
                session.get("oauth_state"),
            )

    # =============================
    # BLUEPRINTS
    # =============================
    from blueprints.patient import patient_bp
    from blueprints.doctor import doctor_bp
    from blueprints.auth import auth_bp
    from blueprints.doctor_templates import bp as doctor_templates_bp
    from blueprints.doctor_visit_types import bp as doctor_visit_types_bp
    from blueprints.site_api import site_api_bp
    from blueprints.payments import payments_bp


    app.register_blueprint(patient_bp, url_prefix="/rejestracja")
    app.register_blueprint(doctor_bp, url_prefix="/doctor")
    app.register_blueprint(auth_bp)
    app.register_blueprint(patient_test_bp)
    app.register_blueprint(payments_bp)


    app.register_blueprint(
        doctor_visit_types_bp,
        url_prefix="/doctor/visit-types"
    )
    app.register_blueprint(doctor_templates_bp)
    app.register_blueprint(site_api_bp)

    # =============================
    # DB INIT + DEFAULT SETTINGS
    # =============================
    with app.app_context():
        init_default_settings()

    # =============================
    # BACKGROUND SCHEDULER (SMS)
    # =============================
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME") == "production":

        scheduler = BackgroundScheduler(daemon=True)

        def reminder_job_wrapper():
            with app.app_context():
                send_reminders_run()

        scheduler.add_job(
            reminder_job_wrapper,
            trigger="interval",
            minutes=15,
            id="send_sms_reminders",
            replace_existing=True
        )

        scheduler.start()
        print("✅ Background SMS reminder scheduler started")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
