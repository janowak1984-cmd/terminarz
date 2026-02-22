from datetime import datetime
from flask import current_app
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from extensions import db
from utils.settings import get_setting, set_setting
from models import VisitType


# ======================================================
# ❌ BRAK POŁĄCZENIA
# ======================================================

class GoogleCalendarNotConnected(Exception):
    pass


# ======================================================
# 📅 GOOGLE CALENDAR SERVICE
# ======================================================

class GoogleCalendarService:
    """
    JEDYNE miejsce w systemie, które:
    - zna Google API
    - zarządza tokenami
    - tworzy / aktualizuje / usuwa eventy
    """

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    # --------------------------------------------------
    # 🔌 NISKIE POZIOMY – AUTORYZACJA
    # --------------------------------------------------

    @staticmethod
    def get_service():
        if get_setting("google_connected") != "1":
            raise GoogleCalendarNotConnected()

        access_token = get_setting("google_access_token")
        refresh_token = get_setting("google_refresh_token")

        if not access_token or not refresh_token:
            GoogleCalendarService.disconnect()
            raise GoogleCalendarNotConnected()

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=current_app.config["GOOGLE_CLIENT_ID"],
            client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
            scopes=GoogleCalendarService.SCOPES,
        )

        return build("calendar", "v3", credentials=creds)

    @staticmethod
    def _refresh_tokens():
        try:
            creds = Credentials(
                token=get_setting("google_access_token"),
                refresh_token=get_setting("google_refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=current_app.config["GOOGLE_CLIENT_ID"],
                client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
                scopes=GoogleCalendarService.SCOPES,
            )

            creds.refresh(Request())

            set_setting("google_access_token", creds.token)
            set_setting("google_connected", "1")
            db.session.commit()

            current_app.logger.warning("[GOOGLE] token refreshed OK")
            return build("calendar", "v3", credentials=creds)

        except Exception as e:
            current_app.logger.error(f"[GOOGLE] token refresh FAILED: {e}")
            GoogleCalendarService.disconnect()
            db.session.commit()
            return None

    @staticmethod
    def ensure_connection():
        """
        🔑 JEDYNA METODA do pobierania service
        - ping do Google
        - refresh jeśli trzeba
        """
        try:
            service = GoogleCalendarService.get_service()
            service.calendarList().list(maxResults=1).execute()
            return service

        except RefreshError:
            return GoogleCalendarService._refresh_tokens()

        except HttpError as e:
            if e.resp.status in (401, 403):
                return GoogleCalendarService._refresh_tokens()
            raise

        except GoogleCalendarNotConnected:
            return None

    @staticmethod
    def disconnect():
        set_setting("google_connected", "0")
        set_setting("google_access_token", "")
        set_setting("google_refresh_token", "")
        set_setting("google_calendar_id", "")

    # --------------------------------------------------
    # 🧱 EVENT BUILDER
    # --------------------------------------------------

    @staticmethod
    def _build_event(appt):

        from models import Payment

        visit_type = VisitType.query.filter_by(code=appt.visit_type).first()
        base_color_id = visit_type.color if visit_type and visit_type.color else "1"
        color_id = base_color_id

        # Źródło wizyty
        if appt.created_by == "patient":
            prefix = "👤"
            source_line = "Źródło wizyty: Rezerwacja online"
        else:
            prefix = "✍️"
            source_line = "Źródło wizyty: Dodana ręcznie"

        # 🔎 STATUS PŁATNOŚCI
        payment = (
            Payment.query
            .filter_by(appointment_id=appt.id)
            .order_by(Payment.id.desc())
            .first()
        )

        if not payment:
            # brak rekordu płatności (np. płatność w gabinecie)
            payment_line = "Status płatności: PŁATNOŚĆ W GABINECIE"
            payment_icon = "💵 "
            # zostawiamy kolor wizyty

        elif payment.status != "paid":
            payment_line = "Status płatności: OCZEKUJE NA PŁATNOŚĆ"
            payment_icon = "⭕ "
            color_id = "11"  # czerwony w Google

        else:
            payment_line = "Status płatności: OPŁACONA"
            payment_icon = "✅ "
            # zostawiamy kolor wizyty

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
    def sync_appointment(appt, force_update=False):
        service = GoogleCalendarService.ensure_connection()
        if not service:
            appt.google_sync_status = "error"
            appt.google_last_sync_at = datetime.utcnow()
            db.session.commit()
            return

        calendar_id = get_setting("google_calendar_id") or "primary"

        if appt.google_sync_status == "synced" and not force_update:
            return

        event_body = GoogleCalendarService._build_event(appt)

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
            if e.resp.status == 404:
                # event skasowany ręcznie w Google
                appt.google_event_id = None
                db.session.commit()
                GoogleCalendarService.sync_appointment(appt, force_update=True)
                return

            appt.google_sync_status = "error"
            db.session.commit()
            current_app.logger.error(f"[GOOGLE] sync failed appt={appt.id}: {e}")

        except Exception as e:
            appt.google_sync_status = "error"
            db.session.commit()
            current_app.logger.error(f"[GOOGLE] sync failed appt={appt.id}: {e}")

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

        calendar_id = get_setting("google_calendar_id") or "primary"

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

        calendar_id = get_setting("google_calendar_id") or "primary"
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
