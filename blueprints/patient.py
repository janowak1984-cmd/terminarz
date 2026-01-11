from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from datetime import datetime, timedelta, time
import uuid
from utils.cancel_policy import can_cancel_appointment

from utils.sms_service import SMSService
from extensions import db
from models import Availability, Appointment, VisitType, Vacation
from utils.blacklist import is_phone_blacklisted
from utils.google_calendar import GoogleCalendarService
from flask import current_app


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
    if not visit_code:
        return jsonify([])

    vt = VisitType.query.filter_by(code=visit_code, active=True).first()
    if not vt:
        return jsonify([])

    visit_minutes = vt.duration_minutes
    required_slots = visit_minutes // SLOT_MINUTES
    now = datetime.now()

    slots = (
        Availability.query
        .filter(
            Availability.start >= now,
            Availability.active == True
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


# ───────────────────────────────────────
# API: DOSTĘPNE GODZINY
# ───────────────────────────────────────

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

    slots = (
        Availability.query
        .filter(
            Availability.doctor_id == 1,
            Availability.start >= datetime.combine(day, time.min),
            Availability.start < datetime.combine(day + timedelta(days=1), time.min),
            Availability.active == True
        )
        .order_by(Availability.start)
        .all()
    )

    hours = set()

    for i in range(len(slots)):
        window = slots[i:i + required_slots]
        if len(window) < required_slots:
            continue

        if _window_is_free_and_continuous(window):
            hours.add(window[0].start.strftime("%H:%M"))

    return jsonify(sorted(hours))


# ───────────────────────────────────────
# REZERWACJA WIZYTY
# ───────────────────────────────────────

@patient_bp.route("/reserve", methods=["POST"])
def reserve():
    phone = request.form.get("phone", "").strip()
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
        flash("Nie możesz umówić wizyty online...", "patient-danger")
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
        cancel_token=uuid.uuid4().hex
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
