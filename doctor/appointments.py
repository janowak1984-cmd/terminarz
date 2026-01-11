from flask import Blueprint, render_template
from flask_login import login_required, current_user
from models import Appointment

bp = Blueprint("doctor_appointments", __name__, url_prefix="/doctor/appointments")

@bp.route("/")
@login_required
def view():
    appointments = Appointment.query.filter_by(
        doctor_id=current_user.id
    ).order_by(Appointment.start).all()

    return render_template(
        "doctor/appointments.html",
        appointments=appointments
    )
