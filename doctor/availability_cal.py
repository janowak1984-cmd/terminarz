from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint(
    "doctor_availability_cal",
    __name__,
    url_prefix="/doctor/availability-calendar"
)

@bp.route("/")
@login_required
def view():
    return render_template("doctor/availability_calendar.html")
