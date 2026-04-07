"""
forms/resolver.py — Answers any form question.

Priority chain:
  1. data/answers.json  (your saved answers)
  2. Built-in map       (name, email, phone, education, etc.)
  3. Regex heuristics   (why this company, tell me about yourself, etc.)
  4. Ollama AI          (local model, resume + JD context)
  5. Telegram ask       (sends to your phone, waits, saves reply)
  6. Empty string       (leave blank rather than fill garbage)
"""
import re, asyncio
from config.settings import ME
from forms.answers import get as ans_get, store as ans_store

# ── 2. Built-in static answers ────────────────────────────────

def _builtin(label: str) -> str | None:
    ll = label.lower().strip()

    mapping = {
        # Identity
        ("full name", "your name", "name"):
            ME["full_name"],
        ("first name",):
            ME["first_name"],
        ("last name", "surname", "family name"):
            ME["last_name"],
        ("email", "e-mail", "email address"):
            ME["email"],
        ("phone", "mobile", "contact number", "phone number"):
            ME["phone"],

        # Links
        ("linkedin", "linkedin url", "linkedin profile"):
            ME["linkedin"],
        ("github", "github url", "github profile"):
            ME["github"],
        ("portfolio", "website", "personal website"):
            ME["portfolio"] or ME["github"],

        # Location
        ("location", "current location", "city", "current city", "where are you based"):
            ME["city"],
        ("country",):
            "India",
        ("state",):
            "Tamil Nadu",
        ("pin", "pincode", "zip", "postal"):
            "600000",

        # Work
        ("notice period", "joining time", "availability", "when can you join"):
            ME["notice_period"],
        ("current ctc", "current salary", "current compensation"):
            ME["current_ctc"],
        ("expected ctc", "expected salary", "salary expectation", "desired salary"):
            ME["expected_ctc"],
        ("years of experience", "total experience", "work experience", "years exp"):
            ME["years_exp"],
        ("current company", "current employer", "current organisation"):
            "Fresher / Not currently employed",
        ("current role", "current designation", "current title"):
            "B.Tech Student",
        ("reason for leaving", "why leaving"):
            "I am a fresh graduate looking for my first full-time role.",

        # Education
        ("highest qualification", "highest education", "degree", "qualification"):
            ME["degree"],
        ("branch", "specialisation", "major", "stream", "field of study"):
            ME["branch"],
        ("university", "college", "institution", "school"):
            ME["college"],
        ("cgpa", "gpa", "percentage", "marks", "grade"):
            ME["cgpa"],
        ("graduation year", "passing year", "year of passing", "batch"):
            ME["grad_year"],
        ("10th percentage", "sslc", "class 10"):
            "85",
        ("12th percentage", "hsc", "class 12", "plus two"):
            "80",

        # Skills
        ("skills", "technical skills", "key skills", "core skills"):
            ME["skills"],
        ("programming languages", "languages known"):
            "Python, TypeScript, JavaScript",

        # Common yes/no
        ("authorized to work", "work authorization", "eligible to work in india"):
            "Yes",
        ("require sponsorship", "visa sponsorship", "need sponsorship"):
            "No",
        ("willing to relocate", "open to relocation", "can relocate"):
            "Yes",
        ("willing to work remotely", "open to remote", "remote work"):
            "Yes",
        ("willing to travel", "open to travel"):
            "Yes, occasional travel is fine.",
        ("background check", "consent to background", "background verification"):
            "Yes",
        ("agree to terms", "accept terms", "i agree"):
            "Yes",
        ("disability", "person with disability", "pwd"):
            "No",
        ("gender",):
            "Male",
        ("how did you hear", "how did you find", "source of application", "referred by"):
            "Job notification via Telegram",
    }

    for keys, value in mapping.items():
        if any(k in ll for k in keys):
            return value
    return None


# ── 3. Regex heuristics ───────────────────────────────────────

def _heuristic(label: str) -> str | None:
    ll = label.lower()

    if re.search(r"why.*(apply|join|interest|want|choose|this (company|role|job))", ll):
        return (
            f"I'm excited about this opportunity because it aligns with my "
            f"background in {ME['branch']}. I want to contribute to a team "
            f"that ships real products and values engineering quality."
        )

    if re.search(r"(tell|describe|about) (me |your)?self", ll):
        projs = ME["projects"][0] if ME["projects"] else "various software projects"
        return (
            f"I'm {ME['full_name']}, a B.Tech graduate in {ME['branch']} "
            f"from {ME['college']} (Class of {ME['grad_year']}). "
            f"I have hands-on experience in {ME['skills'].split(',')[0].strip()}, "
            f"and my notable project is {projs}."
        )

    if re.search(r"strength", ll):
        return (
            "Problem-solving, fast learning, and building systems from scratch. "
            "I enjoy going from 0 to 1 on complex technical challenges."
        )

    if re.search(r"weakness", ll):
        return (
            "I sometimes over-engineer early on. I've been improving by "
            "shipping MVPs first and iterating based on real feedback."
        )

    if re.search(r"(5|five).?year", ll):
        return (
            "In 5 years I aim to be a senior engineer leading technical "
            "decisions on AI or distributed systems, having shipped "
            "products used at real scale."
        )

    if re.search(r"(project|work|experience).*(describe|tell|explain|highlight)", ll):
        if ME["projects"]:
            return ME["projects"][0]
        return "I built several full-stack and AI projects during my degree."

    if re.search(r"(greatest|proudest|best).*(achievement|accomplishment)", ll):
        if ME["projects"]:
            return ME["projects"][0]
        return "My B.Tech final year project which I built entirely from scratch."

    if re.search(r"(certif|course|training)", ll):
        return "I have completed online courses in Python, machine learning, and cloud fundamentals."

    if re.search(r"(hobbies|interests|outside work)", ll):
        return "Competitive programming, building side projects, and contributing to open source."

    if re.search(r"(references|reference available)", ll):
        return "Available upon request."

    if re.search(r"(cover letter|motivation letter|statement of purpose)", ll):
        return ""   # handled separately by cover letter generator

    if re.search(r"(agree|accept|confirm|acknowledge|consent|certify)", ll):
        return "Yes"

    if re.search(r"(number of|how many).*(year|month)", ll):
        return "0"

    if re.search(r"sponsor|visa|permit", ll):
        return "No sponsorship required — Indian citizen."

    return None


# ── 4. Ollama AI fallback ─────────────────────────────────────

def _ask_ollama(label: str, resume_text: str, jd_context: str) -> str:
    try:
        import requests
        prompt = (
            f"You are helping a fresher software engineer fill a job application.\n"
            f"Candidate: {ME['full_name']}, B.Tech CSE, {ME['college']}, "
            f"graduating {ME['grad_year']}.\n"
            f"Skills: {ME['skills']}\n"
            f"Projects: {'; '.join(ME['projects'])}\n\n"
            f"Job context: {jd_context[:400]}\n\n"
            f"Question: {label}\n\n"
            f"Write a concise, honest, 2-4 sentence answer. "
            f"Return ONLY the answer text, no preamble."
        )
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "llama3", "prompt": prompt,
                  "stream": False, "options": {"temperature": 0.3}},
            timeout=60,
        )
        return r.json().get("response", "").strip()
    except Exception:
        return ""


# ── Main resolver ─────────────────────────────────────────────

async def resolve(label: str, company: str = "",
                  resume_text: str = "", jd_context: str = "") -> str:
    """
    Return the best answer for a form question label.
    Goes through the full priority chain.
    """
    if not label or not label.strip():
        return ""

    label = label.strip().rstrip("*:").strip()

    # 1. Saved answers (highest priority)
    saved = ans_get(label)
    if saved:
        return saved

    # 2. Built-in static map
    builtin = _builtin(label)
    if builtin is not None:
        return builtin

    # 3. Heuristics
    heuristic = _heuristic(label)
    if heuristic is not None:
        return heuristic

    # 4. AI
    ai_guess = _ask_ollama(label, resume_text, jd_context)

    # 5. Ask via Telegram — send question + AI guess, wait for reply
    try:
        from telegram.bot import ask_question
        reply = await ask_question(label, company or "the company", ai_guess)
        if reply:
            ans_store(label, reply)   # save for next time
            return reply
    except Exception as e:
        print(f"  ⚠  Telegram ask failed: {e}")

    # 6. Return AI guess even without confirmation
    if ai_guess:
        print(f"  🤖  AI fallback for: '{label[:50]}'")
        return ai_guess

    return ""


# ── Dropdown / radio helpers ──────────────────────────────────

PREFER = [
    "yes", "india", "bangalore", "chennai", "hyderabad",
    "immediate", "fresher", "0", "0-1", "b.tech", "bachelor",
    "full time", "permanent", "male", "2026",
]

def best_option(options: list[str]) -> str | None:
    """Pick the most appropriate dropdown option."""
    opts_lower = [o.lower().strip() for o in options]
    for pref in PREFER:
        for i, opt in enumerate(opts_lower):
            if pref in opt:
                return options[i]
    non_blank = [o for o in options if o.strip()
                 and "select" not in o.lower()
                 and "--" not in o]
    return non_blank[0] if non_blank else None


def should_check(radio_label: str) -> bool:
    """Should we select this radio button?"""
    l = radio_label.lower()
    yes_signals = ["yes", "agree", "india", "bangalore", "chennai",
                   "immediate", "open", "available", "full.?time", "male"]
    no_signals  = [r"\bno\b", "disagree", "not applicable"]
    for s in yes_signals:
        if re.search(s, l):
            return True
    for s in no_signals:
        if re.search(s, l):
            return False
    return False
