"""
main.py — Run this every day.

    python main.py          normal run
    python main.py --dry    scrape only, show what it would do
    python main.py --reset  clear seen history and re-run (use carefully)
"""
import asyncio, argparse, os
from datetime import datetime

from config.settings import MAX_PER_DAY
from telegram.scraper import scrape_groups, save_queue
from telegram.bot import send_summary, send
from core.applier import apply
from core.browser import new_browser, new_page, dismiss_popups
from core.tracker import today_count, print_summary, seen, log
from core.filter import should_apply


def header():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*52}")
    print(f"  Job Bot — {now}")
    print(f"  Applied today: {today_count()} / {MAX_PER_DAY}")
    print(f"{'='*52}\n")


async def run(dry: bool = False, reset: bool = False):
    header()

    if reset:
        if os.path.exists("data/applied.csv"):
            os.remove("data/applied.csv")
            print("  🗑  Cleared applied history\n")

    # ── Scrape ────────────────────────────────────────────────
    print("── Scraping Telegram groups ──────────────────────")
    all_jobs = await scrape_groups()

    if not all_jobs:
        print("  Nothing found.")
        await send("📭 No jobs found today.")
        return

    # ── Show breakdown ────────────────────────────────────────
    already_seen  = [j for j in all_jobs if seen(j.url)]
    not_seen      = [j for j in all_jobs if not seen(j.url)]
    would_skip    = [j for j in not_seen if not should_apply(j)[0]]
    would_apply   = [j for j in not_seen if should_apply(j)[0]]

    print(f"\n  Breakdown:")
    print(f"    Total found    : {len(all_jobs)}")
    print(f"    Already applied: {len(already_seen)}")
    print(f"    Role filtered  : {len(would_skip)}")
    print(f"    Will apply to  : {len(would_apply)}")

    if would_skip:
        print(f"\n  Filtered out (role):")
        for j in would_skip:
            _, reason = should_apply(j)
            print(f"    ⏭  {j.company} — {j.title} ({reason})")

    print()

    if dry:
        print("── DRY RUN — would apply to: ─────────────────────")
        if not would_apply:
            print("  Nothing to apply to.")
        for j in would_apply:
            print(f"  ✅  {j.company} — {j.title}")
            print(f"      {j.url}")
        return

    if not would_apply:
        print("  Nothing new to apply to.")
        await send("✅ All caught up — nothing new today.")
        return

    # ── Apply ─────────────────────────────────────────────────
    print("── Applying ──────────────────────────────────────")
    applied = failed = 0
    leftover = []

    pw, browser = await new_browser()
    try:
        _, page = await new_page(browser)

        for job in would_apply:
            if today_count() >= MAX_PER_DAY:
                print(f"\n  ✋  Daily limit of {MAX_PER_DAY} reached.")
                idx = would_apply.index(job)
                leftover = would_apply[idx:]
                break

            print(f"\n  🎯  {job.company} — {job.title}")
            print(f"      {job.url}")

            success = await apply(job, page)
            if success:
                applied += 1
            else:
                failed += 1

            await asyncio.sleep(3)

    finally:
        await browser.close()
        await pw.stop()

    if leftover:
        save_queue(leftover)
        await send(
            f"⏸ Daily limit hit.\n"
            f"{len(leftover)} jobs queued for tomorrow."
        )

    print_summary()
    await send_summary(applied, failed, len(would_skip))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry",   action="store_true",
                        help="Show what would happen, don't apply")
    parser.add_argument("--reset", action="store_true",
                        help="Clear applied history and re-run")
    args = parser.parse_args()
    asyncio.run(run(dry=args.dry, reset=args.reset))
