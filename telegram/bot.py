"""
telegram/bot.py — Two-way Telegram bot.

Sends you alerts, waits for your replies.
Used for:
  • CAPTCHA — sends screenshot, waits for "done"
  • Unknown form question — sends question, waits for your answer
  • Daily summary — sends stats at end of run
"""
import asyncio, os, time
import httpx
from config.settings import TELEGRAM_BOT

TOKEN   = TELEGRAM_BOT.get("token", "")
CHAT_ID = TELEGRAM_BOT.get("chat_id", 0)
BASE    = f"https://api.telegram.org/bot{TOKEN}"


def _configured() -> bool:
    return bool(TOKEN and CHAT_ID)


async def _post(method: str, **kwargs) -> dict:
    if not _configured():
        return {}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{BASE}/{method}", **kwargs)
            return r.json()
    except Exception as e:
        print(f"  ⚠  Bot error ({method}): {e}")
        return {}


async def _get_updates(offset: int = 0) -> list[dict]:
    if not _configured():
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{BASE}/getUpdates",
                            params={"offset": offset, "limit": 10, "timeout": 2})
            return r.json().get("result", [])
    except Exception:
        return []


async def send(text: str, photo: str = None):
    """Send a text message or photo+caption."""
    if not _configured():
        print(f"  [BOT not configured] {text[:80]}")
        return
    if photo and os.path.exists(photo):
        async with httpx.AsyncClient(timeout=20) as c:
            with open(photo, "rb") as f:
                await c.post(f"{BASE}/sendPhoto",
                             data={"chat_id": CHAT_ID, "caption": text[:1024]},
                             files={"photo": f})
    else:
        await _post("sendMessage",
                    json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})


async def _last_update_id() -> int:
    updates = await _get_updates(offset=-1)
    return updates[-1]["update_id"] if updates else 0


async def wait_for_reply(prompt: str, timeout: int,
                         keywords: list[str] = None,
                         photo: str = None) -> str | None:
    """
    Send prompt, then poll for a reply from you.
    If keywords given → returns True/None (e.g. for "done").
    If no keywords   → returns your full reply text or None.
    """
    await send(prompt, photo)
    last_id = await _last_update_id()
    waited  = 0
    poll    = 4   # seconds between polls

    while waited < timeout:
        await asyncio.sleep(poll)
        waited += poll
        updates = await _get_updates(offset=last_id + 1)
        for upd in updates:
            msg  = upd.get("message", {})
            text = msg.get("text", "").strip()
            cid  = msg.get("chat", {}).get("id")
            uid  = upd.get("update_id", 0)
            if uid > last_id:
                last_id = uid
            if cid != CHAT_ID or not text:
                continue
            if keywords:
                if any(k in text.lower() for k in keywords):
                    return text
            else:
                return text   # any reply = the answer

    return None   # timed out


# ── High-level helpers ────────────────────────────────────────

async def captcha_alert(portal: str, url: str, page=None) -> bool:
    """Notify CAPTCHA, wait for 'done' reply (5 min timeout)."""
    screenshot = f"data/captcha_{int(time.time())}.png"
    if page:
        try:
            await page.screenshot(path=screenshot, full_page=False)
        except Exception:
            screenshot = None

    msg = (
        f"🔴 <b>CAPTCHA — {portal}</b>\n\n"
        f"URL: <code>{url}</code>\n\n"
        f"Solve it in the browser, then reply <b>done</b>.\n"
        f"Auto-resumes in 5 min if no reply."
    )
    reply = await wait_for_reply(msg, timeout=300,
                                 keywords=["done", "ok", "solved", "continue"],
                                 photo=screenshot)
    if reply:
        await send("✅ Resuming now…")
    else:
        await send("⏱ Timeout — resuming anyway.")
    return True


async def ask_question(question: str, company: str, ai_guess: str = "") -> str | None:
    """
    Send an unknown form question to you, wait 3 min for reply.
    Returns your answer, or None if no reply.
    """
    msg = (
        f"❓ <b>Unknown question</b>\n\n"
        f"<b>Company:</b> {company}\n"
        f"<b>Question:</b> <i>{question}</i>\n"
    )
    if ai_guess:
        msg += f"\n🤖 AI guess: <code>{ai_guess[:200]}</code>\n"
    msg += f"\nReply with your answer (3 min). Will be saved and reused."

    reply = await wait_for_reply(msg, timeout=180)
    if reply:
        await send(f"✅ Got it — saved:\n<code>{reply[:200]}</code>")
    else:
        await send("⏱ No reply — leaving field blank.")
    return reply


async def send_summary(applied: int, failed: int, skipped: int):
    emoji = "🎉" if applied > 0 else "📊"
    await send(
        f"{emoji} <b>Run complete</b>\n\n"
        f"✅ Applied:  <b>{applied}</b>\n"
        f"❌ Failed:   {failed}\n"
        f"⏭ Skipped:  {skipped}\n\n"
        f"Check data/applied.csv for details."
    )


async def get_chat_id():
    """Run once after messaging your bot to get your chat_id."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{BASE}/getUpdates")
            results = r.json().get("result", [])
        if results:
            cid = results[-1]["message"]["chat"]["id"]
            print(f"\n  ✅  Your chat_id: {cid}")
            print(f"  Paste into config/settings.py → TELEGRAM_BOT['chat_id'] = {cid}\n")
        else:
            print("  No messages yet — send your bot any message first, then re-run.")
    except Exception as e:
        print(f"  Error: {e}")
