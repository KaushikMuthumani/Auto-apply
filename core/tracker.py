"""
core/tracker.py — Logs every job attempt to data/applied.csv.
Prevents applying to the same URL twice.
"""
import csv, hashlib, os
from datetime import datetime

CSV = "data/applied.csv"
FIELDS = ["id", "company", "title", "location", "url",
          "status", "when", "source", "notes"]


def _id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:10]


def _load() -> dict:
    if not os.path.exists(CSV):
        return {}
    with open(CSV, newline="", encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def _save(data: dict):
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(data.values())


def seen(url: str) -> bool:
    return _id(url) in _load()


def log(company: str, title: str, location: str, url: str,
        status: str, source: str = "", notes: str = ""):
    data = _load()
    jid  = _id(url)
    data[jid] = {
        "id":       jid,
        "company":  company,
        "title":    title,
        "location": location,
        "url":      url,
        "status":   status,
        "when":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source":   source,
        "notes":    notes,
    }
    _save(data)


def today_count() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for r in _load().values()
               if r["status"] == "applied" and r["when"].startswith(today))


def print_summary():
    data  = _load()
    today = datetime.now().strftime("%Y-%m-%d")
    done  = [r for r in data.values()
             if r["status"] == "applied" and r["when"].startswith(today)]
    print(f"\n{'='*50}")
    print(f"  Applied today : {len(done)}")
    print(f"  All time      : {sum(1 for r in data.values() if r['status'] == 'applied')}")
    print(f"{'='*50}")
    for r in done:
        print(f"  ✓ {r['company'][:25]:<25} {r['title'][:35]}")
    print()
