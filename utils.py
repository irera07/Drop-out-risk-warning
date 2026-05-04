# routes/utils.py
# Shared decorators and helpers for all route blueprints

from functools import wraps
from flask import session, redirect, url_for, flash
from models import Teacher, Principal, LocalLeader

ROLE_MODELS = {
    "teacher":      Teacher,
    "principal":    Principal,
    "local_leader": LocalLeader,
}


def login_required(f):
    """Redirect to login if no valid session exists."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id") or not session.get("role"):
            flash("Please log in to continue.", "info")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    """Restrict a route to specific roles. Use after @login_required."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("role") not in roles:
                flash("You do not have permission to view that page.", "error")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def current_user():
    """Return the logged-in user object, or None."""
    role = session.get("role")
    uid  = session.get("user_id")
    if not role or not uid:
        return None
    model = ROLE_MODELS.get(role)
    return model.query.get(uid) if model else None
