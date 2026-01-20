from datetime import datetime, timedelta

def can_cancel_appointment(appt):
    now = datetime.now()

    if appt.status != "scheduled":
        return False, "Ta wizyta nie może zostać anulowana"

    # 🔒 blokada przed potwierdzeniem SMS
    if not (appt.sms_confirmation_sent_at or appt.email_confirmation_sent_at):
        return False, "Wizyta nie została jeszcze potwierdzona"

    if appt.start <= now:
        return False, "Wizyta już się rozpoczęła lub minęła"

    if appt.start - now < timedelta(hours=48):
        return False, "Anulowanie możliwe najpóźniej 48h przed wizytą"

    return True, None
