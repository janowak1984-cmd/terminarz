from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint(
    "doctor_availability_list",
    __name__,
    url_prefix="/doctor/availability"
)

@bp.route("/")
@login_required
def view():
    return render_template("doctor/availability_list.html")
