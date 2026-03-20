from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint("doctor_generate", __name__, url_prefix="/doctor/generate")

@bp.route("/")
@login_required
def view():
    return render_template("doctor/generate.html")
