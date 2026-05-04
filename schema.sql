-- ============================================================
-- Dropout Prediction System — Database Schema
-- Engine: MySQL (localhost)
-- ============================================================

CREATE DATABASE IF NOT EXISTS dropout_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE dropout_db;

-- ------------------------------------------------------------
-- USER TABLES (one per role)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS teachers (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(100)  NOT NULL,
    email         VARCHAR(150)  NOT NULL UNIQUE,
    phone         VARCHAR(20),
    sector        VARCHAR(100)  NOT NULL,
    school_name   VARCHAR(150)  NOT NULL,
    class_name    VARCHAR(50)   NOT NULL,   -- e.g. "P3 A"
    password_hash VARCHAR(255)  NOT NULL,
    created_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS principals (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(100)  NOT NULL,
    email         VARCHAR(150)  NOT NULL UNIQUE,
    phone         VARCHAR(20),
    sector        VARCHAR(100)  NOT NULL,
    school_name   VARCHAR(150)  NOT NULL UNIQUE,
    password_hash VARCHAR(255)  NOT NULL,
    created_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS local_leaders (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(100)  NOT NULL,
    email         VARCHAR(150)  NOT NULL UNIQUE,
    phone         VARCHAR(20),
    sector        VARCHAR(100)  NOT NULL UNIQUE,  -- one leader per sector
    password_hash VARCHAR(255)  NOT NULL,
    created_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------
-- STUDENT FILES
-- Stores every file version submitted by a teacher.
-- is_general = TRUE means this is the merged/aggregated file
-- ready to be loaded into the ML model.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS student_files (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    teacher_id    INT           NOT NULL,
    class_name    VARCHAR(50)   NOT NULL,
    school_name   VARCHAR(150)  NOT NULL,
    sector        VARCHAR(100)  NOT NULL,
    file_version  INT           NOT NULL DEFAULT 1,
    file_data     LONGBLOB      NOT NULL,   -- raw CSV/Excel bytes
    file_name     VARCHAR(255)  NOT NULL,
    num_students  INT,
    is_general    BOOLEAN       NOT NULL DEFAULT FALSE,
    uploaded_at   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
    INDEX idx_sf_teacher    (teacher_id),
    INDEX idx_sf_class      (class_name),
    INDEX idx_sf_school     (school_name),
    INDEX idx_sf_sector     (sector),
    INDEX idx_sf_general    (is_general)
);

-- ------------------------------------------------------------
-- PREDICTIONS
-- One row per prediction run (triggered when teacher clicks
-- "Check updated report"). Stores both summary counters and
-- the full per-student result as JSON.
-- status: 'pending' while model is running, 'done' after.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS predictions (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    file_id         INT           NOT NULL,   -- the general file used
    teacher_id      INT           NOT NULL,
    class_name      VARCHAR(50)   NOT NULL,
    school_name     VARCHAR(150)  NOT NULL,
    sector          VARCHAR(100)  NOT NULL,
    status          ENUM('pending','done') NOT NULL DEFAULT 'pending',

    -- summary counters (populated after model runs)
    total_students  INT,
    dropout_count   INT,
    non_dropout     INT,
    high_risk       INT,
    medium_risk     INT,
    low_risk        INT,
    male_count      INT,
    female_count    INT,

    -- full per-student prediction results
    -- JSON array: [{name, gender, class_level, risk_level,
    --               dropout_predicted, reason, ...}, ...]
    result_data     JSON,

    predicted_at    TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (file_id)    REFERENCES student_files(id) ON DELETE CASCADE,
    FOREIGN KEY (teacher_id) REFERENCES teachers(id)      ON DELETE CASCADE,
    INDEX idx_pred_teacher   (teacher_id),
    INDEX idx_pred_class     (class_name),
    INDEX idx_pred_school    (school_name),
    INDEX idx_pred_sector    (sector),
    INDEX idx_pred_status    (status),
    INDEX idx_pred_date      (predicted_at)
);

-- ============================================================
-- USEFUL VIEWS (optional but handy for reports)
-- ============================================================

-- Latest prediction per class (used by teacher CurrentReport tab)
CREATE OR REPLACE VIEW v_latest_class_prediction AS
    SELECT p.*
    FROM predictions p
    INNER JOIN (
        SELECT class_name, school_name, MAX(predicted_at) AS max_date
        FROM predictions
        WHERE status = 'done'
        GROUP BY class_name, school_name
    ) latest
    ON  p.class_name   = latest.class_name
    AND p.school_name  = latest.school_name
    AND p.predicted_at = latest.max_date;

-- School summary: aggregate across all classes (used by principal)
CREATE OR REPLACE VIEW v_school_summary AS
    SELECT
        school_name,
        sector,
        COUNT(DISTINCT class_name)  AS num_classes,
        SUM(total_students)         AS total_students,
        SUM(dropout_count)          AS dropout_count,
        SUM(non_dropout)            AS non_dropout,
        SUM(high_risk)              AS high_risk,
        SUM(medium_risk)            AS medium_risk,
        SUM(low_risk)               AS low_risk,
        SUM(male_count)             AS male_count,
        SUM(female_count)           AS female_count,
        MAX(predicted_at)           AS last_updated
    FROM v_latest_class_prediction
    GROUP BY school_name, sector;

-- Sector summary: aggregate across all schools (used by local leader)
CREATE OR REPLACE VIEW v_sector_summary AS
    SELECT
        sector,
        COUNT(DISTINCT school_name) AS num_schools,
        SUM(total_students)         AS total_students,
        SUM(dropout_count)          AS dropout_count,
        SUM(non_dropout)            AS non_dropout,
        SUM(high_risk)              AS high_risk,
        SUM(medium_risk)            AS medium_risk,
        SUM(low_risk)               AS low_risk,
        SUM(male_count)             AS male_count,
        SUM(female_count)           AS female_count,
        MAX(last_updated)           AS last_updated
    FROM v_school_summary
    GROUP BY sector;
