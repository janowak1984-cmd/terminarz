from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from datetime import datetime, timedelta, time
import uuid

from extensions import db
from models import Availability, Appointment, VisitType, Vacation
from utils.cancel_policy import can_cancel_appointment
from utils.sms_service import SMSService
from utils.blacklist import is_phone_blacklisted
from utils.google_calendar import GoogleCalendarService
from utils.email_service import EmailService
from utils.ip import get_client_ip


patient_bp = Blueprint(
    "patient",
    __name__,
    url_prefix="/rejestracja"
)

# ───────────────────────────────────────
# KONFIGURACJA
# ───────────────────────────────────────

SLOT_MINUTES = 15


# ───────────────────────────────────────
# STRONA GŁÓWNA PACJENTA
# ───────────────────────────────────────

@patient_bp.route("/")
def index():
    return render_template("patient/index.html")


# ───────────────────────────────────────
# API: LISTA TYPÓW WIZYT
# ───────────────────────────────────────

@patient_bp.route("/api/visit-types")
def api_visit_types():
    visit_types = (
        VisitType.query
        .filter_by(active=True)
        .order_by(VisitType.display_order.asc(), VisitType.id.asc())
        .all()
    )

    return jsonify([
        {
            "name": vt.name,
            "code": vt.code,
            "duration_minutes": vt.duration_minutes,
            "price": float(vt.price) if vt.price is not None else None,
            "color": vt.color
        }
        for vt in visit_types
    ])


# ───────────────────────────────────────
# HELPER: AKTYWNY URLOP
# ───────────────────────────────────────

def is_active_vacation_day(day):
    return (
        Vacation.query
        .filter(
            Vacation.doctor_id == 1,
            Vacation.active == 1,
            Vacation.date_from <= day,
            Vacation.date_to >= day
        )
        .first()
        is not None
    )


# ───────────────────────────────────────
# API: DOSTĘPNE DNI
# ───────────────────────────────────────

@patient_bp.route("/api/days")
def api_days():
    visit_code = request.args.get("visit_type")
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)

    if not visit_code or not year or not month:
        return jsonify([])

    vt = VisitType.query.filter_by(code=visit_code, active=True).first()
    if not vt:
        return jsonify([])

    visit_minutes = vt.duration_minutes
    required_slots = visit_minutes // SLOT_MINUTES

    # ───── zakres miesiąca
    month_start = datetime(year, month, 1)
    if month == 12:
        month_end = datetime(year + 1, 1, 1)
    else:
        month_end = datetime(year, month + 1, 1)

    slots = (
        Availability.query
        .filter(
            Availability.start >= month_start,
            Availability.start < month_end,
            Availability.active.is_(True)
        )
        .order_by(Availability.start)
        .all()
    )

    days = set()

    def has_conflict(start, end):
        return (
            Appointment.query
            .filter(
                Appointment.status.in_(["scheduled", "completed"]),
                Appointment.start < end,
                Appointment.end > start
            )
            .first()
            is not None
        )

    for i in range(len(slots)):
        window = slots[i:i + required_slots]
        if len(window) < required_slots:
            continue

        for j in range(1, len(window)):
            if window[j].start != window[j - 1].end:
                break
        else:
            start = window[0].start
            end = start + timedelta(minutes=visit_minutes)
            day_date = start.date()

            if not is_active_vacation_day(day_date) and not has_conflict(start, end):
                days.add(day_date.isoformat())

    return jsonify(sorted(days))


@patient_bp.route("/api/hours")
def api_hours():
    visit_code = request.args.get("visit_type")
    day_str = request.args.get("day")

    if not visit_code or not day_str:
        return jsonify([])

    day = datetime.strptime(day_str, "%Y-%m-%d").date()

    if is_active_vacation_day(day):
        return jsonify([])

    visit_type = VisitType.query.filter_by(code=visit_code, active=True).first()
    if not visit_type:
        return jsonify([])

    visit_minutes = visit_type.duration_minutes
    required_slots = visit_minutes // SLOT_MINUTES

    # ───── dostępne sloty dnia
    slots = (
        Availability.query
        .filter(
            Availability.doctor_id == 1,
            Availability.start >= datetime.combine(day, time.min),
            Availability.start < datetime.combine(day + timedelta(days=1), time.min),
            Availability.active.is_(True)
        )
        .order_by(Availability.start)
        .all()
    )

    # ───── istniejące wizyty
    appointments = (
        Appointment.query
        .filter(
            Appointment.status.in_(["scheduled", "completed"]),
            Appointment.start >= datetime.combine(day, time.min),
            Appointment.start < datetime.combine(day + timedelta(days=1), time.min)
        )
        .all()
    )

    is_empty_day = len(appointments) == 0

    # ✅ JEDYNE ŹRÓDŁO PRAWDY – dozwolone minuty startu
    def is_nice_start(start):
        if visit_minutes == 60:
            return start.minute == 0
        if visit_minutes == 30:
            return start.minute in (0, 30)
        if visit_minutes == 45:
            return start.minute in (0, 15)
        return True

    candidates = []
    all_starts = []

    for i in range(len(slots)):
        window = slots[i:i + required_slots]
        if len(window) < required_slots:
            continue

        if not _window_is_free_and_continuous(window):
            continue

        start = window[0].start
        end = start + timedelta(minutes=visit_minutes)

        # ⛔ twarda blokada złych minut (ZAWSZE)
        if not is_nice_start(start):
            continue

        score = 0

        if not is_empty_day:
            for appt in appointments:
                if appt.end == start:
                    score += 50   # doklejenie po
                if appt.start == end:
                    score += 40   # doklejenie przed

        if start.hour <= 12:
            score += 10
        if start.hour >= 16:
            score += 10

        candidates.append({
            "start": start,
            "score": score
        })

        all_starts.append(start)

    # ───── PUSTY DZIEŃ + 30 MIN → STRATEGICZNE GODZINY
    if is_empty_day and visit_minutes == 30 and all_starts:
        all_starts = sorted(set(all_starts))

        idx = [
            0,
            int(len(all_starts) * 0.25),
            len(all_starts) // 2,
            int(len(all_starts) * 0.75),
            len(all_starts) - 1
        ]

        picked = [all_starts[i] for i in idx if 0 <= i < len(all_starts)]
        picked = sorted(set(picked))

        return jsonify([dt.strftime("%H:%M") for dt in picked[:5]])

    # ───── NORMALNY TRYB (SCORING)
    candidates.sort(key=lambda x: (-x["score"], x["start"]))

    chosen = [c["start"] for c in candidates[:5]]

    # ✅ KOŃCOWE SORTOWANIE PREZENTACYJNE
    chosen.sort()

    return jsonify([dt.strftime("%H:%M") for dt in chosen])







# ───────────────────────────────────────
# REZERWACJA WIZYTY
# ───────────────────────────────────────

@patient_bp.route("/reserve", methods=["POST"])
def reserve():
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    visit_code = request.form["visit_type"]

    visit_type = VisitType.query.filter_by(code=visit_code, active=True).first()
    if not visit_type:
        flash("Nieprawidłowy typ wizyty", "patient-danger")
        return redirect(url_for("patient.index"))

    visit_minutes = visit_type.duration_minutes
    required_slots = visit_minutes // SLOT_MINUTES

    start = datetime.strptime(
        f"{request.form['day']} {request.form['hour']}",
        "%Y-%m-%d %H:%M"
    )

    if is_active_vacation_day(start.date()):
        flash("Termin niedostępny", "patient-danger")
        return redirect(url_for("patient.index"))

    slots = (
        Availability.query
        .filter(
            Availability.start >= start,
            Availability.start < start + timedelta(minutes=visit_minutes),
            Availability.active == True
        )
        .order_by(Availability.start)
        .all()
    )

    if len(slots) != required_slots:
        flash("Termin niedostępny", "patient-danger")
        return redirect(url_for("patient.index"))

    if not _window_is_free_and_continuous(slots):
        flash("Termin zajęty", "patient-danger")
        return redirect(url_for("patient.index"))

    doctor_id = slots[0].doctor_id

    if is_phone_blacklisted(doctor_id, phone):
        flash("Rezerwacja wizyty za pośrednictwem strony internetowej jest niedostępna. Prosimy o kontakt telefoniczny z gabinetem: +48 698 554 077.", "patient-danger")
        return redirect(url_for("patient.index"))

    appointment = Appointment(
        doctor_id=doctor_id,
        start=start,
        end=start + timedelta(minutes=visit_minutes),
        duration=visit_minutes,
        visit_type=visit_code,
        patient_first_name=request.form["first_name"],
        patient_last_name=request.form["last_name"],
        patient_phone=phone,
        patient_email=email if email else None,
        cancel_token=uuid.uuid4().hex,
        created_by="patient",
        client_ip=get_client_ip()   # 👈 KLUCZOWE
    )




    db.session.add(appointment)
    db.session.commit()

    try:
        gcal = GoogleCalendarService()
        gcal.sync_appointment(appointment)
    except Exception as e:
        current_app.logger.warning(
            f"[GOOGLE][PATIENT CREATE] sync failed: {e}"
        )

    current_app.logger.warning("SMS CONFIRMATION: START")

    try:
        SMSService().send_confirmation(appointment)
    except Exception as e:
        current_app.logger.warning(
            f"[SMS][CONFIRMATION] failed for appointment {appointment.id}: {e}"
        )

    # ===============================
    # 📧 EMAIL (NOWE)
    # ===============================
    try:
        EmailService().send_confirmation(appointment)
    except Exception as e:
        current_app.logger.warning(
            f"[EMAIL][CONFIRMATION] failed for appointment {appointment.id}: {e}"
        )


    flash("Wizyta została zarezerwowana", "patient-success")
    return redirect(url_for("patient.index"))


# ───────────────────────────────────────
# FUNKCJE POMOCNICZE
# ───────────────────────────────────────

def _window_is_free_and_continuous(slots):
    for i in range(1, len(slots)):
        if slots[i].start != slots[i - 1].end:
            return False

    start = slots[0].start
    end = slots[-1].end

    conflict = (
        Appointment.query
        .filter(
            Appointment.status.in_(["scheduled", "completed"]),
            Appointment.start < end,
            Appointment.end > start
        )
        .first()
    )

    return conflict is None


# ───────────────────────────────────────
# ANULOWANIE WIZYTY – LINK Z TOKENEM
# ───────────────────────────────────────

@patient_bp.route("/cancel/<token>")
def cancel_by_token(token):
    appointment = (
        Appointment.query
        .filter_by(cancel_token=token)
        .first()
    )

    if not appointment:
        return render_template(
            "patient/cancel_result.html",
            success=False,
            message="Nieprawidłowy lub wygasły link"
        )

    allowed, reason = can_cancel_appointment(appointment)
    if not allowed:
        return render_template(
            "patient/cancel_result.html",
            success=False,
            message=reason
        )

    appointment.status = "cancelled"
    appointment.cancelled_at = db.func.now()

    db.session.commit()

    try:
        GoogleCalendarService().delete_appointment(appointment)
    except Exception as e:
        current_app.logger.warning(
            f"[GOOGLE][PATIENT CANCEL] delete failed: {e}"
        )

    return render_template(
        "patient/cancel_result.html",
        success=True,
        message="Wizyta została anulowana"
    )


@patient_bp.route("/c/<token>")
def cancel_short(token):
    return redirect(
        url_for("patient.cancel_by_token", token=token)
    )

# ───────────────────────────────────────
# API: STATUS URLOPU (PUBLICZNE)
# ───────────────────────────────────────

from flask import jsonify, request
from datetime import datetime

@patient_bp.route("/api/vacation-status", methods=["GET"])
def vacation_status():
    date_str = request.args.get("date")

    if not date_str:
        return jsonify({"is_vacation": False})

    try:
        today = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"is_vacation": False})

    vacation = (
        Vacation.query
        .filter(
            Vacation.doctor_id == 1,
            Vacation.active.is_(True),          # tylko AKTYWNE
            Vacation.date_from <= today,
            Vacation.date_to >= today
        )
        .first()
    )

    if not vacation:
        return jsonify({"is_vacation": False})

    # 🔴 TYLKO JEDEN DZIEŃ = DZIŚ
    if vacation.date_from == today and vacation.date_to == today:
        message_pl = (
            "W dniu dzisiejszym gabinet jest nieczynny.<br>"
            "Kontakt możliwy przez formularz w zakładce Kontakt."
        )
        message_en = (
            "The clinic is closed today.<br>"
            "Please contact us via the contact form in the Contact section."
        )

    # 🟢 KAŻDY INNY PRZYPADEK = ZAKRES
    else:
        message_pl = (
            f"Gabinet jest nieczynny od {vacation.date_from.strftime('%d.%m.%Y')} "
            f"do {vacation.date_to.strftime('%d.%m.%Y')}.<br>"
            "Kontakt możliwy przez formularz w zakładce Kontakt."
        )
        message_en = (
            f"The clinic is closed from {vacation.date_from.strftime('%Y-%m-%d')} "
            f"to {vacation.date_to.strftime('%Y-%m-%d')}.<br>"
            "Please contact us via the contact form in the Contact section."
        )

    return jsonify({
        "is_vacation": True,
        "message_pl": message_pl,
        "message_en": message_en
    })
