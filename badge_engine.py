"""
badge_engine.py — Gamification Badge Computation Engine
Computes earned badges for a student dict on-the-fly.
No database table required — badges are derived from existing student data.
"""

# ─────────────────────────────────────────────────────────────────
# Badge Definitions
# Each badge has:
#   id       : unique key
#   icon     : emoji
#   name     : display title
#   desc     : short description
#   color    : CSS hex accent color
#   tier     : "gold" | "silver" | "bronze" | "special"
#   check(s) : function that takes the student dict and returns True/False
# ─────────────────────────────────────────────────────────────────

def _safe_int(val, default=0):
    try:
        v = int(val)
        return v
    except (TypeError, ValueError):
        return default

def _safe_float(val, default=0.0):
    try:
        v = float(val)
        return v
    except (TypeError, ValueError):
        return default


BADGE_DEFINITIONS = [
    # ── Coding ─────────────────────────────────────────────────────
    {
        "id": "lc_100",
        "icon": "💻",
        "name": "LeetCode Starter",
        "desc": "Solved 100+ problems on LeetCode",
        "color": "#f6ad55",
        "tier": "bronze",
        "check": lambda s: _safe_int(s.get("LeetCode_Problems_Solved")) >= 100,
    },
    {
        "id": "lc_300",
        "icon": "⚡",
        "name": "LeetCode 300 Club",
        "desc": "Solved 300+ problems on LeetCode",
        "color": "#e2b04a",
        "tier": "silver",
        "check": lambda s: _safe_int(s.get("LeetCode_Problems_Solved")) >= 300,
    },
    {
        "id": "lc_500",
        "icon": "🏆",
        "name": "LeetCode 500 Club",
        "desc": "Solved 500+ problems on LeetCode",
        "color": "#e2b04a",
        "tier": "gold",
        "check": lambda s: _safe_int(s.get("LeetCode_Problems_Solved")) >= 500,
    },
    {
        "id": "cc_1500",
        "icon": "🌟",
        "name": "CodeChef 1500+",
        "desc": "Achieved a CodeChef rating of 1500 or above",
        "color": "#63b3ed",
        "tier": "silver",
        "check": lambda s: _safe_int(s.get("CodeChef_Rating")) >= 1500,
    },
    {
        "id": "cc_2000",
        "icon": "💎",
        "name": "CodeChef Elite",
        "desc": "Achieved a CodeChef rating of 2000 or above",
        "color": "#805ad5",
        "tier": "gold",
        "check": lambda s: _safe_int(s.get("CodeChef_Rating")) >= 2000,
    },

    # ── Academic ───────────────────────────────────────────────────
    {
        "id": "cgpa_85",
        "icon": "📚",
        "name": "Dean's List",
        "desc": "Maintained a CGPA of 8.5 or above",
        "color": "#68d391",
        "tier": "silver",
        "check": lambda s: _safe_float(s.get("CGPA")) >= 8.5,
    },
    {
        "id": "cgpa_90",
        "icon": "🎓",
        "name": "Academic Excellence",
        "desc": "Maintained a CGPA of 9.0 or above — Top tier scholar",
        "color": "#38a169",
        "tier": "gold",
        "check": lambda s: _safe_float(s.get("CGPA")) >= 9.0,
    },

    # ── Research & Projects ────────────────────────────────────────
    {
        "id": "projects_3",
        "icon": "🔧",
        "name": "Builder",
        "desc": "Completed 3 or more projects",
        "color": "#f6ad55",
        "tier": "bronze",
        "check": lambda s: _safe_int(s.get("Projects_Done")) >= 3,
    },
    {
        "id": "projects_6",
        "icon": "🚀",
        "name": "Project Pro",
        "desc": "Completed 6 or more projects",
        "color": "#e2b04a",
        "tier": "silver",
        "check": lambda s: _safe_int(s.get("Projects_Done")) >= 6,
    },
    {
        "id": "researcher",
        "icon": "🔬",
        "name": "Researcher",
        "desc": "Published 1 or more research papers",
        "color": "#63b3ed",
        "tier": "silver",
        "check": lambda s: _safe_int(s.get("Research_Papers_Published")) >= 1,
    },
    {
        "id": "senior_researcher",
        "icon": "🔭",
        "name": "Senior Researcher",
        "desc": "Published 3 or more research papers",
        "color": "#805ad5",
        "tier": "gold",
        "check": lambda s: _safe_int(s.get("Research_Papers_Published")) >= 3,
    },
    {
        "id": "patent",
        "icon": "📋",
        "name": "Inventor",
        "desc": "Granted 1 or more patents",
        "color": "#f6ad55",
        "tier": "gold",
        "check": lambda s: _safe_int(s.get("Patents_Granted")) >= 1,
    },

    # ── Hackathons & Competitions ──────────────────────────────────
    {
        "id": "hackathon_3",
        "icon": "🏅",
        "name": "Hackathon Hero",
        "desc": "Participated in 3 or more hackathons",
        "color": "#f6ad55",
        "tier": "silver",
        "check": lambda s: _safe_int(s.get("Hackathons_Participated")) >= 3,
    },
    {
        "id": "hackathon_5",
        "icon": "⚔️",
        "name": "Hackathon Veteran",
        "desc": "Participated in 5 or more hackathons",
        "color": "#e2b04a",
        "tier": "gold",
        "check": lambda s: _safe_int(s.get("Hackathons_Participated")) >= 5,
    },
    {
        "id": "hackathon_winner",
        "icon": "🥇",
        "name": "Hackathon Champion",
        "desc": "Won or placed in Top 100 at a hackathon",
        "color": "#e2b04a",
        "tier": "gold",
        "check": lambda s: _safe_int(s.get("Hackathons_Won_Top100")) >= 1,
    },

    # ── Certifications ─────────────────────────────────────────────
    {
        "id": "certs_3",
        "icon": "📜",
        "name": "Certified",
        "desc": "Earned 3 or more certifications",
        "color": "#68d391",
        "tier": "bronze",
        "check": lambda s: _safe_int(s.get("Number_of_Certifications")) >= 3,
    },
    {
        "id": "certs_8",
        "icon": "🏅",
        "name": "Certification Master",
        "desc": "Earned 8 or more certifications",
        "color": "#e2b04a",
        "tier": "gold",
        "check": lambda s: _safe_int(s.get("Number_of_Certifications")) >= 8,
    },

    # ── Skill Index ────────────────────────────────────────────────
    {
        "id": "skill_star",
        "icon": "⭐",
        "name": "Skill Star",
        "desc": "Achieved a Skill Index score of 70 or above",
        "color": "#e2b04a",
        "tier": "silver",
        "check": lambda s: _safe_float(s.get("skill_index")) >= 70,
    },
    {
        "id": "elite_performer",
        "icon": "🌠",
        "name": "Elite Performer",
        "desc": "Achieved a Skill Index score of 85 or above — Top 10%",
        "color": "#805ad5",
        "tier": "gold",
        "check": lambda s: _safe_float(s.get("skill_index")) >= 85,
    },

    # ── Communication & Aptitude ───────────────────────────────────
    {
        "id": "communicator",
        "icon": "🗣️",
        "name": "Communicator",
        "desc": "Avg Communication Score of 85 or above",
        "color": "#63b3ed",
        "tier": "silver",
        "check": lambda s: _safe_float(s.get("Avg_Communication_Score")) >= 85,
    },
    {
        "id": "aptitude_ace",
        "icon": "🧠",
        "name": "Aptitude Ace",
        "desc": "Weekly Aptitude Average of 85% or above",
        "color": "#68d391",
        "tier": "silver",
        "check": lambda s: _safe_float(s.get("Weekly_Aptitude_Avg")) >= 85,
    },

    # ── Special / Composite ────────────────────────────────────────
    {
        "id": "all_rounder",
        "icon": "🌟",
        "name": "All-Rounder",
        "desc": "Strong in Coding, Academics, Projects, and Soft Skills",
        "color": "#e2b04a",
        "tier": "special",
        "check": lambda s: (
            _safe_float(s.get("CGPA")) >= 8.0 and
            _safe_int(s.get("LeetCode_Problems_Solved")) >= 100 and
            _safe_int(s.get("Projects_Done")) >= 2 and
            _safe_float(s.get("Avg_Communication_Score")) >= 70
        ),
    },
    {
        "id": "placement_ready",
        "icon": "💼",
        "name": "Placement Ready",
        "desc": "Meets all key placement criteria — CGPA, Coding, Skills",
        "color": "#38a169",
        "tier": "special",
        "check": lambda s: (
            _safe_float(s.get("CGPA")) >= 7.5 and
            _safe_int(s.get("LeetCode_Problems_Solved")) >= 50 and
            _safe_int(s.get("Number_of_Certifications")) >= 1 and
            _safe_float(s.get("skill_index")) >= 50
        ),
    },
    {
        "id": "internship_verified",
        "icon": "💼",
        "name": "Verified Intern",
        "desc": "Completed at least one verified industry internship",
        "color": "#38a169",
        "tier": "special",
        "check": lambda s: _safe_int(s.get("verified_internships_count")) >= 1,
    },
]


def compute_badges(student: dict) -> list:
    """
    Given a student dict (as returned by the dashboard route),
    return a list of earned badge dicts.
    """
    earned = []
    for badge in BADGE_DEFINITIONS:
        try:
            if badge["check"](student):
                earned.append({
                    "id": badge["id"],
                    "icon": badge["icon"],
                    "name": badge["name"],
                    "desc": badge["desc"],
                    "color": badge["color"],
                    "tier": badge["tier"],
                })
        except Exception:
            pass
    return earned


def compute_badge_summary(badges: list) -> dict:
    """Returns counts by tier for the summary bar."""
    return {
        "total": len(badges),
        "gold": sum(1 for b in badges if b["tier"] == "gold"),
        "silver": sum(1 for b in badges if b["tier"] == "silver"),
        "bronze": sum(1 for b in badges if b["tier"] == "bronze"),
        "special": sum(1 for b in badges if b["tier"] == "special"),
    }
