from datetime import datetime
from flask import current_app
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from extensions import db
from utils.settings import get_setting
from models import VisitType, GoogleCalendarError


# ======================================================
# 📅 GOOGLE CALENDAR SERVICE (SERVICE ACCOUNT)
# ======================================================

class GoogleCalendarService:

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    # --------------------------------------------------
    # 🔌 AUTORYZACJA (SERVICE ACCOUNT)
    # --------------------------------------------------

    @staticmethod
    def get_service():
        try:
            credentials = service_account.Credentials.from_service_account_file(
                current_app.config["GOOGLE_SERVICE_ACCOUNT_FILE"],
                scopes=GoogleCalendarService.SCOPES
            )

            return build("calendar", "v3", credentials=credentials)

        except Exception as e:
            current_app.logger.error(f"[GOOGLE] service init error: {e}")
            return None

    @staticmethod
    def ensure_connection():
        service = GoogleCalendarService.get_service()

        if not service:
            return None

        try:
            service.calendarList().list(maxResults=1).execute()
            return service
        except Exception as e:
            current_app.logger.error(f"[GOOGLE] connection test failed: {e}")
            return None

    # --------------------------------------------------
    # 🧱 EVENT BUILDER
    # --------------------------------------------------

    @staticmethod
    def _build_event(appt, payment_context=None):

        from models import Payment

        visit_type = VisitType.query.filter_by(code=appt.visit_type).first()
        base_color_id = visit_type.color if visit_type and visit_type.color else "1"
        color_id = base_color_id

        # ─────────────────────────
        # ŹRÓDŁO
        # ─────────────────────────
        if appt.created_by == "patient":
            prefix = "👤"
            source_line = "Źródło wizyty: Rezerwacja online"
        else:
            prefix = "✍️"
            source_line = "Źródło wizyty: Dodana ręcznie"

        # ─────────────────────────
        # STATUS PŁATNOŚCI
        # ─────────────────────────

        payment = (
            Payment.query
            .filter_by(appointment_id=appt.id)
            .order_by(Payment.id.desc())
            .first()
        )

        payment_icon = ""
        payment_line = ""

        if payment:

            if payment.status == "paid":
                payment_icon = ""
                payment_line = "Status płatności: OPŁACONA"

            else:
                payment_icon = "🚫 "
                payment_line = "Status płatności: OCZEKUJE NA PŁATNOŚĆ"
                color_id = "11"

        elif payment_context and payment_context.get("payment_flow") == "online":

            payment_icon = "🚫 "
            payment_line = "Status płatności: OCZEKUJE NA PŁATNOŚĆ"
            color_id = "11"

        else:

            payment_icon = ""
            payment_line = "Status płatności: PŁATNOŚĆ W GABINECIE"

        description = (
            f"{source_line}\n"
            f"{payment_line}\n\n"
            f"Telefon: {appt.patient_phone}"
        )

        return {
            "summary": f"{payment_icon}{prefix} Wizyta: {appt.patient_first_name} {appt.patient_last_name}",
            "description": description,
            "start": {
                "dateTime": appt.start.isoformat(),
                "timeZone": "Europe/Warsaw",
            },
            "end": {
                "dateTime": appt.end.isoformat(),
                "timeZone": "Europe/Warsaw",
            },
            "colorId": color_id,
        }

    # --------------------------------------------------
    # 🔁 SYNC (CREATE / UPDATE)
    # --------------------------------------------------

    @staticmethod
    def sync_appointment(appt, force_update=False, payment_context=None):

        service = GoogleCalendarService.ensure_connection()

        if not service:

            appt.google_sync_status = "error"
            appt.google_last_sync_at = datetime.utcnow()

            db.session.add(
                GoogleCalendarError(
                    appointment_id=appt.id,
                    email=appt.patient_email,
                    phone=appt.patient_phone,
                    error_type="NotConnected",
                    error="Google Calendar not connected"
                )
            )

            db.session.commit()
            return

        calendar_id = get_setting("google_calendar_id") or current_app.config["GOOGLE_CALENDAR_ID"]

        if appt.google_sync_status == "synced" and not force_update:
            return

        event_body = GoogleCalendarService._build_event(
            appt,
            payment_context=payment_context
        )

        try:

            if appt.google_event_id:

                service.events().update(
                    calendarId=calendar_id,
                    eventId=appt.google_event_id,
                    body=event_body
                ).execute()

            else:

                created = service.events().insert(
                    calendarId=calendar_id,
                    body=event_body
                ).execute()

                appt.google_event_id = created["id"]

            appt.google_sync_status = "synced"
            appt.google_last_sync_at = datetime.utcnow()

            db.session.commit()

        except HttpError as e:

            db.session.rollback()

            # 📅 event nie istnieje → utwórz ponownie
            if e.resp.status == 404:

                appt.google_event_id = None
                db.session.commit()

                GoogleCalendarService.sync_appointment(
                    appt,
                    force_update=True,
                    payment_context=payment_context
                )
                return

            # 🔴 zapis błędu
            appt.google_sync_status = "error"
            appt.google_last_sync_at = datetime.utcnow()

            db.session.add(
                GoogleCalendarError(
                    appointment_id=appt.id,
                    email=appt.patient_email,
                    phone=appt.patient_phone,
                    error_type="HttpError",
                    error=str(e)
                )
            )

            db.session.commit()

            current_app.logger.error(
                f"[GOOGLE] sync failed appt={appt.id}: {e}"
            )

        except Exception as e:

            db.session.rollback()

            appt.google_sync_status = "error"
            appt.google_last_sync_at = datetime.utcnow()

            db.session.add(
                GoogleCalendarError(
                    appointment_id=appt.id,
                    email=appt.patient_email,
                    phone=appt.patient_phone,
                    error_type=type(e).__name__,
                    error=str(e)
                )
            )

            db.session.commit()

            current_app.logger.error(
                f"[GOOGLE] sync failed appt={appt.id}: {e}"
            )

    # --------------------------------------------------
    # 🗑 DELETE
    # --------------------------------------------------

    @staticmethod
    def delete_appointment(appt):
        if not appt.google_event_id:
            return

        service = GoogleCalendarService.ensure_connection()
        if not service:
            return

        calendar_id = get_setting("google_calendar_id") or current_app.config["GOOGLE_CALENDAR_ID"]

        try:
            service.events().delete(
                calendarId=calendar_id,
                eventId=appt.google_event_id
            ).execute()
        except Exception as e:
            current_app.logger.warning(
                f"[GOOGLE] delete skipped appt={appt.id}: {e}"
            )

        appt.google_event_id = None
        appt.google_sync_status = "deleted"
        appt.google_last_sync_at = datetime.utcnow()
        db.session.commit()

    # --------------------------------------------------
    # 🔥 FORCE CREATE
    # --------------------------------------------------

    @staticmethod
    def force_create_event(appt):
        service = GoogleCalendarService.ensure_connection()
        if not service:
            return

        calendar_id = get_setting("google_calendar_id") or current_app.config["GOOGLE_CALENDAR_ID"]
        event_body = GoogleCalendarService._build_event(appt)

        try:
            created = service.events().insert(
                calendarId=calendar_id,
                body=event_body
            ).execute()

            appt.google_event_id = created["id"]
            appt.google_sync_status = "synced"
            appt.google_last_sync_at = datetime.utcnow()
            db.session.commit()

        except Exception as e:
            appt.google_sync_status = "error"
            db.session.commit()
            current_app.logger.error(
                f"[GOOGLE] force create failed appt={appt.id}: {e}"
            )