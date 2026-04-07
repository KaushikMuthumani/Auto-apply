"""
core/applier.py

The correct mental model for every job application:
  Page 1: Job detail page  → has "Apply Now" button
  Page 2: May show login wall OR goes straight to form
  Page 3: Actual application form (may be multi-step)
  Page 4: Confirmation / thank you

Each ATS has its own quirks handled explicitly.
"""
import asyncio, re
from playwright.async_api import Page, TimeoutError as PWTimeout

from forms.filler import fill_form, upload_resume
from core.browser import dismiss_popups, is_logged_in
from core.tracker import log, seen
from core.filter import should_apply
from telegram.bot import captcha_alert, send, wait_for_reply
from telegram.scraper import Job
from config.settings import get_resume

SUCCESS_SIGNALS = [
    "thank you", "thanks for applying", "application submitted",
    "application received", "successfully applied",
    "we'll be in touch", "application complete", "you've applied",
    "your application has been", "submitted successfully",
    "application was submitted", "received your application",
    "application is complete",
]

ATS_MAP = {
    "greenhouse": ["greenhouse.io", "boards.greenhouse", "job-boards.greenhouse"],
    "lever":      ["lever.co", "jobs.lever"],
    "ashby":      ["ashbyhq.com", "jobs.ashbyhq"],
    "workday":    ["myworkdayjobs.com", "wd3.myworkdayjobs",
                   "wd5.myworkdayjobs", "fa.oraclecloud.com/hcmUI"],
    "eightfold":  ["eightfold.ai"],
    "rippling":   ["ats.rippling.com"],
    "smartrecr":  ["smartrecruiters.com"],
    "microsoft":  ["careers.microsoft.com", "apply.careers.microsoft.com"],
    "mastercard": ["careers.mastercard.com"],
    "keka":       ["keka.com/careers"],
    "workable":   ["workable.com"],
    "iqvia":      ["jobs.iqvia.com"],
}

def _ats(url: str) -> str:
    u = url.lower()
    for name, patterns in ATS_MAP.items():
        if any(p in u for p in patterns):
            return name
    return "custom"

def _confirmed(url: str, body: str) -> bool:
    u = url.lower()
    b = body.lower()
    if any(x in u for x in ["thank", "success", "confirm",
                              "submitted", "complete", "applied"]):
        return True
    return any(s in b for s in SUCCESS_SIGNALS)

async def _body(page: Page) -> str:
    try:
        return await page.locator("body").inner_text()
    except Exception:
        return ""

async def _has_captcha(page: Page) -> bool:
    for sel in [
        "iframe[src*='recaptcha']",
        "iframe[title*='reCAPTCHA']",
        "iframe[src*='hcaptcha']",
        ".h-captcha iframe",
        "#recaptcha-anchor",
    ]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                return True
        except Exception:
            continue
    return False

# ── Wait for form fields to appear (JS-heavy ATS) ─────────────

async def _wait_for_form(page: Page, timeout: int = 10) -> bool:
    """
    Wait up to `timeout` seconds for real form inputs to appear.
    Works for React/JS-rendered forms (Workday, Eightfold, etc.)
    Returns True if a form with real inputs appeared.
    """
    for _ in range(timeout * 2):
        await asyncio.sleep(0.5)
        inputs = await page.locator(
            "input[type='email'], input[type='text'], "
            "input[type='tel'], textarea, "
            "input[type='password']"
        ).all()
        real = 0
        for inp in inputs:
            try:
                if not await inp.is_visible():
                    continue
                t = (await inp.get_attribute("type") or "").lower()
                if t not in ("hidden", "submit", "button", "reset", "search"):
                    # Skip search boxes
                    ph = (await inp.get_attribute("placeholder") or "").lower()
                    aria = (await inp.get_attribute("aria-label") or "").lower()
                    if any(k in ph or k in aria for k in
                           ["search", "keyword", "find", "filter"]):
                        continue
                    real += 1
            except Exception:
                continue
        if real >= 2:
            return True
    return False

# ── Apply button clicker ───────────────────────────────────────

async def _click_apply(page: Page) -> bool:
    texts = [
        "Apply now", "Apply Now", "Apply for this job",
        "Apply for this role", "Apply for Job", "Start application",
        "Quick apply", "Easy apply", "Apply",
    ]
    for text in texts:
        for sel in [f"button:has-text('{text}')", f"a:has-text('{text}')"]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    return True
            except Exception:
                continue
    return False

# ── Account management ─────────────────────────────────────────

async def _handle_account(page: Page, url: str, company: str) -> bool:
    """
    Login flow:
      1. Already logged in? Done.
      2. No login wall? Done.
      3. Google SSO available? Click it (works because real Chrome profile).
      4. LinkedIn SSO available? Click it.
      5. Saved credentials? Try them.
      6. Ask user via Telegram.
    """
    from core.browser import get_saved_account, save_account

    if await is_logged_in(page):
        return True

    # Check if page needs login at all
    needs_login = await page.locator(
        "input[type='password'], "
        "button:has-text('Sign in'), button:has-text('Log in'), "
        "a:has-text('Sign in'), a:has-text('Log in'), "
        "button:has-text('Create Account'), button:has-text('Register'), "
        "button:has-text('Sign In'), a:has-text('Sign In')"
    ).count() > 0

    if not needs_login:
        return True  # no login wall

    # 1. Try Google SSO (works with your real Chrome profile)
    for sel in [
        "button:has-text('Sign in with Google')",
        "a:has-text('Sign in with Google')",
        "button:has-text('Continue with Google')",
        "a:has-text('Continue with Google')",
        "[data-provider='google']",
        "button[aria-label*='Google']",
        ".google-sso", ".btn-google",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                print(f"  🔵  Google SSO found — clicking…")
                await btn.click()
                await asyncio.sleep(5)
                # Google popup should auto-select your account
                # Handle account chooser if it appears
                await _handle_google_account_chooser(page)
                await asyncio.sleep(3)
                if await is_logged_in(page):
                    print(f"  ✅  Signed in via Google")
                    return True
                break
        except Exception:
            continue

    # 2. Try LinkedIn SSO
    for sel in [
        "button:has-text('Sign in with LinkedIn')",
        "a:has-text('Sign in with LinkedIn')",
        "button:has-text('Continue with LinkedIn')",
        "[data-provider='linkedin']",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                print(f"  🔵  LinkedIn SSO found — clicking…")
                await btn.click()
                await asyncio.sleep(5)
                if await is_logged_in(page):
                    return True
                break
        except Exception:
            continue

    # Try saved account
    creds = get_saved_account(url)
    if creds:
        print(f"  🔑  Trying saved account for {_domain(url)} …")
        success = await _do_login(page, creds["email"], creds["password"])
        if success:
            return True
        print(f"  ⚠  Saved credentials failed for {_domain(url)}")

    # Ask user via Telegram
    msg = (
        f"🔐 <b>Account needed</b>\n\n"
        f"<b>Company:</b> {company}\n"
        f"<b>Site:</b> <code>{_domain(url)}</code>\n\n"
        f"Reply with: <code>email password</code>\n"
        f"(space-separated, e.g.: john@gmail.com mypassword123)\n\n"
        f"Or reply <b>skip</b> to skip this job.\n"
        f"Waiting 5 minutes…"
    )
    reply = await wait_for_reply(msg, timeout=300)

    if not reply or reply.lower().strip() == "skip":
        await send(f"⏭ Skipping {company} — no credentials provided.")
        return False

    parts = reply.strip().split(" ", 1)
    if len(parts) != 2:
        await send("❌ Format not recognised. Expected: email password")
        return False

    email, password = parts[0].strip(), parts[1].strip()

    # Try login with provided credentials
    success = await _do_login(page, email, password)
    if success:
        save_account(url, email, password)
        await send(f"✅ Logged in to {_domain(url)} — saved for next time.")
        return True

    # Might need account creation — check for register button
    register = await page.locator(
        "button:has-text('Create Account'), button:has-text('Register'), "
        "a:has-text('Create Account'), a:has-text('Register'), "
        "button:has-text('Sign up'), a:has-text('Sign up')"
    ).count()

    if register > 0:
        create_msg = (
            f"🔐 <b>Need to create account</b>\n\n"
            f"<b>Site:</b> <code>{_domain(url)}</code>\n\n"
            f"1. Open this URL in your browser:\n"
            f"<code>{page.url}</code>\n\n"
            f"2. Create an account with:\n"
            f"   Email: <code>{email}</code>\n\n"
            f"3. Reply <b>done</b> when finished."
        )
        reply2 = await wait_for_reply(
            create_msg, timeout=300,
            keywords=["done", "ok", "created", "registered"])
        if reply2:
            # Now try logging in with the credentials they used
            await page.reload()
            await asyncio.sleep(2)
            success = await _do_login(page, email, password)
            if success:
                save_account(url, email, password)
                await send(f"✅ Logged in to {_domain(url)}")
                return True

    await send(f"⚠ Could not log in to {_domain(url)} — skipping job.")
    return False


async def _do_login(page: Page, email: str, password: str) -> bool:
    """Fill login form and submit. Returns True if login succeeded."""
    for sel in ["input[type='email']", "input[name*='email']",
                "input[placeholder*='email' i]", "input[name='username']",
                "input[id*='email']", "input[type='text']"]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                await el.fill(email)
                break
        except Exception:
            continue

    await asyncio.sleep(0.4)

    for sel in ["input[type='password']", "input[name*='password']",
                "input[id*='password']"]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                await el.fill(password)
                break
        except Exception:
            continue

    await asyncio.sleep(0.4)

    for sel in ["button[type='submit']", "button:has-text('Sign in')",
                "button:has-text('Log in')", "button:has-text('Login')",
                "input[type='submit']"]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(4)
                break
        except Exception:
            continue

    return await is_logged_in(page)


def _domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url)
    return m.group(1) if m else url

# ── Navigation helpers ─────────────────────────────────────────

async def _click_next(page: Page) -> bool:
    for text in ["Next", "Continue", "Next Step", "Save and continue",
                 "Next Page", "Proceed"]:
        for sel in [f"button:has-text('{text}')",
                    f"button[aria-label='{text}']",
                    "button[aria-label='Continue to next step']"]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(2)
                    return True
            except Exception:
                continue
    return False

async def _click_submit(page: Page) -> bool:
    for sel in [
        "button[aria-label='Submit application']",
        "button:has-text('Submit Application')",
        "button:has-text('Submit application')",
        "button:has-text('Submit')",
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Send Application')",
        "button:has-text('Complete Application')",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(4)
                return True
        except Exception:
            continue
    return False

# ── CAPTCHA handler ────────────────────────────────────────────

async def _handle_captcha(page: Page, company: str):
    """
    Take screenshot, send to Telegram with instructions.
    Screenshot shows exactly what's on screen.
    """
    screenshot = f"data/captcha_{int(asyncio.get_event_loop().time())}.png"
    try:
        await page.screenshot(path=screenshot, full_page=False)
    except Exception:
        screenshot = None

    msg = (
        f"🔴 <b>CAPTCHA — {company}</b>\n\n"
        f"Screenshot attached shows exactly what's on screen.\n\n"
        f"The browser is open on your laptop.\n"
        f"Solve the CAPTCHA there, then reply <b>done</b>.\n\n"
        f"Auto-resumes in 5 min."
    )
    await wait_for_reply(msg, timeout=300,
                         keywords=["done", "ok", "solved"],
                         photo=screenshot)
    await send("✅ Resuming…")

# ── Main form fill loop ────────────────────────────────────────

async def _fill_and_submit(page: Page, company: str,
                            resume_text: str, jd_text: str,
                            resume_path: str) -> bool:
    uploaded = False

    for step in range(20):
        await asyncio.sleep(1.5)
        await dismiss_popups(page)

        if await _has_captcha(page):
            await _handle_captcha(page, company)
            await asyncio.sleep(2)

        # Upload resume (first time a file input appears)
        if not uploaded:
            if await page.locator("input[type='file']").count() > 0:
                await upload_resume(page, resume_path)
                uploaded = True
                await asyncio.sleep(1)

        # Fill visible fields
        await fill_form(page, company, resume_text, jd_text)

        # Review button
        review = page.locator(
            "button:has-text('Review'), "
            "button:has-text('Review your application'), "
            "button[aria-label='Review your application']")
        if await review.count() > 0:
            vis = [r for r in await review.all() if await r.is_visible()]
            if vis:
                await vis[0].click()
                await asyncio.sleep(2)
                continue

        # Submit?
        has_submit = False
        for sel in [
            "button[aria-label='Submit application']",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button[type='submit']",
            "input[type='submit']",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    has_submit = True
                    break
            except Exception:
                continue

        if has_submit:
            await _click_submit(page)
            body = await _body(page)
            if _confirmed(page.url, body):
                return True
            await asyncio.sleep(4)
            return _confirmed(page.url, body)

        # Next?
        if await _click_next(page):
            continue

        # Check if already confirmed
        body = await _body(page)
        if _confirmed(page.url, body):
            return True
        break

    return False

# ── Main entry ─────────────────────────────────────────────────

async def apply(job: Job, page: Page) -> bool:
    if seen(job.url):
        return False

    ok, reason = should_apply(job)
    if not ok:
        log(job.company, job.title, job.location, job.url,
            "skipped", job.source, reason)
        return False

    ats = _ats(job.url)

    try:
        # 1. Load page
        await page.goto(job.url, wait_until="domcontentloaded", timeout=35000)
        await asyncio.sleep(2)
        await dismiss_popups(page)

        # 2. Real CAPTCHA on load?
        if await _has_captcha(page):
            await _handle_captcha(page, job.company)
            await asyncio.sleep(2)

        # 3. Click Apply button — get from detail page to form
        clicked = await _click_apply(page)
        if clicked:
            await asyncio.sleep(3)
            await dismiss_popups(page)

        # 4. Handle login wall — ONLY if login inputs are visible
        logged_in = await _handle_account(page, job.url, job.company)
        if not logged_in:
            # User said skip or couldn't log in
            log(job.company, job.title, job.location, job.url,
                "failed", job.source, "login required, skipped by user")
            return False

        await asyncio.sleep(2)
        await dismiss_popups(page)

        # 5. After login, Apply button may need clicking again
        if clicked:
            await _click_apply(page)
            await asyncio.sleep(2)
            await dismiss_popups(page)

        # 6. Wait for form to actually load (JS-heavy ATS)
        form_loaded = await _wait_for_form(page, timeout=12)
        if not form_loaded:
            print(f"  ⚠  Form did not load: {job.company} [{ats}]")
            print(f"     Page: {page.url[:80]}")
            log(job.company, job.title, job.location, job.url,
                "failed", job.source, f"form not loaded [{ats}]")
            return False

        # 7. Get JD text
        jd_text = ""
        for sel in ["main", "article", ".description",
                    ".job-description", "#job-description"]:
            el = page.locator(sel)
            if await el.count() > 0:
                try:
                    t = await el.first.inner_text()
                    if len(t) > 100:
                        jd_text = t
                        break
                except Exception:
                    pass

        # 8. Resume
        resume_path = get_resume(job.title)
        resume_text = _extract_text(resume_path)

        # 9. Fill and submit
        success = await _fill_and_submit(
            page, job.company, resume_text, jd_text, resume_path)

        status = "applied" if success else "failed"
        log(job.company, job.title, job.location, job.url,
            status, job.source, f"ats={ats}")

        if success:
            print(f"  ✅  Applied: {job.company} — {job.title}")
        else:
            print(f"  ❌  Could not confirm: {job.company} — {job.title} [{ats}]")

        return success

    except PWTimeout:
        print(f"  ⏱  Timeout: {job.url[:70]}")
        log(job.company, job.title, job.location, job.url,
            "failed", job.source, "timeout")
        return False
    except Exception as e:
        print(f"  ⚠  Error ({job.company}): {e}")
        log(job.company, job.title, job.location, job.url,
            "failed", job.source, str(e)[:100])
        return False


def _extract_text(path: str) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(
                p.extract_text() or "" for p in pdf.pages
            )
    except Exception:
        return ""
