from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
import pandas as pd
import os
import random
import csv
import json
import ast
import math
import hmac
import hashlib
from datetime import datetime
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from scheme_recommender import ml_recommend_schemes
from auth_decorators import student_required

# ReportLab for PDF resume generation
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

# HMAC secret for proctor token signing (loaded from env or fallback)
PROCTOR_SECRET = os.environ.get("PROCTOR_HMAC_SECRET", "proctor_signing_secret_2025_yH7nW2kR")
DEFAULT_PASSWORD = "helloeveryone"

student_bp = Blueprint("student", __name__)

# Paths resolved relative to the main project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CERT_UPLOAD_DIR = os.path.join(DATA_DIR, "certificates")
RESUME_DIR = os.path.join(DATA_DIR, "resumes")
CERT_CSV = os.path.join(DATA_DIR, "certificates.csv")
MASTER_CSV = os.path.join(DATA_DIR, "master_students.csv")
COMPANY_DRIVES = os.path.join(DATA_DIR, "company_drives.csv")
TESTS_DIR = os.path.join(DATA_DIR, "tests")
RESULTS_CSV = os.path.join(DATA_DIR, "test_results.csv")

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CERT_UPLOAD_DIR, exist_ok=True)
os.makedirs(RESUME_DIR, exist_ok=True)
os.makedirs(TESTS_DIR, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _db_ok():
    try:
        from models import Student, db
        db.session.execute(db.select(Student).limit(1))
        return True
    except Exception:
        return False


def load_students():
    """Return all active students as a DataFrame."""
    if _db_ok():
        from utils import read_master_df
        df = read_master_df()
        if not df.empty and "Register_Number" in df.columns:
            df["Register_Number"] = df["Register_Number"].astype(str)
        return df
    # Fallback: CSV
    if not os.path.exists(MASTER_CSV):
        return pd.DataFrame()
    df = pd.read_csv(MASTER_CSV)
    df["Register_Number"] = df["Register_Number"].astype(str)
    if "Password" not in df.columns:
        df["Password"] = "helloeveryone"
        df.to_csv(MASTER_CSV, index=False)
    return df


def load_company_drives():
    """Return all drives as a DataFrame."""
    if _db_ok():
        from models import Drive
        rows = [{
            "drive_id": d.drive_id, "hr_email": d.hr_email,
            "company_name": d.company_name, "position": d.position,
            "package": d.package, "time_period": d.time_period,
            "number_required": d.number_required, "min_cgpa": d.min_cgpa,
            "domain_required": d.domain_required, "description": d.description,
            "mode": d.mode, "location": d.location,
            "end_date": d.end_date, "created_at": d.created_at,
        } for d in Drive.query.all()]
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    if os.path.exists(COMPANY_DRIVES):
        return pd.read_csv(COMPANY_DRIVES)
    return pd.DataFrame()


def has_attempted_test(reg_no, drive_index, round_name):
    """Return True if the student already submitted this round."""
    if _db_ok():
        from models import TestResult
        return TestResult.query.filter_by(
            register_number=reg_no,
            drive_index=int(drive_index),
            round=round_name
        ).first() is not None
    # Fallback: CSV
    if not os.path.exists(RESULTS_CSV):
        return False
    df = pd.read_csv(RESULTS_CSV)
    match = df[
        (df["register_number"] == reg_no) &
        (df["drive_index"] == drive_index) &
        (df["round"] == round_name)
    ]
    return not match.empty


def save_to_results_row(row):
    """Persist a test result row to the DB (and mirror to CSV)."""
    if _db_ok():
        from models import TestResult, db
        def fv(k): v = row.get(k, 0); return float(v) if v else 0
        def iv(k): v = row.get(k, 0); return int(float(v)) if v else 0
        obj = TestResult(
            register_number = str(row.get("register_number", "")),
            drive_index     = iv("drive_index"),
            round           = str(row.get("round", "")),
            score           = fv("score"),
            total           = iv("total"),
            attempted       = iv("attempted"),
            correct         = iv("correct"),
            wrong           = iv("wrong"),
            marks_correct   = fv("marks_correct"),
            marks_wrong     = fv("marks_wrong"),
            cheated         = iv("cheated"),
            submitted_at    = str(row.get("submitted_at", "")),
        )
        db.session.add(obj)
        db.session.commit()
    # Mirror to CSV
    headers = [
        "register_number", "drive_index", "round", "score", "total",
        "attempted", "correct", "wrong", "marks_correct", "marks_wrong",
        "cheated", "submitted_at"
    ]
    file_exists = os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)



def read_test_file(filename, desired_count=60):
    path = os.path.join(TESTS_DIR, filename)
    if not os.path.exists(path):
        return []

    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]

    category_col = None
    for candidate in ("Category", "Topic", "category", "topic"):
        if candidate in df.columns:
            category_col = candidate
            break

    all_questions = []

    def build_question_from_row(r):
        q_text = str(r.get("Question", "")).strip()
        options = [
            str(r.get("OptionA", "")).strip(),
            str(r.get("OptionB", "")).strip(),
            str(r.get("OptionC", "")).strip(),
            str(r.get("OptionD", "")).strip(),
        ]
        correct_ans = str(r.get("Answer", "")).strip()
        correct_index = None
        if correct_ans.upper() in ["A", "B", "C", "D"]:
            try:
                correct_index = ord(correct_ans.upper()) - ord("A")
            except Exception:
                correct_index = None
        if correct_index is None:
            try:
                correct_index = options.index(correct_ans)
            except Exception:
                correct_index = 0

        correct_text = options[correct_index] if 0 <= correct_index < len(options) else options[0]
        shuffled = options.copy()
        random.shuffle(shuffled)
        try:
            new_correct_index = shuffled.index(correct_text)
        except ValueError:
            new_correct_index = 0

        return {"q": q_text, "options": shuffled, "answer_index": new_correct_index}

    if category_col is None:
        for _, r in df.iterrows():
            all_questions.append(build_question_from_row(r))
        random.shuffle(all_questions)
        return all_questions[:min(desired_count, len(all_questions))]

    topic_groups = {}
    for idx, r in df.iterrows():
        topic = str(r.get(category_col, "")).strip()
        if topic == "" or topic.lower() == "nan":
            topic = "Unspecified"
        topic_groups.setdefault(topic, []).append(r)

    topic_counts = {t: len(lst) for t, lst in topic_groups.items()}
    total_questions_available = sum(topic_counts.values())
    if total_questions_available == 0:
        return []

    if desired_count >= total_questions_available:
        for t, rows in topic_groups.items():
            for r in rows:
                all_questions.append(build_question_from_row(r))
        random.shuffle(all_questions)
        return all_questions

    ideal = {t: (cnt / total_questions_available) * desired_count for t, cnt in topic_counts.items()}
    quotas = {}
    for t, val in ideal.items():
        q = max(1, int(math.floor(val)))
        q = min(q, topic_counts[t])
        quotas[t] = q

    assigned = sum(quotas.values())
    remaining = desired_count - assigned
    frac_parts = sorted([(val - math.floor(val), t) for t, val in ideal.items()], reverse=True)

    i = 0
    while remaining > 0 and i < len(frac_parts):
        _, t = frac_parts[i]
        if quotas[t] < topic_counts[t]:
            quotas[t] += 1
            remaining -= 1
        i += 1
        if i == len(frac_parts) and remaining > 0:
            for t2 in topic_counts:
                if remaining == 0:
                    break
                if quotas[t2] < topic_counts[t2]:
                    quotas[t2] += 1
                    remaining -= 1

    while sum(quotas.values()) > desired_count:
        candidates = [t for t, q in quotas.items() if q > 1]
        if not candidates:
            break
        tmax = max(candidates, key=lambda x: quotas[x])
        quotas[tmax] -= 1

    selected_questions = []
    for t, q in quotas.items():
        rows = topic_groups[t].copy()
        chosen = rows if q >= len(rows) else random.sample(rows, q)
        for r in chosen:
            selected_questions.append(build_question_from_row(r))

    random.shuffle(selected_questions)
    return selected_questions


# -----------------------------------------------
# CERTIFICATE UPLOAD
# -----------------------------------------------

@student_bp.route("/upload_certificate", methods=["GET", "POST"])
@student_required
def upload_certificate():
    reg_no = session["student_reg_no"]
    df = load_students()
    student = df[df["Register_Number"] == reg_no].iloc[0]

    if request.method == "POST":
        cert_name = request.form.get("certificate_name", "").strip()
        file = request.files.get("certificate")

        if not cert_name or not file:
            flash("All fields are required")
            return redirect(request.url)

        filename = f"{reg_no}_{int(datetime.now().timestamp())}_{file.filename}"
        save_path = os.path.join(CERT_UPLOAD_DIR, filename)
        file.save(save_path)

        cert_id_str = None

        # ── DB write ──────────────────────────────────────────────────────
        try:
            from models import Certificate, db
            db.session.execute(db.select(Certificate).limit(1))  # probe
            # generate a unique cert ID
            max_row = db.session.execute(
                db.select(db.func.max(Certificate.certificate_id))
            ).scalar()
            new_id = str(int(max_row) + 1) if max_row and str(max_row).isdigit() else "1"
            cert_id_str = new_id
            db.session.add(Certificate(
                certificate_id   = new_id,
                register_number  = reg_no,
                student_name     = student["Student_Name"],
                certificate_name = cert_name,
                file_path        = filename,
                status           = "pending",
                uploaded_at      = datetime.now().strftime("%Y-%m-%d %H:%M"),
                reviewed_by      = "",
                reviewed_at      = "",
                remarks          = "",
            ))
            db.session.commit()
        except Exception:
            pass

        # ── CSV mirror ────────────────────────────────────────────────────
        if os.path.exists(CERT_CSV):
            cert_df = pd.read_csv(CERT_CSV)
        else:
            cert_df = pd.DataFrame(columns=[
                "certificate_id", "register_number", "student_name",
                "certificate_name", "file_path", "status", "uploaded_at",
                "reviewed_by", "reviewed_at", "remarks"
            ])

        new_cert_id = cert_id_str or str(len(cert_df) + 1)
        cert_df.loc[len(cert_df)] = {
            "certificate_id":   new_cert_id,
            "register_number":  reg_no,
            "student_name":     student["Student_Name"],
            "certificate_name": cert_name,
            "file_path":        filename,
            "status":           "pending",
            "uploaded_at":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            "reviewed_by":      "",
            "reviewed_at":      "",
            "remarks":          ""
        }
        cert_df.to_csv(CERT_CSV, index=False)

        flash("Certificate submitted for admin approval")
        return redirect(url_for("student.dashboard"))

    return render_template("student_upload_certificate.html")


# -----------------------------------------------
# RESUME UPLOAD
# -----------------------------------------------

@student_bp.route("/upload_resume", methods=["GET", "POST"])
@student_required
def upload_resume():
    reg_no = session["student_reg_no"]

    if request.method == "POST":
        file = request.files.get("resume")
        if not file:
            flash("Please select a resume file.")
            return redirect(request.url)

        filename = secure_filename(f"{reg_no}_resume_{file.filename}")
        save_path = os.path.join(RESUME_DIR, filename)
        file.save(save_path)
        flash("Resume uploaded successfully.")
        return redirect(url_for("student.dashboard"))

    return render_template("student_upload_resume.html")


# -----------------------------------------------
# STUDENT CERTIFICATES VIEW
# -----------------------------------------------

@student_bp.route("/certificates")
@student_required
def student_certificates():
    if not os.path.exists(CERT_CSV):
        return render_template("student_certificates.html", certs=[])

    df = pd.read_csv(CERT_CSV)
    certs = df[
        (df["register_number"] == session["student_reg_no"]) &
        (df["status"] == "approved")
    ]
    return render_template("student_certificates.html", certs=certs.to_dict(orient="records"))


@student_bp.route("/certificates/view/<path:filename>")
@student_required
def view_certificate_file(filename):
    file_path = os.path.join(CERT_UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        return "File not found", 404
    return send_file(file_path)


# -----------------------------------------------
# AUTH
# -----------------------------------------------

@student_bp.route("/", methods=["GET", "POST"])
@student_bp.route("/login", methods=["GET", "POST"])
def login():
    if "student_reg_no" in session:
        return redirect(url_for("student.dashboard"))

    if request.method == "POST":
        reg_no = request.form["register_number"].strip()
        password = request.form["password"].strip()

        df = load_students()

        if df.empty:
            flash("No student records found.")
            return redirect(url_for("student.login"))

        df["Register_Number"] = df["Register_Number"].astype(str).str.strip()
        if "Password" not in df.columns:
            df["Password"] = DEFAULT_PASSWORD
            df.to_csv(MASTER_CSV, index=False)

        df["Password"] = df["Password"].astype(str).str.strip()
        student = df[df["Register_Number"] == reg_no]

        if student.empty:
            flash("Invalid Register Number.")
            return redirect(url_for("student.login"))

        stored_password = student.iloc[0]["Password"]

        # First-login flow: default plain-text password triggers forced reset
        if stored_password == DEFAULT_PASSWORD:
            if password == DEFAULT_PASSWORD:
                session["temp_student"] = reg_no
                return redirect(url_for("student.create_password"))
            else:
                flash("You must enter the default password 'helloeveryone' for your first login.")
                return redirect(url_for("student.login"))

        # Hashed password check (post-reset)
        if stored_password.startswith("pbkdf2:") or stored_password.startswith("scrypt:"):
            if check_password_hash(stored_password, password):
                session["student_reg_no"] = reg_no
                return redirect(url_for("student.dashboard"))
            else:
                flash("Incorrect password.")
                return redirect(url_for("student.login"))

        # Legacy plain-text password: auto-migrate to hash on successful login
        if password == stored_password:
            hashed = generate_password_hash(password)
            df.loc[df["Register_Number"] == reg_no, "Password"] = hashed
            df.to_csv(MASTER_CSV, index=False)
            session["student_reg_no"] = reg_no
            return redirect(url_for("student.dashboard"))
        else:
            flash("Incorrect password.")
            return redirect(url_for("student.login"))

    return render_template("student_login.html")


@student_bp.route("/create_password", methods=["GET", "POST"])
def create_password():
    if "temp_student" not in session:
        return redirect(url_for("student.login"))

    reg_no = session["temp_student"]

    if request.method == "POST":
        new_password = request.form["new_password"].strip()
        if len(new_password) < 6:
            flash("Password must be at least 6 characters.")
            return redirect(request.url)
        # Store securely as a hash — never plain text
        hashed = generate_password_hash(new_password)
        df = load_students()
        df.loc[df["Register_Number"].astype(str).str.strip() == reg_no, "Password"] = hashed
        df.to_csv(MASTER_CSV, index=False)
        session["student_reg_no"] = reg_no
        session.pop("temp_student", None)
        return redirect(url_for("student.dashboard"))

    return render_template("create_password.html")


@student_bp.route("/logout")
def logout():
    session.pop("student_reg_no", None)
    return redirect(url_for("student.login"))


# -----------------------------------------------
# STUDENT DASHBOARD & WEAKNESS EVALUATOR
# -----------------------------------------------

def get_student_weaknesses(student):
    weaknesses = []
    # Map common subjects (lowercase keywords) to course names and reference URLs
    subject_map = {
        "machine learning": ("Stanford Machine Learning (Coursera)", "https://www.coursera.org/specializations/machine-learning-introduction"),
        "deep learning": ("DeepLearning.AI Specialization (Coursera)", "https://www.coursera.org/specializations/deep-learning"),
        "neural networks": ("Neural Networks and Deep Learning", "https://www.coursera.org/learn/neural-networks-deep-learning"),
        "artificial intelligence": ("AI for Everyone (Coursera)", "https://www.coursera.org/learn/ai-for-everyone"),
        "web technology": ("Responsive Web Design (freeCodeCamp)", "https://www.freecodecamp.org/learn/2022/responsive-web-design/"),
        "internet programming": ("Modern JavaScript (MDN Web Docs)", "https://developer.mozilla.org/en-US/docs/Web/JavaScript"),
        "dbms": ("SQL Bootcamp (Udemy)", "https://www.udemy.com/course/the-complete-sql-bootcamp/"),
        "database": ("Introduction to Databases (Coursera)", "https://www.coursera.org/learn/database-management"),
        "computer networks": ("Computer Networking (Udacity)", "https://www.udacity.com/course/computer-networking--ud818"),
        "network security": ("CompTIA Security+ Prep (Udemy)", "https://www.udemy.com/course/comptia-security-certification-sy0-601-the-total-course/"),
        "operating systems": ("Operating Systems Introduction (GeeksforGeeks)", "https://www.geeksforgeeks.org/operating-systems/"),
        "data structures": ("Data Structures and Algorithms Specialization", "https://www.coursera.org/specializations/data-structures-algorithms"),
        "algorithms": ("Algorithms Specialization by Stanford (Coursera)", "https://www.coursera.org/specializations/algorithms"),
        "oops": ("Object Oriented Programming in Java (Coursera)", "https://www.coursera.org/learn/object-oriented-java"),
        "cloud computing": ("AWS Certified Cloud Practitioner Study Path", "https://aws.amazon.com/certification/certified-cloud-practitioner/"),
        "iot": ("Introduction to IoT (Cisco Networking Academy)", "https://www.netacad.com/courses/iot/introduction-iot"),
        "embedded systems": ("Introduction to Embedded Systems (Coursera)", "https://www.coursera.org/learn/introduction-embedded-systems"),
        "python": ("Python for Everybody (Coursera)", "https://www.coursera.org/specializations/python-for-everybody"),
        "java": ("Java Programming Masterclass (Udemy)", "https://www.udemy.com/course/java-the-complete-java-developer-course/"),
        "c++": ("C++ Programming Beg-to-Adv (Udemy)", "https://www.udemy.com/course/free-c-tutorial-for-beginners/")
    }

    for sem in range(1, 9):
        subjects = student.get(f"Sem{sem}_Subjects", [])
        ia1_list = student.get(f"Sem{sem}_IA1", [])
        ia2_list = student.get(f"Sem{sem}_IA2", [])
        model_list = student.get(f"Sem{sem}_Model", [])

        if not isinstance(subjects, list) or not subjects:
            continue

        for i, sub in enumerate(subjects):
            sub_name = str(sub).strip()
            if not sub_name or sub_name.lower() == "nan":
                continue

            try:
                ia1 = float(ia1_list[i]) if i < len(ia1_list) else 0.0
            except:
                ia1 = 0.0
            try:
                ia2 = float(ia2_list[i]) if i < len(ia2_list) else 0.0
            except:
                ia2 = 0.0
            try:
                model = float(model_list[i]) if i < len(model_list) else 0.0
            except:
                model = 0.0

            # Calculate average percentage of marks
            ia1_pct = (ia1 / 20.0) * 100.0
            ia2_pct = (ia2 / 20.0) * 100.0
            model_pct = (model / 100.0) * 100.0
            avg_pct = round((ia1_pct + ia2_pct + model_pct) / 3.0, 2)

            # Mark as weakness if average score is below placement standard (70%)
            if avg_pct < 70.0:
                matched_val = ("NPTEL / GeeksforGeeks Reference Guide", "https://www.geeksforgeeks.org/")
                sub_lower = sub_name.lower()
                for key, val in subject_map.items():
                    if key in sub_lower:
                        matched_val = val
                        break
                
                weaknesses.append({
                    "subject": sub_name,
                    "avg_percentage": avg_pct,
                    "semester": f"Sem {sem}",
                    "course_name": matched_val[0],
                    "course_link": matched_val[1]
                })

    return weaknesses

@student_bp.route("/dashboard")
@student_required
def dashboard():
    reg_no = session["student_reg_no"]
    df = load_students()

    student_df = df[df["Register_Number"] == reg_no]
    if student_df.empty:
        flash("Your profile was removed by admin.")
        return redirect(url_for("student.login"))

    student = student_df.to_dict(orient="records")[0]
    # Clean NaN values to None so Jinja's "or" fallback works properly
    for k, v in list(student.items()):
        if isinstance(v, float) and pd.isna(v):
            student[k] = None

    for col in df.columns:
        if col.startswith("Sem") and col.endswith("_GPA"):
            sem = col.split("_")[0]
            for key in ["Subjects", "IA1", "IA2", "Model", "Grades"]:
                full_key = f"{sem}_{key}"
                value = student.get(full_key, "")
                if pd.isna(value) or value == "":
                    student[full_key] = []
                else:
                    student[full_key] = str(value).split(",")

    schemes_all = ml_recommend_schemes(student)
    eligible_schemes = [s for s in schemes_all if s["probability"] >= 70]
    
    # Calculate academic weaknesses to recommend resources
    weaknesses = get_student_weaknesses(student)

    # ── Gamification: compute earned badges ──────────────────────
    try:
        from models import StudentInternship
        verified_count = StudentInternship.query.filter_by(register_number=reg_no, status="Verified").count()
        student["verified_internships_count"] = verified_count
    except Exception:
        student["verified_internships_count"] = 0

    try:
        from badge_engine import compute_badges, compute_badge_summary
        earned_badges = compute_badges(student)
        badge_summary = compute_badge_summary(earned_badges)
    except Exception:
        earned_badges = []
        badge_summary = {"total": 0, "gold": 0, "silver": 0, "bronze": 0, "special": 0}

    semesters = sorted(
        [c.split("_")[0] for c in df.columns if c.startswith("Sem") and c.endswith("_GPA")],
        key=lambda x: int(x.replace("Sem", ""))
    )

    return render_template(
        "student_dashboard.html",
        student=student,
        semesters=semesters,
        schemes=eligible_schemes,
        weaknesses=weaknesses,
        earned_badges=earned_badges,
        badge_summary=badge_summary
    )


# -----------------------------------------------
# DRIVES
# -----------------------------------------------

@student_bp.route("/drives")
@student_required
def student_drives():
    return render_template("student_drives.html")


@student_bp.route("/drives/current")
@student_required
def student_current_drives():
    reg_no = session["student_reg_no"]
    df = load_company_drives()
    results_df = pd.read_csv(RESULTS_CSV) if os.path.exists(RESULTS_CSV) else pd.DataFrame()

    status_list = []
    for i in range(len(df)):
        row = df.iloc[i].copy()
        drive_status = "attend"
        if not results_df.empty:
            attempts = results_df[
                (results_df["register_number"] == reg_no) &
                (results_df["drive_index"] == i)
            ]
            if not attempts.empty:
                drive_status = "cheated" if (attempts["cheated"] == 1).any() else "attended"

        row["test_status"] = drive_status
        status_list.append(row)

    updated_df = pd.DataFrame(status_list)
    return render_template("student_current_drives.html", drives=updated_df)


@student_bp.route("/drives/test/<int:index>")
@student_required
def student_attend_test(index):
    df = load_company_drives()
    if index >= len(df):
        return "Invalid test link", 404

    link = df.iloc[index].get("test_link", "")
    if link == "" or pd.isna(link):
        return "Test not available yet", 404

    return redirect(link)


# -----------------------------------------------
# TEST INSTRUCTIONS
# -----------------------------------------------

@student_bp.route("/test/instructions/<int:drive_index>")
@student_required
def test_instructions(drive_index):
    df = load_company_drives()
    row = df.iloc[drive_index]

    tests_available = {
        "Aptitude Test": bool(row.get("aptitude_test_link")),
        "Domain Test": bool(row.get("domain_test_link")),
        "Coding Test": bool(row.get("coding_test_link"))
    }

    return render_template(
        "student_test_instructions.html",
        drive=row,
        drive_index=drive_index,
        tests=tests_available
    )


@student_bp.route("/test/instructions/<int:drive_index>/<round_name>")
@student_required
def round_instructions(drive_index, round_name):
    df = load_company_drives()
    row = df.iloc[drive_index]

    test_names = {
        "aptitude": "Aptitude Test",
        "domain": "Domain-Based Test",
        "coding": "Coding Test"
    }

    duration = row.get(f"{round_name}_duration", 30)
    question_count = 60

    return render_template(
        "student_round_instructions.html",
        drive_index=drive_index,
        round=round_name,
        round_name=test_names.get(round_name, round_name),
        duration=duration,
        question_count=question_count
    )


# -----------------------------------------------
# TEST START & SUBMIT
# -----------------------------------------------

@student_bp.route("/test/start/<int:drive_index>/<round_name>")
@student_required
def start_test_round(drive_index, round_name):
    reg_no = session.get("student_reg_no")

    if os.path.exists(RESULTS_CSV):
        df_results = pd.read_csv(RESULTS_CSV)
        if "cheated" not in df_results.columns:
            df_results["cheated"] = 0

        cheated_record = df_results[
            (df_results["register_number"] == reg_no) &
            (df_results["drive_index"] == drive_index) &
            (df_results["cheated"] == 1)
        ]
        if not cheated_record.empty:
            return "You are disqualified due to cheating and cannot continue.", 403

    if has_attempted_test(reg_no, drive_index, round_name):
        return "You have already attempted this test. Reattempt is not allowed.", 403

    df = load_company_drives()
    row = df.iloc[drive_index]

    raw_file = row.get(f"{round_name}_test_link", "")
    if not isinstance(raw_file, str):
        raw_file = ""

    filename = raw_file.replace("internal:", "").strip()
    if filename == "":
        return "Test file missing or not assigned by admin", 404

    duration = row.get(f"{round_name}_duration", 30)
    questions = read_test_file(filename)

    # Generate a server-side HMAC token to bind this test session to the student.
    # This prevents a student from forging a 'cheated=0' payload via Postman/curl.
    token_data = f"{reg_no}:{drive_index}:{round_name}"
    proctor_token = hmac.new(
        PROCTOR_SECRET.encode(),
        token_data.encode(),
        hashlib.sha256
    ).hexdigest()
    session["proctor_token"] = proctor_token

    return render_template(
        "student_take_test.html",
        questions=questions,
        drive_index=drive_index,
        round=round_name,
        duration_minutes=duration,
        proctor_token=proctor_token
    )


@student_bp.route("/test/submit/<int:drive_index>/<round_name>", methods=["POST"])
@student_required
def submit_round(drive_index, round_name):
    reg_no = session.get("student_reg_no")

    df = load_company_drives()
    row = df.iloc[drive_index]

    raw_file = row.get(f"{round_name}_test_link", "")
    if not isinstance(raw_file, str):
        raw_file = ""

    filename = raw_file.replace("internal:", "").strip()
    if filename == "":
        return "Test file missing or not assigned by admin", 404

    questions = read_test_file(filename)

    answers = json.loads(request.form.get("answers_json", "[]"))
    submitted_token = request.form.get("proctor_token", "")
    cheated = int(request.form.get("cheated", 0))

    # --- HMAC Verification ---
    # Recompute expected token and compare against what the browser submitted.
    # A mismatch means the request was forged outside the browser (curl / Postman).
    token_data = f"{reg_no}:{drive_index}:{round_name}"
    expected_token = hmac.new(
        PROCTOR_SECRET.encode(),
        token_data.encode(),
        hashlib.sha256
    ).hexdigest()
    session_token = session.pop("proctor_token", None)

    token_valid = (
        session_token is not None and
        hmac.compare_digest(submitted_token, expected_token) and
        hmac.compare_digest(session_token, expected_token)
    )
    if not token_valid:
        # Reject forged submissions silently by logging as cheated
        cheated = 1

    total = len(questions)
    attempted = 0
    correct = 0
    wrong = 0
    marks_correct = 5
    marks_wrong = -1

    for i, q in enumerate(questions):
        chosen = answers[i] if i < len(answers) else None
        if chosen is not None:
            attempted += 1
            if int(chosen) == q["answer_index"]:
                correct += 1
            else:
                wrong += 1

    score = (correct * marks_correct) + (wrong * marks_wrong)

    if cheated == 1:
        save_to_results_row({
            "register_number": reg_no,
            "drive_index": drive_index,
            "round": round_name,
            "score": 0,
            "total": total,
            "attempted": attempted,
            "correct": correct,
            "wrong": wrong,
            "marks_correct": marks_correct,
            "marks_wrong": marks_wrong,
            "cheated": 1,
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        return "You have been disqualified for cheating. Test cancelled.", 403

    save_to_results_row({
        "register_number": reg_no,
        "drive_index": drive_index,
        "round": round_name,
        "score": score,
        "total": total,
        "attempted": attempted,
        "correct": correct,
        "wrong": wrong,
        "marks_correct": marks_correct,
        "marks_wrong": marks_wrong,
        "cheated": 0,
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    # Navigate to next round
    if round_name == "aptitude":
        return redirect(url_for("student.round_instructions", drive_index=drive_index, round_name="domain"))
    if round_name == "domain":
        return redirect(url_for("student.round_instructions", drive_index=drive_index, round_name="coding"))

    return redirect(url_for("student.test_summary", drive_index=drive_index))


@student_bp.route("/test/summary/<int:drive_index>")
@student_required
def test_summary(drive_index):
    """Show the student's test scores for this drive after completing all rounds."""
    if "student_reg_no" not in session:
        return redirect(url_for("student.login"))

    reg_no = session["student_reg_no"]

    if not os.path.exists(RESULTS_CSV):
        flash("No results found.")
        return redirect(url_for("student.dashboard"))

    df = pd.read_csv(RESULTS_CSV)
    results = df[
        (df["register_number"] == reg_no) &
        (df["drive_index"] == drive_index)
    ].to_dict(orient="records")

    df_drives = pd.read_csv(COMPANY_DRIVES) if os.path.exists(COMPANY_DRIVES) else pd.DataFrame()
    company_name = ""
    if not df_drives.empty and drive_index < len(df_drives):
        company_name = df_drives.iloc[drive_index].get("company_name", "")

    return render_template(
        "student_test_summary.html",
        results=results,
        drive_index=drive_index,
        company_name=company_name
    )


# -----------------------------------------------
# RESUME GENERATION (ReportLab PDF)
# -----------------------------------------------

def safe_number(value, default=0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def parse_resume_list(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [item.strip() for item in text.split(",") if item.strip()]


def draw_wrapped_text(pdf, text, x, y, max_width, font_name="Helvetica", font_size=10.5, leading=14, color=colors.black):
    pdf.setFillColor(color)
    pdf.setFont(font_name, font_size)
    words = str(text).split()
    if not words:
        return y
    line = ""
    for word in words:
        test_line = f"{line} {word}".strip()
        if pdf.stringWidth(test_line, font_name, font_size) <= max_width:
            line = test_line
        else:
            pdf.drawString(x, y, line)
            y -= leading
            line = word
    if line:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def draw_bullet_list(pdf, items, x, y, max_width, bullet_color=colors.HexColor("#C6952A")):
    for item in items:
        pdf.setFillColor(bullet_color)
        pdf.circle(x + 2, y + 3, 1.8, fill=1, stroke=0)
        y = draw_wrapped_text(pdf, item, x + 12, y, max_width - 12,
                              font_name="Helvetica", font_size=10.2, leading=13,
                              color=colors.HexColor("#222222"))
        y -= 3
    return y


def draw_section_heading(pdf, title, x, y, width):
    pdf.setFillColor(colors.HexColor("#1A1A1A"))
    pdf.setFont("Helvetica-Bold", 12.5)
    pdf.drawString(x, y, title.upper())
    pdf.setStrokeColor(colors.HexColor("#E2B04A"))
    pdf.setLineWidth(1.2)
    pdf.line(x, y - 4, x + width, y - 4)
    return y - 20


def ensure_resume_space(pdf, y, needed_height, page_width, page_height):
    if y - needed_height < 50:
        pdf.showPage()
        pdf.setFillColor(colors.black)
        return page_height - 55
    return y


@student_bp.route("/generate_resume")
@student_required
def generate_resume():
    reg_no = session["student_reg_no"]
    df = load_students()
    student = df[df["Register_Number"] == reg_no].iloc[0]
    cert_list = []

    if os.path.exists(CERT_CSV):
        cert_df = pd.read_csv(CERT_CSV)
        student_certs = cert_df[
            (cert_df["register_number"] == reg_no) &
            (cert_df["status"] == "approved")
        ]
        cert_list = student_certs["certificate_name"].tolist()

    filename = f"{reg_no}_generated_resume.pdf"
    path = os.path.join(RESUME_DIR, filename)

    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    left_margin = 48
    right_margin = width - 48
    content_width = right_margin - left_margin
    y = height - 48

    cgpa = safe_number(student.get("CGPA", 0))
    semester = student.get("Current_Sem", "")
    projects = int(safe_number(student.get("Projects_Done", 0)))
    hackathons = int(safe_number(student.get("Hackathons_Participated", 0)))
    patents = int(safe_number(student.get("Patents_Granted", 0)))
    papers = int(safe_number(student.get("Research_Papers_Published", 0)))
    communication = safe_number(student.get("Avg_Communication_Score", 0))
    aptitude = safe_number(student.get("Weekly_Aptitude_Avg", 0))
    leetcode = int(safe_number(student.get("LeetCode_Problems_Solved", 0)))
    codechef = int(safe_number(student.get("CodeChef_Rating", 0)))
    skill_index = safe_number(student.get("skill_index", 0))
    department = str(student.get("Department", "")).strip()

    certification_names = (cert_list or parse_resume_list(student.get("Certifications_List", "")))[:6]

    skill_items = []
    if department:
        skill_items.append(f"Domain Focus: {department}")
    if leetcode > 0:
        skill_items.append(f"Problem Solving: {leetcode} LeetCode problems solved")
    if codechef > 0:
        skill_items.append(f"Competitive Coding: CodeChef rating {codechef}")
    if communication > 0:
        skill_items.append(f"Communication: Average score {communication:.0f}")
    if aptitude > 0:
        skill_items.append(f"Aptitude: Weekly average {aptitude:.0f}")
    foreign_language = str(student.get("Foreign_Language_Known", "")).strip()
    if foreign_language and foreign_language.lower() != "nan":
        skill_items.append(f"Additional Language: {foreign_language}")

    achievement_items = [a for a in [
        f"Maintained a CGPA of {cgpa:.2f} in Semester {semester}" if cgpa else "",
        f"Completed {projects} academic or practical projects" if projects else "",
        f"Participated in {hackathons} hackathons" if hackathons else "",
        f"Published {papers} research or review papers" if papers else "",
        f"Holds {patents} patent grants" if patents else "",
        f"Built a skill index score of {skill_index:.0f}" if skill_index else "",
    ] if a]

    summary_parts = []
    if department:
        summary_parts.append(f"{department} student")
    if semester:
        summary_parts.append(f"currently in semester {semester}")
    if cgpa:
        summary_parts.append(f"with a CGPA of {cgpa:.2f}")
    base_summary = " ".join(summary_parts).strip()
    if base_summary:
        base_summary = base_summary[0].upper() + base_summary[1:]

    profile_summary = (
        f"{base_summary}. Strong interest in technology-driven roles with proven exposure to projects, "
        f"coding practice, certifications, and campus-level achievement metrics."
    ).replace("..", ".")

    # Header bar
    c.setFillColor(colors.HexColor("#F7F1E1"))
    c.rect(0, height - 130, width, 130, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#E2B04A"))
    c.rect(0, height - 18, width, 18, fill=1, stroke=0)

    c.setFillColor(colors.HexColor("#1A1A1A"))
    c.setFont("Helvetica-Bold", 23)
    c.drawString(left_margin, height - 62, str(student.get("Student_Name", "Student")).upper())

    c.setFont("Helvetica", 10.8)
    contact_line = " | ".join([
        f"Register No: {student.get('Register_Number', '')}",
        f"Department: {department}",
        f"Semester: {semester}",
        f"CGPA: {cgpa:.2f}" if cgpa else "CGPA: -"
    ])
    c.drawString(left_margin, height - 86, contact_line)
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(left_margin, height - 104, "Professional student resume generated from verified portal profile data")

    y = height - 158
    y = draw_section_heading(c, "Profile Summary", left_margin, y, content_width)
    y = draw_wrapped_text(c, profile_summary, left_margin, y, content_width,
                          font_name="Helvetica", font_size=10.6, leading=15, color=colors.HexColor("#222222"))
    y -= 6

    y = ensure_resume_space(c, y, 115, width, height)
    y = draw_section_heading(c, "Education Snapshot", left_margin, y, content_width)
    education_points = [p for p in [
        f"Programme: {department}" if department else "",
        f"Current Semester: {semester}" if semester != "" else "",
        f"Current CGPA: {cgpa:.2f}" if cgpa else "",
        f"Student ID: {student.get('Student_ID', '')}" if str(student.get('Student_ID', '')).strip() else "",
    ] if p]
    y = draw_bullet_list(c, education_points, left_margin, y, content_width)

    y = ensure_resume_space(c, y, 130, width, height)
    y = draw_section_heading(c, "Technical & Professional Highlights", left_margin, y, content_width)
    y = draw_bullet_list(c, skill_items or ["Profile skills will appear here after updating profile."], left_margin, y, content_width)

    y = ensure_resume_space(c, y, 130, width, height)
    y = draw_section_heading(c, "Achievements", left_margin, y, content_width)
    y = draw_bullet_list(c, achievement_items or ["Achievements will appear here once updated in the profile."], left_margin, y, content_width)

    y = ensure_resume_space(c, y, 120, width, height)
    y = draw_section_heading(c, "Certifications", left_margin, y, content_width)
    y = draw_bullet_list(c, certification_names or ["No approved certifications available in the portal yet."], left_margin, y, content_width)

    y = ensure_resume_space(c, y, 70, width, height)
    y = draw_section_heading(c, "Recruiter Quick View", left_margin, y, content_width)
    quick_view = (
        f"Projects: {projects}    |    Hackathons: {hackathons}    |    "
        f"Research Papers: {papers}    |    Patents: {patents}    |    Skill Index: {skill_index:.0f}"
    )
    draw_wrapped_text(c, quick_view, left_margin, y, content_width,
                      font_name="Helvetica-Bold", font_size=10.4, leading=14, color=colors.HexColor("#222222"))

    c.save()
    return send_file(path, as_attachment=True)


@student_bp.route("/resume_builder", methods=["GET", "POST"])
@student_required
def resume_builder():
    from models import Student, db
    reg_no = session["student_reg_no"]
    student = Student.query.filter_by(register_number=reg_no).first_or_404()

    if request.method == "POST":
        # Save custom resume fields
        student.resume_email = request.form.get("resume_email", "").strip()
        student.resume_phone = request.form.get("resume_phone", "").strip()
        student.resume_linkedin = request.form.get("resume_linkedin", "").strip()
        student.resume_github = request.form.get("resume_github", "").strip()
        student.resume_summary = request.form.get("resume_summary", "").strip()
        student.resume_work_experience = request.form.get("resume_work_experience", "").strip()

        # Save profile overrides
        student.student_name = request.form.get("student_name", "").strip()
        student.department = request.form.get("department", "").strip()
        
        try:
            student.cgpa = float(request.form.get("cgpa", 0.0))
        except ValueError:
            pass
        try:
            student.current_sem = int(request.form.get("current_sem", 1))
        except ValueError:
            pass
        try:
            student.leetcode_problems_solved = int(request.form.get("leetcode", 0))
        except ValueError:
            pass
        try:
            student.codechef_rating = int(request.form.get("codechef", 0))
        except ValueError:
            pass
        try:
            student.hackathons_participated = int(request.form.get("hackathons", 0))
        except ValueError:
            pass
        try:
            student.research_papers_published = int(request.form.get("papers", 0))
        except ValueError:
            pass
        try:
            student.skill_index = float(request.form.get("skill_index", 0.0))
        except ValueError:
            pass

        student.certifications_list = request.form.get("certifications", "").strip()

        db.session.commit()
        flash("Resume content and student profile updated successfully!")
        return redirect(url_for("student.resume_builder"))

    # Prepare default summary if empty
    default_summary = student.resume_summary
    if not default_summary:
        dept = student.department or "Technology"
        sem = student.current_sem or 6
        cgpa = student.cgpa or 0.0
        default_summary = (
            f"Ambitious {dept} student in Semester {sem} with a CGPA of {cgpa:.2f}. "
            f"Strong interest in tech-driven roles with proven exposure to projects, coding practice, "
            f"certifications, and academic problem-solving."
        )

    # Parse certifications
    certifications = []
    if student.certifications_list:
        certifications = [c.strip() for c in student.certifications_list.split(",") if c.strip()]

    # Fetch approved certificates from database
    try:
        from models import Certificate
        db_certs = Certificate.query.filter_by(register_number=reg_no, status="approved").all()
        if db_certs:
            certifications = [c.certificate_name for c in db_certs]
    except Exception:
        pass

    # Fetch verified internships from database
    verified_internships = []
    try:
        from models import StudentInternship
        verified_internships = StudentInternship.query.filter_by(register_number=reg_no, status="Verified").all()
    except Exception:
        pass

    return render_template(
        "student_resume_builder.html",
        student=student,
        default_summary=default_summary,
        certifications=certifications,
        verified_internships=verified_internships
    )


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT PROPOSALS & MENTORSHIP
# ─────────────────────────────────────────────────────────────────────────────

@student_bp.route("/project_proposals", methods=["GET", "POST"])
@student_required
def project_proposals():
    from models import Student, Mentor, ProjectProposal, ProjectUpdate, db
    reg_no = session["student_reg_no"]
    student = Student.query.filter_by(register_number=reg_no).first_or_404()

    # Dynamic project upload directory
    PROJECT_UPLOAD_DIR = os.path.join(DATA_DIR, "projects")
    os.makedirs(PROJECT_UPLOAD_DIR, exist_ok=True)

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "submit":
            title = request.form.get("project_title", "").strip()
            desc = request.form.get("description", "").strip()
            domain = request.form.get("domain", "").strip()
            file = request.files.get("project_ppt")

            if not title or not desc or not domain or not file:
                flash("All fields and a PPT file upload are required to submit.")
                return redirect(url_for("student.project_proposals"))

            # Save the PPT file
            filename = f"{reg_no}_{int(datetime.now().timestamp())}_{secure_filename(file.filename)}"
            file.save(os.path.join(PROJECT_UPLOAD_DIR, filename))

            # Create proposal
            proposal = ProjectProposal(
                register_number=reg_no,
                project_title=title,
                description=desc,
                domain=domain,
                ppt_path=filename,
                status="Pending Review"
            )
            db.session.add(proposal)
            db.session.commit()
            flash("Project proposal submitted successfully!")
            return redirect(url_for("student.project_proposals"))

        elif action == "select_mentor":
            proposal_id = request.form.get("proposal_id")
            mentor_id = request.form.get("mentor_id")

            proposal = ProjectProposal.query.get_or_404(proposal_id)
            if proposal.register_number != reg_no:
                flash("Unauthorized request.")
                return redirect(url_for("student.project_proposals"))

            mentor = Mentor.query.get_or_404(mentor_id)
            if mentor.current_slots >= mentor.max_slots:
                flash("This mentor has no available slots. Please choose another mentor.")
                return redirect(url_for("student.project_proposals"))

            # Assign mentor and update status
            proposal.mentor_id = mentor.id
            proposal.status = "Mentorship Active"
            mentor.current_slots += 1
            db.session.commit()
            flash(f"Successfully selected {mentor.name} as your mentor!")
            return redirect(url_for("student.project_proposals"))

        elif action == "log_progress":
            proposal_id = request.form.get("proposal_id")
            update_text = request.form.get("update_text", "").strip()

            if not update_text:
                flash("Progress update content cannot be empty.")
                return redirect(url_for("student.project_proposals"))

            proposal = ProjectProposal.query.get_or_404(proposal_id)
            if proposal.register_number != reg_no:
                flash("Unauthorized request.")
                return redirect(url_for("student.project_proposals"))

            # Determine week number
            last_update = ProjectUpdate.query.filter_by(proposal_id=proposal_id).order_by(ProjectUpdate.week_no.desc()).first()
            next_week = (last_update.week_no + 1) if last_update else 1

            # Log update
            p_update = ProjectUpdate(
                proposal_id=proposal_id,
                week_no=next_week,
                update_text=update_text
            )
            db.session.add(p_update)
            db.session.commit()
            flash(f"Logged progress update for Week {next_week} successfully!")
            return redirect(url_for("student.project_proposals"))

    # Fetch active proposals and available mentors
    proposals = ProjectProposal.query.filter_by(register_number=reg_no).order_by(ProjectProposal.submitted_at.desc()).all()
    mentors = Mentor.query.filter(Mentor.current_slots < Mentor.max_slots).all()

    return render_template(
        "student_project_proposals.html",
        student=student,
        proposals=proposals,
        mentors=mentors
    )


@student_bp.route("/download_project_ppt/<int:proposal_id>")
@student_required
def download_project_ppt(proposal_id):
    from models import ProjectProposal
    proposal = ProjectProposal.query.get_or_404(proposal_id)
    
    # Check authorization (Student can only download their own PPT, admin can download any)
    if "student_reg_no" in session and proposal.register_number != session["student_reg_no"]:
        return "Unauthorized", 403

    PROJECT_UPLOAD_DIR = os.path.join(DATA_DIR, "projects")
    file_path = os.path.join(PROJECT_UPLOAD_DIR, proposal.ppt_path)
    if not os.path.exists(file_path):
        return "File not found", 404

    return send_file(file_path, as_attachment=True)


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATION CENTRE
# ─────────────────────────────────────────────────────────────────────────────

@student_bp.route("/notifications")
@student_required
def notifications():
    from models import Notification, db
    reg_no = session["student_reg_no"]

    # Fetch: personal notifications + broadcast (register_number IS NULL)
    notifs = Notification.query.filter(
        (Notification.register_number == reg_no) |
        (Notification.register_number == None)
    ).order_by(Notification.created_at.desc()).all()

    unread_count = sum(1 for n in notifs if not n.is_read)
    return render_template("student_notifications.html",
                           notifications=notifs,
                           unread_count=unread_count)


@student_bp.route("/notifications/mark_read/<int:notif_id>", methods=["POST"])
@student_required
def mark_notification_read(notif_id):
    from models import Notification, db
    reg_no = session["student_reg_no"]
    notif = Notification.query.get_or_404(notif_id)
    # Authorise: student owns it OR it's a broadcast
    if notif.register_number is None or notif.register_number == reg_no:
        notif.is_read = True
        db.session.commit()
    return redirect(url_for("student.notifications"))


@student_bp.route("/notifications/mark_all_read", methods=["POST"])
@student_required
def mark_all_notifications_read():
    from models import Notification, db
    reg_no = session["student_reg_no"]
    Notification.query.filter(
        (Notification.register_number == reg_no) |
        (Notification.register_number == None),
        Notification.is_read == False
    ).update({"is_read": True}, synchronize_session=False)
    db.session.commit()
    flash("All notifications marked as read.")
    return redirect(url_for("student.notifications"))


@student_bp.context_processor
def inject_unread_notif_count():
    """Injects unread_notif_count into every student template."""
    count = 0
    try:
        if "student_reg_no" in session:
            from models import Notification
            reg_no = session["student_reg_no"]
            count = Notification.query.filter(
                (Notification.register_number == reg_no) |
                (Notification.register_number == None),
                Notification.is_read == False
            ).count()
    except Exception:
        pass
    return dict(unread_notif_count=count)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNSHIP TRACKER
# ─────────────────────────────────────────────────────────────────────────────

@student_bp.route("/internships", methods=["GET", "POST"])
@student_required
def internships():
    from models import StudentInternship, db, Student
    reg_no = session["student_reg_no"]
    student = Student.query.filter_by(register_number=reg_no).first_or_404()

    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        role         = request.form.get("role", "").strip()
        duration     = request.form.get("duration", "").strip()
        stipend      = request.form.get("stipend", "").strip()
        mode         = request.form.get("mode", "Onsite").strip()

        if not company_name or not role or not duration:
            flash("❌ Company name, role, and duration are required.")
            return redirect(url_for("student.internships"))

        new_internship = StudentInternship(
            register_number=reg_no,
            company_name=company_name,
            role=role,
            duration=duration,
            stipend=stipend or "Unpaid",
            mode=mode,
            status="Pending Verification"
        )
        db.session.add(new_internship)
        db.session.commit()
        flash("🎉 Internship logged successfully! Awaiting administrator verification.")
        return redirect(url_for("student.internships"))

    my_internships = StudentInternship.query.filter_by(register_number=reg_no).order_by(StudentInternship.submitted_at.desc()).all()
    return render_template("student_internships.html", student=student, internships=my_internships)

