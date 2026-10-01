from auth_decorators import admin_required
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import pandas as pd
import os
import numpy as np
import json
from io import StringIO
from datetime import datetime
from utils import (
    create_admin, verify_admin, merge_upload_df, read_master_df,
    read_recycle_df, save_master_df, save_recycle_df,
    compute_skill_index_for_row, compute_analysis_from_df, parse_list_field
)

admin_bp = Blueprint("admin", __name__)

# Paths resolved relative to the main project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CERT_UPLOAD_DIR = os.path.join(DATA_DIR, "certificates")
RESUME_DIR = os.path.join(DATA_DIR, "resumes")
RESUME_EXPORT_CSV = os.path.join(DATA_DIR, "resume_export.csv")
CERT_CSV = os.path.join(DATA_DIR, "certificates.csv")
MASTER_CSV = os.path.join(DATA_DIR, "master_students.csv")
RECYCLE_CSV = os.path.join(DATA_DIR, "recycle_bin.csv")
COMPANY_DRIVES = os.path.join(DATA_DIR, "company_drives.csv")
TESTS_DIR = os.path.join(DATA_DIR, "tests")
RESULTS_CSV = os.path.join(DATA_DIR, "test_results.csv")

def read_company_drives():
    if not os.path.exists(COMPANY_DRIVES):
        return pd.DataFrame()
    return pd.read_csv(COMPANY_DRIVES)

def load_company_drives():
    return read_company_drives()

def save_company_drives(df):
    df.to_csv(COMPANY_DRIVES, index=False)

# ----------------------------------------------
# AUTH
# ----------------------------------------------

@admin_bp.route("/", methods=["GET", "POST"])
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if "admin_user" in session:
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if verify_admin(username, password):
            session["admin_user"] = username
            return redirect(url_for("admin.dashboard"))
        else:
            flash("Invalid credentials")
    return render_template("login.html")

@admin_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        try:
            create_admin(username, password)
            flash("Admin created! Please login.")
            return redirect(url_for("admin.login"))
        except ValueError as e:
            flash(str(e))
    return render_template("register.html")

@admin_bp.route("/certificates")
@admin_required
def admin_certificates():
    # ── DB path ──────────────────────────────────────────────────────────
    try:
        from models import Certificate, db
        db.session.execute(db.select(Certificate).limit(1))   # probe
        pending_objs = Certificate.query.filter(
            Certificate.status.in_(["pending", "Pending"])
        ).order_by(Certificate.id.desc()).all()
        certs = [{
            "certificate_id": c.certificate_id,
            "register_number": c.register_number,
            "student_name":    c.student_name,
            "certificate_name":c.certificate_name,
            "file_path":       c.file_path or "",
            "status":          c.status,
            "uploaded_at":     c.uploaded_at or "",
        } for c in pending_objs]
        return render_template("admin_certificates.html", certs=certs)
    except Exception:
        pass

    # ── CSV fallback ──────────────────────────────────────────────────────
    if not os.path.exists(CERT_CSV):
        return render_template("admin_certificates.html", certs=[])

    df = pd.read_csv(CERT_CSV)
    df.columns = df.columns.str.strip()
    if "file_path" not in df.columns:
        df["file_path"] = ""
    df["file_path"] = df["file_path"].fillna("").astype(str).str.strip()
    df["certificate_id"] = pd.to_numeric(df["certificate_id"], errors="coerce").fillna(0).astype(int)
    pending = df[df["status"].str.lower() == "pending"]
    return render_template("admin_certificates.html", certs=pending.to_dict(orient="records"))

@admin_bp.route("/certificates/review/<int:cert_id>", methods=["POST"])
@admin_required
def review_certificate(cert_id):
    action  = request.form.get("action")
    remarks = request.form.get("remarks", "")
    new_status  = "approved" if action == "approve" else "rejected"
    reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    reviewer    = session["admin_user"]

    reg_no    = None
    cert_name = None

    # ── DB path ──────────────────────────────────────────────────────────
    db_used = False
    try:
        from models import Certificate, db
        cert_obj = Certificate.query.filter_by(certificate_id=str(cert_id)).first()
        if cert_obj:
            cert_obj.status      = new_status
            cert_obj.reviewed_by = reviewer
            cert_obj.reviewed_at = reviewed_at
            cert_obj.remarks     = remarks
            db.session.commit()
            reg_no    = cert_obj.register_number
            cert_name = cert_obj.certificate_name
            db_used   = True
        else:
            flash("Certificate not found")
            return redirect(url_for("admin.admin_certificates"))
    except Exception:
        pass

    # ── CSV mirror / fallback ─────────────────────────────────────────────
    if os.path.exists(CERT_CSV):
        try:
            df  = pd.read_csv(CERT_CSV)
            idx = df[df["certificate_id"] == cert_id].index
            if not idx.empty:
                df.at[idx[0], "status"]      = new_status
                df.at[idx[0], "reviewed_by"] = reviewer
                df.at[idx[0], "reviewed_at"] = reviewed_at
                df.at[idx[0], "remarks"]     = remarks
                if not db_used:
                    reg_no    = str(df.at[idx[0], "register_number"])
                    cert_name = df.at[idx[0], "certificate_name"]
                df.to_csv(CERT_CSV, index=False)
        except Exception:
            pass

    # ── On approval: update student record ───────────────────────────────
    if action == "approve" and reg_no and cert_name:
        master    = read_master_df()
        stu_idx   = master[master["Register_Number"].astype(str) == reg_no].index
        if not stu_idx.empty:
            sidx = stu_idx[0]
            try:
                current = int(master.at[sidx, "Number_of_Certifications"])
            except Exception:
                current = 0
            master.at[sidx, "Number_of_Certifications"] = current + 1

            old = str(master.at[sidx, "Certifications_List"]).strip()
            master.at[sidx, "Certifications_List"] = (
                old + ", " + cert_name if old and old.lower() != "nan" else cert_name
            )
            master.at[sidx, "skill_index"] = compute_skill_index_for_row(master.loc[sidx])
            save_master_df(master)

    flash(f"Certificate {action}d successfully")
    return redirect(url_for("admin.admin_certificates"))

@admin_bp.route("/logout")
def logout():
    session.pop("admin_user", None)
    flash("Logged out successfully.")
    return redirect(url_for("admin.login"))

# ----------------------------------------------
# DASHBOARD
# ----------------------------------------------

@admin_bp.route("/certificates/view/<path:filename>")
@admin_required
def view_certificate_file(filename):
    file_path = os.path.join(CERT_UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        return "File not found", 404
    return send_file(file_path)

@admin_bp.route("/resumes/view/<path:filename>")
@admin_required
def view_resume_file(filename):
    file_path = os.path.join(RESUME_DIR, filename)
    if not os.path.exists(file_path):
        return "File not found", 404
    return send_file(file_path)

@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    return render_template("dashboard.html", user=session["admin_user"])

@admin_bp.route("/drives")
@admin_required
def drives():
    drives_df = read_company_drives()
    return render_template("drives.html", drives=drives_df)

@admin_bp.route("/drives/<int:drive_id>")
@admin_required
def view_drive_eligibility(drive_id):
    drives_df = read_company_drives()
    if drive_id >= len(drives_df):
        flash("Invalid drive ID")
        return redirect(url_for("admin.drives"))

    company = drives_df.iloc[drive_id]

    from utils import get_eligible_students_for_company
    students = get_eligible_students_for_company(company)

    sort_order = request.args.get("sort", "none")
    if sort_order == "asc":
        students = sorted(students, key=lambda x: float(x.get("skill_index", 0)))
    elif sort_order == "desc":
        students = sorted(students, key=lambda x: float(x.get("skill_index", 0)), reverse=True)

    return render_template(
        "eligible_students.html",
        company=company,
        students=students,
        sort_order=sort_order
    )

@admin_bp.route("/assign_test/<int:drive_index>", methods=["GET", "POST"])
@admin_required
def admin_assign_test(drive_index):
    df = load_company_drives()
    if df.empty or drive_index >= len(df):
        flash("Invalid drive index")
        return redirect(url_for("admin.drives"))

    if request.method == "POST":
        files = {
            "aptitude": request.files.get("aptitude_test"),
            "domain": request.files.get("domain_test"),
            "coding": request.files.get("coding_test"),
        }

        durations = {
            "aptitude": request.form.get("aptitude_duration", "30"),
            "domain": request.form.get("domain_duration", "30"),
            "coding": request.form.get("coding_duration", "30"),
        }

        for test_type, uploaded_file in files.items():
            if uploaded_file and uploaded_file.filename.endswith(".csv"):
                filename = f"{test_type}_{drive_index}_{uploaded_file.filename}"
                file_path = os.path.join(TESTS_DIR, filename)
                uploaded_file.save(file_path)

                df.at[drive_index, f"{test_type}_test_link"] = f"internal:{filename}"
                df.at[drive_index, f"{test_type}_duration"] = durations[test_type]

        save_company_drives(df)
        flash("Tests uploaded and assigned successfully!")
        return redirect(url_for("admin.admin_assign_test", drive_index=drive_index))

    return render_template(
        "admin_assign_test.html",
        drive=df.iloc[drive_index],
        drive_index=drive_index
    )

# ----------------------------------------------
# ADD STUDENTS
# ----------------------------------------------

@admin_bp.route("/add_students", methods=["GET", "POST"])
@admin_required
def add_students():
    if request.method == "POST":
        input_method = request.form.get("input_method", "csv")

        # ── Manual Entry ────────────────────────────────────────────────────
        if input_method == "manual":
            from models import Student, db
            from utils import compute_skill_index_for_row, classify_skill_level

            reg_no = request.form.get("register_number", "").strip()
            if not reg_no:
                flash("Register Number is required.")
                return redirect(url_for("admin.add_students"))

            # Check if student already exists
            existing = Student.query.filter_by(register_number=reg_no).first()

            s = existing or Student()
            s.register_number          = reg_no
            s.student_name             = request.form.get("student_name", "").strip()
            s.batch                    = request.form.get("batch", "").strip()
            s.department               = request.form.get("department", "").strip()
            s.gender                   = request.form.get("gender", "").strip()
            s.current_sem              = request.form.get("current_sem", type=int)
            s.cgpa                     = request.form.get("cgpa", type=float)
            s.foreign_language_known   = request.form.get("foreign_language_known", "").strip()
            s.projects_done            = request.form.get("projects_done", 0, type=int)
            s.hackathons_participated  = request.form.get("hackathons_participated", 0, type=int)
            s.hackathons_won_top100    = request.form.get("hackathons_won_top100", 0, type=int)
            s.leetcode_problems_solved = request.form.get("leetcode_problems_solved", 0, type=int)
            s.codechef_rating          = request.form.get("codechef_rating", 0, type=int)
            s.number_of_certifications = request.form.get("number_of_certifications", 0, type=int)
            s.research_papers_published= request.form.get("research_papers_published", 0, type=int)
            s.weekly_aptitude_avg      = request.form.get("weekly_aptitude_avg", 0.0, type=float)
            s.avg_communication_score  = request.form.get("avg_communication_score", 0.0, type=float)
            s.certifications_list      = request.form.get("certifications_list", "").strip()
            s.is_active                = True

            # Set a default password if new student
            if not existing or not s.password:
                from werkzeug.security import generate_password_hash
                default_pw = reg_no  # default password = register number
                s.password = generate_password_hash(default_pw)

            # Compute skill index
            try:
                row_dict = {
                    "CGPA": s.cgpa or 0,
                    "Projects_Done": s.projects_done or 0,
                    "Hackathons_Participated": s.hackathons_participated or 0,
                    "LeetCode_Problems_Solved": s.leetcode_problems_solved or 0,
                    "CodeChef_Rating": s.codechef_rating or 0,
                    "Number_of_Certifications": s.number_of_certifications or 0,
                    "Research_Papers_Published": s.research_papers_published or 0,
                    "Weekly_Aptitude_Avg": s.weekly_aptitude_avg or 0,
                    "Avg_Communication_Score": s.avg_communication_score or 0,
                }
                import pandas as _pd
                s.skill_index = compute_skill_index_for_row(_pd.Series(row_dict))
                s.skill_level = classify_skill_level(s.skill_index)
            except Exception:
                s.skill_index = 0.0
                s.skill_level = "Beginner"

            if not existing:
                db.session.add(s)
            db.session.commit()

            action_word = "updated" if existing else "added"
            flash(f"Student {s.student_name} ({reg_no}) {action_word} successfully! Default password is the Register Number.")
            return redirect(url_for("admin.view_students"))

        # ── CSV Upload (original) ────────────────────────────────────────────
        file = request.files.get("file")
        filename = getattr(file, "filename", "") if file is not None else ""
        if not filename or not filename.lower().endswith(".csv"):
            flash("Please upload a valid CSV file.")
            return redirect(url_for("admin.add_students"))
        df_upload = pd.read_csv(file)
        result = merge_upload_df(df_upload, session["admin_user"])
        flash(f"Upload complete: {result['updated']} records updated.")
        return redirect(url_for("admin.view_students"))

    return render_template("add_students.html")

# ----------------------------------------------
# VIEW STUDENTS
# ----------------------------------------------

@admin_bp.route("/view_students", methods=["GET", "POST"])
@admin_required
def view_students():
    df = read_master_df()
    if df.empty:
        flash("No student data available.")
        return render_template("view_students.html", students=[], semesters=[])

    if request.method == "POST":
        selected = request.form.getlist("selected_students")
        if not selected:
            flash("No students selected for deletion.")
            return redirect(url_for("admin.view_students"))

        master = read_master_df()
        recycle = read_recycle_df()
        moved = []

        for reg in selected:
            row = master[master["Register_Number"].astype(str) == str(reg)]
            if not row.empty:
                row_dict = row.iloc[0].to_dict()
                row_dict["deleted_at"] = datetime.utcnow().isoformat()
                row_dict["deleted_by"] = session["admin_user"]

                recycle = pd.concat([recycle, pd.DataFrame([row_dict])], ignore_index=True)
                master = master[master["Register_Number"].astype(str) != str(reg)]
                moved.append(reg)

        save_master_df(master)
        save_recycle_df(recycle)

        flash(f"Moved {len(moved)} students to recycle bin.")
        return redirect(url_for("admin.view_students"))

    batches = sorted(df["Batch"].dropna().unique())
    depts = sorted(df["Department"].dropna().unique())
    semesters = sorted(df["Current_Sem"].dropna().unique())

    batch_filter = request.args.get("batch")
    dept_filter = request.args.get("dept")
    sem_filter = request.args.get("current_sem")
    cgpa_filter_type = request.args.get("cgpa_filter_type")
    cgpa_value = request.args.get("cgpa_value")

    filtered_df = df.copy()

    if batch_filter and batch_filter != "all":
        filtered_df = filtered_df[filtered_df["Batch"] == batch_filter]

    if dept_filter and dept_filter != "all":
        filtered_df = filtered_df[filtered_df["Department"] == dept_filter]

    if sem_filter and sem_filter != "all":
        filtered_df = filtered_df[filtered_df["Current_Sem"] == int(sem_filter)]

    if cgpa_filter_type and cgpa_value:
        try:
            cgpa_value = float(cgpa_value)
            if cgpa_filter_type == "greater":
                filtered_df = filtered_df[filtered_df["CGPA"] > cgpa_value]
            elif cgpa_filter_type == "less":
                filtered_df = filtered_df[filtered_df["CGPA"] < cgpa_value]
        except ValueError:
            pass

    students = filtered_df.to_dict(orient="records")

    return render_template(
        "view_students.html",
        students=students,
        batches=batches,
        depts=depts,
        semesters=semesters
    )

@admin_bp.route("/student/<reg_no>")
@admin_required
def student_profile(reg_no):
    df = read_master_df()
    if df.empty:
        flash("No student data available.")
        return redirect(url_for("admin.view_students"))

    reg_no = str(reg_no)
    student = df[df["Register_Number"].astype(str) == reg_no]
    if student.empty:
        flash("Student not found.")
        return redirect(url_for("admin.view_students"))

    student_data = student.to_dict(orient="records")[0]

    semesters = []
    for i in range(1, 11):
        if f"Sem{i}_GPA" in df.columns:
            semesters.append(f"Sem{i}")

    return render_template(
        "student_profile.html",
        student=student_data,
        semesters=semesters
    )

# ----------------------------------------------
# CGPA ANALYSIS & RETRAINING
# ----------------------------------------------

@admin_bp.route("/analysis/retrain", methods=["POST"])
@admin_required
def admin_analysis_retrain():
    try:
        # Load actual student profiles
        df = read_master_df()
        if df.empty:
            return jsonify(success=False, message="No student data available to train model"), 400

        features_list = []
        for _, row in df.iterrows():
            cgpa = float(row.get("CGPA", 0))
            projects = float(row.get("Projects_Done", 0))
            papers = float(row.get("Research_Papers_Published", 0))
            hackathons = float(row.get("Hackathons_Participated", 0))
            academic_score = cgpa * 10 + projects * 4 + papers * 8 + hackathons * 5

            # Compute cert score based on weights
            levels = str(row.get("Certificate_Course_Level", "")).split(",")
            platforms = str(row.get("Certificate_Platform", "")).split(",")
            domains = str(row.get("Certificate_Domain", "")).split(",")

            level_weight = {"Beginner": 5, "Intermediate": 10, "Advanced": 15, "Professional": 20}
            platform_weight = {"Coursera": 1.4, "Google": 1.4, "Microsoft": 1.4, "Cisco": 1.5, "NPTEL": 1.5, "Udemy": 1.2}
            domain_weight = {"AI": 1.5, "Data Science": 1.4, "Cybersecurity": 1.4, "Cloud Computing": 1.3, "Programming": 1.2, "Networking": 1.2}

            cert_score = 0
            for i in range(len(levels)):
                lvl = levels[i].strip()
                plat = platforms[i].strip() if i < len(platforms) else ""
                dom = domains[i].strip() if i < len(domains) else ""
                base = level_weight.get(lvl, 5)
                pw = platform_weight.get(plat, 1.0)
                dw = domain_weight.get(dom, 1.0)
                cert_score += base * pw * dw

            cert_count = float(row.get("Number_of_Certifications", 0))
            features_list.append([academic_score, cert_score, cert_count, hackathons])

        actual_X = pd.DataFrame(features_list, columns=["academic_score", "certificate_score", "certificate_count", "hackathons"])

        # Calculate targets for actual data
        actual_indices = 0.5 * actual_X["academic_score"] + 0.5 * actual_X["certificate_score"]
        actual_y = []
        for idx in actual_indices:
            idx = min(idx, 100)
            if idx < 40:
                actual_y.append(0)
            elif idx < 60:
                actual_y.append(1)
            elif idx < 80:
                actual_y.append(2)
            else:
                actual_y.append(3)
        actual_y = np.array(actual_y)

        # Generate synthetic data for robust training
        np.random.seed(42)
        num_synthetic = 1000

        sys_cgpa = np.random.uniform(5.0, 10.0, num_synthetic)
        sys_projects = np.random.randint(0, 8, num_synthetic)
        sys_papers = np.random.randint(0, 4, num_synthetic)
        sys_hackathons = np.random.randint(0, 10, num_synthetic)
        sys_cert_count = np.random.randint(0, 20, num_synthetic)

        # Generate academic score
        sys_academic = sys_cgpa * 10 + sys_projects * 4 + sys_papers * 8 + sys_hackathons * 5

        # Generate certificate score
        sys_cert_score = sys_cert_count * np.random.uniform(8.0, 18.0, num_synthetic)

        synthetic_X = pd.DataFrame({
            "academic_score": sys_academic,
            "certificate_score": sys_cert_score,
            "certificate_count": sys_cert_count.astype(float),
            "hackathons": sys_hackathons.astype(float)
        })

        # Calculate targets for synthetic data
        synthetic_indices = 0.5 * synthetic_X["academic_score"] + 0.5 * synthetic_X["certificate_score"]
        synthetic_y = []
        for idx in synthetic_indices:
            idx = min(idx, 100)
            if idx < 40:
                synthetic_y.append(0)
            elif idx < 60:
                synthetic_y.append(1)
            elif idx < 80:
                synthetic_y.append(2)
            else:
                synthetic_y.append(3)
        synthetic_y = np.array(synthetic_y)

        # Combine datasets
        X = pd.concat([actual_X, synthetic_X], ignore_index=True)
        y = np.concatenate([actual_y, synthetic_y])

        import joblib
        from sklearn.ensemble import RandomForestClassifier

        clf = RandomForestClassifier(n_estimators=100, random_state=42)
        clf.fit(X, y)

        # Save model
        joblib.dump(clf, MODEL_PATH)

        # Dynamically reload in memory
        import utils
        utils.MODEL = clf

        # Recompute skill index for all students
        master = read_master_df()
        master["skill_index"] = master.apply(compute_skill_index_for_row, axis=1)
        from utils import classify_skill_level
        master["skill_level"] = master["skill_index"].apply(classify_skill_level)
        save_master_df(master)

        return jsonify(success=True, message="Skill Index ML model retrained successfully and all student profiles updated.")

    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

@admin_bp.route("/analysis")
@admin_required
def analysis_index():
    return render_template("analysis.html")

@admin_bp.route("/analysis/upload", methods=["POST"])
def admin_analysis_upload():
    if "admin_user" not in session:
        return jsonify(success=False, message="Unauthorized"), 401

    file = request.files.get("file")
    if not file:
        return jsonify(success=False, message="No file provided")

    try:
        df = pd.read_csv(file)
        sem = request.form.get("sem")
        result = compute_analysis_from_df(df, sem)
        return jsonify(success=True, analysis=result)
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

@admin_bp.route("/analysis/bucket_students", methods=["POST"])
def analysis_bucket_students():
    if "admin_user" not in session:
        return jsonify(success=False, message="Unauthorized"), 401

    data = request.get_json()
    subject = data.get("subject")
    low = float(data.get("low", 0))
    high = float(data.get("high", 0))
    csv_text = data.get("csv")

    if not subject or csv_text is None:
        return jsonify(success=False, message="Missing parameters"), 400

    try:
        df = pd.read_csv(StringIO(csv_text))
        sem = data.get("sem")
        batch = data.get("batch")
        dept = data.get("dept")
        cgpa_type = data.get("cgpaType")
        cgpa_val = data.get("cgpaValue")

        if sem and sem != "all":
            df = df[df["Current_Sem"] == int(sem)]

        if batch and batch != "all":
            df = df[df["Batch"].astype(str).str.contains(batch, case=False)]

        if dept and dept != "all":
            df = df[df["Department"].astype(str).str.contains(dept, case=False)]

        if cgpa_type and cgpa_type != "none" and cgpa_val:
            cgpa_val = float(cgpa_val)
            if cgpa_type == "greater":
                df = df[df["CGPA"] > cgpa_val]
            elif cgpa_type == "less":
                df = df[df["CGPA"] < cgpa_val]

        raw_scores = []
        rows_for_subject = []

        for sem_num in range(1, 9):
            subj_col = f"Sem{sem_num}_Subjects"
            if subj_col not in df.columns:
                continue

            for idx, row in df.iterrows():
                subj_list = parse_list_field(row.get(subj_col, ""))
                if not subj_list:
                    continue

                ia1_list = parse_list_field(row.get(f"Sem{sem_num}_IA1", ""))
                ia2_list = parse_list_field(row.get(f"Sem{sem_num}_IA2", ""))
                model_list = parse_list_field(row.get(f"Sem{sem_num}_Model", ""))

                for i, subj in enumerate(subj_list):
                    if str(subj).strip() != subject:
                        continue

                    try:
                        ia1 = float(ia1_list[i]) if i < len(ia1_list) else 0
                    except: ia1 = 0
                    try:
                        ia2 = float(ia2_list[i]) if i < len(ia2_list) else 0
                    except: ia2 = 0
                    try:
                        model = float(model_list[i]) if i < len(model_list) else 0
                    except: model = 0

                    raw_total = ia1 + ia2 + model
                    raw_scores.append(raw_total)
                    rows_for_subject.append((row, raw_total))

        if not raw_scores:
            return jsonify(success=False, message="Subject not found"), 404

        max_raw = max(raw_scores)
        if max_raw <= 0:
            max_raw = 1

        matched = []
        for row, raw_total in rows_for_subject:
            norm = round((raw_total / max_raw) * 100, 2)
            if low <= norm <= high:
                matched.append({
                    "student_id": row.get("Student_ID"),
                    "register": row.get("Register_Number"),
                    "student_name": row.get("Student_Name"),
                    "score": norm,
                    "cgpa": row.get("CGPA"),
                })

        return jsonify(success=True, students=matched)
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

# ----------------------------------------------
# DELETE / RECYCLE BIN
# ----------------------------------------------

@admin_bp.route("/delete_students", methods=["POST"])
def delete_students():
    if "admin_user" not in session:
        return redirect(url_for("admin.login"))
    regs = request.form.getlist("reg")
    if not regs:
        flash("No students selected.")
        return redirect(url_for("admin.view_students"))

    master = read_master_df()
    recycle = read_recycle_df()
    moved = []

    for reg in regs:
        idx = master[master["Register_Number"].astype(str) == str(reg)].index
        if not idx.empty:
            row = master.loc[idx[0]].to_dict()
            row["deleted_at"] = datetime.utcnow().isoformat()
            row["deleted_by"] = session["admin_user"]
            recycle = pd.concat([recycle, pd.DataFrame([row])], ignore_index=True)
            master = master.drop(index=idx)
            moved.append(reg)

    save_master_df(master)
    save_recycle_df(recycle)
    flash(f"Moved {len(moved)} students to recycle bin.")
    return redirect(url_for("admin.view_students"))

@admin_bp.route("/recycle_bin")
@admin_required
def recycle_bin():
    df = read_recycle_df()
    students = df.to_dict(orient="records")
    return render_template("recycle_bin.html", students=students)

@admin_bp.route("/restore", methods=["POST"])
def restore():
    if "admin_user" not in session:
        return redirect(url_for("admin.login"))
    regs = request.form.getlist("reg")
    recycle = read_recycle_df()
    master = read_master_df()
    restored = []
    for reg in regs:
        idx = recycle[recycle["Register_Number"].astype(str) == str(reg)].index
        if not idx.empty:
            row = recycle.loc[idx[0]].to_dict()
            for k in ["deleted_at", "deleted_by"]:
                row.pop(k, None)
            master = pd.concat([master, pd.DataFrame([row])], ignore_index=True)
            recycle = recycle.drop(index=idx)
            restored.append(reg)
    save_master_df(master)
    save_recycle_df(recycle)
    flash(f"Restored {len(restored)} students.")
    return redirect(url_for("admin.recycle_bin"))

@admin_bp.route("/permanent_delete", methods=["POST"])
def permanent_delete():
    regs = request.form.getlist("reg")
    recycle = read_recycle_df()
    for reg in regs:
        recycle = recycle[recycle["Register_Number"].astype(str) != str(reg)]
    save_recycle_df(recycle)
    flash("Deleted permanently.")
    return redirect(url_for("admin.recycle_bin"))

@admin_bp.route("/download_master")
@admin_required
def download_master():
    if not os.path.exists(MASTER_CSV):
        flash("No data available.")
        return redirect(url_for("admin.dashboard"))
    return send_file(MASTER_CSV, as_attachment=True)

@admin_bp.route("/resumes/download_csv")
@admin_required
def download_resume_csv():
    if not os.path.exists(RESUME_DIR):
        flash("No resumes available yet.")
        return redirect(url_for("admin.dashboard"))

    master_df = read_master_df()
    has_student_lookup = not master_df.empty and "Register_Number" in master_df.columns
    resume_rows = []

    for file_name in sorted(os.listdir(RESUME_DIR)):
        file_path = os.path.join(RESUME_DIR, file_name)
        if not os.path.isfile(file_path):
            continue

        reg_no = file_name.split("_", 1)[0].strip()
        student_row = pd.DataFrame()
        if has_student_lookup:
            student_row = master_df[master_df["Register_Number"].astype(str).str.strip() == reg_no]

        student_name = ""
        department = ""
        if not student_row.empty:
            student_name = str(student_row.iloc[0].get("Student_Name", "")).strip()
            department = str(student_row.iloc[0].get("Department", "")).strip()

        resume_rows.append({
            "register_number": reg_no,
            "student_name": student_name,
            "department": department,
            "resume_file_name": file_name,
            "resume_link": request.host_url.rstrip("/") + url_for("admin.view_resume_file", filename=file_name),
            "saved_at": datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S")
        })

    if not resume_rows:
        flash("No resumes available yet.")
        return redirect(url_for("admin.dashboard"))

    export_df = pd.DataFrame(resume_rows)
    export_df.to_csv(RESUME_EXPORT_CSV, index=False)

    return send_file(
        RESUME_EXPORT_CSV,
        as_attachment=True,
        download_name="student_resumes_export.csv"
    )

@admin_bp.route("/test_results")
@admin_required
def admin_test_results():
    results_file = RESULTS_CSV
    if not os.path.exists(results_file):
        flash("No test results available yet.")
        return render_template("admin_test_results.html", results=[])

    df_results = pd.read_csv(results_file)
    df_drives = read_company_drives()
    df_drives["drive_index"] = df_drives.index

    merged = pd.merge(df_results, df_drives, on="drive_index", how="left")
    results = merged.to_dict(orient="records")

    return render_template("admin_test_results.html", results=results)

# ----------------------------------------------
# AI RESUME SEMANTIC SEARCH
# ----------------------------------------------

@admin_bp.route("/resumes/search")
@admin_required
def resume_search():
    return render_template("resume_search.html")

@admin_bp.route("/resumes/search/query", methods=["POST"])
@admin_required
def resume_search_query():
    query_text = request.form.get("query", "").strip()
    top_k = int(request.form.get("top_k", 5))

    if not query_text:
        return jsonify(success=False, message="Query is required"), 400

    try:
        from faiss_indexer import search_resumes
        raw_results = search_resumes(query_text, top_k=top_k)

        # Hydrate results with master student data details
        master_df = read_master_df()
        hydrated = []

        for item in raw_results:
            reg_no = item["register_number"]
            match = master_df[master_df["Register_Number"].astype(str).str.strip() == reg_no]
            if not match.empty:
                s_info = match.iloc[0]
                item["student_name"] = str(s_info.get("Student_Name", "Student")).strip()
                item["department"] = str(s_info.get("Department", "")).strip()
                item["cgpa"] = float(s_info.get("CGPA", 0))
                item["skill_index"] = float(s_info.get("skill_index", 0))
            else:
                item["student_name"] = "Unknown Student"
                item["department"] = "N/A"
                item["cgpa"] = "N/A"
                item["skill_index"] = "N/A"
            hydrated.append(item)

        return jsonify(success=True, results=hydrated)

    except Exception as e:
        return jsonify(success=False, message=str(e)), 500

@admin_bp.route("/resumes/search/rebuild", methods=["POST"])
@admin_required
def resume_rebuild_index():
    try:
        from faiss_indexer import build_resume_index
        success = build_resume_index()
        if success:
            return jsonify(success=True, message="FAISS semantic resume index rebuilt successfully.")
        else:
            return jsonify(success=False, message="No PDF resumes found or index build failed. Please upload resumes first.")
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT PROPOSALS & MENTORSHIP ADMIN ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/proposals", methods=["GET"])
@admin_required
def proposals():
    from models import ProjectProposal
    # Fetch all proposals sorted by submit date
    pending = ProjectProposal.query.filter_by(status="Pending Review").order_by(ProjectProposal.submitted_at.desc()).all()
    approved = ProjectProposal.query.filter(ProjectProposal.status.in_(["Approved - Select Mentor", "Mentorship Active"])).order_by(ProjectProposal.submitted_at.desc()).all()
    others = ProjectProposal.query.filter(ProjectProposal.status.in_(["Rejected", "Completed"])).order_by(ProjectProposal.submitted_at.desc()).all()

    return render_template(
        "admin_project_proposals.html",
        pending=pending,
        approved=approved,
        others=others
    )


@admin_bp.route("/proposals/review/<int:proposal_id>", methods=["POST"])
@admin_required
def review_proposal(proposal_id):
    from models import ProjectProposal, db
    proposal = ProjectProposal.query.get_or_404(proposal_id)
    action = request.form.get("action", "")
    remarks = request.form.get("remarks", "").strip()

    if action == "approve":
        proposal.status = "Approved - Select Mentor"
        flash(f"Approved project proposal: '{proposal.project_title}'!")
    elif action == "reject":
        proposal.status = "Rejected"
        flash(f"Rejected project proposal: '{proposal.project_title}'!")
    
    proposal.remarks = remarks
    proposal.reviewed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("admin.proposals"))


@admin_bp.route("/proposals/updates/<int:proposal_id>", methods=["GET", "POST"])
@admin_required
def project_updates(proposal_id):
    from models import ProjectProposal, ProjectUpdate, db
    proposal = ProjectProposal.query.get_or_404(proposal_id)

    if request.method == "POST":
        update_id = request.form.get("update_id")
        feedback = request.form.get("feedback", "").strip()
        
        p_update = ProjectUpdate.query.get_or_404(update_id)
        p_update.mentor_feedback = feedback
        db.session.commit()
        flash(f"Feedback added for Week {p_update.week_no}!")
        return redirect(url_for("admin.project_updates", proposal_id=proposal_id))

    return render_template(
        "admin_project_updates.html",
        proposal=proposal
    )


@admin_bp.route("/mentors", methods=["GET", "POST"])
@admin_required
def mentors():
    from models import Mentor, db
    
    if request.method == "POST":
        action = request.form.get("action", "")
        
        if action == "add":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            dept = request.form.get("department", "").strip()
            desig = request.form.get("designation", "").strip()
            exp = request.form.get("expertise", "").strip()
            slots = int(request.form.get("max_slots", 5))

            if not name or not email:
                flash("Name and Email are required to register a mentor.")
                return redirect(url_for("admin.mentors"))

            # Check if email is unique
            exists = Mentor.query.filter_by(email=email).first()
            if exists:
                flash(f"A mentor with email {email} already exists.")
                return redirect(url_for("admin.mentors"))

            mentor = Mentor(
                name=name,
                email=email,
                department=dept,
                designation=desig,
                expertise=exp,
                max_slots=slots
            )
            db.session.add(mentor)
            db.session.commit()
            flash(f"Successfully registered Faculty Mentor {name}!")
            return redirect(url_for("admin.mentors"))

        elif action == "delete":
            mentor_id = request.form.get("mentor_id")
            mentor = Mentor.query.get_or_404(mentor_id)
            
            # Reset any proposals mentored by this mentor back to 'Approved - Select Mentor'
            proposals = ProjectProposal.query.filter_by(mentor_id=mentor.id).all()
            for prop in proposals:
                prop.mentor_id = None
                prop.status = "Approved - Select Mentor"
                
            db.session.delete(mentor)
            db.session.commit()
            flash(f"Deleted Faculty Mentor {mentor.name}.")
            return redirect(url_for("admin.mentors"))

    all_mentors = Mentor.query.order_by(Mentor.name.asc()).all()
    return render_template("admin_mentors.html", mentors=all_mentors)


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATION BROADCAST (Admin)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/notifications", methods=["GET", "POST"])
@admin_required
def admin_notifications():
    from models import Notification, Student, db

    if request.method == "POST":
        action = request.form.get("action", "send")

        if action == "send":
            title      = request.form.get("title", "").strip()
            message    = request.form.get("message", "").strip()
            notif_type = request.form.get("notif_type", "info")
            target     = request.form.get("target", "all").strip()  # "all" or a register_number
            link       = request.form.get("link", "").strip() or None

            if not title or not message:
                flash("Title and message are required.")
                return redirect(url_for("admin.admin_notifications"))

            if target == "all":
                # Broadcast — register_number = NULL
                notif = Notification(
                    register_number=None,
                    title=title,
                    message=message,
                    notif_type=notif_type,
                    link=link
                )
                db.session.add(notif)
                db.session.commit()
                flash(f"✅ Broadcast notification sent to all students.")
            else:
                student = Student.query.filter_by(register_number=target).first()
                if not student:
                    flash(f"❌ Student with register number '{target}' not found.")
                    return redirect(url_for("admin.admin_notifications"))
                notif = Notification(
                    register_number=target,
                    title=title,
                    message=message,
                    notif_type=notif_type,
                    link=link
                )
                db.session.add(notif)
                db.session.commit()
                flash(f"✅ Notification sent to {student.student_name}.")

            return redirect(url_for("admin.admin_notifications"))

        elif action == "delete":
            notif_id = request.form.get("notif_id")
            notif = Notification.query.get_or_404(notif_id)
            db.session.delete(notif)
            db.session.commit()
            flash("Notification deleted.")
            return redirect(url_for("admin.admin_notifications"))

    all_notifs = Notification.query.order_by(Notification.created_at.desc()).limit(200).all()
    total_broadcast = Notification.query.filter_by(register_number=None).count()
    total_personal  = Notification.query.filter(Notification.register_number != None).count()
    return render_template("admin_notifications.html",
                           notifications=all_notifs,
                           total_broadcast=total_broadcast,
                           total_personal=total_personal)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNSHIP TRACKER VERIFICATION (Admin)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/internships", methods=["GET", "POST"])
@admin_required
def admin_internships():
    from models import StudentInternship, Notification, Student, db

    if request.method == "POST":
        internship_id = request.form.get("internship_id")
        action        = request.form.get("action")  # "verify" | "reject"
        internship    = StudentInternship.query.get_or_404(internship_id)

        if action == "verify":
            internship.status = "Verified"
            internship.verified_by = session["admin_user"]
            internship.verified_at = datetime.utcnow()

            # Trigger automated notification
            notif = Notification(
                register_number=internship.register_number,
                title="✅ Internship Verified!",
                message=f"Your internship at {internship.company_name} as {internship.role} ({internship.duration}) has been verified by the administrator.",
                notif_type="success",
                link="/student/internships"
            )
            db.session.add(notif)
            db.session.commit()
            flash(f"Verified internship for student {internship.register_number}.")

        elif action == "reject":
            internship.status = "Rejected"
            internship.verified_by = session["admin_user"]
            internship.verified_at = datetime.utcnow()

            # Trigger automated notification
            notif = Notification(
                register_number=internship.register_number,
                title="❌ Internship Verification Declined",
                message=f"Verification for your internship at {internship.company_name} was declined. Please verify details and contact support.",
                notif_type="error",
                link="/student/internships"
            )
            db.session.add(notif)
            db.session.commit()
            flash(f"Declined verification for internship of student {internship.register_number}.")

        return redirect(url_for("admin.admin_internships"))

    all_internships = StudentInternship.query.order_by(StudentInternship.submitted_at.desc()).all()
    pending_count = StudentInternship.query.filter_by(status="Pending Verification").count()
    verified_count = StudentInternship.query.filter_by(status="Verified").count()
    return render_template("admin_internships.html",
                           internships=all_internships,
                           pending_count=pending_count,
                           verified_count=verified_count)

