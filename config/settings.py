# ============================================================
#  JOB BOT — SETTINGS
# ============================================================

ME = {
    "full_name":     "Kaushik M",
    "first_name":    "Kaushik",
    "last_name":     "M",
    "email":         "kaushikmuthumani10@gmail.com",
    "phone":         "+91 9345692899",
    "location":      "Salem, India",
    "city":          "Salem",
    "linkedin":      "https://www.linkedin.com/in/kaushik-m-29320324b/",
    "github":        "https://github.com/KaushikMuthumani",
    "portfolio":     "https://kaushikmuthumani.github.io/portfolio/",

    "notice_period": "Immediate",
    "current_ctc":   "Fresher",
    "expected_ctc":  "As per company norms",
    "years_exp":     "0",
    "experience":    "Fresher",

    "degree":        "B.Tech",
    "branch":        "Computer Science and Engineering",
    "college":       "Amrita Vishwa Vidyapeetham",
    "cgpa":          "7.25",
    "grad_year":     "2026",

    "projects": [
        "EdgeDet — eBPF-based IoT Intrusion Detection System detecting anomalies with sub-2ms overhead",
        "Automated API Validation Agent using Composio SDK, Bun runtime, OAuth-connected Gmail and Google Calendar",
        "ContextCode — VS Code extension for managing AI coding context across Cursor, Claude, and Cline",
    ],
    "skills": "Python, TypeScript, Node.js, FastAPI, React, eBPF, Docker, Git, LLM APIs, Playwright",
}

# ── Resumes ───────────────────────────────────────────────────
# General fallback — used when no specific match found
RESUME_PDF = "config/resumes/resume_general.pdf"

# Role-specific resumes — keyword matched against job title (lowercase)
# Put your PDFs in config/resumes/ folder
RESUME_MAP = {
    "sre":         "config/resumes/resume_sre.pdf",
    "reliability": "config/resumes/resume_sre.pdf",
    "devops":      "config/resumes/resume_sre.pdf",
    "platform":    "config/resumes/resume_sre.pdf",
    "cloud":       "config/resumes/resume_sre.pdf",

    "security":    "config/resumes/resume_security.pdf",
    "appsec":      "config/resumes/resume_security.pdf",
    "pentest":     "config/resumes/resume_security.pdf",

    "ai":          "config/resumes/resume_ai.pdf",
    "ml":          "config/resumes/resume_ai.pdf",
    "machine learning": "config/resumes/resume_ai.pdf",
    "llm":         "config/resumes/resume_ai.pdf",
    "agent":       "config/resumes/resume_ai.pdf",
    "data scientist": "config/resumes/resume_ai.pdf",

    "analyst":     "config/resumes/resume_ba.pdf",
    "business":    "config/resumes/resume_ba.pdf",
    "product":     "config/resumes/resume_ba.pdf",

    # Everything else (sde, backend, fullstack, intern, graduate etc.)
    # falls through to RESUME_PDF (general)
}


def get_resume(job_title: str) -> str:
    """Return the best matching resume path for a job title."""
    import os
    title = job_title.lower()
    for keyword, path in RESUME_MAP.items():
        if keyword in title:
            if os.path.exists(path):
                return path
    return RESUME_PDF


# ── Telegram USER account (my.telegram.org) ──────────────────
TELEGRAM_USER = {
    "api_id":       33334343,            # number from my.telegram.org
    "api_hash":     "1b55ea392376bc91e1e859532d542fc0",           # string from my.telegram.org
    "phone":        "+91 9345692899",
    "session_file": "data/user.session",
    "groups": [
        "TechUprise_Updates"
    ],
    "lookback_days": 5,           # scan past 5 days of messages
}

# ── Telegram BOT (@BotFather) — notifications to your phone ──
TELEGRAM_BOT = {
    "token":   "8663259775:AAFHLfcrCAlEevNcMNcL_ag74KiBvzzfPQU",   # from @BotFather
    "chat_id": 1917055511,    # run: python get_chat_id.py
}

# ── Job filter — what to apply to ────────────────────────────
# BROAD on purpose — you're a fresher, cast wide net
# Only hard-blocked roles are filtered out (see SKIP_IF below)
APPLY_TO = [
    # Core SWE
    "software engineer", "software developer", "software development",
    "associate software", "junior software",
    "sde", "swe", "mts", "member of technical staff",
    # Backend / Full stack / Frontend
    "backend", "full stack", "fullstack", "full-stack",
    "frontend", "front end", "front-end",
    # Intern (YOU WANT THESE)
    "intern", "internship", "trainee",
    # Graduate / Fresher
    "graduate engineer", "graduate developer", "graduate software",
    "technology graduate", "tech graduate", "campus hire",
    "fresher", "entry level", "associate engineer",
    "junior engineer", "junior developer",
    # AI / ML / Data
    "ai engineer", "ml engineer", "machine learning",
    "llm", "data engineer", "data scientist", "nlp",
    # Infra / DevOps / SRE
    "devops", "platform engineer", "sre", "site reliability",
    "cloud engineer", "infrastructure",
    # Security
    "security engineer", "appsec", "application security",
    # Generic catches
    "engineer", "developer", "programmer",
]

# Hard stop — skip if title contains any of these
SKIP_IF = [
    "senior ", " sr.", "lead engineer", "principal ",
    "staff engineer", "engineering manager",
    "vp ", "vice president", "director ", "head of",
    "5+ years", "6+ years", "7+ years", "8+ years", "10+ years",
    "5 years experience", "6 years experience",
]

MAX_PER_DAY = 30
HEADLESS    = False   # False = you watch the browser, solve CAPTCHA yourself
SLOW_MO     = 40

# ── Chrome profile (IMPORTANT — read this) ───────────────────
# Using your real Chrome profile means:
#   - You're already logged into Google
#   - "Sign in with Google" works on every site automatically
#   - Sites you've visited before have your cookies
#   - Your saved passwords are available
#
# How to find your profile path:
#   1. Open Chrome
#   2. Go to:  chrome://version
#   3. Look for "Profile Path"
#   4. Copy everything EXCEPT the last folder (e.g. "Default")
#
# Example on Windows:
#   C:\\Users\\KAUSHIK\\AppData\\Local\\Google\\Chrome\\User Data
#
# Example on Mac:
#   /Users/kaushik/Library/Application Support/Google/Chrome
#
# Example on Linux:
#   /home/kaushik/.config/google-chrome
#
# CHROME_PROFILE_NAME is the profile folder name inside User Data.
# Usually "Default" for your main profile.
# Check chrome://version — last part of "Profile Path" is the name.

CHROME_PROFILE      = r"C:\Users\KAUSHIK\AppData\Local\Google\Chrome\User Data"
CHROME_PROFILE_NAME = "Profile 4"   # the profile folder name
