# routes/teacher.py
# Teacher blueprint — handles all 6 tabs

import io
import json
import pandas as pd
from datetime import datetime
from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, session,
    jsonify, send_file
)
from models import db, StudentFile, Prediction
from utils import login_required, role_required, current_user

teacher_bp = Blueprint("teacher", __name__)


# ── helpers ───────────────────────────────────────────────────

def build_general_file(teacher_id, class_name):
    """
    Merge all file versions for this class using 70% weighting rule:
    weighted average = 70% latest file + 30% average of all previous files.
    Returns a DataFrame or None.
    """
    files = (StudentFile.query
             .filter_by(teacher_id=teacher_id, class_name=class_name, is_general=False)
             .order_by(StudentFile.uploaded_at.asc())
             .all())
    if not files:
        return None

    dfs = []
    for f in files:
        try:
            buf = io.BytesIO(f.file_data)
            df  = pd.read_csv(buf) if f.file_name.endswith(".csv") else pd.read_excel(buf)
            dfs.append(df)
        except Exception:
            continue

    if not dfs:
        return None
    if len(dfs) == 1:
        return dfs[0]

    # 70 % latest + 30 % mean of all previous
    latest   = dfs[-1]
    previous = dfs[:-1]
    num_cols = latest.select_dtypes(include="number").columns

    prev_mean = pd.concat(previous)[num_cols].mean()
    general   = latest.copy()
    general[num_cols] = (latest[num_cols] * 0.7) + (prev_mean * 0.3)
    
    return general


# ── HOME ──────────────────────────────────────────────────────

@teacher_bp.route("/home")
@login_required
@role_required("teacher")
def home():
    user = current_user()
    return render_template("teacher/dashboard.html",
                           user=user, active_tab="home")


# ── DAILY CHECKING ────────────────────────────────────────────

@teacher_bp.route("/daily-checking", methods=["GET"])
@login_required
@role_required("teacher")
def daily_checking():
    user  = current_user()
    # Load the most recent file for this class to display
    latest = (StudentFile.query
              .filter_by(teacher_id=user.id, class_name=user.class_name, is_general=False)
              .order_by(StudentFile.uploaded_at.desc())
              .first())

    students = []
    columns  = []
    if latest:
        try:
            buf = io.BytesIO(latest.file_data)
            df  = pd.read_csv(buf) if latest.file_name.endswith(".csv") else pd.read_excel(buf)
            columns  = df.columns.tolist()
            students = df.to_dict(orient="records")
        except Exception:
            flash("Could not parse the stored file.", "error")

    return render_template("teacher/dashboard.html",
                           user=user, active_tab="daily",
                           students=students, columns=columns,
                           latest_file=latest)


@teacher_bp.route("/upload", methods=["POST"])
@login_required
@role_required("teacher")
def upload_file():
    user = current_user()
    f    = request.files.get("student_file")
    if not f or f.filename == "":
        flash("Please select a file to upload.", "error")
        return redirect(url_for("teacher.daily_checking"))

    allowed = {".csv", ".xlsx", ".xls"}
    ext = "." + f.filename.rsplit(".", 1)[-1].lower()
    if ext not in allowed:
        flash("Only CSV and Excel files are accepted.", "error")
        return redirect(url_for("teacher.daily_checking"))

    raw = f.read()

    # Count rows
    try:
        buf = io.BytesIO(raw)
        df  = pd.read_csv(buf) if ext == ".csv" else pd.read_excel(buf)
        num = len(df)
    except Exception:
        flash("Could not read the file. Check the format.", "error")
        return redirect(url_for("teacher.daily_checking"))

    # Get next version number
    last = (StudentFile.query
            .filter_by(teacher_id=user.id, class_name=user.class_name)
            .order_by(StudentFile.file_version.desc())
            .first())
    version = (last.file_version + 1) if last else 1

    record = StudentFile(
        teacher_id   = user.id,
        class_name   = user.class_name,
        school_name  = user.school_name,
        sector       = user.sector,
        file_version = version,
        file_data    = raw,
        file_name    = f.filename,
        num_students = num,
        is_general   = False,
    )
    db.session.add(record)
    db.session.commit()
    flash(f"File uploaded ({num} students, version {version}).", "success")
    return redirect(url_for("teacher.daily_checking"))


@teacher_bp.route("/update-student", methods=["POST"])
@login_required
@role_required("teacher")
def update_student():
    """Save inline edits to the current file as a new version."""
    user     = current_user()
    data     = request.get_json()
    students = data.get("students", [])

    if not students:
        return jsonify({"ok": False, "msg": "No data received."})

    df  = pd.DataFrame(students)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    raw = buf.getvalue()

    last = (StudentFile.query
            .filter_by(teacher_id=user.id, class_name=user.class_name)
            .order_by(StudentFile.file_version.desc())
            .first())
    version = (last.file_version + 1) if last else 1

    record = StudentFile(
        teacher_id=user.id, class_name=user.class_name,
        school_name=user.school_name, sector=user.sector,
        file_version=version, file_data=raw,
        file_name=f"modified_v{version}.csv",
        num_students=len(df), is_general=False,
    )
    db.session.add(record)
    db.session.commit()
    return jsonify({"ok": True, "msg": f"Saved as version {version}."})


@teacher_bp.route("/add-student", methods=["POST"])
@login_required
@role_required("teacher")
def add_student():
    """Append a new student row to the latest file."""
    user       = current_user()
    new_student = request.get_json()

    latest = (StudentFile.query
              .filter_by(teacher_id=user.id, class_name=user.class_name, is_general=False)
              .order_by(StudentFile.uploaded_at.desc())
              .first())

    if latest:
        buf = io.BytesIO(latest.file_data)
        df  = pd.read_csv(buf) if latest.file_name.endswith(".csv") else pd.read_excel(buf)
        new_row = pd.DataFrame([new_student])
        df = pd.concat([df, new_row], ignore_index=True)
    else:
        df = pd.DataFrame([new_student])

    buf2 = io.BytesIO()
    df.to_csv(buf2, index=False)
    raw = buf2.getvalue()

    last = (StudentFile.query
            .filter_by(teacher_id=user.id, class_name=user.class_name)
            .order_by(StudentFile.file_version.desc())
            .first())
    version = (last.file_version + 1) if last else 1

    record = StudentFile(
        teacher_id=user.id, class_name=user.class_name,
        school_name=user.school_name, sector=user.sector,
        file_version=version, file_data=raw,
        file_name=f"modified_v{version}.csv",
        num_students=len(df), is_general=False,
    )
    db.session.add(record)
    db.session.commit()
    return jsonify({"ok": True, "student": new_student})

@teacher_bp.route("/delete-all-students", methods=["POST"])
@login_required
@role_required("teacher")
def delete_all_students():
    user = current_user()
    files = StudentFile.query.filter_by(
        teacher_id=user.id,
        class_name=user.class_name,
        is_general=False
    ).all()
    if not files:
        flash("No student table found to delete.", "warning")
        return redirect(url_for("teacher.daily_checking"))

    for f in files:
        db.session.delete(f)
    db.session.commit()

    flash("Deleted existing student table. Upload a new file.", "success")
    return redirect(url_for("teacher.daily_checking"))


@teacher_bp.route("/delete-student", methods=["POST"])
@login_required
@role_required("teacher")
def delete_student():
    user = current_user()
    data = request.get_json() or {}
    idx = data.get("index")
    if idx is None:
        return jsonify({"ok": False, "msg": "Missing row index."})

    try:
        idx = int(idx)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "msg": "Invalid row index."})

    latest = (StudentFile.query
              .filter_by(teacher_id=user.id, class_name=user.class_name, is_general=False)
              .order_by(StudentFile.uploaded_at.desc())
              .first())
    if not latest:
        return jsonify({"ok": False, "msg": "No student file available."})

    try:
        buf = io.BytesIO(latest.file_data)
        df = pd.read_csv(buf) if latest.file_name.endswith(".csv") else pd.read_excel(buf)
        if idx < 0 or idx >= len(df):
            return jsonify({"ok": False, "msg": "Row index out of bounds."})

        df = df.drop(df.index[idx]).reset_index(drop=True)

        last = (StudentFile.query
                .filter_by(teacher_id=user.id, class_name=user.class_name)
                .order_by(StudentFile.file_version.desc())
                .first())
        version = (last.file_version + 1) if last else 1

        buf2 = io.BytesIO()
        df.to_csv(buf2, index=False)
        record = StudentFile(
            teacher_id=user.id,
            class_name=user.class_name,
            school_name=user.school_name,
            sector=user.sector,
            file_version=version,
            file_data=buf2.getvalue(),
            file_name=f"modified_v{version}.csv",
            num_students=len(df),
            is_general=False,
        )
        db.session.add(record)
        db.session.commit()

        return jsonify({"ok": True, "msg": "Student removed and table saved."})

    except Exception as e:
        return jsonify({"ok": False, "msg": f"Error removing student: {str(e)}"})

# ── CURRENT REPORT ────────────────────────────────────────────

@teacher_bp.route("/current-report", methods=["GET"])
@login_required
@role_required("teacher")
def current_report():
    user = current_user()
    # Fetch the latest completed prediction for this class
    pred = (Prediction.query
            .filter_by(teacher_id=user.id, class_name=user.class_name, status="done")
            .order_by(Prediction.predicted_at.desc())
            .first())
    return render_template("teacher/dashboard.html",
                           user=user, active_tab="current",
                           prediction=pred)


@teacher_bp.route("/run-prediction", methods=["POST"])
@login_required
@role_required("teacher")
def run_prediction_route():
    user = current_user()

    # Build general file
    general_df = build_general_file(user.id, user.class_name)
    if general_df is None:
        flash("No student files found. Please upload data first.", "error")
        return redirect(url_for("teacher.current_report"))

    # Save general file record
    buf = io.BytesIO()
    general_df.to_csv(buf, index=False)
    raw = buf.getvalue()
    gen_file = StudentFile(
        teacher_id=user.id, class_name=user.class_name,
        school_name=user.school_name, sector=user.sector,
        file_version=0, file_data=raw,
        file_name="general.csv",
        num_students=len(general_df), is_general=True,
    )
    db.session.add(gen_file)
    db.session.flush()

    # Create pending prediction record
    pred = Prediction(
        file_id=gen_file.id, teacher_id=user.id,
        class_name=user.class_name, school_name=user.school_name,
        sector=user.sector, status="pending",
    )
    db.session.add(pred)
    db.session.commit()

    # Run model (import from app.py)
    try:
        from model.predictor import predict_dataframe as run_prediction
        
        # Convert Yes/No to 1/0 for numeric columns
        numeric_cols = [
            "Lack_of_School_Material", "Lack_of_School_Fees", "Job_opportunity",
            "Pregnancy", "Family_conflicts", "Drug_abuse", "Lack_of_motivation",
            "Illness", "Absenteism", "Bad_Discipline"
        ]
        for col in numeric_cols:
            if col in general_df.columns:
                general_df[col] = general_df[col].map({"Yes": 1, "No": 0})
        
        results, summary = run_prediction(general_df)
        pred.result_data    = results
        pred.status         = "done"
        pred.total_students = summary["total_students"]
        pred.dropout_count  = summary["dropout_count"]
        pred.non_dropout    = summary["non_dropout"]
        pred.high_risk      = summary["high_risk"]
        pred.medium_risk    = summary["medium_risk"]
        pred.low_risk       = summary["low_risk"]
        pred.male_count     = summary["male_count"]
        pred.female_count   = summary["female_count"]
        pred.predicted_at   = datetime.utcnow()
        db.session.commit()
        flash("Report generated successfully.", "success")
    except Exception as e:
        pred.status = "done"   # mark done even on error so it doesn't hang
        db.session.commit()
        flash(f"Prediction error: {str(e)}", "error")

    return redirect(url_for("teacher.current_report"))


# ── PREVIOUS REPORTS ──────────────────────────────────────────

@teacher_bp.route("/previous-reports")
@login_required
@role_required("teacher")
def previous_reports():
    user  = current_user()
    preds = (Prediction.query
             .filter_by(teacher_id=user.id, class_name=user.class_name, status="done")
             .order_by(Prediction.predicted_at.desc())
             .all())
    return render_template("teacher/dashboard.html",
                           user=user, active_tab="previous",
                           predictions=preds)


@teacher_bp.route("/get-report-data/<int:pred_id>")
@login_required
@role_required("teacher")
def get_report_data(pred_id):
    pred = Prediction.query.get_or_404(pred_id)
    if pred.teacher_id != current_user().id:
        return jsonify({"error": "Access denied"}), 403
    return jsonify(pred.result_data or [])


@teacher_bp.route("/delete-report/<int:pred_id>", methods=["POST"])
@login_required
@role_required("teacher")
def delete_report(pred_id):
    pred = Prediction.query.get_or_404(pred_id)
    if pred.teacher_id != current_user().id:
        flash("Access denied.", "error")
        return redirect(url_for("teacher.previous_reports"))

    db.session.delete(pred)
    db.session.commit()
    flash("Report deleted successfully.", "success")
    return redirect(url_for("teacher.previous_reports"))


@teacher_bp.route("/report/<int:pred_id>/download")
@login_required
@role_required("teacher")
def download_report(pred_id):
    pred = Prediction.query.get_or_404(pred_id)
    if pred.teacher_id != current_user().id:
        flash("Access denied.", "error")
        return redirect(url_for("teacher.previous_reports"))

    rows = pred.result_data or []
    df   = pd.DataFrame(rows)
    buf  = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    filename = f"report_{pred.class_name}_{pred.predicted_at.strftime('%Y%m%d')}.csv"
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=filename)


# ── CONTACT ───────────────────────────────────────────────────

@teacher_bp.route("/contact", methods=["GET", "POST"])
@login_required
@role_required("teacher")
def contact():
    user = current_user()
    if request.method == "POST":
        # In production: save to DB or send email
        flash("Your message has been sent. Thank you!", "success")
        return redirect(url_for("teacher.contact"))
    return render_template("teacher/dashboard.html",
                           user=user, active_tab="contact")


# ── HELP ──────────────────────────────────────────────────────

@teacher_bp.route("/help")
@login_required
@role_required("teacher")
def help_page():
    user = current_user()
    return render_template("teacher/dashboard.html",
                           user=user, active_tab="help")


# ── API ENDPOINTS for reports (accessible to other users) ─────

@teacher_bp.route("/api/current-report")
@login_required
@role_required("teacher")
def api_current_report():
    """Get current report data for the logged-in teacher (cached from model)."""
    user = current_user()
    pred = (Prediction.query
            .filter_by(teacher_id=user.id, class_name=user.class_name, status="done")
            .order_by(Prediction.predicted_at.desc())
            .first())
    if not pred:
        return jsonify({"error": "No report available"}), 404
    return jsonify({
        "id": pred.id,
        "class_name": pred.class_name,
        "school_name": pred.school_name,
        "sector": pred.sector,
        "teacher_id": pred.teacher_id,
        "total_students": pred.total_students,
        "dropout_count": pred.dropout_count,
        "non_dropout": pred.non_dropout,
        "high_risk": pred.high_risk,
        "medium_risk": pred.medium_risk,
        "low_risk": pred.low_risk,
        "male_count": pred.male_count,
        "female_count": pred.female_count,
        "predicted_at": pred.predicted_at.isoformat(),
        "result_data": pred.result_data or []
    })


@teacher_bp.route("/api/general-file/<int:teacher_id>/<class_name>")
def api_get_general_file(teacher_id, class_name):
    """
    Get general file (merged versions) for a specific teacher class.
    Loads all versions into model and returns merged data.
    Accessible to principal/leader for reference to teachers.
    """
    # Get all file versions for this teacher/class
    files = (StudentFile.query
             .filter_by(teacher_id=teacher_id, class_name=class_name, is_general=False)
             .order_by(StudentFile.uploaded_at.asc())
             .all())
    
    if not files:
        return jsonify({"error": "No student files found"}), 404
    
    # Build general file from all versions (70% latest + 30% average)
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
    
    # Return as JSON
    return jsonify({
        "teacher_id": teacher_id,
        "class_name": class_name,
        "num_versions": len(files),
        "total_students": len(general),
        "columns": general.columns.tolist(),
        "data": general.to_dict(orient="records")
    })


@teacher_bp.route("/api/file-versions/<int:teacher_id>/<class_name>")
def api_file_versions(teacher_id, class_name):
    """
    Get metadata for all file versions for a teacher/class.
    Accessible to principal/leader for reference.
    """
    files = (StudentFile.query
             .filter_by(teacher_id=teacher_id, class_name=class_name, is_general=False)
             .order_by(StudentFile.file_version.asc())
             .all())
    
    return jsonify({
        "teacher_id": teacher_id,
        "class_name": class_name,
        "versions": [
            {
                "file_id": f.id,
                "version": f.file_version,
                "file_name": f.file_name,
                "num_students": f.num_students,
                "uploaded_at": f.uploaded_at.isoformat()
            }
            for f in files
        ]
    })
