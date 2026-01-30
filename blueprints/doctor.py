import os
import json
import secrets
from datetime import datetime, timedelta, date, time
from calendar import monthrange

import holidays

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    session,
    current_app,
)
from flask_login import login_required, current_user

from sqlalchemy import (
    extract,
    func,
    case,
    or_,
)

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from extensions import db
from models import (
    Appointment,
    Availability,
    VisitType,
    Vacation,
    BlacklistPatient,
    Setting,
    SMSMessage,
)

from utils.settings import get_setting
from utils.google_calendar import GoogleCalendarService
from utils.sms_service import SMSService


# ⚠️ TYLKO DO DEV / HTTP (nie produkcja!)
if os.environ.get("FLASK_ENV") == "development":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"




GOOGLE_COLORS = {
    "1": "#7986CB",
    "2": "#33B679",
    "3": "#8E24AA",
    "4": "#E67C73",
    "5": "#F6BF26",
    "6": "#F4511E",
    "7": "#039BE5",
    "8": "#616161",
    "9": "#3F51B5",
    "10": "#0B8043",
    "11": "#D50000",
}



#pl_holidays = holidays.country_holidays("PL")

def is_polish_holiday(d: date) -> bool:
    pl_holidays = holidays.PL(years={d.year})
    return d in pl_holidays


doctor_bp = Blueprint("doctor", __name__, url_prefix="/doctor")

# =================================================
# DASHBOARD
# =================================================
@doctor_bp.route("/")
@login_required
def dashboard():
    return redirect(url_for("doctor.appointments"))

PER_PAGE = 20

# =================================================
# SORTOWANIE TERMINARZA – WHITELIST
# =================================================
SORTABLE_COLUMNS = {
    "start": Appointment.start,
    "end": Appointment.end,
    "duration": Appointment.duration,
    "patient_first_name": Appointment.patient_first_name,
    "patient_last_name": Appointment.patient_last_name,
    "patient_phone": Appointment.patient_phone,
    "patient_email": Appointment.patient_email,
    "client_ip": Appointment.client_ip,
    "status": Appointment.status,
    "created_by": Appointment.created_by,
    "visit_type": Appointment.visit_type,
}


from sqlalchemy import or_, and_, case
from datetime import datetime

@doctor_bp.route("/appointments")
@login_required
def appointments():
    page = request.args.get("page", 1, type=int)

    # ─────────────────────────────
    # PARAMETRY FILTRÓW
    # ─────────────────────────────
    first_name = request.args.get("first_name", "").strip()
    last_name = request.args.get("last_name", "").strip()
    phone = request.args.get("phone", "").strip()
    email = request.args.get("email", "").strip()
    client_ip = request.args.get("client_ip", "").strip()
    visit_type = request.args.get("visit_type")
    status = request.args.get("status")
    created_by = request.args.get("created_by")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    show_past = request.args.get("show_past") == "1"

    sort = request.args.get("sort", "start")
    dir_ = request.args.get("dir", "asc")

    now = datetime.now()

    # ─────────────────────────────
    # 📌 BAZOWE ZAPYTANIE (ZAWSZE PIERWSZE)
    # ─────────────────────────────
    query = Appointment.query.filter(
        Appointment.doctor_id == current_user.id
    )

    # ─────────────────────────────
    # 🔍 FILTRY (JAK SMS)
    # ─────────────────────────────
    if first_name:
        query = query.filter(
            Appointment.patient_first_name.ilike(f"%{first_name}%")
        )

    if last_name:
        query = query.filter(
            Appointment.patient_last_name.ilike(f"%{last_name}%")
        )

    if phone:
        query = query.filter(
            Appointment.patient_phone.ilike(f"%{phone}%")
        )

    if email:
        query = query.filter(
            Appointment.patient_email.ilike(f"%{email}%")
        )
    if client_ip:
        query = query.filter(
            Appointment.client_ip.ilike(f"%{client_ip}%")
        )

    if visit_type:
        query = query.filter(Appointment.visit_type == visit_type)

    if status:
        query = query.filter(Appointment.status == status)

    if created_by in ("doctor", "patient"):
        query = query.filter(Appointment.created_by == created_by)

    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Appointment.start >= df)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Appointment.start < dt)
        except ValueError:
            pass

    # ─────────────────────────────
    # ⏱️ TYLKO PRZYSZŁE (DOMYŚLNIE)
    # ─────────────────────────────
    if not show_past:
        query = query.filter(Appointment.end >= now)

    if sort not in SORTABLE_COLUMNS:
        sort = "start"

    if dir_ not in ("asc", "desc"):
        dir_ = "asc"

    column = SORTABLE_COLUMNS[sort]

    if sort == "start" and dir_ == "asc":
        # najpierw przyszłe, potem przeszłe
        is_past = case(
    (Appointment.end < now, 1),
            else_=0
        )

        query = query.order_by(
            is_past.asc(),
            Appointment.start.asc()
        )
    else:
        query = query.order_by(
            column.desc() if dir_ == "desc" else column.asc()
        )

    # ─────────────────────────────
    # 📄 PAGINACJA
    # ─────────────────────────────
    pagination = query.paginate(
        page=page,
        per_page=PER_PAGE,
        error_out=False
    )

    return render_template(
        "doctor/appointments.html",
        appointments=pagination.items,
        pagination=pagination,
        show_past=show_past,
        sort=sort,
        dir=dir_,
        visit_types=VisitType.query
            .filter_by(active=True)
            .order_by(VisitType.display_order.asc(), VisitType.id.asc())
            .all(),
        active_page="appointments"
    )






@doctor_bp.route("/cancel/<int:appointment_id>", methods=["POST"])
@login_required
def cancel_appointment(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)

    if appt.doctor_id != current_user.id:
        flash("Brak dostępu", "error")
        return redirect(url_for("doctor.appointments"))

    if appt.status == "cancelled":
        flash("Wizyta już anulowana", "doctor-warning")
        return redirect(url_for("doctor.appointments"))

    # 1️⃣ NAJPIERW USUŃ Z GOOGLE
    try:
        GoogleCalendarService.delete_appointment(appt)
        appt.google_event_id = None
        appt.google_sync_status = "deleted"
        appt.google_last_sync_at = datetime.utcnow()
        db.session.commit()

    except Exception as e:
        current_app.logger.error(f"Google delete error: {e}")

    # 2️⃣ POTEM ZMIANA STATUSU
    appt.status = "cancelled"

    db.session.commit()

    flash("✔ Wizyta anulowana", "doctor-success")
    return redirect(url_for(
        "doctor.appointments",
        show_past=request.form.get("show_past"),
        q=request.form.get("q"),
        page=request.form.get("page")
    ))




@doctor_bp.route("/appointments/<int:appointment_id>/complete", methods=["POST"])
@login_required
def complete_appointment(appointment_id):
    appt = Appointment.query.get_or_404(appointment_id)

    if appt.doctor_id != current_user.id:
        flash("Brak dostępu", "error")
        return redirect(url_for("doctor.appointments"))

    if appt.status != "scheduled":
        flash("Nie można zmienić statusu tej wizyty", "doctor-warning")
        return redirect(url_for("doctor.appointments"))

    appt.status = "completed"
    db.session.commit()

    flash("✔ Wizyta oznaczona jako zrealizowana", "doctor-success")
    return redirect(url_for(
    "doctor.appointments",
    show_past=request.form.get("show_past"),
    q=request.form.get("q"),
    page=request.form.get("page")
))



# =================================================
# API – GRAFIK (FULLCALENDAR)
# =================================================
@doctor_bp.route(
    "/api/availability-calendar",
    endpoint="api_availability_calendar"
)
@login_required
def api_availability_calendar():

    events = []

    appointments = Appointment.query.filter(
        Appointment.doctor_id == current_user.id,
        Appointment.status.in_(["scheduled", "completed"])
    ).all()



    vacations = Vacation.query.filter_by(
        doctor_id=current_user.id,
        active=True
    ).all()

    slots = Availability.query.filter_by(
        doctor_id=current_user.id
    ).all()

    # ---------- HELPERY ----------
    def slot_has_appointment(slot):
        for a in appointments:
            if slot.start < a.end and slot.end > a.start:
                return True
        return False

    def is_vacation_day(d):
        return any(v.date_from <= d <= v.date_to for v in vacations)

    # ---------- SLOTY ----------
    for s in slots:
        if slot_has_appointment(s):
            continue

        vacation_flag = is_vacation_day(s.start.date())

        if vacation_flag:
            bg = "#e2e3e5"
        else:
            bg = "#d4edda" if s.active else "#f8d7da"

        events.append({
            "id": f"slot-{s.id}",
            "start": s.start.isoformat(),
            "end": s.end.isoformat(),
            "display": "block",
            "backgroundColor": bg,
            "borderColor": bg,
            "extendedProps": {
                "slot_id": s.id,
                "active": s.active,
                "is_vacation": vacation_flag
            }
        })

    # ---------- WIZYTY ----------
    for a in appointments:
        vt = VisitType.query.filter_by(code=a.visit_type).first()

        color_id = vt.color if vt and vt.color else "1"
        color_hex = GOOGLE_COLORS.get(color_id, "#3788d8")

        events.append({
        "id": f"appt-{a.id}",
        "title": f"{a.patient_first_name} {a.patient_last_name}",
        "start": a.start.isoformat(),
        "end": a.end.isoformat(),
        "display": "block",
        "backgroundColor": color_hex,
        "borderColor": color_hex,
        "extendedProps": {
            "appointment_id": a.id,
            "phone": a.patient_phone,
            "visit_type": a.visit_type,
            "duration": a.duration,
            "created_by": a.created_by   # 👤 / ✍️ źródło wizyty
        }
    })




    # ---------- URLOPY ----------
    for v in vacations:
        events.append({
            "id": f"vac-{v.id}",
            "start": datetime.combine(v.date_from, time.min).isoformat(),
            "end": datetime.combine(v.date_to + timedelta(days=1), time.min).isoformat(),
            "display": "background",
            "backgroundColor": "#ffeeba"
        })

    # ---------- ŚWIĘTA ----------
    years = {
        int(y[0]) for y in
        db.session.query(db.func.extract('year', Availability.start))
        .filter(Availability.doctor_id == current_user.id)
        .distinct()
        .all()
        if y[0]
    } or {date.today().year}

    for d, name in holidays.PL(years=years).items():
        events.append({
            "id": f"holiday-{d}",
            "start": datetime.combine(d, time.min).isoformat(),
            "end": datetime.combine(d + timedelta(days=1), time.min).isoformat(),
            "display": "background",
            "backgroundColor": "#fff3cd",
            "extendedProps": {"name": name}
        })

    current_app.logger.warning(f"EVENTS COUNT: {len(events)}")
    #for e in events:
    #       current_app.logger.warning(e)


    return jsonify(events)


def _window_is_free_and_continuous(
    doctor_id,
    start,
    end,
    exclude_appointment_id=None
):
    # 1️⃣ SLOTY
    required_slots = int((end - start).total_seconds() // 900)

    slots = (
        Availability.query
        .filter(
            Availability.doctor_id == doctor_id,
            Availability.start >= start,
            Availability.start < end,
            Availability.active.is_(True)
        )
        .order_by(Availability.start)
        .all()
    )

    if len(slots) != required_slots:
        return False

    for i in range(1, len(slots)):
        if slots[i].start != slots[i - 1].end:
            return False

    # 2️⃣ KONFLIKT WIZYT – TYLKO scheduled
    q = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.status == "scheduled",
        Appointment.start < end,
        Appointment.end > start
    )

    if exclude_appointment_id:
        q = q.filter(Appointment.id != exclude_appointment_id)

    if q.first():
        return False

    return True



# =================================================
# GENEROWANIE GRAFIKU
# =================================================
@doctor_bp.route("/generate")
@login_required
def generate_view():
    return render_template("doctor/generate.html", active_page="generate")

@doctor_bp.route("/generate_schedule", methods=["POST"])
@login_required
def generate_schedule():
    data = request.get_json()

    year = int(data["year"])
    month = int(data["month"])
    days_cfg = data["days"]  # np. {"mon": ["09", "10"], "tue": []}

    today = date.today()
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])

    start_date = max(today, first)

    # usuń stare sloty
    Availability.query.filter(
        Availability.doctor_id == current_user.id,
        Availability.start >= datetime.combine(start_date, time.min),
        Availability.start <= datetime.combine(last, time.max)
    ).delete(synchronize_session=False)

    weekday_map = {
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4
    }

    # aktywne urlopy
    vacations = Vacation.query.filter_by(
        doctor_id=current_user.id,
        active=True
    ).all()

    def is_vacation_day(d):
        return any(v.date_from <= d <= v.date_to for v in vacations)

    d = start_date
    while d <= last:

        # ❌ urlop LUB święto państwowe - > brak slotow
        if is_vacation_day(d) or is_polish_holiday(d):
            d += timedelta(days=1)
            continue


        # sprawdź czy dzień roboczy i zaznaczony
        day_key = next(
            (k for k, v in weekday_map.items() if v == d.weekday()),
            None
        )

        if day_key is None or day_key not in days_cfg:
            d += timedelta(days=1)
            continue

        # godziny zaznaczone w UI (np. ["09","10"])
        active_hours = {h.split(":")[0].zfill(2) for h in days_cfg.get(day_key, [])}

        current = datetime.combine(d, time(8, 0))
        end_time = datetime.combine(d, time(19, 0))

        while current < end_time:
            if current >= datetime.now():
                hour_key = current.strftime("%H")

                db.session.add(
                    Availability(
                        doctor_id=current_user.id,
                        start=current,
                        end=current + timedelta(minutes=15),
                        active=hour_key in active_hours
                    )
                )

            current += timedelta(minutes=15)

        d += timedelta(days=1)

    db.session.commit()
    return jsonify({"status": "ok"})




# =================================================
# TOGGLE SLOTU
# =================================================
@doctor_bp.route("/availability/toggle", methods=["POST"])
@login_required
def toggle_availability():
    data = request.get_json() or {}
    slot_id = data.get("slot_id")

    slot = Availability.query.filter_by(
        id=slot_id,
        doctor_id=current_user.id
    ).first_or_404()

    if "active" in data:
        slot.active = bool(data["active"])
    else:
        slot.active = not slot.active

    db.session.commit()
    return jsonify({"status": "ok", "active": slot.active})

# =================================================
# API – WIZYTA (GET / PUT)
# =================================================
@doctor_bp.route("/appointments/api/<int:appointment_id>", methods=["GET", "PUT"])
@login_required
def appointment_api(appointment_id):
    appt = Appointment.query.filter_by(
        id=appointment_id,
        doctor_id=current_user.id
    ).first_or_404()

    # ---------- GET ----------
    if request.method == "GET":
        return jsonify({
            "id": appt.id,
            "first_name": appt.patient_first_name,
            "last_name": appt.patient_last_name,
            "phone": appt.patient_phone,
            "email": appt.patient_email or "",
            "visit_type": appt.visit_type,
            "start": appt.start.strftime("%Y-%m-%d %H:%M"),
            "end": appt.end.strftime("%Y-%m-%d %H:%M"),
            "duration": appt.duration,
            "created_by": appt.created_by

        })

    # ---------- PUT ----------
    data = request.get_json() or {}

    for field in ("first_name", "last_name", "phone", "visit_type"):
        if not data.get(field):
            return jsonify({"error": f"Brak pola: {field}"}), 400

    visit_type = VisitType.query.filter_by(
        code=data["visit_type"],
        active=True
    ).first_or_404()

    appt.patient_first_name = data["first_name"].strip()
    appt.patient_last_name = data["last_name"].strip()
    appt.patient_phone = data["phone"].strip()
    appt.patient_email = data.get("email") or None
    appt.visit_type = visit_type.code
    appt.duration = visit_type.duration_minutes
    appt.end = appt.start + timedelta(minutes=visit_type.duration_minutes)

    #appt.google_sync_status = "pending"
    db.session.commit()

    # 🔗 UPDATE GOOGLE CALENDAR
    try:
        GoogleCalendarService.sync_appointment(appt, force_update=True)
    except Exception as e:
        current_app.logger.error(f"Google sync error (edit): {e}")



    return jsonify({"status": "ok"})

# =================================================
# PRZENOSZENIE WIZYTY
# =================================================
@doctor_bp.route("/appointments/move", methods=["POST"])
@login_required
def move_appointment():
    data = request.get_json() or {}

    appointment_id = data.get("id")
    start_raw = data.get("start")

    # 🔒 WALIDACJA DANYCH
    if not appointment_id or not start_raw:
        return jsonify({"error": "Brak danych"}), 400

    appt = Appointment.query.filter_by(
        id=appointment_id,
        doctor_id=current_user.id
    ).first_or_404()

    # 🔒 BLOKADA: nie przenosimy zakończonych / anulowanych
    if appt.status != "scheduled":
        return jsonify({"error": "Nie można przenosić tej wizyty"}), 400

    # 🔥 lokalny czas (BEZ UTC)
    try:
        new_start = datetime.strptime(start_raw, "%Y-%m-%d %H:%M")
    except ValueError:
        return jsonify({"error": "Nieprawidłowy format daty"}), 400

    new_end = new_start + timedelta(minutes=appt.duration)
    day = new_start.date()

    # 🔒 URLOP
    vacation = Vacation.query.filter(
        Vacation.doctor_id == current_user.id,
        Vacation.active.is_(True),
        Vacation.date_from <= day,
        Vacation.date_to >= day
    ).first()

    if vacation:
        return jsonify({"error": "Termin wypada w urlopie"}), 400

    # 🔒 ŚWIĘTO
    if is_polish_holiday(day):
        return jsonify({"error": "Termin wypada w święto"}), 400

    # 🔒 SLOTY (ciągłość + aktywność)
    if not _window_is_free_and_continuous(
        current_user.id,
        new_start,
        new_end,
        exclude_appointment_id=appt.id
    ):
        return jsonify({"error": "Termin niedostępny"}), 400

    # 🔒 KONFLIKT – TYLKO scheduled
    conflict = Appointment.query.filter(
        Appointment.doctor_id == current_user.id,
        Appointment.id != appt.id,
        Appointment.status == "scheduled",
        Appointment.start < new_end,
        Appointment.end > new_start
    ).first()

    if conflict:
        return jsonify({"error": "Termin zajęty"}), 400

    # 1️⃣ ZAPIS LOKALNY
    appt.start = new_start
    appt.end = new_end
    db.session.commit()

    # 2️⃣ UPDATE W GOOGLE
    try:
        GoogleCalendarService.sync_appointment(appt, force_update=True)
    except Exception as e:
        current_app.logger.error(f"Google sync error (move): {e}")

    return jsonify({"status": "ok"})

# =================================================
# Wymuszenie dodania do kalendarza google
# =================================================
@doctor_bp.route("/appointments/<int:appointment_id>/google-force", methods=["POST"])
@login_required
def google_force_add(appointment_id):
    appt = Appointment.query.filter_by(
        id=appointment_id,
        doctor_id=current_user.id
    ).first_or_404()

    GoogleCalendarService.force_create_event(appt)

    return jsonify({"status": "ok"})




# =================================================
# DODANIE WIZYTY (LEKARZ / KALENDARZ)
# =================================================
@doctor_bp.route("/appointments/create", methods=["POST"])
@login_required
def create_appointment_doctor():
    data = request.get_json() or {}

    # 1️⃣ typ wizyty
    visit_type = VisitType.query.filter_by(
        code=data.get("visit_type"),
        active=True
    ).first()

    if not visit_type:
        return jsonify({"error": "Nieprawidłowy typ wizyty"}), 400

    # 2️⃣ start / end
    try:
        start = datetime.strptime(
            f'{data["date"]} {data["time"]}',
            "%Y-%m-%d %H:%M"
        )
    except Exception:
        return jsonify({"error": "Nieprawidłowa data lub godzina"}), 400

    end = start + timedelta(minutes=visit_type.duration_minutes)

    # 3️⃣ URLOP
    day = start.date()
    vacation = Vacation.query.filter(
        Vacation.doctor_id == current_user.id,
        Vacation.active.is_(True),
        Vacation.date_from <= day,
        Vacation.date_to >= day
    ).first()

    if vacation:
        return jsonify({"error": "Termin wypada w urlopie"}), 400

    # 4️⃣ SLOTY
    required_slots = visit_type.duration_minutes // 15

    slots = (
        Availability.query
        .filter(
            Availability.doctor_id == current_user.id,
            Availability.start >= start,
            Availability.start < end,
            Availability.active.is_(True)
        )
        .order_by(Availability.start)
        .all()
    )

    if len(slots) != required_slots:
        return jsonify({"error": "Termin niedostępny"}), 400

    for i in range(1, len(slots)):
        if slots[i].start != slots[i - 1].end:
            return jsonify({"error": "Brak ciągłości slotów"}), 400

    # 5️⃣ KONFLIKT
    conflict = Appointment.query.filter(
        Appointment.doctor_id == current_user.id,
        Appointment.status == "scheduled",
        Appointment.start < end,
        Appointment.end > start
    ).first()


    if conflict:
        return jsonify({"error": "Termin zajęty"}), 400

    # 6️⃣ ZAPIS
    appt = Appointment(
        doctor_id=current_user.id,
        patient_first_name=data.get("first_name", "").strip(),
        patient_last_name=data.get("last_name", "").strip(),
        patient_phone=data.get("phone", "").strip(),
        patient_email=data.get("email") or None,
        visit_type=visit_type.code,
        duration=visit_type.duration_minutes,
        start=start,
        end=end,
        status="scheduled",
        cancel_token=secrets.token_urlsafe(16),
        created_by="doctor"   # ✍️ KLUCZOWE
    )



    db.session.add(appt)
    db.session.commit()

    # 🔗 AUTO-SYNC DO GOOGLE
    try:
        GoogleCalendarService.sync_appointment(appt)
    except Exception as e:
        current_app.logger.error(f"Google sync error: {e}")

    return jsonify({"status": "ok"})



# =================================================
# LISTA TYPÓW WIZYT (DO KALENDARZA / EDYCJI)
# =================================================
@doctor_bp.route("/visit-types/api")
@login_required
def visit_types_api():
    types = (
        VisitType.query
        .filter_by(active=True)
        .order_by(
            VisitType.display_order_doctor.asc(),
            VisitType.id.asc()
        )
        .all()
    )

    return jsonify([
        {
            "code": t.code,
            "name": t.name,
            "display_order_doctor": t.display_order_doctor,
            "only_online_payment": bool(t.only_online_payment)
        }
        for t in types
    ])



# =================================================
# TABELA TYPÓW WIZYT aktualnie ten kod nie jest juz używany
# =================================================
@doctor_bp.route("/visit-types/table-api")
@login_required
def visit_types_table_api():
    types = (
        VisitType.query
        .filter_by(active=True)
        .order_by(VisitType.display_order.asc(), VisitType.id.asc())
        .all()
    )

    return jsonify([
        {
            "id": t.id,
            "name": t.name,
            "code": t.code,
            "description": t.description,
            "duration_minutes": t.duration_minutes,
            "price": float(t.price) if t.price is not None else None,
            "color": t.color,
            "active": t.active,
            "display_order": t.display_order,  # ✅ KLUCZOWE
            "display_order_doctor": t.display_order_doctor,
            "only_online_payment": bool(t.only_online_payment)
        }
        for t in types
    ])




# =================================================
# URLOPY – WIDOK
# =================================================
@doctor_bp.route("/vacations")
@login_required
def vacations_view():
    return render_template("doctor/vacations.html", active_page="vacations")


@doctor_bp.route("/vacations/api", methods=["GET"])
@login_required
def list_vacations():
    vacations = (
        Vacation.query
        .filter_by(doctor_id=current_user.id)
        .order_by(Vacation.date_from.desc())
        .all()
    )

    return jsonify([
        {
            "id": v.id,
            "date_from": v.date_from.strftime("%Y-%m-%d"),
            "date_to": v.date_to.strftime("%Y-%m-%d"),
            "description": v.description,
            "active": v.active
        }
        for v in vacations
    ])

@doctor_bp.route("/vacations/create", methods=["POST"])
@login_required
def create_vacation():
    data = request.get_json()

    date_from = datetime.strptime(data["date_from"], "%Y-%m-%d").date()
    date_to = datetime.strptime(data["date_to"], "%Y-%m-%d").date()

    if date_from > date_to:
        return jsonify({"error": "Data od nie może być po dacie do"}), 400

    v = Vacation(
        doctor_id=current_user.id,
        date_from=date_from,
        date_to=date_to,
        description=data.get("description"),
        active=data.get("active", True)
    )

    db.session.add(v)
    db.session.commit()

    # 🔒 DEZAKTYWUJ SLOTY W ZAKRESIE URLOPU
    Availability.query.filter(
        Availability.doctor_id == current_user.id,
        Availability.start >= datetime.combine(v.date_from, time.min),
        Availability.start <= datetime.combine(v.date_to, time.max)
    ).update(
        {"active": False},
        synchronize_session=False
    )

    db.session.commit()

    return jsonify({"status": "ok", "id": v.id})

@doctor_bp.route("/vacations/<int:vacation_id>", methods=["PUT"])
@login_required
def update_vacation(vacation_id):
    v = Vacation.query.filter_by(
        id=vacation_id,
        doctor_id=current_user.id
    ).first_or_404()

    data = request.get_json()

    v.date_from = datetime.strptime(data["date_from"], "%Y-%m-%d").date()
    v.date_to = datetime.strptime(data["date_to"], "%Y-%m-%d").date()
    v.description = data.get("description")
    v.active = data.get("active", v.active)

    db.session.commit()
    Availability.query.filter(
        Availability.doctor_id == current_user.id,
        Availability.start >= datetime.combine(v.date_from, time.min),
        Availability.start <= datetime.combine(v.date_to, time.max)
    ).update(
        {"active": False},
        synchronize_session=False
    )

    db.session.commit()

    return jsonify({"status": "ok"})

@doctor_bp.route("/vacations/<int:vacation_id>/toggle", methods=["POST"])
@login_required
def toggle_vacation(vacation_id):
    v = Vacation.query.filter_by(
        id=vacation_id,
        doctor_id=current_user.id
    ).first_or_404()

    v.active = not v.active
    db.session.commit()
    return jsonify({"status": "ok", "active": v.active})

@doctor_bp.route("/vacations/<int:vacation_id>", methods=["DELETE"])
@login_required
def delete_vacation(vacation_id):
    v = Vacation.query.filter_by(
        id=vacation_id,
        doctor_id=current_user.id
    ).first_or_404()

    db.session.delete(v)
    db.session.commit()
    return jsonify({"status": "ok"})

# =================================================
# CZARNA LISTA – LISTA
# =================================================
from sqlalchemy import or_

@doctor_bp.route("/blacklist")
@login_required
def blacklist():
    q = request.args.get("q", "").strip()

    query = BlacklistPatient.query.filter(
        BlacklistPatient.doctor_id == current_user.id
    )

    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            BlacklistPatient.first_name.ilike(like),
            BlacklistPatient.last_name.ilike(like),
            BlacklistPatient.phone.ilike(like),
            BlacklistPatient.email.ilike(like),
        ))

    items = (
        query
        .order_by(BlacklistPatient.blocked_at.desc())
        .all()
    )

    return render_template(
        "doctor/blacklist.html",
        active_page="blacklist",
        items=items
    )



# =================================================
# CZARNA LISTA – DODANIE Z LISTY (MODAL)
# =================================================
@doctor_bp.route("/blacklist/add", methods=["POST"])
@login_required
def blacklist_add():
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip() or None
    description = request.form.get("description", "").strip()

    if not first_name or not last_name or not phone:
        flash("Imię, nazwisko i telefon są wymagane", "doctor-danger")
        return redirect(url_for("doctor.blacklist"))

    existing = BlacklistPatient.query.filter_by(
        doctor_id=current_user.id,
        phone=phone
    ).first()

    if existing:
        existing.first_name = first_name
        existing.last_name = last_name
        existing.email = email
        existing.description = description
        existing.active = True
        existing.blocked_at = datetime.utcnow()
    else:
        db.session.add(
            BlacklistPatient(
                doctor_id=current_user.id,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                email=email,
                description=description,
                active=True
            )
        )

    db.session.commit()
    flash("Pacjent dodany do czarnej listy", "doctor-success")
    return redirect(url_for("doctor.blacklist"))


# =================================================
# CZARNA LISTA – TOGGLE
# =================================================
@doctor_bp.route("/blacklist/<int:item_id>/toggle", methods=["POST"])
@login_required
def blacklist_toggle(item_id):
    item = BlacklistPatient.query.filter_by(
        id=item_id,
        doctor_id=current_user.id
    ).first_or_404()

    item.active = not item.active
    db.session.commit()

    flash(
        "Pacjent ponownie zablokowany" if item.active else "Pacjent odblokowany",
        "doctor-warning" if item.active else "doctor-success"
    )

    return redirect(url_for("doctor.blacklist"))


# =================================================
# CZARNA LISTA – DELETE
# =================================================
@doctor_bp.route("/blacklist/<int:item_id>/delete", methods=["POST"])
@login_required
def blacklist_delete(item_id):
    item = BlacklistPatient.query.filter_by(
        id=item_id,
        doctor_id=current_user.id
    ).first_or_404()

    db.session.delete(item)
    db.session.commit()

    flash("Wpis usunięty z czarnej listy", "doctor-success")
    return redirect(url_for("doctor.blacklist"))


# =================================================
# CZARNA LISTA – Z WIZYTY (AJAX, ZOSTAJEMY NA GRAFIKU)
# =================================================
@doctor_bp.route("/appointments/<int:appointment_id>/blacklist", methods=["POST"])
@login_required
def blacklist_from_appointment_ajax(appointment_id):

    appt = Appointment.query.filter_by(
        id=appointment_id,
        doctor_id=current_user.id
    ).first_or_404()

    data = request.get_json(silent=True) or {}
    description = (data.get("description") or "").strip()
    cancel_appointment = bool(data.get("cancel_appointment", False))

    if not description:
        return jsonify({"error": "Opis jest wymagany"}), 400

    # =========================
    # 1️⃣ CZARNA LISTA
    # =========================
    existing = BlacklistPatient.query.filter_by(
        doctor_id=current_user.id,
        phone=appt.patient_phone
    ).first()

    if existing:
        existing.active = True
        existing.description = description
        existing.blocked_at = datetime.utcnow()
    else:
        db.session.add(
            BlacklistPatient(
                doctor_id=current_user.id,
                first_name=appt.patient_first_name,
                last_name=appt.patient_last_name,
                phone=appt.patient_phone,
                email=appt.patient_email,
                description=description,
                active=True,
                blocked_at=datetime.utcnow()
            )
        )

    # =========================
    # 2️⃣ OPCJONALNE ANULOWANIE WIZYTY
    # =========================
    if cancel_appointment and appt.status != "cancelled":
        appt.status = "cancelled"

    db.session.commit()
    try:
        GoogleCalendarService.delete_appointment(appt)
        appt.google_event_id = None
        appt.google_sync_status = "deleted"
        appt.google_last_sync_at = datetime.utcnow()
        db.session.commit()

    except Exception as e:
        current_app.logger.error(f"Google delete error (blacklist): {e}")

    # ❗ ZAWSZE JSON + 200 (AJAX)
    return jsonify({"status": "ok"})


# =================================================
# CZARNA LISTA – EDYCJA
# =================================================
@doctor_bp.route("/blacklist/<int:item_id>/edit", methods=["POST"])
@login_required
def blacklist_edit(item_id):
    item = BlacklistPatient.query.filter_by(
        id=item_id,
        doctor_id=current_user.id
    ).first_or_404()

    item.first_name = request.form.get("first_name", "").strip()
    item.last_name = request.form.get("last_name", "").strip()
    item.phone = request.form.get("phone", "").strip()
    item.email = request.form.get("email", "").strip() or None
    item.description = request.form.get("description", "").strip()

    if not item.first_name or not item.last_name or not item.phone:
        flash("Imię, nazwisko i telefon są wymagane", "doctor-danger")
        return redirect(url_for("doctor.blacklist"))

    db.session.commit()
    flash("✔ Dane pacjenta zaktualizowane", "doctor-success")
    return redirect(url_for("doctor.blacklist"))


# =================================================
# HELPER – PACJENT
# =================================================
def is_phone_blacklisted(doctor_id, phone):
    return db.session.query(BlacklistPatient.id).filter(
        BlacklistPatient.doctor_id == doctor_id,
        BlacklistPatient.phone == phone,
        BlacklistPatient.active.is_(True)
    ).first() is not None

@doctor_bp.route("/statistics")
@login_required
def statistics():
    year = request.args.get("year", type=int, default=datetime.now().year)  
    tab = request.args.get("tab", "visits")
    current_year = datetime.now().year

    # ───────────────────────────────────────
    # WIZYTY – inicjalizacja 12 miesięcy
    # ───────────────────────────────────────
    stats = {m: {} for m in range(1, 13)}

    visit_types = VisitType.query.filter_by(active=True).order_by(VisitType.display_order.asc(), VisitType.id.asc()).all()


    visit_rows = (
        db.session.query(
            extract("month", Appointment.start).label("month"),
            Appointment.visit_type,
            func.count(Appointment.id)
        )
        .filter(
            extract("year", Appointment.start) == year,
            Appointment.status == "completed"
        )
        .group_by("month", Appointment.visit_type)
        .all()
    )

    for month, visit_code, count in visit_rows:
        stats[int(month)][visit_code] = count

    # ───────────────────────────────────────
    # SMS – inicjalizacja 12 miesięcy
    # ───────────────────────────────────────
    sms_stats = {
        m: {"sent": 0, "failed": 0}
        for m in range(1, 13)
    }

    sms_rows = (
        db.session.query(
            extract("month", SMSMessage.created_at).label("month"),
            SMSMessage.status,
            func.count(SMSMessage.id)
        )
        .filter(extract("year", SMSMessage.created_at) == year)
        .group_by("month", SMSMessage.status)
        .all()
    )

    for month, status, count in sms_rows:
        if status in ("sent", "failed"):
            sms_stats[int(month)][status] = count

    return render_template(
        "doctor/statistics.html",
        year=year,
        current_year=current_year,
        tab=tab,
        visit_types=visit_types,
        stats=stats,
        sms_stats=sms_stats,
        active_page="statistics"
    )
# =================================================
# Konfiguracja
# =================================================
@doctor_bp.route("/settings")
@login_required
def settings_view():
    VISIBLE_SETTINGS = {
        "calendar_visible_days",
        "sms_enabled",
        "sms_reminders_enabled",
        "email_enabled",
        "email_reminders_enabled",
    }



    settings = Setting.query.filter(
        Setting.key.in_(VISIBLE_SETTINGS)
    ).all()


    for s in settings:
        if s.key == "calendar_visible_days":
            try:
                s.value_list = json.loads(s.value)
            except Exception:
                s.value_list = []

    
    return render_template(
    "doctor/settings.html",
    settings=settings,
    doctor=current_user,
    google_connected=get_setting("google_connected") == "1",
    sms_enabled=get_setting("sms_enabled") == "1",
    active_page="settings"
    )



@doctor_bp.route("/settings/<key>", methods=["POST"])
@login_required
def update_setting(key):
    setting = Setting.query.filter_by(key=key).first_or_404()

    # ===============================
    # DNI WIDOCZNE W KALENDARZU
    # ===============================
    if key == "calendar_visible_days":
        days = request.form.getlist("days")
        allowed = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

        if not days or not set(days).issubset(allowed):
            flash("Nieprawidłowe dni tygodnia", "doctor-danger")
            return redirect(url_for("doctor.settings_view"))

        setting.value = ",".join(days)

    # ===============================
    # WŁĄCZNIKI SMS / EMAIL
    # ===============================
    elif key in (
        "sms_enabled",
        "sms_reminders_enabled",
        "email_enabled",
        "email_reminders_enabled",
    ):
        values = request.form.getlist("value")
        setting.value = "1" if "1" in values else "0"

    db.session.commit()
    flash("✔ Zapisano konfigurację", "doctor-success")
    return redirect(url_for("doctor.settings_view"))



@doctor_bp.route("/calendar")
@login_required
def calendar():
    visible_days_raw = get_setting(
        "calendar_visible_days",
        "mon,tue,wed,thu,fri"
    )

    visible_days = visible_days_raw.split(",")

    # mapowanie → FullCalendar
    day_map = {
        "sun": 0,
        "mon": 1,
        "tue": 2,
        "wed": 3,
        "thu": 4,
        "fri": 5,
        "sat": 6
    }

    visible_numbers = {day_map[d] for d in visible_days if d in day_map}
    hidden_days = [d for d in range(7) if d not in visible_numbers]

    return render_template(
        "doctor/availability_calendar.html",
        active_page="calendar",
        hidden_days=hidden_days
    )

@doctor_bp.route("/google/connect")
@login_required
def google_connect():
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": current_app.config["GOOGLE_CLIENT_ID"],
                "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=["https://www.googleapis.com/auth/calendar"],
        redirect_uri=url_for(
            "doctor.google_callback",
            _external=True,
            _scheme="https"
        )
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    return redirect(authorization_url)



@doctor_bp.route("/google/callback")
def google_callback():
    # 🔒 STATE TYLKO Z URL (NIE Z SESJI)
    state = request.args.get("state")
    if not state:
        flash("Nieprawidłowa odpowiedź z Google (brak state)", "error")
        return redirect(url_for("doctor.settings_view"))

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": current_app.config["GOOGLE_CLIENT_ID"],
                "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=["https://www.googleapis.com/auth/calendar"],
        redirect_uri=current_app.config["GOOGLE_REDIRECT_URI"],
        state=state
    )

    # 🔑 WYMIANA CODE → TOKEN
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials

    # 🔹 POBIERZ PRIMARY CALENDAR
    service = build("calendar", "v3", credentials=creds)
    calendar = service.calendarList().get(calendarId="primary").execute()

    # 💾 ZAPIS TOKENÓW
    set_setting("google_access_token", creds.token)
    set_setting("google_refresh_token", creds.refresh_token)
    set_setting("google_calendar_id", calendar["id"])
    set_setting("google_connected", "1")

    db.session.commit()

    flash("Połączono z Google Calendar", "success")
    return redirect(url_for("doctor.settings_view"))


def set_setting(key, value):
    s = Setting.query.filter_by(key=key).first()
    if s:
        s.value = value
    else:
        s = Setting(key=key, description=key, value=value)
        db.session.add(s)


def get_google_service():
    creds = Credentials(
        token=get_setting("google_access_token"),
        refresh_token=get_setting("google_refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=current_app.config["GOOGLE_CLIENT_ID"],
        client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds)

@doctor_bp.route("/google/rebuild", methods=["POST"])
@login_required
def google_rebuild_calendar():
    """
    🔄 ODBUDOWA KALENDARZA GOOGLE
    - usuwa wszystkie eventy aplikacji
    - tworzy je od nowa z DB
    """

    # 1️⃣ pobierz wizyty które MAJĄ być w Google
    appointments = (
        Appointment.query
        .filter(
            Appointment.status.in_(["scheduled", "completed"]),
            (
                Appointment.google_event_id.is_(None)
                | (Appointment.google_sync_status.in_(["error", "deleted"]))
            )
        )
        .all()
    )


    deleted = 0
    created = 0

    # 2️⃣ USUŃ eventy z Google (jeśli istnieją)
    for appt in appointments:
        google_event_id = getattr(appt, "google_event_id", None)
        if google_event_id:
            try:
                GoogleCalendarService.delete_appointment(appt)
                appt.google_event_id = None
                appt.google_sync_status = "deleted"
                appt.google_last_sync_at = datetime.utcnow()
                db.session.commit()

                deleted += 1
            except Exception as e:
                current_app.logger.warning(
                    f"[GOOGLE REBUILD] delete failed appt {appt.id}: {e}"
                )


    # 3️⃣ UTWÓRZ WSZYSTKO OD NOWA
    for appt in appointments:
        try:
            GoogleCalendarService.sync_appointment(appt, force_update=True)
            created += 1
        except Exception as e:
            current_app.logger.error(
                f"[GOOGLE REBUILD] create failed appt {appt.id}: {e}"
            )

    flash(
        f"🔄 Kalendarz Google odbudowany "
        f"(usunięto: {deleted}, utworzono: {created})",
        "success"
    )

    return {
    "status": "ok",
    "deleted": deleted,
    "created": created
}



@doctor_bp.route("/google/sync-batch", methods=["POST"])
@login_required
def google_sync_batch():
    MAX_BATCH = 20

    appts = (
        Appointment.query
        .filter(
            Appointment.doctor_id == current_user.id,
            Appointment.status == "scheduled",
            Appointment.google_sync_status != "synced"
        )
        .order_by(Appointment.start)
        .limit(MAX_BATCH)
        .all()
    )


    synced = 0
    skipped = 0

    for appt in appts:
        try:
            GoogleCalendarService.sync_appointment(
                appt,
                force_update=True
            )
            synced += 1
        except Exception as e:
            current_app.logger.warning(f"Batch sync skip {appt.id}: {e}")
            skipped += 1

    return jsonify({
        "synced": synced,
        "skipped": skipped,
        "limit": MAX_BATCH
    })

# ───────────────────────────────────────
# SMS – HISTORIA
# ───────────────────────────────────────

@doctor_bp.route("/sms")
@login_required
def sms_list():
    query = SMSMessage.query.join(Appointment)

    phone = request.args.get("phone")
    if phone:
        query = query.filter(SMSMessage.phone.ilike(f"%{phone}%"))

    sms_type = request.args.get("type")
    if sms_type:
        query = query.filter(SMSMessage.type == sms_type)

    status = request.args.get("status")
    if status:
        query = query.filter(SMSMessage.status == status)

    appointment_id = request.args.get("appointment_id")
    if appointment_id:
        query = query.filter(SMSMessage.appointment_id == appointment_id)

    date_from = request.args.get("date_from")
    if date_from:
        query = query.filter(SMSMessage.created_at >= date_from)

    date_to = request.args.get("date_to")
    if date_to:
        query = query.filter(SMSMessage.created_at <= date_to)

    page = request.args.get("page", 1, type=int)
    per_page = 20

    pagination = (
        query
        .order_by(SMSMessage.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    # 👇 KLUCZOWE
    args = request.args.to_dict(flat=True)
    args.pop("page", None)

    return render_template(
        "doctor/sms.html",
        sms_messages=pagination.items,
        pagination=pagination,
        pagination_args=args,
        active_page="sms"
    )


# ───────────────────────────────────────
# SMS – RETRY FAILED
# ───────────────────────────────────────

@doctor_bp.route("/sms/<int:sms_id>/retry", methods=["POST"])
@login_required
def sms_retry(sms_id):
    sms = SMSMessage.query.get_or_404(sms_id)
    appointment = Appointment.query.get_or_404(sms.appointment_id)

    service = SMSService()

    if sms.type == "confirmation":
        service.send_confirmation(appointment)
    elif sms.type == "reminder":
        service.send_reminder(appointment)

    flash("Ponowiono wysyłkę SMS", "success")
    return redirect(url_for("doctor.sms_list"))



