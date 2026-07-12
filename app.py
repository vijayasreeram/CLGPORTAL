
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import pandas as pd
import os
import numpy as np
import json
from io import StringIO
from flask import jsonify
from utils import (
    create_admin, verify_admin, merge_upload_df, read_master_df,
    read_recycle_df, save_master_df, save_recycle_df,
    compute_skill_index_for_row, compute_analysis_from_df, parse_list_field
    
)


from datetime import datetime
DATA_DIR = "data"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


CERT_UPLOAD_DIR = os.path.join(DATA_DIR, "certificates")
RESUME_DIR = os.path.join(DATA_DIR, "resumes")
RESUME_EXPORT_CSV = os.path.join(DATA_DIR, "resume_export.csv")
CERT_CSV = os.path.join(DATA_DIR, "certificates.csv")
os.makedirs(CERT_UPLOAD_DIR, exist_ok=True)
os.makedirs(RESUME_DIR, exist_ok=True)


MASTER_CSV = os.path.join(DATA_DIR, "master_students.csv")
RECYCLE_CSV = os.path.join(DATA_DIR, "recycle_bin.csv")
# 🔹 Company Drives CSV
COMPANY_DRIVES = os.path.join(DATA_DIR, "company_drives.csv")
TESTS_DIR = os.path.join(DATA_DIR, "tests")
RESULTS_CSV = os.path.join(DATA_DIR, "test_results.csv")

os.makedirs(TESTS_DIR, exist_ok=True) 
os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "supersecretkey123"

# ----------------------------------------------
# AUTH
# ----------------------------------------------

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if verify_admin(username, password):
            session["admin_user"] = username
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        try:
            create_admin(username, password)
            flash("Admin created! Please login.")
            return redirect(url_for("login"))
        except ValueError as e:
            flash(str(e))
    return render_template("register.html")


@app.route("/admin/certificates")
def admin_certificates():
    if "admin_user" not in session:
        return redirect(url_for("login"))

    df = pd.read_csv(CERT_CSV)
    df.columns = df.columns.str.strip()

    # 🔧 Backward compatibility for old CSVs
    if "file_name" not in df.columns:
        if "file_path" in df.columns:
            df["file_name"] = df["file_path"]
        else:
            df["file_name"] = ""

    df["file_name"] = df["file_name"].fillna("").astype(str).str.strip()

    df["certificate_id"] = df["certificate_id"].astype(int)

    pending = df[df["status"] == "pending"]

    return render_template(
        "admin_certificates.html",
        certs=pending.to_dict(orient="records")
    )
@app.route("/admin/certificates/review/<int:cert_id>", methods=["POST"])
def review_certificate(cert_id):
    if "admin_user" not in session:
        return redirect(url_for("login"))

    action = request.form.get("action")
    remarks = request.form.get("remarks", "")

    df = pd.read_csv(CERT_CSV)

    idx = df[df["certificate_id"] == cert_id].index
    if idx.empty:
        flash("Certificate not found")
        return redirect(url_for("admin_certificates"))

    df.at[idx[0], "status"] = "approved" if action == "approve" else "rejected"
    df.at[idx[0], "reviewed_by"] = session["admin_user"]
    df.at[idx[0], "reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    df.at[idx[0], "remarks"] = remarks

    df.to_csv(CERT_CSV, index=False)
    if action == "approve":
    # ------------------------------------
    # UPDATE STUDENT MASTER DATA
    # ------------------------------------
        master = read_master_df()

        cert_row = df.loc[idx[0]]
        reg_no = str(cert_row["register_number"])
        cert_name = cert_row["certificate_name"]

        student_idx = master[master["Register_Number"].astype(str) == reg_no].index

        if not student_idx.empty:
            sidx = student_idx[0]

        # 1️⃣ Update certificate count
            if "Number_of_Certifications" not in master.columns:
                master["Number_of_Certifications"] = 0

            try:
                current = int(master.at[sidx, "Number_of_Certifications"])
            except:
                current = 0

            master.at[sidx, "Number_of_Certifications"] = current + 1

        # 2️⃣ Update certificate list
            cert_col = "Certifications_List"
            if cert_col not in master.columns:
                master[cert_col] = ""

            old = str(master.at[sidx, cert_col]).strip()
            if old and old.lower() != "nan":
                master.at[sidx, cert_col] = old + ", " + cert_name
            else:
                  master.at[sidx, cert_col] = cert_name

        # 3️⃣ Recalculate Skill Index
            master.at[sidx, "skill_index"] = compute_skill_index_for_row(master.loc[sidx])

            save_master_df(master)

    

    flash(f"Certificate {action}d successfully")
    return redirect(url_for("admin_certificates"))

    df.at[idx[0], "status"] = "approved" if action == "approve" else "rejected"
    df.at[idx[0], "reviewed_by"] = session["admin_user"]
    df.at[idx[0], "reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    df.at[idx[0], "remarks"] = remarks

    df.to_csv(CERT_CSV, index=False)

    flash(f"Certificate {action}d successfully")
    return redirect(url_for("admin_certificates"))

@app.route("/logout")
def logout():
    session.pop("admin_user", None)
    flash("Logged out successfully.")
    return redirect(url_for("login"))

# ----------------------------------------------
# DASHBOARD
# ----------------------------------------------

@app.route("/certificates/view/<path:filename>")
def view_certificate_file(filename):
    file_path = os.path.join(CERT_UPLOAD_DIR, filename)
               
    if not os.path.exists(file_path):
        return "File not found", 404

    return send_file(file_path)

@app.route("/resumes/view/<path:filename>")
def view_resume_file(filename):
    if "admin_user" not in session:
        return redirect(url_for("login"))

    file_path = os.path.join(RESUME_DIR, filename)

    if not os.path.exists(file_path):
        return "File not found", 404

    return send_file(file_path)
@app.route("/dashboard")
def dashboard():
    if "admin_user" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["admin_user"])
   
@app.route("/drives")
def drives():
    if "admin_user" not in session:
        return redirect(url_for("login"))

    drives_df = read_company_drives()
    return render_template("drives.html", drives=drives_df)
@app.route("/drives/<int:drive_id>")
def view_drive_eligibility(drive_id):
    if "admin_user" not in session:
        return redirect(url_for("login"))

    drives_df = read_company_drives()

    if drive_id >= len(drives_df):
        flash("Invalid drive ID")
        return redirect(url_for("drives"))

    company = drives_df.iloc[drive_id]

    from utils import get_eligible_students_for_company
    students = get_eligible_students_for_company(company)

    # -------- Sorting logic --------
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
@app.route("/admin/assign_test/<int:drive_index>", methods=["GET", "POST"])
def admin_assign_test(drive_index):
    if "admin_user" not in session:
        return redirect(url_for("login"))

    df = load_company_drives()

    if df.empty or drive_index >= len(df):
        flash("Invalid drive index")
        return redirect(url_for("drives"))

    if request.method == "POST":
        # Uploaded files
        files = {
            "aptitude": request.files.get("aptitude_test"),
            "domain": request.files.get("domain_test"),
            "coding": request.files.get("coding_test"),
        }

        # Duration fields
        durations = {
            "aptitude": request.form.get("aptitude_duration", "30"),
            "domain": request.form.get("domain_duration", "30"),
            "coding": request.form.get("coding_duration", "30"),
        }

        # Store each file
        for test_type, uploaded_file in files.items():
            if uploaded_file and uploaded_file.filename.endswith(".csv"): # type: ignore
                filename = f"{test_type}_{drive_index}_{uploaded_file.filename}"
                file_path = os.path.join(TESTS_DIR, filename)
                uploaded_file.save(file_path)

                # Save link inside company_drives.csv
                df.at[drive_index, f"{test_type}_test_link"] = f"internal:{filename}"
                df.at[drive_index, f"{test_type}_duration"] = durations[test_type]

        save_company_drives(df)
        flash("Tests uploaded and assigned successfully!")
        return redirect(url_for("admin_assign_test", drive_index=drive_index))

    return render_template(
        "admin_assign_test.html",
        drive=df.iloc[drive_index],
        drive_index=drive_index
    )




# ----------------------------------------------
# ADD STUDENTS
# ----------------------------------------------
@app.route("/add_students", methods=["GET", "POST"])
def add_students():
    if "admin_user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        file = request.files.get("file")
        filename = getattr(file, "filename", "") if file is not None else ""
        if not filename or not filename.lower().endswith(".csv"):
            flash("Please upload a CSV file")
            return redirect(url_for("add_students"))
        df_upload = pd.read_csv(file) # type: ignore
        result = merge_upload_df(df_upload, session["admin_user"])
        flash(f"Upload complete: {result['updated']} records updated.")
        return redirect(url_for("view_students"))

    return render_template("add_students.html")

# ----------------------------------------------
# VIEW STUDENTS
# ----------------------------------------------

@app.route("/view_students", methods=["GET", "POST"])
def view_students():
    if "admin_user" not in session:
        return redirect(url_for("login"))

    df = read_master_df()
    if df.empty:
        flash("No student data available.")
        return render_template("view_students.html", students=[], semesters=[])

    # 🔹 Handle delete requests
    if request.method == "POST":
        selected = request.form.getlist("selected_students")

        if not selected:
            flash("No students selected for deletion.")
            return redirect(url_for("view_students"))

        # Load data
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
        return redirect(url_for("view_students"))


    # 🔹 Filter dropdown options
    batches = sorted(df["Batch"].dropna().unique())
    depts = sorted(df["Department"].dropna().unique())
    semesters = sorted(df["Current_Sem"].dropna().unique())

    # 🔹 Filtering logic
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



# ----------------------------------------------
# 🧩 STUDENT PROFILE PAGE
# ----------------------------------------------
@app.route("/student/<reg_no>")
def student_profile(reg_no):
    if "admin_user" not in session:
        return redirect(url_for("login"))
    
    df = read_master_df()
    if df.empty:
        flash("No student data available.")
        return redirect(url_for("view_students"))

    reg_no = str(reg_no)
    student = df[df["Register_Number"].astype(str) == reg_no]
    if student.empty:
        flash("Student not found.")
        return redirect(url_for("view_students"))

    student_data = student.to_dict(orient="records")[0]

    # 🔹 Identify semesters dynamically based on your dataset structure
    semesters = []
    for i in range(1, 11):  # up to Sem10 future-proof
        if f"Sem{i}_GPA" in df.columns:
            semesters.append(f"Sem{i}")

    return render_template(
        "student_profile.html",
        student=student_data,
        semesters=semesters
    )

# ----------------------------------------------
# CGPA ANALYSIS
# ----------------------------------------------
@app.route("/admin/analysis")
def analysis_index():
    if "admin_user" not in session:
        return redirect(url_for("login"))
    return render_template("analysis.html")
@app.route("/admin/analysis/upload", methods=["POST"])
def admin_analysis_upload():
    print("🔥 Upload Route Reached")
    if "admin_user" not in session:
        return jsonify(success=False, message="Unauthorized"), 401

    file = request.files.get("file")
    if not file:
        return jsonify(success=False, message="No file provided")

    try:
        df = pd.read_csv(file) # type: ignore
        print("🔥 DF Columns:", df.columns.tolist())

        sem = request.form.get("sem")   # <-- add this line above if not present
        result = compute_analysis_from_df(df, sem)
        return jsonify(success=True, analysis=result)

    except Exception as e:
        print("❌ ERROR in analysis:", e)
        return jsonify(success=False, message=str(e)), 500

@app.route("/admin/analysis/bucket_students", methods=["POST"])
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

        if batch:
            df = df[df["Batch"].astype(str).str.contains(batch, case=False)]

        if dept:
            df = df[df["Department"].astype(str).str.contains(dept, case=False)]

        if cgpa_type and cgpa_val:
            cgpa_val = float(cgpa_val)

            if cgpa_type == "greater":
                df = df[df["CGPA"] > cgpa_val]

            elif cgpa_type == "less":
                df = df[df["CGPA"] < cgpa_val]

        # find subject raw scores
        raw_scores = []
        rows_for_subject = []

        for sem in range(1, 9):
            subj_col = f"Sem{sem}_Subjects"
            if subj_col not in df.columns:
                continue

            for idx, row in df.iterrows():
                subj_list = parse_list_field(row.get(subj_col, ""))

                if not subj_list:
                    continue

                ia1_list = parse_list_field(row.get(f"Sem{sem}_IA1", ""))
                ia2_list = parse_list_field(row.get(f"Sem{sem}_IA2", ""))
                model_list = parse_list_field(row.get(f"Sem{sem}_Model", ""))

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
@app.route("/delete_students", methods=["POST"])
def delete_students():
    if "admin_user" not in session:
        return redirect(url_for("login"))
    regs = request.form.getlist("reg")
    if not regs:
        flash("No students selected.")
        return redirect(url_for("view_students"))

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
    return redirect(url_for("view_students"))

@app.route("/recycle_bin")
def recycle_bin():
    if "admin_user" not in session:
        return redirect(url_for("login"))
    df = read_recycle_df()
    students = df.to_dict(orient="records")
    return render_template("recycle_bin.html", students=students)
# ----------------------------------------------
# READ COMPANY DRIVES
# ----------------------------------------------
def read_company_drives():
    if not os.path.exists(COMPANY_DRIVES):
        return pd.DataFrame()
    return pd.read_csv(COMPANY_DRIVES)
def load_company_drives():
    return read_company_drives()

def save_company_drives(df):
    df.to_csv(COMPANY_DRIVES, index=False)


@app.route("/restore", methods=["POST"])
def restore():
    if "admin_user" not in session:
        return redirect(url_for("login"))
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
    return redirect(url_for("recycle_bin"))

@app.route("/permanent_delete", methods=["POST"])
def permanent_delete():
    regs = request.form.getlist("reg")
    recycle = read_recycle_df()
    for reg in regs:
        recycle = recycle[recycle["Register_Number"].astype(str) != str(reg)]
    save_recycle_df(recycle)
    flash("Deleted permanently.")
    return redirect(url_for("recycle_bin"))

@app.route("/download_master")
def download_master():
    if not os.path.exists(MASTER_CSV):
        flash("No data available.")
        return redirect(url_for("dashboard"))
    return send_file(MASTER_CSV, as_attachment=True)

@app.route("/admin/resumes/download_csv")
def download_resume_csv():
    if "admin_user" not in session:
        return redirect(url_for("login"))

    if not os.path.exists(RESUME_DIR):
        flash("No resumes available yet.")
        return redirect(url_for("dashboard"))

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
            "resume_link": request.host_url.rstrip("/") + url_for("view_resume_file", filename=file_name),
            "saved_at": datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S")
        })

    if not resume_rows:
        flash("No resumes available yet.")
        return redirect(url_for("dashboard"))

    export_df = pd.DataFrame(resume_rows)
    export_df.to_csv(RESUME_EXPORT_CSV, index=False)

    return send_file(
        RESUME_EXPORT_CSV,
        as_attachment=True,
        download_name="student_resumes_export.csv"
    )
# ----------------------------------------------
# ADMIN → VIEW ALL TEST RESULTS
# ----------------------------------------------
@app.route("/admin/test_results")
def admin_test_results():
    if "admin_user" not in session:
        return redirect(url_for("login"))

    results_file = RESULTS_CSV

    if not os.path.exists(results_file):
        flash("No test results available yet.")
        return render_template("admin_test_results.html", results=[])

    # Load test results
    df_results = pd.read_csv(results_file)

    # Load drives to attach company name
    df_drives = read_company_drives()
    df_drives["drive_index"] = df_drives.index

    # Merge
    merged = pd.merge(df_results, df_drives, on="drive_index", how="left")

    results = merged.to_dict(orient="records")

    return render_template("admin_test_results.html", results=results)

if __name__ == "__main__":
    app.run(debug=True,port=5001)
