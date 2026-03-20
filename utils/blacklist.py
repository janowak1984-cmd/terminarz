from extensions import db
from models import BlacklistPatient


#############################################################################
## Sprawdza czy numer telefonu jest aktywnie zablokowany dla danego lekarza.#
#############################################################################
def is_phone_blacklisted(doctor_id, phone):

    if not doctor_id or not phone:
        return False

    return db.session.query(BlacklistPatient.id).filter(
        BlacklistPatient.doctor_id == doctor_id,
        BlacklistPatient.phone == phone,
        BlacklistPatient.active.is_(True)
    ).first() is not None
