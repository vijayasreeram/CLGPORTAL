"""
Consolidated Flask application — Single Server Entry Point
Runs on Port 5000 (configurable via .env). All portals accessible via URL prefixes:
  /admin   → Admin Portal
  /student → Student Portal
  /company → Company Portal
"""

import os
from flask import Flask, render_template
from dotenv import load_dotenv
from models import db  # SQLAlchemy instance

# Load environment variables from .env file
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# -----------------------------------------------
# SQLAlchemy — SQLite database configuration
# -----------------------------------------------
DB_PATH = os.path.join(DATA_DIR, "portal.db")
app.config["SQLALCHEMY_DATABASE_URI"]        = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"]      = {"connect_args": {"check_same_thread": False}}

db.init_app(app)

# Secret key loaded from .env — never hardcoded
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_change_this_in_production")

# -----------------------------------------------
# Register Blueprints with URL prefixes
# -----------------------------------------------
from blueprints.admin   import admin_bp
from blueprints.student import student_bp
from blueprints.company import company_bp

app.register_blueprint(admin_bp,   url_prefix="/admin")
app.register_blueprint(student_bp, url_prefix="/student")
app.register_blueprint(company_bp, url_prefix="/company")


# -----------------------------------------------
# Main Landing Page
# -----------------------------------------------
@app.route("/")
def home():
    return render_template("main_portal.html")


# -----------------------------------------------
# DB Init + one-time CSV migration on startup
# -----------------------------------------------
with app.app_context():
    db.create_all()                        # create tables if they don't exist
    
    # ── Database schema patch ─────────────────────────────────────────────
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            for col, col_type in [
                ("resume_email", "VARCHAR(100)"),
                ("resume_phone", "VARCHAR(50)"),
                ("resume_linkedin", "VARCHAR(200)"),
                ("resume_github", "VARCHAR(200)"),
                ("resume_summary", "TEXT"),
                ("resume_work_experience", "TEXT")
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE students ADD COLUMN {col} {col_type}"))
                    conn.commit()
                except Exception:
                    pass  # Column already exists
    except Exception as _schema_err:
        print(f"[Schema Patch Warning] {_schema_err}")

    _sentinel = os.path.join(DATA_DIR, ".db_migrated")
    if not os.path.exists(_sentinel):
        try:
            from db_init import run_migration
            print("\n[Migration] First run -- migrating CSV data to SQLite...\n")
            run_migration(app, db)
            open(_sentinel, "w").write("done")    # mark migration as done
        except Exception as _e:
            print(f"[Migration Warning] {_e}")

    # Seed sample Mentors if empty
    try:
        from models import Mentor
        if Mentor.query.count() == 0:
            db.session.add_all([
                Mentor(name="Dr. Arul Prasad", email="arul.prasad@cit.edu", department="CSE", designation="Associate Professor", expertise="Machine Learning, Deep Learning, NLP", max_slots=5),
                Mentor(name="Prof. Meera Nair", email="meera.nair@cit.edu", department="IT", designation="Assistant Professor", expertise="Full Stack Web Dev, Cloud Computing, DevOps", max_slots=5),
                Mentor(name="Dr. Rajesh Kumar", email="rajesh.kumar@cit.edu", department="ECE", designation="Professor", expertise="IoT, Embedded Systems, Robotics", max_slots=5),
                Mentor(name="Prof. Sarah D'Souza", email="sarah.dsouza@cit.edu", department="CSE", designation="Assistant Professor", expertise="Cyber Security, Cryptography, Blockchain", max_slots=5)
            ])
            db.session.commit()
            print("[Mentors Seed] Seeded sample faculty mentors successfully!")
    except Exception as _seed_err:
        print(f"[Mentors Seed Warning] Seeding mentors failed: {_seed_err}")




if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "True").lower() == "true"
    print("\n" + "="*60)
    print("  Internship Portal — Consolidated Server")
    print("="*60)
    print(f"  Admin  Portal : http://localhost:{port}/admin")
    print(f"  Student Portal: http://localhost:{port}/student")
    print(f"  Company Portal: http://localhost:{port}/company")
    print("="*60 + "\n")
    app.run(debug=debug, port=port)
