# routes/leader.py
# Local Leader blueprint — 5 tabs: Home, CurrentReport, PreviousReport, Contact, Help

import io
from datetime import datetime
import pandas as pd
from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, send_file, jsonify
)
from models import db, Principal, Teacher, Prediction, StudentFile
from utils import login_required, role_required, current_user

leader_bp = Blueprint("leader", __name__)


# ── helpers ───────────────────────────────────────────────────

def split_names(value):
    if not value:
        return []
    return [name.strip() for name in value.split(",") if name.strip()]


def join_names(names):
    cleaned = sorted({name.strip() for name in names if name and name.strip()})
    return ",".join(cleaned) if cleaned else None


def get_requested_schools(leader):
    return set(split_names(getattr(leader, "requested_school_name", "")))


def get_approved_schools(leader):
    return set(split_names(getattr(leader, "approved_school_names", "")))


def get_all_sector_schools(sector):
    """Return ALL distinct school names registered in this sector (no restrictions)."""
    principals = Principal.query.filter_by(sector=sector).all()
    schools = {p.school_name for p in principals}
    teachers = Teacher.query.filter_by(sector=sector).all()
    schools |= {t.school_name for t in teachers}
    return sorted(schools)


def get_sector_schools(sector, leader=None):
    """Return approved school names for a local leader, or all sector schools otherwise."""
    if leader:
        return sorted(get_approved_schools(leader))

    principals = Principal.query.filter_by(sector=sector).all()
    schools = {p.school_name for p in principals}
    teachers = Teacher.query.filter_by(sector=sector).all()
    schools |= {t.school_name for t in teachers}
    return sorted(schools)


def get_school_classes(sector, school_name):
    """Return distinct class names for a school in this sector."""
    teachers = Teacher.query.filter_by(sector=sector, school_name=school_name).all()
    return sorted({t.class_name for t in teachers})


def get_sector_school_class_pairs(sector):
    teachers = Teacher.query.filter_by(sector=sector).all()
    return sorted({(t.school_name, t.class_name) for t in teachers}, key=lambda s: (s[0], s[1]))


def latest_pred_for_class(sector, school_name, class_name):
    return (Prediction.query
            .filter_by(sector=sector, school_name=school_name,
                       class_name=class_name, status="done")
            .order_by(Prediction.predicted_at.desc())
            .first())


def aggregate_predictions(preds):
    """Sum KPI counters across a list of Prediction objects."""
    if not preds:
        return None
    return {
        "total_students": sum(p.total_students or 0 for p in preds),
        "dropout_count":  sum(p.dropout_count  or 0 for p in preds),
        "non_dropout":    sum(p.non_dropout    or 0 for p in preds),
        "high_risk":      sum(p.high_risk      or 0 for p in preds),
        "medium_risk":    sum(p.medium_risk    or 0 for p in preds),
        "low_risk":       sum(p.low_risk       or 0 for p in preds),
        "male_count":     sum(p.male_count     or 0 for p in preds),
        "female_count":   sum(p.female_count   or 0 for p in preds),
        "count":          len(preds),
    }


def build_school_summaries(sector, schools):
    """
    For each school, aggregate latest predictions across all its classes.
    Returns a list of dicts with school-level KPIs.
    """
    summaries = []
    for school in schools:
        classes = get_school_classes(sector, school)
        preds   = [p for cls in classes
                   if (p := latest_pred_for_class(sector, school, cls))]
        agg = aggregate_predictions(preds)
        if agg:
            agg["school_name"] = school
            agg["classes"]     = len(preds)
            summaries.append(agg)
    return summaries


# ── HOME ──────────────────────────────────────────────────────

@leader_bp.route("/home")
@login_required
@role_required("local_leader")
def home():
    user    = current_user()
    schools = get_sector_schools(user.sector, user)
    return render_template("leader/leader_dashboard.html",
                           user=user, active_tab="home",
                           num_schools=len(schools))


# ── BROWSE SCHOOLS ────────────────────────────────────────────

@leader_bp.route("/schools", methods=["GET", "POST"])
@login_required
@role_required("local_leader")
def browse_schools():
    """Display all schools in the sector and allow requesting access."""
    user = current_user()
    
    # Get all schools in this sector
    all_schools = get_all_sector_schools(user.sector)
    requested_schools = get_requested_schools(user)
    approved_schools = get_approved_schools(user)
    
    # Handle permission request
    if request.method == "POST":
        selected_schools = set(request.form.getlist("school_names"))
        if not selected_schools:
            flash("Please select at least one school to request access.", "error")
            return redirect(url_for("leader.browse_schools"))
        
        valid_schools = [s for s in selected_schools if s in all_schools]
        if not valid_schools:
            flash("Invalid school selection.", "error")
            return redirect(url_for("leader.browse_schools"))

        pending = requested_schools | {s for s in valid_schools if s not in approved_schools}
        if not pending:
            flash("All selected schools are already approved.", "info")
            return redirect(url_for("leader.browse_schools"))

        user.requested_school_name = join_names(pending)
        user.access_status = "approved" if approved_schools else "pending"
        db.session.commit()
        flash(f"Permission request submitted for {len(pending)} school(s): {', '.join(sorted(pending))}. "
              "The school principal(s) will review your request.", "success")
        return redirect(url_for("leader.browse_schools"))
    
    # Build school info with access status
    school_info = []
    for school in all_schools:
        teachers = Teacher.query.filter_by(sector=user.sector, school_name=school).all()
        classes = {t.class_name for t in teachers}
        
        latest_preds = (Prediction.query
                       .filter_by(sector=user.sector, school_name=school, status="done")
                       .order_by(Prediction.predicted_at.desc())
                       .limit(5)
                       .all())
        
        if school in approved_schools:
            access_status = "approved"
        elif school in requested_schools:
            access_status = "pending"
        else:
            access_status = "none"
        
        school_info.append({
            "name": school,
            "num_classes": len(classes),
            "num_teachers": len(teachers),
            "num_predictions": len(latest_preds),
            "access_status": access_status,
            "teachers": teachers
        })
    
    return render_template("leader/leader_dashboard.html",
                           user=user, active_tab="schools",
                           school_info=school_info,
                           all_schools=all_schools)


# ── CURRENT REPORT ────────────────────────────────────────────

@leader_bp.route("/current-report", methods=["GET", "POST"])
@login_required
@role_required("local_leader")
def current_report():
    user = current_user()
    approved_schools = get_approved_schools(user)

    if not approved_schools:
        flash("No approved schools yet. Request access from the Schools tab.", "error")
        return redirect(url_for("leader.home"))

    selected = request.form.get("school_name") or request.args.get("school_name") or ""
    if selected and selected not in approved_schools:
        flash("You do not have approved access for that school.", "error")
        return redirect(url_for("leader.current_report"))

    schools = sorted(approved_schools)
    school_preds = []
    school_agg = None
    sector_agg = None
    school_summaries = []

    # Per-school detail
    if selected:
        classes = get_school_classes(user.sector, selected)
        school_preds = [p for cls in classes
                        if (p := latest_pred_for_class(user.sector, selected, cls))]
        school_agg = aggregate_predictions(school_preds)

    # School-level summary only for approved schools
    school_summaries = build_school_summaries(user.sector, schools)
    all_sector_preds = []
    for school in schools:
        classes = get_school_classes(user.sector, school)
        for cls in classes:
            p = latest_pred_for_class(user.sector, school, cls)
            if p:
                all_sector_preds.append(p)
    sector_agg = aggregate_predictions(all_sector_preds)

    return render_template("leader/leader_dashboard.html",
                           user=user, active_tab="current",
                           schools=schools, selected=selected,
                           school_preds=school_preds,
                           school_agg=school_agg,
                           sector_agg=sector_agg,
                           school_summaries=school_summaries)


# ── PREVIOUS REPORTS ──────────────────────────────────────────

@leader_bp.route("/previous-reports")
@login_required
@role_required("local_leader")
def previous_reports():
    user = current_user()
    approved_schools = get_approved_schools(user)
    if not approved_schools:
        flash("Access denied. No approved schools yet.", "error")
        return redirect(url_for("leader.home"))

    schools = sorted(approved_schools)
    selected = request.args.get("school_name", "")
    if selected and selected not in approved_schools:
        flash("You do not have approved access for that school.", "error")
        return redirect(url_for("leader.previous_reports"))

    query = Prediction.query.filter_by(sector=user.sector, status="done")
    if selected:
        query = query.filter_by(school_name=selected)
    else:
        query = query.filter(Prediction.school_name.in_(schools))
    preds = query.order_by(Prediction.predicted_at.desc()).all()

    return render_template("leader/leader_dashboard.html",
                           user=user, active_tab="previous",
                           schools=schools, selected=selected,
                           predictions=preds)


@leader_bp.route("/report/<int:pred_id>/download")
@login_required
@role_required("local_leader")
def download_report(pred_id):
    user = current_user()
    approved_schools = get_approved_schools(user)
    if not approved_schools:
        flash("Access denied.", "error")
        return redirect(url_for("leader.home"))
    
    pred = Prediction.query.get_or_404(pred_id)
    if pred.sector != user.sector or pred.school_name not in approved_schools:
        flash("Access denied.", "error")
        return redirect(url_for("leader.previous_reports"))

    rows = pred.result_data or []
    df   = pd.DataFrame(rows)
    buf  = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    fname = f"report_{pred.school_name}_{pred.class_name}_{pred.predicted_at.strftime('%Y%m%d')}.csv"
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=fname)


@leader_bp.route("/sector-report/download")
@login_required
@role_required("local_leader")
def download_sector_report():
    """Merged CSV of all latest predictions across approved schools."""
    user = current_user()
    approved_schools = get_approved_schools(user)
    if not approved_schools:
        flash("Access denied.", "error")
        return redirect(url_for("leader.home"))
    
    rows = []
    for school in approved_schools:
        classes = get_school_classes(user.sector, school)
        for cls in classes:
            p = latest_pred_for_class(user.sector, school, cls)
            if p and p.result_data:
                for r in p.result_data:
                    r["school_name"] = school
                    r["class_name"] = cls
                    rows.append(r)

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    fname = f"sector_report_{user.sector}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=fname)


# ── CONTACT ───────────────────────────────────────────────────

@leader_bp.route("/contact", methods=["GET", "POST"])
@login_required
@role_required("local_leader")
def contact():
    user = current_user()
    if request.method == "POST":
        flash("Your message has been sent. Thank you!", "success")
        return redirect(url_for("leader.contact"))
    return render_template("leader/leader_dashboard.html",
                           user=user, active_tab="contact")


# ── HELP ──────────────────────────────────────────────────────

@leader_bp.route("/help")
@login_required
@role_required("local_leader")
def help_page():
    user = current_user()
    return render_template("leader/leader_dashboard.html",
                           user=user, active_tab="help")


# ── API ENDPOINTS for accessing teacher reports in sector ───────

@leader_bp.route("/api/all-schools", methods=["GET"])
@login_required
@role_required("local_leader")
def api_all_schools():
    """
    Get all schools registered in the local leader's sector.
    Includes school metadata and permission status.
    """
    user = current_user()
    all_schools = get_all_sector_schools(user.sector)
    
    school_list = []
    for school in all_schools:
        # Get school details
        principal = Principal.query.filter_by(school_name=school, sector=user.sector).first()
        teachers = Teacher.query.filter_by(sector=user.sector, school_name=school).all()
        classes = {t.class_name for t in teachers}
        
        # Get latest predictions
        latest_preds = (Prediction.query
                       .filter_by(sector=user.sector, school_name=school, status="done")
                       .order_by(Prediction.predicted_at.desc())
                       .all())
        
        # Determine access status
        access_status = "none"
        if user.access_status == "approved" and user.requested_school_name == school:
            access_status = "approved"
        elif user.access_status == "pending" and user.requested_school_name == school:
            access_status = "pending"
        
        school_list.append({
            "school_name": school,
            "principal_name": principal.full_name if principal else "Not Registered",
            "principal_email": principal.email if principal else None,
            "num_classes": len(classes),
            "num_teachers": len(teachers),
            "num_predictions": len(latest_preds),
            "access_status": access_status,
            "classes": sorted(list(classes))
        })
    
    return jsonify({
        "sector": user.sector,
        "total_schools": len(all_schools),
        "schools": school_list
    })


@leader_bp.route("/api/request-school-access", methods=["POST"])
@login_required
@role_required("local_leader")
def api_request_school_access():
    """
    Request access to a specific school's data.
    """
    user = current_user()
    data = request.get_json() or {}
    school_name = data.get("school_name", "").strip()
    
    if not school_name:
        return jsonify({"error": "School name required"}), 400
    
    # Verify school exists in sector
    all_schools = get_all_sector_schools(user.sector)
    if school_name not in all_schools:
        return jsonify({"error": "School not found in sector"}), 404
    
    # Update access request
    user.requested_school_name = school_name
    user.access_status = "pending"
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": f"Permission request submitted for {school_name}",
        "school_name": school_name,
        "access_status": "pending"
    })


@leader_bp.route("/api/sector-teacher-reports", methods=["GET"])
@login_required
@role_required("local_leader")
def api_sector_teacher_reports():
    """
    Get all teacher reports in this sector.
    Returns list of current reports from all teachers in the sector.
    """
    user = current_user()
    
    # Get all teachers in this sector
    teachers = Teacher.query.filter_by(sector=user.sector).all()
    
    reports = []
    for teacher in teachers:
        # Get latest prediction for each teacher
        pred = (Prediction.query
                .filter_by(teacher_id=teacher.id, status="done")
                .order_by(Prediction.predicted_at.desc())
                .first())
        
        if pred:
            reports.append({
                "teacher_id": teacher.id,
                "teacher_name": teacher.full_name,
                "school_name": teacher.school_name,
                "class_name": teacher.class_name,
                "prediction_id": pred.id,
                "total_students": pred.total_students,
                "dropout_count": pred.dropout_count,
                "non_dropout": pred.non_dropout,
                "high_risk": pred.high_risk,
                "medium_risk": pred.medium_risk,
                "low_risk": pred.low_risk,
                "male_count": pred.male_count,
                "female_count": pred.female_count,
                "predicted_at": pred.predicted_at.isoformat()
            })
    
    return jsonify({"sector": user.sector, "reports": reports})


@leader_bp.route("/api/school-teacher-reports/<school_name>", methods=["GET"])
@login_required
@role_required("local_leader")
def api_school_teacher_reports(school_name):
    """
    Get all teacher reports for a specific school in this sector.
    """
    user = current_user()
    
    # Get all teachers in this school and sector
    teachers = Teacher.query.filter_by(sector=user.sector, school_name=school_name).all()
    
    reports = []
    for teacher in teachers:
        # Get latest prediction for each teacher
        pred = (Prediction.query
                .filter_by(teacher_id=teacher.id, status="done")
                .order_by(Prediction.predicted_at.desc())
                .first())
        
        if pred:
            reports.append({
                "teacher_id": teacher.id,
                "teacher_name": teacher.full_name,
                "class_name": teacher.class_name,
                "prediction_id": pred.id,
                "total_students": pred.total_students,
                "dropout_count": pred.dropout_count,
                "non_dropout": pred.non_dropout,
                "high_risk": pred.high_risk,
                "medium_risk": pred.medium_risk,
                "low_risk": pred.low_risk,
                "male_count": pred.male_count,
                "female_count": pred.female_count,
                "predicted_at": pred.predicted_at.isoformat()
            })
    
    return jsonify({"sector": user.sector, "school_name": school_name, "reports": reports})


@leader_bp.route("/api/teacher-general-file/<int:teacher_id>/<class_name>", methods=["GET"])
@login_required
@role_required("local_leader")
def api_teacher_general_file(teacher_id, class_name):
    """
    Get general file (merged all versions) for a specific teacher.
    This allows sector leader to reference teacher's accumulated data.
    """
    user = current_user()
    teacher = Teacher.query.get_or_404(teacher_id)
    
    # Verify teacher belongs to this sector
    if teacher.sector != user.sector:
        return jsonify({"error": "Access denied"}), 403
    
    # Get all file versions
    files = (StudentFile.query
             .filter_by(teacher_id=teacher_id, class_name=class_name, is_general=False)
             .order_by(StudentFile.uploaded_at.asc())
             .all())
    
    if not files:
        return jsonify({"error": "No student files found"}), 404
    
    # Build general file
    dfs = []
    for f in files:
        try:
            buf = io.BytesIO(f.file_data)
            df = pd.read_csv(buf) if f.file_name.endswith(".csv") else pd.read_excel(buf)
            dfs.append(df)
        except Exception:
            continue
    
    if not dfs:
        return jsonify({"error": "Could not parse files"}), 400
    
    if len(dfs) == 1:
        general = dfs[0]
    else:
        latest = dfs[-1]
        previous = dfs[:-1]
        num_cols = latest.select_dtypes(include="number").columns
        prev_mean = pd.concat(previous)[num_cols].mean()
        general = latest.copy()
        general[num_cols] = (latest[num_cols] * 0.7) + (prev_mean * 0.3)
    
    from models import StudentFile
    
    return jsonify({
        "teacher_id": teacher_id,
        "teacher_name": teacher.full_name,
        "school_name": teacher.school_name,
        "class_name": class_name,
        "num_versions": len(files),
        "total_students": len(general),
        "columns": general.columns.tolist(),
        "data": general.to_dict(orient="records")
    })
