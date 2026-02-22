import uuid
import json
import hashlib
import requests
import base64

PL_MAP = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l",
    "ń": "n", "ó": "o", "ś": "s", "ż": "z", "ź": "z",
    "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L",
    "Ń": "N", "Ó": "O", "Ś": "S", "Ż": "Z", "Ź": "Z"
})

def normalize_pl(text):
    if not text:
        return ""
    return text.translate(PL_MAP)

from decimal import Decimal
from datetime import datetime
from utils.sms_service import SMSService
from utils.email_service import EmailService
from flask import Blueprint, request, jsonify, current_app, render_template
from extensions import db
from models import Appointment, Payment, VisitType
from utils.google_calendar import GoogleCalendarService


payments_bp = Blueprint(
    "payments",
    __name__,
    url_prefix="/payments"
)

# ==================================================
# INIT PAYMENT
# ==================================================
@payments_bp.route("/init", methods=["POST"])
def init_payment():

    data = request.get_json() or {}
    appointment_id = data.get("appointment_id")

    if not appointment_id:
        return jsonify({"error": "appointment_id required"}), 400

    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.status != "scheduled":
        return jsonify({"error": "Invalid appointment status"}), 400

    visit_type = VisitType.query.filter_by(
        code=appointment.visit_type,
        active=True
    ).first()

    if not visit_type or not visit_type.price or visit_type.price <= 0:
        return jsonify({"error": "Visit type not payable"}), 400
    
    existing = Payment.query.filter_by(
        appointment_id=appointment.id,
        provider="przelewy24"
    ).filter(
        Payment.status.in_(["init", "pending"])
    ).first()

    if existing:
        return jsonify({
            "payment_id": existing.id,
            "session_id": existing.provider_session_id
        })


    amount_int = int((visit_type.price * Decimal("100")).quantize(Decimal("1")))
    session_id = uuid.uuid4().hex

    payment = Payment(
        appointment_id=appointment.id,
        provider="przelewy24",
        provider_session_id=session_id,
        amount=amount_int,
        currency="PLN",
        status="init"
    )

    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "payment_id": payment.id,
        "session_id": session_id
    })


# ==================================================
# REGISTER – REST API v1
# ==================================================
@payments_bp.route("/register", methods=["POST"])
def register_payment():
    data = request.get_json() or {}
    payment_id = data.get("payment_id")

    if not payment_id:
        return jsonify({"error": "payment_id required"}), 400

    payment = Payment.query.get_or_404(payment_id)

    if payment.status != "init":
        return jsonify({"error": "Invalid payment status"}), 400

    cfg = current_app.config
    payload = _build_p24_payload(payment)

    auth_raw = f"{cfg['P24_POS_ID']}:{cfg['P24_API_KEY']}"
    auth_b64 = base64.b64encode(auth_raw.encode()).decode()

    r = requests.post(
        cfg["P24_REGISTER_URL"],
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_b64}",
        },
        timeout=15
    )

    if r.status_code != 200:
        current_app.logger.error(f"[P24] register HTTP {r.status_code} {r.text}")
        return jsonify({"error": "Payment provider error"}), 502

    resp = r.json()
    token = resp.get("data", {}).get("token")

    if not token:
        return jsonify({"error": "No token from provider"}), 500

    payment.provider_order_id = token
    payment.status = "pending"
    db.session.commit()

    return jsonify({
        "redirect_url": f"{cfg['P24_REDIRECT_URL']}/{token}"
    })

@payments_bp.route("/status", methods=["POST"])
def payment_status():

    data = request.form.to_dict() if request.form else request.get_json(silent=True) or {}

    required_fields = [
        "merchantId",
        "posId",
        "sessionId",
        "amount",
        "originAmount",
        "currency",
        "orderId",
        "methodId",
        "statement",
        "sign",
    ]

    if not all(field in data for field in required_fields):
        current_app.logger.warning("[P24 STATUS] Missing required fields")
        return "ERROR", 400
    
    cfg = current_app.config

    if int(data["merchantId"]) != int(cfg["P24_MERCHANT_ID"]):
        current_app.logger.warning("[P24 STATUS] Invalid merchantId")
        return "ERROR", 400

    if int(data["posId"]) != int(cfg["P24_POS_ID"]):
        current_app.logger.warning("[P24 STATUS] Invalid posId")
        return "ERROR", 400

    session_id = data["sessionId"]
    order_id = data["orderId"]
    amount = data["amount"]
    received_sign = data["sign"]

    payment = Payment.query.filter_by(
        provider="przelewy24",
        provider_session_id=session_id
    ).first()

    if not payment:
        current_app.logger.warning("[P24 STATUS] Payment not found")
        return "ERROR", 404

    # 🔁 IDEMPOTENCY
    if payment.status == "paid":
        current_app.logger.warning("[P24 STATUS] Already paid - idempotent OK")
        return "OK", 200

    # ==================================================
    # WALIDACJA KWOTY
    # ==================================================
    try:
        if int(payment.amount) != int(amount):
            current_app.logger.warning("[P24 STATUS] Amount mismatch")

            payment.status = "failed"
            db.session.commit()

            if payment.appointment:
                try:
                    EmailService().send_payment_retry(payment.appointment)
                except Exception:
                    pass

            return "ERROR", 400

    except Exception:
        current_app.logger.warning("[P24 STATUS] Invalid amount format")
        return "ERROR", 400

    # ==================================================
    # WALIDACJA SIGN
    # ==================================================
    cfg = current_app.config

    sign_payload = {
        "merchantId": int(data["merchantId"]),
        "posId": int(data["posId"]),
        "sessionId": data["sessionId"],
        "amount": int(data["amount"]),
        "originAmount": int(data["originAmount"]),
        "currency": data["currency"],
        "orderId": int(data["orderId"]),
        "methodId": int(data["methodId"]),
        "statement": data["statement"],
        "crc": cfg["P24_CRC"],
    }

    json_string = json.dumps(
        sign_payload,
        separators=(",", ":"),
        ensure_ascii=False
    )

    calculated_sign = hashlib.sha384(
        json_string.encode("utf-8")
    ).hexdigest()

    if calculated_sign != received_sign:
        current_app.logger.warning("[P24 STATUS] Invalid sign")
        return "ERROR", 400

    payment.provider_order_id = order_id

    # ==================================================
    # VERIFY CALL
    # ==================================================
    if not _p24_verify_transaction(payment):
        payment.status = "failed"
        db.session.commit()

        if payment.appointment:
            try:
                EmailService().send_payment_retry(payment.appointment)
            except Exception:
                pass

        return "ERROR", 400

    # ==================================================
    # SUKCES
    # ==================================================
    payment.status = "paid"
    payment.paid_at = datetime.utcnow()

    appointment = payment.appointment

    # 🔒 jeśli ktoś anulował wizytę w międzyczasie – nie przywracamy jej
    if appointment and appointment.status != "cancelled":
        appointment.status = "scheduled"

    db.session.commit()

    current_app.logger.warning(f"[P24 STATUS] Payment {payment.id} marked as PAID")

    # 🔐 jeśli brak wizyty — kończymy
    if not appointment:
        current_app.logger.error(
            f"[PAYMENT SUCCESS] Payment {payment.id} has no appointment!"
        )
        return "OK", 200

    # ==================================================
    # 🔄 GOOGLE UPDATE (PENDING → CONFIRMED)
    # ==================================================
    try:
        GoogleCalendarService.sync_appointment(appointment, force_update=True)
    except Exception as e:
        current_app.logger.warning(
            f"[GOOGLE][PAYMENT SUCCESS] failed for appointment {appointment.id}: {e}"
        )

    # ==================================================
    # 📩 WYŚLIJ POTWIERDZENIE (TYLKO PO PŁATNOŚCI ONLINE)
    # ==================================================
    try:
        SMSService().send_confirmation(appointment)
    except Exception as e:
        current_app.logger.warning(
            f"[SMS][PAYMENT SUCCESS] failed for appointment {appointment.id}: {e}"
        )

    try:
        EmailService().send_confirmation(appointment)
    except Exception as e:
        current_app.logger.warning(
            f"[EMAIL][PAYMENT SUCCESS] failed for appointment {appointment.id}: {e}"
        )

    return "OK", 200

@payments_bp.route("/return", methods=["GET"])
def payment_return():
    session_id = request.args.get("sessionId")

    current_app.logger.warning(
        f"[P24 RETURN] sessionId from query: {session_id}"
    )

    current_app.logger.warning(f"[RETURN PARAMS] {request.args}")

    if not session_id:
        return render_template("payments/payment_fail.html")

    payment = Payment.query.filter_by(
        provider="przelewy24",
        provider_session_id=session_id
    ).first()

    if not payment:
        return render_template(
            "payments/payment_fail.html",
            reason="Nie znaleziono płatności."
        )

    # ✅ SUKCES
    if payment.status == "paid":
        return render_template(
            "payments/payment_success.html",
            appointment=payment.appointment,
            payment=payment
        )

    # ⏳ W TRAKCIE
    if payment.status in ("pending", "init"):
        return render_template("payments/pending.html")

    # ❌ FAKTYCZNA PORAŻKA
    if payment.status == "failed":
        return render_template(
            "payments/payment_fail.html",
            reason="Płatność nie została potwierdzona."
        )

    # 🔐 Fallback (nie powinno się zdarzyć)
    current_app.logger.warning(
        f"[P24 RETURN] Unexpected payment status: {payment.status}"
    )

    return render_template("payments/pending.html")

# ==================================================
# BUILD PAYLOAD – ZGODNIE Z DOKUMENTACJĄ
# ==================================================
def _build_p24_payload(payment: Payment):
    cfg = current_app.config

    sign_payload = {
        "sessionId": payment.provider_session_id,
        "merchantId": int(cfg["P24_MERCHANT_ID"]),
        "amount": int(payment.amount),
        "currency": "PLN",
        "crc": cfg["P24_CRC"],
    }

    json_string = json.dumps(
        sign_payload,
        separators=(",", ":"),
        ensure_ascii=False
    )

    checksum = hashlib.sha384(json_string.encode("utf-8")).hexdigest()

    appointment = payment.appointment

    email = (
        appointment.patient_email
        if appointment and appointment.patient_email
        else "kontakt@kingabobinska.pl"
    )

    client_name = ""
    phone = ""

    if appointment:
        raw_name = f"{appointment.patient_first_name} {appointment.patient_last_name}"
        client_name = normalize_pl(raw_name)

        phone = appointment.patient_phone or ""

    payload = {
        "merchantId": int(cfg["P24_MERCHANT_ID"]),
        "posId": int(cfg["P24_POS_ID"]),
        "sessionId": payment.provider_session_id,
        "amount": int(payment.amount),
        "currency": "PLN",
        "description": f"Rezerwacja wizyty #{appointment.id}" if appointment else "Rezerwacja wizyty",
        "email": email,
        "client": client_name,        # 👈 imię i nazwisko w panelu P24
        "phone": phone,               # 👈 opcjonalnie telefon
        "country": "PL",
        "language": "pl",
        "urlReturn": f"{cfg['P24_RETURN_URL']}?sessionId={payment.provider_session_id}",
        "urlStatus": cfg["P24_STATUS_URL"],
        "sign": checksum
    }

    current_app.logger.warning(f"[P24 DEBUG] SIGN JSON = {json_string}")

    return payload

# ==================================================
# VERIFY TRANSACTION – REST API v1
# ==================================================
def _p24_verify_transaction(payment: Payment):
    cfg = current_app.config

    sign_payload = {
        "sessionId": payment.provider_session_id,
        "orderId": int(payment.provider_order_id),
        "amount": int(payment.amount),
        "currency": "PLN",
        "crc": cfg["P24_CRC"],
    }

    json_string = json.dumps(
        sign_payload,
        separators=(",", ":"),
        ensure_ascii=False
    )

    checksum = hashlib.sha384(json_string.encode("utf-8")).hexdigest()

    payload = {
        "merchantId": int(cfg["P24_MERCHANT_ID"]),
        "posId": int(cfg["P24_POS_ID"]),
        "sessionId": payment.provider_session_id,
        "orderId": int(payment.provider_order_id),
        "amount": int(payment.amount),
        "currency": "PLN",
        "sign": checksum
    }


    auth_raw = f"{cfg['P24_POS_ID']}:{cfg['P24_API_KEY']}"
    auth_b64 = base64.b64encode(auth_raw.encode()).decode()

    r = requests.put(
        cfg["P24_VERIFY_URL"],
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_b64}",
        },
        timeout=15
    )

    if r.status_code != 200:
        current_app.logger.error(f"[P24 VERIFY] HTTP {r.status_code} {r.text}")
        return False

    resp = r.json()

    if resp.get("data", {}).get("status") != "success":
        current_app.logger.error(f"[P24 VERIFY] invalid response {resp}")
        return False

    current_app.logger.warning("[P24 VERIFY] OK")

    return True



