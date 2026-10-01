# 🚀 Smart Internship & Scheme Recommendation Portal (S.I.S.R.P.)

An AI/ML-driven, gamified talent deployment and scholarship/scheme matching ecosystem built for educational institutions, corporate recruiters, and government welfare tracking.

Developed as a submission for **Build With Bharat 2.0 (Open Innovation Track)** in collaboration with NIT Delhi and CodeVerse Community.

---

## 💡 The Problem Statement
College students, especially those from underrepresented or regional colleges, face significant hurdles in starting their careers due to:
1. **Information Asymmetry:** Students are unaware of government schemes, subsidies, and corporate internships they qualify for.
2. **Static Resume Profiling:** Traditional recruitment systems filter resumes using rigid keyword matching, overlooking skilled students who lack resume formatting experience.
3. **Lack of Standardized Testing & Alignment:** Recruiting portals lack integrated testing environments aligned dynamically with Job Descriptions (JDs).

---

## 🌟 Core Innovations

Our platform addresses these challenges through **four major innovations**:

### 1. 📊 Automated Skill Indexing (`utils.py` & `badge_engine.py`)
* **Multi-Dimensional Metrics:** Dynamically computes a unified student **Skill Index** (scale of 0–100) combining academic performance (CGPA), projects completed, research publications, hackathon participations, test scores, and certification levels.
* **Hybrid Prediction Engine:** Integrates a trained **Random Forest Classifier** (`best_model.pkl`) to categorize and predict student proficiency levels, falling back on an optimized weighted mathematical formula where model outputs are unavailable.
* **Gamified Achievement Badges:** Incentivizes students by computing achievement tiers (Gold, Silver, Bronze badges for LeetCode, CodeChef, and Academics) on-the-fly without database overhead.

### 2. 🔮 AI-Driven Scheme Recommendation (`scheme_recommender.py`)
* **Eligibility & Probability Prediction:** Employs a custom Random Forest Classifier to assess a student's profile (CGPA, gender, skills, and existing certifications) and calculate their probability of qualification for various national/state schemes.
* **Automatic Skill Parsing:** Automatically extracts relevant tech skills from certifications list dates to find matches.
* **Proactive Discoverability:** Students receive real-time visibility into government/corporate schemes they are highly likely to qualify for, ensuring equal access to support programs.

### 3. 🎨 Interactive Resume Layout Selection & Real-Time Editing (`student_portal.py`)
* **Dual-Pane Real-Time Editor:** Students can modify personal details, projects, and experiences on a sidebar panel and preview changes instantly on an A4 preview sheet.
* **Layout Switcher:** Supports shifting between multiple professional layouts (e.g., **Academic**, **Corporate**, and **Modern/Creative** formats) instantly.
* **Standardized PDF Compilation:** Compiles verified profile details and user inputs directly into a clean, ATS-compliant, machine-readable PDF resume.

### 4. 🎯 Job Description (JD) Based Filtering & Testing (`company_portal.py` & `student_portal.py`)
* **Recruiter Search & Filtering:** Corporate HRs can search candidate pools semantically via a **SentenceTransformers** & **FAISS** vector search engine using natural language (e.g., *"Candidates with cloud and database scaling experience"*).
* **Targeted Assessments:** Recruiter accounts can filter students matching a Job Description (CGPA, department, skills) and assign customizable assessments (Aptitude, Domain-Specific, or Coding tests) directly through the portal.
* **Integrated Testing Sandbox:** Students take locked, time-bounded tests in their portal. Results automatically sync to the Recruiter dashboard, creating a direct, objective hiring funnel.

---

## 🛠 Tech Stack
* **Frontend:** Glassmorphic UI dashboard built with HTML5, Vanilla CSS Grid/Flexbox, and responsive JS.
* **Backend:** Multi-threaded Python Flask instance coordinator (`main_portal.py` running on ports `5000` - `5003`).
* **Database & Indexing:** SQLite (SQLAlchemy ORM) & FAISS Vector Indexing.
* **Machine Learning:** `scikit-learn` (Random Forest Models), `sentence-transformers` (all-MiniLM-L6-v2), `numpy`, `pandas`.
* **Resume Parsing & Compilation:** `pdfplumber` (reading/indexing), `reportlab` (generating PDF resumes).

---

## 🧱 Project Architecture & Portals
The application launches a central gateway on port `5000` which manages three independent Flask threads:
1. **Central Gateway (`port 5000`):** Simple, premium home interface directing users to Admin, Student, or Recruiter entries.
2. **Admin Portal (`port 5001`):** For institutional coordinators to approve student certifications, manage student databases, create test files, and view cumulative stats.
3. **Student Portal (`port 5002`):** For students to manage profiles, view their skill badges, edit & download resumes, take assigned tests, and view recommended schemes.
4. **Recruiter Portal (`port 5003`):** For HR reps to create job drives, filter candidates, view test results, and run semantic queries across student resumes.

---

## 🏃 Setup & Installation

### Prerequisites
Make sure you have Python 3.8+ installed on your system.

### 1. Clone the Repository
```bash
git clone https://github.com/<your-username>/internshipportal-master.git
cd internshipportal-master
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Initialize Database and ML Model
Run the migration script to populate data files (from CSVs to the SQLite database):
```bash
python db_init.py
```

### 4. Run the Project
Start all portals simultaneously:
```bash
python main_portal.py
```
Open your browser and navigate to `http://localhost:5000` to access the central gateway.
