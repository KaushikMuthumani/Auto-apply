"""
core/browser.py

Uses your REAL Chrome profile instead of a blank test browser.
This means:
  - Your Google account is already signed in
  - Google Sign-In / Sign in with Google works on every site
  - Sites you've already created accounts on are already logged in
  - Your saved passwords auto-fill
  - Cookies from previous visits are present

How to find your Chrome profile path:
  Open Chrome → go to chrome://version → look for "Profile Path"
  Copy everything up to (but not including) the last folder name.
  e.g. C:\\Users\\KAUSHIK\\AppData\\Local\\Google\\Chrome\\User Data

Set CHROME_PROFILE in config/settings.py
"""
import asyncio, json, os, re
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from config.settings import HEADLESS, SLOW_MO, CHROME_PROFILE, CHROME_PROFILE_NAME

ACCOUNTS_FILE = "data/accounts.json"


# ── Account store (fallback for sites without Google SSO) ────

def _load_accounts() -> dict:
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_accounts(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_saved_account(url: str) -> dict | None:
    domain = _domain(url)
    accounts = _load_accounts()
    if domain in accounts:
        return accounts[domain]
    for d, creds in accounts.items():
        if d in domain or domain in d:
            return creds
    return None

def save_account(url: str, email: str, password: str):
    domain = _domain(url)
    accounts = _load_accounts()
    accounts[domain] = {"email": email, "password": password}
    _save_accounts(accounts)
    print(f"  💾  Account saved for {domain}")

def _domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url)
    return m.group(1) if m else url


# ── Browser launch using your real Chrome profile ─────────────

async def new_browser():
    """
    Launch using your real Chrome profile.
    You stay logged into Google, all your cookies and passwords are available.
    """
    pw = await async_playwright().start()

    if CHROME_PROFILE and os.path.exists(CHROME_PROFILE):
        print(f"  🌐  Using your Chrome profile: {CHROME_PROFILE_NAME}")
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE,
            channel="chrome",          # use real Chrome, not Chromium
            headless=HEADLESS,
            slow_mo=SLOW_MO,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-notifications",
                "--disable-infobars",
            ],
            ignore_default_args=["--enable-automation"],
        )
        # persistent_context IS the context — return it as both browser and ctx
        return pw, browser   # browser here is actually a BrowserContext
    else:
        print("  ⚠  Chrome profile not set — using blank browser.")
        print("     Set CHROME_PROFILE in config/settings.py for Google SSO.")
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-notifications",
                "--disable-infobars",
            ],
        )
        return pw, browser


async def new_page(browser_or_ctx) -> tuple:
    """
    Create a new page. Works whether browser_or_ctx is a
    Browser or a persistent BrowserContext.
    """
    # Check if it's a persistent context (has new_page but no new_context)
    if hasattr(browser_or_ctx, 'new_page') and not hasattr(browser_or_ctx, 'new_context'):
        # It's a persistent BrowserContext
        page = await browser_or_ctx.new_page()
    elif hasattr(browser_or_ctx, 'new_context'):
        # It's a regular Browser
        ctx = await browser_or_ctx.new_context(
            permissions=[],
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
    else:
        page = await browser_or_ctx.new_page()

    page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
    return None, page   # ctx not needed externally


# ── Cookie / permission banner dismissal ─────────────────────

COOKIE_SELECTORS = [
    "button:has-text('Accept All')",
    "button:has-text('Accept all')",
    "button:has-text('Accept Cookies')",
    "button:has-text('ACCEPT ALL')",
    "button:has-text('Allow All')",
    "button:has-text('I Accept')",
    "button:has-text('I agree')",
    "button:has-text('Agree')",
    "button:has-text('Got it')",
    "#onetrust-accept-btn-handler",
    "#accept-all-cookies",
    ".cookie-accept",
    "[data-testid='cookie-accept']",
    "[aria-label='Accept cookies']",
]

DENY_SELECTORS = [
    "button:has-text('Never allow')",
    "button:has-text('Block')",
    "button:has-text('Deny')",
    "button:has-text('Not now')",
]

async def dismiss_popups(page: Page):
    """Dismiss cookie banners and permission dialogs."""
    await asyncio.sleep(0.8)

    for sel in DENY_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.4)
                break
        except Exception:
            continue

    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.4)
                break
        except Exception:
            continue

    # iFrame cookie banners
    for frame in page.frames:
        for sel in COOKIE_SELECTORS[:4]:
            try:
                btn = frame.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.4)
            except Exception:
                continue


# ── Login detection ───────────────────────────────────────────

async def is_logged_in(page: Page) -> bool:
    signals = [
        ".user-avatar", ".profile-icon", "[data-testid='user-menu']",
        ".account-menu", ".logout", "a:has-text('Sign out')",
        "button:has-text('Sign out')", "a:has-text('Log out')",
        "button:has-text('Log out')", ".my-profile", ".my-account",
        "[aria-label='My account']", ".user-name", ".user-email",
    ]
    for sel in signals:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False
