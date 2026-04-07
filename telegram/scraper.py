"""
telegram/scraper.py — Reads job posts from Telegram groups.

Features:
  - Handles single-job AND multi-job messages
  - 5-day lookback (configurable via settings)
  - Persistent queue: unapplied jobs saved to data/queue.json
    so they carry over to the next run if daily limit hit
"""
import re, json, os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from config.settings import TELEGRAM_USER

_URL_RE = re.compile(r"https?://[^\s\)\]\>\"\'\,\|]+")
QUEUE_FILE = "data/queue.json"


# ── Job dataclass ─────────────────────────────────────────────

@dataclass
class Job:
    company:   str
    title:     str
    location:  str
    url:       str
    source:    str
    posted_at: str
    raw_text:  str = ""


# ── Queue — persists unapplied jobs across runs ───────────────

def load_queue() -> list[Job]:
    """Load leftover jobs from previous run."""
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [Job(**d) for d in data]
    except Exception:
        return []


def save_queue(jobs: list[Job]):
    """Save unapplied jobs for next run."""
    os.makedirs("data", exist_ok=True)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump([asdict(j) for j in jobs], f, indent=2, ensure_ascii=False)
    if jobs:
        print(f"  📋  {len(jobs)} jobs saved to queue for next run")


def clear_queue():
    if os.path.exists(QUEUE_FILE):
        os.remove(QUEUE_FILE)


# ── URL scoring ───────────────────────────────────────────────

ATS = [
    "greenhouse.io", "lever.co", "ashbyhq.com",
    "myworkdayjobs.com", "workday.com", "fa.oraclecloud.com",
    "smartrecruiters.com", "jobvite.com", "icims.com",
    "eightfold.ai", "ats.rippling.com", "keka.com",
    "amazon.jobs", "careers.google.com", "jobs.boeing.com",
    "careerzenith.ai", "njoyn.com", "taleo.net",
    "successfactors", "workable.com", "phenom",
    "geaerospace.com", "careers.salesforce.com",
]

SKIP = [
    "t.me/", "telegram.me/", "twitter.com", "x.com",
    "youtube.com", "instagram.com", "facebook.com",
    "docs.google.com/forms", "forms.gle",
    "growthschool.io", "topmate.io",
    "bit.ly", "tinyurl.com", "lnkd.in",
    "freshershunt.in", "naukri.com",
    "unstop.com", "fhlinks.in", "hirist.tech",
]


def _score(url: str) -> int:
    u = url.lower()
    if any(s in u for s in SKIP):
        return -1
    score = 0
    if any(a in u for a in ATS):
        score += 20
    if re.search(r"/(job|jobs|careers?|apply|opening|position)/", u):
        score += 8
    if re.search(r"(job_?id|jid|req_?id|gh_jid|jobid)=", u):
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


# ── Message parsers ───────────────────────────────────────────

def _clean(text: str) -> str:
    """Strip emoji, markdown bold/italic."""
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"[*_`#]", "", text)
    return text.strip()


def _parse_single(text: str, source: str, posted_at: str) -> "Job | None":
    lines = [_clean(l) for l in text.splitlines() if _clean(l)]
    company = title = location = apply_url = ""

    for line in lines:
        ll  = line.lower()
        val = re.split(r":\s*", line, 1)[-1].strip() if ":" in line else ""

        if re.match(r"(company(\s+name)?)\s*:", ll):
            company = val
        elif re.match(r"(role|position|title|hiring\s+for|designation)\s*:", ll):
            title = val[:80]
        elif re.match(r"(location|loc|city|place)\s*:", ll):
            location = val
        elif re.match(r"(apply\s*(link|here|now)?|link|register(ation)?\s*link)\s*:", ll):
            urls = _URL_RE.findall(line)
            if urls:
                apply_url = urls[0]

    # "X is hiring Y" pattern
    m = re.search(
        r"([A-Za-z0-9 &\.\-\(\)]{2,45}?)\s+is\s+hiring\s+(.+?)[\!\.\n]",
        text, re.IGNORECASE)
    if m:
        if not company:
            company = _clean(m.group(1))
        if not title:
            title = _clean(m.group(2))[:80]

    # Role line without label
    if not title:
        for line in lines:
            ll = line.lower()
            if any(k in ll for k in [
                "engineer", "developer", "intern", "analyst",
                "scientist", "mts", "sde", "swe", "trainee",
                "associate", "graduate", "fresher",
            ]):
                title = line[:80]
                break

    # Company from first clean line
    if not company and lines:
        for line in lines:
            if (not line.startswith("http") and len(line) < 60
                    and not any(k in line.lower() for k in
                                ["apply", "link", "batch", "eligibility",
                                 "location", "lpa", "salary", "http"])):
                company = line
                break

    # Best URL fallback
    if not apply_url:
        apply_url = _best_url(_URL_RE.findall(text)) or ""

    if not apply_url or not title:
        return None

    return Job(company=company or "Unknown", title=title,
               location=location or "India", url=apply_url,
               source=source, posted_at=posted_at,
               raw_text=text[:400])


def _is_multi(text: str) -> bool:
    url_count = len(_URL_RE.findall(text))
    if url_count >= 3:
        return True
    return bool(re.search(
        r"(top\s*\d+|multiple|companies\s+hiring|hiring\s+list|\d+\s+companies)",
        text, re.IGNORECASE))


def _parse_multi(text: str, source: str, posted_at: str) -> list["Job"]:
    blocks = re.split(
        r"\n{2,}"
        r"|\n(?=\d+[\.\)]\s)"
        r"|\n(?=[🔴🟢🟡🔵⭐✅❌📌🚀💼🎯➡️▶️•►]\s*\S)",
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
    """
    Scrape Telegram groups for the past LOOKBACK_DAYS days.
    Merges with any jobs left in the queue from previous runs.
    Returns combined list (queue first, then new jobs).
    """
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
                posted = msg.date.isoformat()

                # Inject embedded hyperlink URLs into text
                if msg.entities:
                    for ent in msg.entities:
                        if isinstance(ent, MessageEntityTextUrl):
                            text += f"\n{ent.url}"

                batch = _parse_multi(text, group, posted) \
                        if _is_multi(text) \
                        else ([j] if (j := _parse_single(text, group, posted)) else [])

                for job in batch:
                    if job.url not in seen_urls:
                        seen_urls.add(job.url)
                        new_jobs.append(job)
                        found += 1

            print(f"      {msgs} messages → {found} new job links")

    finally:
        await client.disconnect()

    # ── Merge with saved queue ────────────────────────────────
    queued = load_queue()
    if queued:
        print(f"\n  📋  {len(queued)} jobs carried over from last run's queue")
        # Deduplicate: don't re-add URLs already in new_jobs
        new_urls = {j.url for j in new_jobs}
        queued   = [j for j in queued if j.url not in new_urls]

    # Queue first so older unapplied jobs get priority
    all_jobs = queued + new_jobs
    print(f"\n  Total to process: {len(all_jobs)} "
          f"({len(queued)} queued + {len(new_jobs)} new)\n")

    clear_queue()   # will re-save whatever's left after this run
    return all_jobs
