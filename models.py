from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime



# ==================================================
# LEKARZ / AUTH
# ==================================================
class Doctor(UserMixin, db.Model):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


# ==================================================
# DOSTĘPNOŚĆ (SLOTY)
# ==================================================
class Availability(db.Model):
    __tablename__ = "availabilities"

    id = db.Column(db.Integer, primary_key=True)

    doctor_id = db.Column(
        db.Integer,
        db.ForeignKey("doctors.id"),
        nullable=False
    )

    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)

    active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )


# ==================================================
# WIZYTY
# ==================================================
class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)

    doctor_id = db.Column(db.Integer, nullable=False)

    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.Integer, nullable=False)

    visit_type = db.Column(db.String(50), nullable=False)

    patient_first_name = db.Column(db.String(100))
    patient_last_name = db.Column(db.String(100))
    patient_phone = db.Column(db.String(20))
    patient_email = db.Column(db.String(120))

    status = db.Column(
        db.Enum("scheduled", "completed", "cancelled", name="appointment_status"),
        default="scheduled",
        nullable=False
    )

    created_by = db.Column(
        db.Enum("patient", "doctor", name="appointment_created_by"),
        nullable=False
    )

    cancel_token = db.Column(db.String(64), unique=True, index=True)
    cancelled_at = db.Column(db.DateTime)

    # ===== GOOGLE CALENDAR SYNC =====
    google_event_id = db.Column(db.String(255), nullable=True)
    google_sync_status = db.Column(
        db.Enum("never", "synced", "deleted", "error", name="google_sync_status"),
        default="never",
        nullable=False
    )
    google_last_sync_at = db.Column(db.DateTime, nullable=True)

    # ===== SMS =====
    sms_confirmation_sent_at = db.Column(db.DateTime)
    sms_reminder_sent_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=db.func.now())

    # relacja
    sms_messages = db.relationship(
        "SMSMessage",
        backref="appointment",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )




class SMSMessage(db.Model):
    __tablename__ = "sms_messages"

    id = db.Column(db.Integer, primary_key=True)

    appointment_id = db.Column(
        db.Integer,
        db.ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    phone = db.Column(db.String(20), nullable=False)

    type = db.Column(
        db.Enum("confirmation", "reminder", "custom", name="sms_type"),
        nullable=False
    )

    status = db.Column(
        db.Enum("pending", "sent", "failed", name="sms_status"),
        default="pending",
        nullable=False
    )

    provider = db.Column(db.String(50), default="smsapi")
    provider_message_id = db.Column(db.String(100))

    content = db.Column(db.Text, nullable=False)

    error_message = db.Column(db.Text)

    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=db.func.now())



# ==================================================
# SZABLONY GENEROWANIA GRAFIKU
# ==================================================
class ScheduleTemplate(db.Model):
    __tablename__ = "schedule_templates"

    id = db.Column(db.Integer, primary_key=True)

    doctor_id = db.Column(
        db.Integer,
        db.ForeignKey("doctors.id"),
        nullable=False
    )

    name = db.Column(db.String(100), nullable=False)

    days_json = db.Column(db.JSON, nullable=False)

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        nullable=False
    )


# ==================================================
# TYPY WIZYT
# ==================================================
class VisitType(db.Model):
    __tablename__ = "visit_types"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), nullable=False, unique=True)

    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2))

    duration_minutes = db.Column(db.Integer, nullable=False)

    # 🔢 kolejność wyświetlania (lista pacjenta + lekarza)
    display_order = db.Column(
        db.Integer,
        nullable=False,
        default=100
    )

    # 🎨 kolor wyświetlania w kalendarzu (FullCalendar)
    color = db.Column(
        db.String(7),
        nullable=False,
        default="#3788d8"
    )

    active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
        nullable=False
    )


# ==================================================
# Urlopy
# ==================================================
class Vacation(db.Model):
    __tablename__ = 'vacations'

    id = db.Column(db.Integer, primary_key=True)

    doctor_id = db.Column(
        db.Integer,
        db.ForeignKey('doctors.id'),
        nullable=False,
        index=True
    )

    date_from = db.Column(db.Date, nullable=False)
    date_to = db.Column(db.Date, nullable=False)

    description = db.Column(db.String(255))

    active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    google_event_id = db.Column(db.String(255), nullable=True)


    # relacja pomocnicza (opcjonalna, nie wpływa na logikę)
    doctor = db.relationship('Doctor', backref='vacations')

    def __repr__(self):
        return f'<Vacation {self.date_from} - {self.date_to} doctor={self.doctor_id}>'

class BlacklistPatient(db.Model):
    __tablename__ = "blacklist_patients"

    id = db.Column(db.Integer, primary_key=True)

    doctor_id = db.Column(
        db.Integer,
        db.ForeignKey("doctors.id"),
        nullable=False,
        index=True
    )

    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)

    phone = db.Column(db.String(30), nullable=False, index=True)
    email = db.Column(db.String(120), nullable=True)

    description = db.Column(db.Text, nullable=False)

    blocked_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    def __repr__(self):
        return (
            f"<BlacklistPatient "
            f"{self.first_name} {self.last_name} "
            f"phone={self.phone} "
            f"active={self.active}>"
        )
# ==================================================
# Konfiguracja
# ==================================================
class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False)
    value = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f"<Setting {self.key}>"
    

import json
from extensions import db

DEFAULT_SETTINGS = [
    {
        "key": "calendar_visible_days",
        "description": "Dni tygodnia widoczne w kalendarzu lekarza",
        "value": json.dumps(["mon", "tue", "wed", "thu", "fri"])
    },

    # ============================
    # GOOGLE CALENDAR – KONFIG
    # ============================

    {
        "key": "google_calendar_id",
        "description": "ID kalendarza Google (np. primary)",
        "value": ""
    },
    {
        "key": "google_access_token",
        "description": "Access token Google Calendar (OAuth)",
        "value": ""
    },
    {
        "key": "google_refresh_token",
        "description": "Refresh token Google Calendar (OAuth)",
        "value": ""
    },
    {
        "key": "google_connected",
        "description": "Czy konto Google Calendar jest połączone",
        "value": "false"
    }
]


def init_default_settings():
    from models import Setting  # ⛔ import lokalny – ważne

    for s in DEFAULT_SETTINGS:
        exists = Setting.query.filter_by(key=s["key"]).first()
        if not exists:
            db.session.add(
                Setting(
                    key=s["key"],
                    description=s["description"],
                    value=s["value"]
                )
            )

    db.session.commit()

