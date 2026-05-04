# routes/principal.py
# Principal blueprint — 5 tabs: Home, CurrentReport, PreviousReport, Contact, Help

import io
import pandas as pd
from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, send_file, jsonify
)
from models import db, Teacher, Prediction, LocalLeader, StudentFile
from utils import login_required, role_required, current_user

principal_bp = Blueprint("principal", __name__)


# ── helpers ───────────────────────────────────────────────────

def get_school_classes(school_name):
    """Return distinct class names registered under this school."""
    teachers = Teacher.query.filter_by(school_name=school_name).all()
    return sorted({t.class_name for t in teachers})


def latest_pred_for_class(school_name, class_name):
    """Return the most recent completed prediction for a class."""
    return (Prediction.query
            .filter_by(school_name=school_name, class_name=class_name, status="done")
            .order_by(Prediction.predicted_at.desc())
            .first())


def aggregate_predictions(preds):
    """
    Sum up KPI counters across a list of Prediction objects.
    Returns a dict of school-level totals.
    """
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
        "classes":        len(preds),
    }


def get_school_teachers(school_name):
    return Teacher.query.filter_by(school_name=school_name).all()


def split_names(value):
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def join_names(names):
    cleaned = sorted({name.strip() for name in names if name and name.strip()})
    return ",".join(cleaned) if cleaned else None


def get_school_leader_requests(school_name):
    return LocalLeader.query.filter(LocalLeader.requested_school_name.like(f"%{school_name}%")).order_by(LocalLeader.full_name).all()


def get_daily_updates(school_name):
    """Return the latest daily data upload for each class in the school."""
    updates = {}
    files = (StudentFile.query
             .filter_by(school_name=school_name, is_general=False)
             .order_by(StudentFile.class_name.asc(), StudentFile.uploaded_at.desc())
             .all())
    for f in files:
        if f.class_name not in updates:
            updates[f.class_name] = f
    return list(updates.values())


# ── HOME ──────────────────────────────────────────────────────

@principal_bp.route("/home")
@login_required
@role_required("principal")
def home():
    user    = current_user()
    classes = get_school_classes(user.school_name)
    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="home",
                           num_classes=len(classes))


# ── CONTROL ───────────────────────────────────────────────────

@principal_bp.route("/control")
@login_required
@role_required("principal")
def control():
    user = current_user()
    teachers = get_school_teachers(user.school_name)
    leader_requests = get_school_leader_requests(user.school_name)
    daily_updates = get_daily_updates(user.school_name)
    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="control",
                           teachers=teachers,
                           leader_requests=leader_requests,
                           daily_updates=daily_updates)


@principal_bp.route("/control/teacher/<int:teacher_id>", methods=["POST"])
@login_required
@role_required("principal")
def control_teacher(teacher_id):
    action = request.form.get("action")
    teacher = Teacher.query.get_or_404(teacher_id)
    user = current_user()
    if teacher.school_name != user.school_name:
        flash("Teacher does not belong to your school.", "error")
        return redirect(url_for("principal.control"))

    if action == "approve":
        teacher.account_status = "active"
        flash(f"Teacher {teacher.full_name} has been admitted.", "success")
    elif action == "decline":
        teacher.account_status = "disabled"
        flash(f"Teacher {teacher.full_name} has been declined.", "info")
    elif action == "disable":
        teacher.account_status = "disabled"
        flash(f"Teacher {teacher.full_name} has been disabled.", "info")
    elif action == "activate":
        teacher.account_status = "active"
        flash(f"Teacher {teacher.full_name} has been activated.", "success")
    else:
        flash("Unknown action.", "error")
        return redirect(url_for("principal.control"))

    db.session.commit()
    return redirect(url_for("principal.control"))


@principal_bp.route("/control/local-leader/<int:leader_id>", methods=["POST"])
@login_required
@role_required("principal")
def control_local_leader(leader_id):
    action = request.form.get("action")
    leader = LocalLeader.query.get_or_404(leader_id)
    user = current_user()
    requested_schools = set(split_names(leader.requested_school_name))
    approved_schools = set(split_names(leader.approved_school_names))
    if user.school_name not in requested_schools:
        flash("This access request does not include your school.", "error")
        return redirect(url_for("principal.control"))

    requested_schools.discard(user.school_name)
    if action == "approve":
        approved_schools.add(user.school_name)
        flash(f"Local leader {leader.full_name} has been granted access for {user.school_name}.", "success")
    elif action == "deny":
        flash(f"Local leader {leader.full_name} access request for {user.school_name} has been denied.", "info")
    else:
        flash("Unknown action.", "error")
        return redirect(url_for("principal.control"))

    leader.requested_school_name = join_names(requested_schools)
    leader.approved_school_names = join_names(approved_schools)
    if approved_schools:
        leader.access_status = "approved"
    elif requested_schools:
        leader.access_status = "pending"
    else:
        leader.access_status = "denied"

    db.session.commit()
    return redirect(url_for("principal.control"))


# ── DAILY CLASS UPDATES ──────────────────────────────────────

@principal_bp.route("/daily-update/<class_name>")
@login_required
@role_required("principal")
def daily_update(class_name):
    user = current_user()
    # Get ALL uploads for this class, ordered by date (newest first)
    all_updates = (StudentFile.query
                   .filter_by(school_name=user.school_name, class_name=class_name, is_general=False)
                   .order_by(StudentFile.uploaded_at.desc())
                   .all())
    
    if not all_updates:
        flash(f"No daily updates found for {class_name}.", "info")
        return redirect(url_for("principal.control"))
    
    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="daily-update",
                           class_name=class_name,
                           all_updates=all_updates)


@principal_bp.route("/daily-update/<class_name>/<int:file_id>")
@login_required
@role_required("principal")
def daily_update_detail(class_name, file_id):
    user = current_user()
    # Get the specific file
    file_obj = StudentFile.query.get_or_404(file_id)
    
    if file_obj.school_name != user.school_name or file_obj.class_name != class_name:
        flash("Access denied.", "error")
        return redirect(url_for("principal.control"))
    
    students = []
    columns  = []
    try:
        buf = io.BytesIO(file_obj.file_data)
        df  = pd.read_csv(buf) if file_obj.file_name.endswith(".csv") else pd.read_excel(buf)
        columns  = df.columns.tolist()
        students = df.to_dict(orient="records")
    except Exception as e:
        flash(f"Could not parse the file: {str(e)}", "error")
        return redirect(url_for("principal.daily_update", class_name=class_name))
    
    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="daily-update-detail",
                           class_name=class_name,
                           file_obj=file_obj,
                           students=students, columns=columns,
                           teacher_name=file_obj.teacher.full_name if file_obj.teacher else "Unknown")


# ── MESSAGES ─────────────────────────────────────────────────

@principal_bp.route("/messages", methods=["GET", "POST"])
@login_required
@role_required("principal")
def messages():
    user = current_user()
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        if not subject or not body:
            flash("Please provide both subject and message.", "error")
            return redirect(url_for("principal.messages"))
        flash("Message sent to your school staff.", "success")
        return redirect(url_for("principal.messages"))
    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="messages")


# ── CURRENT REPORT ────────────────────────────────────────────

@principal_bp.route("/current-report", methods=["GET", "POST"])
@login_required
@role_required("principal")
def current_report():
    user       = current_user()
    classes    = get_school_classes(user.school_name)
    selected   = request.form.get("class_name") or request.args.get("class_name") or ""
    class_pred = None
    school_agg = None
    all_preds  = []

    # Per-class view
    if selected:
        class_pred = latest_pred_for_class(user.school_name, selected)

    # School-wide aggregation — latest pred per class
    for cls in classes:
        p = latest_pred_for_class(user.school_name, cls)
        if p:
            all_preds.append(p)
    school_agg = aggregate_predictions(all_preds)

    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="current",
                           classes=classes, selected=selected,
                           class_pred=class_pred,
                           school_agg=school_agg,
                           all_preds=all_preds)


# ── PREVIOUS REPORTS ──────────────────────────────────────────

@principal_bp.route("/previous-reports")
@login_required
@role_required("principal")
def previous_reports():
    user     = current_user()
    classes  = get_school_classes(user.school_name)
    selected = request.args.get("class_name", "")

    query = Prediction.query.filter_by(school_name=user.school_name, status="done")
    if selected:
        query = query.filter_by(class_name=selected)
    preds = query.order_by(Prediction.predicted_at.desc()).all()

    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="previous",
                           classes=classes, selected=selected,
                           predictions=preds)


@principal_bp.route("/report/<int:pred_id>/download")
@login_required
@role_required("principal")
def download_report(pred_id):
    pred = Prediction.query.get_or_404(pred_id)
    # Verify the report belongs to this principal's school
    if pred.school_name != current_user().school_name:
        flash("Access denied.", "error")
        return redirect(url_for("principal.previous_reports"))

    rows = pred.result_data or []
    df   = pd.DataFrame(rows)
    buf  = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    filename = f"report_{pred.class_name}_{pred.predicted_at.strftime('%Y%m%d')}.csv"
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=filename)


@principal_bp.route("/school-report/download")
@login_required
@role_required("principal")
def download_school_report():
    """Download a merged CSV of all latest class predictions for this school."""
    user    = current_user()
    classes = get_school_classes(user.school_name)
    rows    = []
    for cls in classes:
        p = latest_pred_for_class(user.school_name, cls)
        if p and p.result_data:
            for r in p.result_data:
                r["class_name"] = cls
                rows.append(r)

    df  = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    from datetime import datetime
    fname = f"school_report_{user.school_name}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=fname)


# ── CONTACT ───────────────────────────────────────────────────

@principal_bp.route("/contact", methods=["GET", "POST"])
@login_required
@role_required("principal")
def contact():
    user = current_user()
    if request.method == "POST":
        flash("Your message has been sent. Thank you!", "success")
        return redirect(url_for("principal.contact"))
    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="contact")


# ── HELP ──────────────────────────────────────────────────────

@principal_bp.route("/help")
@login_required
@role_required("principal")
def help_page():
    user = current_user()
    return render_template("principal/principal_dashboard.html",
                           user=user, active_tab="help")


# ── API ENDPOINTS for accessing teacher reports ───────────────

@principal_bp.route("/api/teacher-reports/<int:school_id>", methods=["GET"])
@login_required
@role_required("principal")
def api_teacher_reports(school_id):
    """
    Get all teacher reports for this school.
    Returns list of current reports from all teachers.
    """
    user = current_user()
    
    # Get all teachers in this school
    teachers = Teacher.query.filter_by(school_name=user.school_name).all()
    
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
    
    return jsonify({"school_name": user.school_name, "reports": reports})


@principal_bp.route("/api/teacher-general-file/<int:teacher_id>/<class_name>", methods=["GET"])
@login_required
@role_required("principal")
def api_teacher_general_file(teacher_id, class_name):
    """
    Get general file (merged all versions) for a specific teacher.
    This allows principal to reference teacher's accumulated data.
    """
    user = current_user()
    teacher = Teacher.query.get_or_404(teacher_id)
    
    # Verify teacher belongs to this school
    if teacher.school_name != user.school_name:
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
    
    return jsonify({
        "teacher_id": teacher_id,
        "teacher_name": teacher.full_name,
        "class_name": class_name,
        "num_versions": len(files),
        "total_students": len(general),
        "columns": general.columns.tolist(),
        "data": general.to_dict(orient="records")
    })
