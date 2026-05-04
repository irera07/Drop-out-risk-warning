# models.py
# SQLAlchemy ORM models for the Dropout Prediction System
# Run: flask db init / flask db migrate / flask db upgrade
# Or:  db.create_all() inside app context for quick setup

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# ─────────────────────────────────────────────
# USER MODELS
# ─────────────────────────────────────────────

class Teacher(db.Model):
    __tablename__ = "teachers"

    id            = db.Column(db.Integer, primary_key=True)
    full_name     = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(150), nullable=False, unique=True)
    phone         = db.Column(db.String(20))
    sector        = db.Column(db.String(100), nullable=False)
    school_name   = db.Column(db.String(150), nullable=False)
    class_name    = db.Column(db.String(50),  nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    account_status = db.Column(db.Enum("pending", "active", "disabled"), nullable=False, default="pending")
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    files       = db.relationship("StudentFile", backref="teacher", lazy=True)
    predictions = db.relationship("Prediction",  backref="teacher", lazy=True)

    def to_dict(self):
        return {
            "id":          self.id,
            "full_name":   self.full_name,
            "email":       self.email,
            "phone":       self.phone,
            "sector":      self.sector,
            "school_name": self.school_name,
            "class_name":  self.class_name,
            "created_at":  self.created_at.isoformat(),
        }


class Principal(db.Model):
    __tablename__ = "principals"

    id            = db.Column(db.Integer, primary_key=True)
    full_name     = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(150), nullable=False, unique=True)
    phone         = db.Column(db.String(20))
    sector        = db.Column(db.String(100), nullable=False)
    school_name   = db.Column(db.String(150), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":          self.id,
            "full_name":   self.full_name,
            "email":       self.email,
            "phone":       self.phone,
            "sector":      self.sector,
            "school_name": self.school_name,
            "created_at":  self.created_at.isoformat(),
        }


class LocalLeader(db.Model):
    __tablename__ = "local_leaders"

    id            = db.Column(db.Integer, primary_key=True)
    full_name     = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(150), nullable=False, unique=True)
    phone         = db.Column(db.String(20))
    sector                = db.Column(db.String(100), nullable=False, unique=True)
    requested_school_name = db.Column(db.String(250), nullable=True)
    approved_school_names = db.Column(db.String(250), nullable=True)
    requested_class_name  = db.Column(db.String(50), nullable=True)
    access_status         = db.Column(db.Enum("pending", "approved", "denied"), nullable=False, default="pending")
    password_hash         = db.Column(db.String(255), nullable=False)
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":        self.id,
            "full_name": self.full_name,
            "email":     self.email,
            "phone":     self.phone,
            "sector":    self.sector,
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────
# STUDENT FILES
# ─────────────────────────────────────────────

class StudentFile(db.Model):
    __tablename__ = "student_files"

    id            = db.Column(db.Integer, primary_key=True)
    teacher_id    = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False)
    class_name    = db.Column(db.String(50),  nullable=False)
    school_name   = db.Column(db.String(150), nullable=False)
    sector        = db.Column(db.String(100), nullable=False)
    file_version  = db.Column(db.Integer, nullable=False, default=1)
    file_data     = db.Column(db.LargeBinary, nullable=False)   # raw bytes
    file_name     = db.Column(db.String(255), nullable=False)
    num_students  = db.Column(db.Integer)
    is_general    = db.Column(db.Boolean, nullable=False, default=False)
    uploaded_at   = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    predictions = db.relationship("Prediction", backref="source_file", lazy=True)

    def to_dict(self):
        return {
            "id":           self.id,
            "teacher_id":   self.teacher_id,
            "class_name":   self.class_name,
            "school_name":  self.school_name,
            "sector":       self.sector,
            "file_version": self.file_version,
            "file_name":    self.file_name,
            "num_students": self.num_students,
            "is_general":   self.is_general,
            "uploaded_at":  self.uploaded_at.isoformat(),
        }


# ─────────────────────────────────────────────
# PREDICTIONS
# ─────────────────────────────────────────────

class Prediction(db.Model):
    __tablename__ = "predictions"

    id             = db.Column(db.Integer, primary_key=True)
    file_id        = db.Column(db.Integer, db.ForeignKey("student_files.id"), nullable=False)
    teacher_id     = db.Column(db.Integer, db.ForeignKey("teachers.id"),      nullable=False)
    class_name     = db.Column(db.String(50),  nullable=False)
    school_name    = db.Column(db.String(150), nullable=False)
    sector         = db.Column(db.String(100), nullable=False)
    status         = db.Column(db.Enum("pending", "done"), nullable=False, default="pending")

    # Summary counters
    total_students = db.Column(db.Integer)
    dropout_count  = db.Column(db.Integer)
    non_dropout    = db.Column(db.Integer)
    high_risk      = db.Column(db.Integer)
    medium_risk    = db.Column(db.Integer)
    low_risk       = db.Column(db.Integer)
    male_count     = db.Column(db.Integer)
    female_count   = db.Column(db.Integer)

    # Full per-student results as JSON
    # Structure: [{"name": ..., "gender": ..., "class_level": ...,
    #              "risk_level": "high"|"medium"|"low",
    #              "dropout_predicted": true|false,
    #              "reason": "...", ...}, ...]
    result_data    = db.Column(db.JSON)

    predicted_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, include_results=False):
        d = {
            "id":             self.id,
            "file_id":        self.file_id,
            "teacher_id":     self.teacher_id,
            "class_name":     self.class_name,
            "school_name":    self.school_name,
            "sector":         self.sector,
            "status":         self.status,
            "total_students": self.total_students,
            "dropout_count":  self.dropout_count,
            "non_dropout":    self.non_dropout,
            "high_risk":      self.high_risk,
            "medium_risk":    self.medium_risk,
            "low_risk":       self.low_risk,
            "male_count":     self.male_count,
            "female_count":   self.female_count,
            "predicted_at":   self.predicted_at.isoformat(),
        }
        if include_results:
            d["result_data"] = self.result_data
        return d
