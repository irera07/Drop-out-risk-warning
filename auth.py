# routes/auth.py
# Auth blueprint: register, login, logout, role-based redirect

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, session
)
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Teacher, Principal, LocalLeader

auth_bp = Blueprint("auth", __name__)


# ─── helpers ──────────────────────────────────────────────────

ROLE_MODELS = {
    "teacher":       Teacher,
    "principal":     Principal,
    "local_leader":  LocalLeader,
}

ROLE_HOME = {
    "teacher":      "teacher.home",
    "principal":    "principal.home",
    "local_leader": "leader.home",
}

def get_user():
    """Return (user_object, role) from session, or (None, None)."""
    role = session.get("role")
    uid  = session.get("user_id")
    if not role or not uid:
        return None, None
    model = ROLE_MODELS.get(role)
    if not model:
        return None, None
    return model.query.get(uid), role


# ─── login ────────────────────────────────────────────────────

@auth_bp.route("/", methods=["GET"])
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Already logged in → go home
    user, role = get_user()
    if user:
        return redirect(url_for(ROLE_HOME[role]))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Search all three user tables
        found_user, found_role = None, None
        for role_key, model in ROLE_MODELS.items():
            u = model.query.filter_by(email=email).first()
            if u:
                found_user, found_role = u, role_key
                break

        if not found_user or not check_password_hash(found_user.password_hash, password):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html")

        if found_role == "teacher":
            if getattr(found_user, "account_status", "pending") != "active":
                flash("Your account has not yet been admitted or is disabled. Please contact your principal.", "error")
                return render_template("auth/login.html")

        session.clear()
        session["user_id"] = found_user.id
        session["role"]    = found_role
        session["name"]    = found_user.full_name
        session.permanent  = True

        if found_role == "local_leader" and getattr(found_user, "access_status", None) != "approved":
            if getattr(found_user, "requested_school_name", None):
                flash("Your access request is pending approval from the principal.", "info")
            else:
                flash("Please request access to a school report from your dashboard.", "info")

        return redirect(url_for(ROLE_HOME[found_role]))

    return render_template("auth/login.html")


# ─── register ─────────────────────────────────────────────────

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form

        full_name = f.get("full_name", "").strip()
        email     = f.get("email", "").strip().lower()
        phone     = f.get("phone", "").strip()
        sector    = f.get("sector", "").strip()
        role      = f.get("role", "").strip()
        password  = f.get("password", "")
        confirm   = f.get("confirm_password", "")

        # ── Basic validation ──────────────────────────────────
        errors = []
        if not all([full_name, email, sector, role, password]):
            errors.append("Please fill in all required fields.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if role not in ROLE_MODELS:
            errors.append("Invalid role selected.")

        # ── Check email uniqueness across all tables ──────────
        if not errors:
            for model in ROLE_MODELS.values():
                if model.query.filter_by(email=email).first():
                    errors.append("An account with this email already exists.")
                    break

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("auth/register.html", form=f)

        pw_hash = generate_password_hash(password)

        # ── Create user by role ───────────────────────────────
        try:
            if role == "teacher":
                school = f.get("school_name", "").strip()
                cls    = f.get("class_name", "").strip()
                if not school or not cls:
                    flash("Teachers must provide school and class.", "error")
                    return render_template("auth/register.html", form=f)
                new_user = Teacher(
                    full_name=full_name, email=email, phone=phone,
                    sector=sector, school_name=school,
                    class_name=cls, password_hash=pw_hash
                )

            elif role == "principal":
                school = f.get("school_name", "").strip()
                if not school:
                    flash("Principals must provide school name.", "error")
                    return render_template("auth/register.html", form=f)
                new_user = Principal(
                    full_name=full_name, email=email, phone=phone,
                    sector=sector, school_name=school,
                    password_hash=pw_hash
                )

            else:  # local_leader
                new_user = LocalLeader(
                    full_name=full_name, email=email, phone=phone,
                    sector=sector,
                    access_status="pending",
                    password_hash=pw_hash
                )

            db.session.add(new_user)
            db.session.commit()

            flash("Account created! Please log in.", "success")
            return redirect(url_for("auth.login"))

        except Exception as e:
            db.session.rollback()
            flash(f"Registration failed: {str(e)}", "error")
            return render_template("auth/register.html", form=f)

    return render_template("auth/register.html", form={})


# ─── logout ───────────────────────────────────────────────────

@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
