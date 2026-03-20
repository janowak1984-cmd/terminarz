from flask import Blueprint, request, jsonify, current_app
import re
from utils.email_service import EmailService

site_api_bp = Blueprint("site_api", __name__)

NAME_REGEX = re.compile(r"^[A-Za-zÀ-žąćęłńóśżźĄĆĘŁŃÓŚŻŹ\s-]+$")
EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_REGEX = re.compile(r"^\+48\d{9}$")


@site_api_bp.route("/api/contact", methods=["POST"])
def contact_form():
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    message = data.get("message", "").strip()

    # ───── WALIDACJA ─────
    if not name or not NAME_REGEX.fullmatch(name):
        return jsonify(success=False, error="invalid_name"), 400

    if not email or not EMAIL_REGEX.fullmatch(email):
        return jsonify(success=False, error="invalid_email"), 400

    if phone:
        if phone != "+48" and not PHONE_REGEX.fullmatch(phone):
            return jsonify(success=False, error="invalid_phone"), 400
        if phone == "+48":
            phone = ""

    if not message:
        return jsonify(success=False, error="empty_message"), 400

    # ───── TREŚĆ MAILA ─────
    body = (
        f"Nowa wiadomość z formularza kontaktowego – kingabobinska.pl\n\n"
        f"Imię i nazwisko: {name}\n"
        f"Email: {email}\n"
        f"Telefon: {phone or '—'}\n\n"
        f"Treść wiadomości:\n"
        f"{message}"
    )

    to_email = current_app.config.get("CONTACT_FORM_TO")

    if not to_email:
        current_app.logger.error("[CONTACT FORM] CONTACT_FORM_TO not set")
        return jsonify(success=False), 500

    # ───── WYSYŁKA ─────
    try:
        EmailService().send_raw(
            to=to_email,
            subject="Nowa wiadomość z formularza – kingabobinska.pl",
            body=body,
            reply_to=email
        )
    except Exception as e:
        current_app.logger.error(
            f"[CONTACT FORM] email send failed: {e}"
        )
        return jsonify(success=False), 500

    return jsonify(success=True)
