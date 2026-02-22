from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json


# ==================================================
# WSPÓLNY TIMESTAMP MIXIN
# ==================================================
class TimestampMixin:
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
# LEKARZ / AUTH
# ==================================================
class Doctor(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


# ==================================================
# DOSTĘPNOŚĆ
# ==================================================
class Availability(TimestampMixin, db.Model):
    __tablename__ = "availabilities"

    id = db.Column(db.Integer, primary_key=True)

    doctor_id = db.Column(
        db.Integer,
        db.ForeignKey("doctors.id"),
        nullable=False
    )

    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=False)

    active = db.Column(db.Boolean, nullable=False, default=True)


# ==================================================
# WIZYTY
# ==================================================
class Appointment(TimestampMixin, db.Model):
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
    cancelled_by = db.Column(
        db.Enum("patient", "doctor", name="appointment_cancelled_by"),
        nullable=True
    )

    google_event_id = db.Column(db.String(255))
    google_sync_status = db.Column(
        db.Enum("never", "synced", "deleted", "error", name="google_sync_status"),
        default="never",
        nullable=False
    )
    google_last_sync_at = db.Column(db.DateTime)

    sms_confirmation_sent_at = db.Column(db.DateTime)
    sms_reminder_sent_at = db.Column(db.DateTime)

    email_confirmation_sent_at = db.Column(db.DateTime)
    email_reminder_sent_at = db.Column(db.DateTime)

    client_ip = db.Column(db.String(45))

    sms_messages = db.relationship(
        "SMSMessage",
        backref="appointment",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    email_messages = db.relationship(
        "EmailMessage",
        backref="appointment",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    payments = db.relationship(
        "Payment",
        backref="appointment",
        lazy=True,
        cascade="all, delete-orphan"
    )


# ==================================================
# SMS
# ==================================================
class SMSMessage(TimestampMixin, db.Model):
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


# ==================================================
# EMAIL
# ==================================================
class EmailMessage(TimestampMixin, db.Model):
    __tablename__ = "email_messages"

    id = db.Column(db.Integer, primary_key=True)

    appointment_id = db.Column(
        db.Integer,
        db.ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    email = db.Column(db.String(120), nullable=False)

    type = db.Column(
        db.Enum("confirmation", "reminder", "payment_retry", "custom",
                name="email_type"),
        nullable=False
    )

    status = db.Column(
        db.Enum("pending", "sent", "failed", name="email_status"),
        default="pending",
        nullable=False
    )

    provider = db.Column(db.String(50), default="sendgrid")
    provider_message_id = db.Column(db.String(100))

    subject = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)

    error_message = db.Column(db.Text)
    sent_at = db.Column(db.DateTime)


# ==================================================
# SZABLONY
# ==================================================
class ScheduleTemplate(TimestampMixin, db.Model):
    __tablename__ = "schedule_templates"

    id = db.Column(db.Integer, primary_key=True)

    doctor_id = db.Column(
        db.Integer,
        db.ForeignKey("doctors.id"),
        nullable=False
    )

    name = db.Column(db.String(100), nullable=False)
    days_json = db.Column(db.JSON, nullable=False)


# ==================================================
# TYPY WIZYT
# ==================================================
class VisitType(TimestampMixin, db.Model):
    __tablename__ = "visit_types"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(50), nullable=False, unique=True)

    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2))
    duration_minutes = db.Column(db.Integer, nullable=False)

    display_order = db.Column(db.Integer, nullable=False, default=100)
    display_order_doctor = db.Column(db.Integer, nullable=False, default=100)

    color = db.Column(db.String(7), nullable=False, default="#3788d8")

    active = db.Column(db.Boolean, nullable=False, default=True)
    only_online_payment = db.Column(db.Boolean, nullable=False, default=False)


# ==================================================
# URLOPY
# ==================================================
class Vacation(TimestampMixin, db.Model):
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

    google_event_id = db.Column(db.String(255))

    doctor = db.relationship('Doctor', backref='vacations')


# ==================================================
# BLACKLISTA
# ==================================================
class BlacklistPatient(TimestampMixin, db.Model):
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
    email = db.Column(db.String(120))

    description = db.Column(db.Text, nullable=False)
    blocked_at = db.Column(db.DateTime, default=datetime.utcnow)

    active = db.Column(db.Boolean, nullable=False, default=True)


# ==================================================
# PŁATNOŚCI
# ==================================================
class Payment(TimestampMixin, db.Model):
    __tablename__ = "payments"
    __table_args__ = (
        db.UniqueConstraint(
            "provider",
            "provider_session_id",
            name="uq_provider_session"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    appointment_id = db.Column(
        db.Integer,
        db.ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False
    )

    provider = db.Column(db.String(32), nullable=False, default="przelewy24")
    provider_session_id = db.Column(db.String(128), nullable=False)
    provider_order_id = db.Column(db.String(128))

    amount = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="PLN")

    status = db.Column(
        db.Enum(
            "init", "pending", "paid",
            "failed", "cancelled", "refunded",
            name="payment_status"
        ),
        nullable=False,
        default="init"
    )

    paid_at = db.Column(db.DateTime)


# ==================================================
# KONFIGURACJA
# ==================================================
class Setting(TimestampMixin, db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False)
    value = db.Column(db.Text, nullable=False)


# ==================================================
# DEFAULT SETTINGS
# ==================================================
DEFAULT_SETTINGS = [
    {
        "key": "calendar_visible_days",
        "description": "Dni tygodnia widoczne w kalendarzu lekarza",
        "value": json.dumps(["mon", "tue", "wed", "thu", "fri"])
    },
    {
        "key": "google_calendar_id",
        "description": "ID kalendarza Google",
        "value": ""
    },
    {
        "key": "google_access_token",
        "description": "Access token Google Calendar",
        "value": ""
    },
    {
        "key": "google_refresh_token",
        "description": "Refresh token Google Calendar",
        "value": ""
    },
    {
        "key": "google_connected",
        "description": "Czy Google Calendar jest połączony",
        "value": "false"
    }
]


def init_default_settings():
    from models import Setting

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