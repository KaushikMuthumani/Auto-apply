"""
forms/filler.py — Fills application forms intelligently.

Key fixes:
  - Skips honeypot fields (hidden, aria-hidden, off-screen)
  - Skips search/autocomplete boxes (not application fields)
  - Skips read-only and disabled fields
  - Only fills actual visible application form fields
"""
import asyncio, os, re
from playwright.async_api import Page
from forms.resolver import resolve, best_option, should_check

# Field labels to always SKIP — these are not application questions
SKIP_LABELS = {
    # Search / filter fields — NOT application fields
    "search", "search jobs", "search job title", "search by keyword",
    "search location", "keywords", "enter keyword", "keyword",
    "filter", "all countries", "select country", "search country",
    "all locations", "search city", "find jobs", "job search",
    # Honeypot traps
    "honeypot", "bot check", "leave this blank",
    "do not fill", "leave empty", "spam",
    # Misc
    "website url", "coupon", "promo code", "captcha", "verification code",
}

# Attributes that indicate a honeypot or hidden trap field
HONEYPOT_ATTRS = [
    "tabindex=-1", "aria-hidden=true", "display:none",
    "visibility:hidden", "opacity:0",
]


async def _is_real_field(page: Page, element) -> bool:
    """
    Returns False if this field should be skipped:
      - hidden / aria-hidden
      - off-screen (position absolute, tiny size)
      - disabled / readonly
      - has a label matching SKIP_LABELS
      - honeypot attributes
    """
    try:
        # Disabled / readonly
        if await element.is_disabled():
            return False
        if await element.get_attribute("readonly") is not None:
            return False
        if await element.get_attribute("aria-hidden") == "true":
            return False

        # Visibility check
        if not await element.is_visible():
            return False

        # Bounding box — skip off-screen or zero-size fields
        box = await element.bounding_box()
        if box is None:
            return False
        if box["width"] < 5 or box["height"] < 5:
            return False
        # Off-screen (way outside viewport) — common honeypot trick
        if box["x"] < -100 or box["y"] < -100:
            return False

        # Type check — skip hidden inputs
        inp_type = (await element.get_attribute("type") or "").lower()
        if inp_type in ("hidden", "submit", "button", "reset", "image"):
            return False

        # Autocomplete / search role
        role = (await element.get_attribute("role") or "").lower()
        if role in ("searchbox", "combobox"):
            # combobox is ok for selects, but searchbox is a trap
            if role == "searchbox":
                return False

        return True
    except Exception:
        return False


async def _label_for(page: Page, element) -> str:
    """Get visible label text for a form element."""
    try:
        el_id  = await element.get_attribute("id")
        name   = await element.get_attribute("name") or ""
        ph     = await element.get_attribute("placeholder") or ""
        aria   = await element.get_attribute("aria-label") or ""
        autocomplete = await element.get_attribute("autocomplete") or ""

        # Direct label[for=id]
        if el_id:
            lbl = page.locator(f"label[for='{el_id}']")
            if await lbl.count() > 0:
                txt = (await lbl.first.inner_text()).strip()
                if txt:
                    return txt

        # Ancestor label
        try:
            anc = element.locator("xpath=ancestor::label[1]")
            if await anc.count() > 0:
                txt = (await anc.first.inner_text()).strip()
                if txt:
                    return txt
        except Exception:
            pass

        # Nearest preceding sibling label or div with label-like class
        try:
            prev = element.locator(
                "xpath=preceding-sibling::label[1] | "
                "xpath=../preceding-sibling::*[contains(@class,'label')][1]")
            if await prev.count() > 0:
                txt = (await prev.first.inner_text()).strip()
                if txt:
                    return txt
        except Exception:
            pass

        return aria or autocomplete or name or ph
    except Exception:
        return ""


def _is_skip_label(label: str) -> bool:
    ll = label.lower().strip()
    return any(skip in ll for skip in SKIP_LABELS)


async def fill_form(page: Page, company: str,
                    resume_text: str = "", jd_text: str = ""):
    """
    Fill all real visible application form fields.
    Skips honeypots, search boxes, hidden fields.
    """

    # ── Text / email / tel / number inputs ───────────────────
    for inp in await page.locator(
            "input[type='text'], input[type='email'], "
            "input[type='tel'], input[type='number'], "
            "input:not([type])").all():
        try:
            if not await _is_real_field(page, inp):
                continue
            if (await inp.input_value()).strip():
                continue   # already has a value
            label = await _label_for(page, inp)
            if _is_skip_label(label):
                continue
            answer = await resolve(label, company, resume_text, jd_text)
            if answer:
                await inp.click()
                await asyncio.sleep(0.2)
                await inp.fill(str(answer))
                await asyncio.sleep(0.2)
        except Exception:
            continue

    # ── Textareas ─────────────────────────────────────────────
    for ta in await page.locator("textarea").all():
        try:
            if not await _is_real_field(page, ta):
                continue
            if (await ta.input_value()).strip():
                continue
            label = await _label_for(page, ta)
            if _is_skip_label(label):
                continue
            answer = await resolve(label, company, resume_text, jd_text)
            if answer:
                await ta.fill(answer)
                await asyncio.sleep(0.2)
        except Exception:
            continue

    # ── Selects ───────────────────────────────────────────────
    for sel in await page.locator("select").all():
        try:
            if not await _is_real_field(page, sel):
                continue
            if await sel.input_value():
                continue
            label = await _label_for(page, sel)
            if _is_skip_label(label):
                continue
            opts_els = await sel.locator("option").all()
            options  = [(await o.inner_text()).strip() for o in opts_els]
            options  = [o for o in options if o
                        and "select" not in o.lower()
                        and o != "--" and o != "---"]
            if not options:
                continue
            answer = await resolve(label, company, resume_text, jd_text)
            matched = False
            if answer:
                for opt in options:
                    if answer.lower() in opt.lower() or opt.lower() in answer.lower():
                        await sel.select_option(label=opt)
                        matched = True
                        break
            if not matched:
                picked = best_option(options)
                if picked:
                    await sel.select_option(label=picked)
            await asyncio.sleep(0.15)
        except Exception:
            continue

    # ── Radio buttons ─────────────────────────────────────────
    for group in await page.locator("fieldset, [role='radiogroup']").all():
        try:
            radios = await group.locator("input[type='radio']").all()
            if not radios:
                continue
            if any([await r.is_checked() for r in radios]):
                continue
            checked = False
            for r in radios:
                r_id = await r.get_attribute("id") or ""
                r_lbl = ""
                if r_id:
                    lel = page.locator(f"label[for='{r_id}']")
                    if await lel.count() > 0:
                        r_lbl = (await lel.first.inner_text()).strip()
                if should_check(r_lbl):
                    await r.check()
                    checked = True
                    break
            if not checked and radios:
                if await radios[0].is_visible():
                    await radios[0].check()
        except Exception:
            continue

    # ── Consent checkboxes only ───────────────────────────────
    for cb in await page.locator("input[type='checkbox']").all():
        try:
            if not await cb.is_visible():
                continue
            if await cb.is_checked():
                continue
            cb_id = await cb.get_attribute("id") or ""
            label = ""
            if cb_id:
                lel = page.locator(f"label[for='{cb_id}']")
                if await lel.count() > 0:
                    label = (await lel.first.inner_text()).strip()
            if any(k in label.lower() for k in [
                "agree", "consent", "accept", "terms", "authorize",
                "confirm", "acknowledge", "privacy", "certify"
            ]):
                await cb.check()
        except Exception:
            continue


async def upload_resume(page: Page, resume_path: str) -> bool:
    """Upload resume to any file input on the page."""
    if not os.path.exists(resume_path):
        print(f"  ⚠  Resume not found: {resume_path}")
        return False
    try:
        for fi in await page.locator("input[type='file']").all():
            accept = (await fi.get_attribute("accept") or "").lower()
            if not accept or "pdf" in accept or "doc" in accept or "*" in accept:
                await fi.set_input_files(resume_path)
                await asyncio.sleep(2)
                print(f"  📎  Resume uploaded")
                return True
    except Exception as e:
        print(f"  ⚠  Upload failed: {e}")
    return False


async def click_apply_button(page: Page) -> bool:
    """Find and click an Apply button if on a job detail page."""
    for text in ["Apply Now", "Apply for this Job", "Apply for this Role",
                 "Apply for Job", "Apply for Position",
                 "Start Application", "Easy Apply", "Apply"]:
        for selector in [f"a:has-text('{text}')", f"button:has-text('{text}')"]:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    return True
            except Exception:
                continue
    return False


async def find_and_submit(page: Page) -> bool:
    """Find and click the Submit/Send application button."""
    for sel in [
        "button[aria-label='Submit application']",
        "input[type='submit']",
        "button:has-text('Submit Application')",
        "button:has-text('Submit')",
        "button[type='submit']",
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
