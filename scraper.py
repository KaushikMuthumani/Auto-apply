"""
telegram/scraper.py — Telegram group job scraper.

Handles:
  - Single-job messages (structured with Company:/Role: labels)
  - "X is hiring Y" pattern
  - Multi-job messages (numbered lists, emoji-separated blocks)
  - Persistent queue (unapplied jobs carry over to next run)
"""
import re, json, os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from config.settings import TELEGRAM_USER

_URL_RE = re.compile(r"https?://[^\s\)\]\>\"\'\,\|\<]+")
QUEUE_FILE = "data/queue.json"


@dataclass
class Job:
    company:   str
    title:     str
    location:  str
    url:       str
    source:    str
    posted_at: str
    raw_text:  str = ""


# ── Queue ─────────────────────────────────────────────────────

def load_queue() -> list[Job]:
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, encoding="utf-8") as f:
            return [Job(**d) for d in json.load(f)]
    except Exception:
        return []

def save_queue(jobs: list[Job]):
    os.makedirs("data", exist_ok=True)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump([asdict(j) for j in jobs], f, indent=2, ensure_ascii=False)
    if jobs:
        print(f"  📋  {len(jobs)} jobs queued for next run")

def clear_queue():
    if os.path.exists(QUEUE_FILE):
        os.remove(QUEUE_FILE)


# ── URL scoring ───────────────────────────────────────────────

ATS_DOMAINS = [
    "greenhouse.io", "lever.co", "ashbyhq.com",
    "myworkdayjobs.com", "wd3.myworkdayjobs", "wd5.myworkdayjobs",
    "workday.com", "fa.oraclecloud.com",
    "smartrecruiters.com", "jobvite.com", "icims.com",
    "eightfold.ai", "ats.rippling.com", "keka.com",
    "amazon.jobs", "careers.google.com",
    "careers.microsoft.com", "apply.careers.microsoft.com",
    "careers.mastercard.com", "careers.salesforce.com",
    "geaerospace.com", "jobs.boeing.com",
    "careerzenith.ai", "taleo.net", "successfactors",
    "workable.com", "phenom", "njoyn.com",
    "relx.wd", "wipro.com/job", "honeywell",
]

SKIP_DOMAINS = [
    "t.me/", "telegram.me/", "twitter.com", "x.com",
    "youtube.com", "instagram.com", "facebook.com",
    "docs.google.com/forms", "forms.gle",
    "growthschool.io", "topmate.io",
    "bit.ly", "tinyurl.com", "lnkd.in",
    "freshershunt.in",          # landing page aggregator
    "unstop.com",
    "fhlinks.in", "hirist.tech",
]

def _score(url: str) -> int:
    u = url.lower()
    if any(s in u for s in SKIP_DOMAINS):
        return -1
    score = 0
    if any(a in u for a in ATS_DOMAINS):
        score += 20
    if re.search(r"/(job|jobs|careers?|apply|opening|position)/", u):
        score += 8
    if re.search(r"(job_?id|jid|req_?id|gh_jid|jobid|job-\d)=?", u):
        score += 5
    if len(url) > 50:
        score += 3
    return score

def _best_url(urls: list[str]) -> str | None:
    scored = [(u, _score(u)) for u in urls if _score(u) >= 0]
    if not scored:
        return None
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored[0][1] > 0 else None


# ── Text cleaning ─────────────────────────────────────────────

def _strip(text: str) -> str:
    """Remove emoji, markdown, and clean up whitespace."""
    # Remove emoji (unicode ranges)
    text = re.sub(
        r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        r"\U00002702-\U000027B0\U000024C2-\U0001F251"
        r"\U0001f926-\U0001f937\U00010000-\U0010ffff"
        r"\u2640-\u2642\u2600-\u2B55\u200d\u23cf"
        r"\u23e9\u231a\ufe0f\u3030]+",
        "", text, flags=re.UNICODE
    )
    # Remove bold/italic/code markdown
    text = re.sub(r"[*_`#]", "", text)
    # Unicode bold letters → normal (𝐍𝐚𝐦𝐞 → Name)
    bold_map = str.maketrans(
        "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
        "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
    )
    text = text.translate(bold_map)
    return text.strip()


# ── Single-job message parser ─────────────────────────────────

# Prefixes that indicate a structured field
_COMPANY_RE  = re.compile(r"^(company(\s+name)?|organization|org)\s*[:\-]\s*", re.I)
_ROLE_RE     = re.compile(r"^(role|position|title|designation|job title|hiring for)\s*[:\-]\s*", re.I)
_LOC_RE      = re.compile(r"^(location|loc|city|place|based in)\s*[:\-]\s*", re.I)
_APPLY_RE    = re.compile(r"^(apply\s*(link|here|now|@)?|link|apply\s*link|registration\s*link|register\s*(here|link)?|application\s*link)\s*[:\-]\s*", re.I)
_BATCH_RE    = re.compile(r"^(batch|eligibility|passout|year of passing|yoe|experience)\s*[:\-]\s*", re.I)

# "Company is hiring Role" / "Company hiring Role"
_HIRING_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9 &\.\-\(\)]{1,50}?)"
    r"\s+(?:is\s+)?hiring\s+(?:for\s+)?"
    r"(.{5,80}?)(?:\s*[!\.\n]|$)",
    re.IGNORECASE
)

# "Role @ Company" or "Role at Company"
_AT_RE = re.compile(
    r"^(.{5,60}?)\s+[@at]+\s+([A-Za-z0-9][A-Za-z0-9 &\.\-]{2,40})",
    re.IGNORECASE
)


def _parse_single(text: str, source: str, posted_at: str) -> "Job | None":
    clean   = _strip(text)
    lines   = [l.strip() for l in clean.splitlines() if l.strip()]
    company = title = location = apply_url = ""

    for line in lines:
        if _COMPANY_RE.match(line):
            company = _COMPANY_RE.sub("", line).strip()
        elif _ROLE_RE.match(line):
            title = _ROLE_RE.sub("", line).strip()[:80]
        elif _LOC_RE.match(line):
            location = _LOC_RE.sub("", line).strip()
        elif _APPLY_RE.match(line):
            urls = _URL_RE.findall(line)
            if urls:
                apply_url = urls[0]

    # "X is hiring Y" fallback
    if not company or not title:
        m = _HIRING_RE.search(clean)
        if m:
            if not company:
                company = m.group(1).strip()
            if not title:
                title = m.group(2).strip()[:80]

    # "Role at Company" fallback
    if not company or not title:
        for line in lines:
            m = _AT_RE.match(line)
            if m:
                if not title:
                    title = m.group(1).strip()[:80]
                if not company:
                    company = m.group(2).strip()
                break

    # Role from any line containing engineer/developer/intern etc.
    if not title:
        role_words = [
            "software engineer", "data engineer", "data scientist",
            "backend", "frontend", "full stack", "fullstack",
            "ml engineer", "ai engineer", "llm", "sde", "swe", "mts",
            "intern", "graduate engineer", "associate engineer",
            "developer", "engineer", "analyst", "scientist",
            "trainee", "fresher", "campus", "graduate",
        ]
        for line in lines:
            ll = line.lower()
            if (any(rw in ll for rw in role_words)
                    and not line.startswith("http")
                    and len(line) < 100):
                title = line[:80]
                break

    # Company from first short non-URL non-keyword line
    if not company:
        skip_words = {"apply", "link", "batch", "eligibility",
                      "location", "lpa", "salary", "http", "www",
                      "strong", "good", "must", "required", "skill",
                      "qualification", "note", "please", "hiring"}
        for line in lines:
            if (not line.startswith("http")
                    and len(line) < 60
                    and len(line) > 2
                    and not any(sw in line.lower() for sw in skip_words)):
                company = line
                break

    # Best apply URL
    if not apply_url:
        all_urls = _URL_RE.findall(text)
        apply_url = _best_url(all_urls) or ""

    # Reject if no URL or no recognisable title
    if not apply_url or not title or title.startswith("http"):
        return None

    # Reject if company looks like garbage (all punctuation, too long, URL-like)
    if company.startswith("http") or len(company) > 80:
        company = "Unknown"

    return Job(
        company   = company.strip() or "Unknown",
        title     = title.strip(),
        location  = location.strip() or "India",
        url       = apply_url,
        source    = source,
        posted_at = posted_at,
        raw_text  = text[:400],
    )


# ── Multi-job message detection and parsing ───────────────────

def _is_multi(text: str) -> bool:
    url_count = len(_URL_RE.findall(text))
    if url_count >= 3:
        return True
    return bool(re.search(
        r"(top\s*\d+|multiple|companies\s+hiring|hiring\s+list|\d+\s+companies|"
        r"\d+\s+jobs|openings|positions)",
        text, re.I
    ))


def _parse_multi(text: str, source: str, posted_at: str) -> list[Job]:
    # Split on blank lines, emoji bullets, numbered list items
    blocks = re.split(
        r"\n{2,}"
        r"|\n(?=\d+[\.\)]\s)"
        r"|\n(?=[-•►▶]\s)",
        text
    )
    jobs = []
    for block in blocks:
        block = block.strip()
        if len(block) < 20 or not _URL_RE.search(block):
            continue
        j = _parse_single(block, source, posted_at)
        if j:
            jobs.append(j)
    return jobs


# ── Main scrape ───────────────────────────────────────────────

async def scrape_groups() -> list[Job]:
    try:
        from telethon import TelegramClient
        from telethon.tl.types import MessageEntityTextUrl
    except ImportError:
        print("  ⚠  pip install telethon")
        return []

    cfg    = TELEGRAM_USER
    days   = cfg.get("lookback_days", 5)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    new_jobs: list[Job] = []
    seen_urls: set[str] = set()

    client = TelegramClient(cfg["session_file"], cfg["api_id"], cfg["api_hash"])
    await client.start(phone=cfg["phone"])

    try:
        for group in cfg["groups"]:
            print(f"  📲  @{group} (past {days} days)")
            try:
                entity = await client.get_entity(group)
            except Exception as e:
                print(f"      ⚠  Can't access: {e}")
                continue

            msgs = found = 0
            async for msg in client.iter_messages(entity, limit=1000):
                if not msg.date:
                    continue
                if msg.date < cutoff:
                    break
                if not msg.text:
                    continue
                msgs += 1

                text = msg.text
                # Inject embedded hyperlink URLs
                if msg.entities:
                    for ent in msg.entities:
                        if isinstance(ent, MessageEntityTextUrl):
                            text += f"\n{ent.url}"

                posted = msg.date.isoformat()
                batch  = (_parse_multi(text, group, posted)
                          if _is_multi(text)
                          else ([j] if (j := _parse_single(text, group, posted)) else []))

                for job in batch:
                    if job.url not in seen_urls:
                        seen_urls.add(job.url)
                        new_jobs.append(job)
                        found += 1

            print(f"      {msgs} messages → {found} job links")
    finally:
        await client.disconnect()

    # Merge with queue from previous run
    queued = load_queue()
    if queued:
        new_urls = {j.url for j in new_jobs}
        queued   = [j for j in queued if j.url not in new_urls]
        print(f"\n  📋  {len(queued)} jobs from previous queue")

    all_jobs = queued + new_jobs
    print(f"  Total: {len(all_jobs)} ({len(queued)} queued + {len(new_jobs)} new)\n")
    clear_queue()
    return all_jobs
