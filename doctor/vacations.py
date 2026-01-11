from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime

from app import db
from models import Vacation

doctor_vacations_bp = Blueprint(
    'doctor_vacations',
    __name__,
    url_prefix='/doctor/vacations'
)
