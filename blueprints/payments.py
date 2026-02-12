import uuid
import json
import hashlib
import requests
import base64
from decimal import Decimal
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app, render_template
from extensions import db
from models import Appointment, Payment, VisitType


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

    session_id = data["sessionId"]
    order_id = data["orderId"]
    amount = data["amount"]
    currency = data["currency"]
    received_sign = data["sign"]

    payment = Payment.query.filter_by(
        provider="przelewy24",
        provider_session_id=session_id
    ).first()

    if not payment:
        current_app.logger.warning("[P24 STATUS] Payment not found")
        return "ERROR", 404

    # ✅ Idempotency
    if payment.status == "paid":
        current_app.logger.warning("[P24 STATUS] Already paid - idempotent OK")
        return "OK", 200

    # ✅ Amount validation
    try:
        if int(payment.amount) != int(amount):
            current_app.logger.warning("[P24 STATUS] Amount mismatch")
            payment.status = "failed"
            db.session.commit()
            return "ERROR", 400
    except Exception:
        current_app.logger.warning("[P24 STATUS] Invalid amount format")
        return "ERROR", 400

    # 🔐 POPRAWNE LICZENIE SIGN DLA CALLBACK
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

    current_app.logger.warning(f"[P24 STATUS] SIGN JSON = {json_string}")
    current_app.logger.warning(f"[P24 STATUS] CALCULATED SIGN = {calculated_sign}")
    current_app.logger.warning(f"[P24 STATUS] RECEIVED SIGN = {received_sign}")

    if calculated_sign != received_sign:
        current_app.logger.warning("[P24 STATUS] Invalid sign")
        return "ERROR", 400

    # zapisujemy orderId
    payment.provider_order_id = order_id

    # 🔐 VERIFY CALL (transaction/verify)
    if not _p24_verify_transaction(payment):
        payment.status = "failed"
        db.session.commit()
        return "ERROR", 400

    payment.status = "paid"
    payment.paid_at = datetime.utcnow()
    #payment.appointment.status = "confirmed"

    db.session.commit()

    current_app.logger.warning("[P24 STATUS] Payment verified and marked as PAID")

    return "OK", 200


# ==================================================
# RETURN
# ==================================================
@payments_bp.route("/return", methods=["GET"])
def payment_return():
    session_id = request.args.get("sessionId")

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

    if payment.status == "paid":
        return render_template(
            "payments/payment_success.html",
            appointment=payment.appointment,
            payment=payment
        )

    if payment.status == "pending":
        return render_template("payments/pending.html")

    return render_template(
        "payments/payment_fail.html",
        reason="Płatność nie została potwierdzona."
    )



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

    payload = {
        "merchantId": int(cfg["P24_MERCHANT_ID"]),
        "posId": int(cfg["P24_POS_ID"]),
        "sessionId": payment.provider_session_id,
        "amount": int(payment.amount),
        "currency": "PLN",
        "description": "Rezerwacja wizyty",
        "email": payment.appointment.patient_email or "kontakt@kingabobinska.pl",
        "country": "PL",
        "language": "pl",
        "urlReturn": cfg["P24_RETURN_URL"],
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

