"""
linkedin.py  — LinkedIn Easy Apply bot
"""
from __future__ import annotations
import time, os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from bot_state      import stop_event
from config         import LINKEDIN_EMAIL, LINKEDIN_PASSWORD, MAX_PER_PLATFORM, PHONE, CITY_STATE, CITY, STATE, ZIP
from resume_tailor  import process_resume
from folder_manager import setup_job_folder
from logger         import log_application
from ai_agent       import answer_questions_batch, smart_fallback
from job_tracker    import already_applied, record_application
from job_scorer     import should_apply
from stealth        import (
    make_stealth_context, human_delay, micro_delay,
    human_fill, human_move_and_click, periodic_keep_alive,
    is_safe_run_time,
)

SEARCH_TITLES = [
    "Salesforce Developer",
    "Salesforce Administrator",
    "Salesforce CRM Analyst",
    "Agentforce Developer",
]

ALLOWED_TITLES = [
    "salesforce developer", "salesforce administrator", "salesforce admin",
    "salesforce business analyst", "salesforce business systems analyst",
    "salesforce engineer", "salesforce analyst", "salesforce specialist",
    "salesforce consultant", "salesforce crm", "salesforce platform",
    "agentforce developer", "sr salesforce", "senior salesforce",
    "salesforce marketing cloud", "salesforce service cloud",
    "salesforce experience cloud", "salesforce dev", "salesforce cloud",
    "salesforce fsl", "salesforce field service", "salesforce cpq",
    "salesforce data cloud", "salesforce ba", "salesforce support",
]

BLOCKED_TITLES = [
    "architect", "director", "vp ", "vice president", "principal",
    "manager", "head of", "chief", "staff engineer",
    "technical lead", "tech lead",
]


def is_allowed(title: str) -> bool:
    t = title.lower()
    for b in BLOCKED_TITLES:
        if b in t:
            print(f"  Blocked: {title}")
            return False
    for a in ALLOWED_TITLES:
        if a in t:
            return True
    # Catch titles where "salesforce" or "sfdc" appears anywhere (e.g. "Business Systems Analyst (Salesforce)")
    if ("salesforce" in t or "sfdc" in t) and any(kw in t for kw in (
        "analyst", "developer", "admin", "engineer", "consultant", "specialist", "architect"
    )):
        return True
    print(f"  Not in list: {title}")
    return False


def match_role(title: str) -> str:
    t = title.lower()
    if "agentforce" in t:                    return "Agentforce Developer"
    if "admin" in t or "administrator" in t: return "Salesforce Admin"
    if "analyst" in t or "business" in t:   return "Salesforce Business Analyst"
    return "Salesforce Developer"


def get_text(page, *selectors) -> str:
    """Try multiple selectors, return first non-empty text found."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                t = el.inner_text().strip()
                if t:
                    return t
        except Exception:
            continue
    return ""


def dismiss_popups(page) -> str:
    """For use OUTSIDE the apply modal — dismisses generic LinkedIn popups."""
    try:
        for label, tag in [("Show jobs", "show_jobs"), ("Not now", "not_now"), ("Done", "done"), ("Got it", "got_it")]:
            btn = page.query_selector(f"button:has-text('{label}')")
            if btn:
                try:
                    btn.click()
                    human_delay(0.5, 1)
                    return tag
                except Exception:
                    pass
    except Exception:
        pass
    return ""


def handle_modal_interruption(page) -> str:
    """
    Called inside the apply modal loop.
    If LinkedIn's 'Save this application?' dialog appeared (triggered by accidental
    outside click), close it with X so we can continue — never Discard.
    Returns 'closed' if handled, '' otherwise.
    """
    try:
        # Detect the save/discard dialog
        save_dialog = page.query_selector("div.artdeco-modal__content:has-text('Save this application')")
        if not save_dialog:
            # Also try by checking if both Save and Discard buttons exist together
            has_save = page.query_selector("button:has-text('Save')")
            has_discard = page.query_selector("button:has-text('Discard')")
            if not (has_save and has_discard):
                return ""

        # Close the dialog with X — this returns to the application in progress
        close_btn = (
            page.query_selector("button[aria-label='Dismiss']") or
            page.query_selector("button.artdeco-modal__dismiss") or
            page.query_selector("button[data-test-dialog-close-btn]")
        )
        if close_btn:
            close_btn.click()
            human_delay(1, 1.5)
            print("  Closed 'Save?' dialog — continuing application")
            return "closed"
    except Exception:
        pass
    return ""


def remove_filters(page):
    try:
        for pill in page.query_selector_all("button.search-reusables__filter-pill-button"):
            try:
                t = pill.inner_text().lower()
                if "under 10" in t or "10 applicants" in t:
                    pill.click()
                    human_delay(1, 2)
                    print("  Removed 'Under 10 applicants' filter")
            except Exception:
                pass
    except Exception:
        pass


def get_title(page) -> str:
    """Extract job title — try many selectors then fallback to first h1."""
    for sel in [
        "h1.t-24",
        "h1.jobs-unified-top-card__job-title",
        ".job-details-jobs-unified-top-card__job-title h1",
        ".job-details-jobs-unified-top-card__job-title",
        ".jobs-unified-top-card__job-title",
        "h1[class*='job']",
        "h1",
    ]:
        t = get_text(page, sel)
        if t:
            return t
    return ""


def get_company(page) -> str:
    for sel in [
        ".job-details-jobs-unified-top-card__company-name a",
        ".job-details-jobs-unified-top-card__company-name",
        ".jobs-unified-top-card__company-name a",
        ".jobs-unified-top-card__company-name",
        "a[data-tracking-control-name*='company']",
        ".topcard__org-name-link",
        "[class*='company-name']",
    ]:
        t = get_text(page, sel)
        if t:
            return t
    return "Unknown"


def get_description(page) -> str:
    for sel in [
        "#job-details",
        ".jobs-description__content",
        ".jobs-description-content__text",
        ".job-view-layout .jobs-description",
        "[class*='description']",
    ]:
        t = get_text(page, sel)
        if len(t) > 100:
            return t
    return ""


def _fire_change(el) -> None:
    """Fire change + input events so LinkedIn registers the selection as valid."""
    try:
        el.evaluate("""el => {
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new Event('input',  {bubbles: true}));
            el.dispatchEvent(new Event('blur',   {bubbles: true}));
        }""")
    except Exception:
        pass


_STATE_MAP = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def _best_option(opts, answer: str) -> str | None:
    """
    Pick the best <option> text for a given AI answer.
    Priority:
      1. Exact match (case-insensitive)
      2. State name → abbreviation mapping (e.g. "Texas" → "TX")
      3. Answer contains option text or option text contains answer
      4. Yes/No heuristic
      5. First non-placeholder option (last resort)
    """
    al = answer.lower().strip()
    valid = [opt.inner_text().strip() for opt in opts
             if opt.inner_text().strip() and "select" not in opt.inner_text().lower()]

    # 1. Exact
    for ot in valid:
        if ot.lower() == al:
            return ot

    # 2. State name → abbreviation (handles "Texas" → "TX" dropdowns)
    state_abbr = _STATE_MAP.get(al)
    if state_abbr:
        for ot in valid:
            if ot.upper() == state_abbr or ot.lower().startswith(state_abbr.lower()):
                return ot

    # 3. Substring match
    for ot in valid:
        if ot.lower() in al or al in ot.lower():
            return ot

    # 4. Yes/No heuristic
    positive = any(w in al for w in ("yes", "true", "have", "do", "certified", "can", "will", "am"))
    negative = any(w in al for w in ("no", "false", "don't", "not", "cannot", "won't"))
    yes_opts = [ot for ot in valid if ot.lower() in ("yes", "y")]
    no_opts  = [ot for ot in valid if ot.lower() in ("no",  "n")]

    if yes_opts and positive and not negative:
        return yes_opts[0]
    if no_opts and negative:
        return no_opts[0]

    # 5. First valid option
    return valid[0] if valid else None


def fill_page(page, resume_path: str, job_title: str, company: str, job_desc: str = "") -> int:
    """
    Collect every unanswered field on the current modal page,
    batch-call AI for answers, fill them in.
    Fires change/input/blur events after each select so LinkedIn
    marks the field as valid (fixes 'Please enter a valid answer').
    """
    filled   = 0
    pending  = []
    seen_qs: set[str] = set()   # dedup — same Q can appear in multiple DOM groups

    try:
        groups = page.query_selector_all(
            ".jobs-easy-apply-form-section__grouping, "
            ".fb-dash-form-element, "
            "fieldset, "
            "div[data-test-form-element]"
        )
        for group in groups:
            try:
                label_el = group.query_selector(
                    "label, legend, .fb-dash-form-element__label, "
                    ".artdeco-text-input--label, .fb-form-element-label"
                )
                q = label_el.inner_text().strip() if label_el else ""
                if not q:
                    continue
                # Skip LinkedIn search UI elements that aren't application questions
                if any(skip in q.lower() for skip in (
                    "filter results by", "search by", "sort by", "filter by"
                )):
                    continue
                # Skip duplicate questions already queued from another DOM group
                if q in seen_qs:
                    continue

                # Number — always collect; store current value for verification
                num = group.query_selector("input[type='number']")
                if num:
                    try:
                        cv = num.input_value() or ""
                        pending.append((q, "number", num, cv)); seen_qs.add(q)
                    except Exception:
                        pass
                    continue

                # Text — always collect
                txt = (group.query_selector("input[type='text']") or
                       group.query_selector(".artdeco-text-input--input"))
                if txt:
                    try:
                        cv = txt.input_value() or ""
                        pending.append((q, "text", txt, cv)); seen_qs.add(q)
                    except Exception:
                        pass
                    continue

                # Textarea — only fill if empty (long-form answers shouldn't be overwritten)
                ta = group.query_selector("textarea")
                if ta:
                    try:
                        cv = ta.input_value() or ""
                        if not cv:
                            pending.append((q, "textarea", ta, "")); seen_qs.add(q)
                    except Exception:
                        pass
                    continue

                # Select / dropdown — always collect
                sel = group.query_selector("select, .fb-dropdown__select")
                if sel:
                    try:
                        cv = sel.input_value() or ""
                        if cv.lower().startswith("select"):
                            cv = ""
                        pending.append((q, "select", sel, cv)); seen_qs.add(q)
                    except Exception:
                        pass
                    continue

                # Radio — always collect; track currently checked label
                radios = group.query_selector_all("input[type='radio']")
                if radios:
                    cv = ""
                    for r in radios:
                        if r.is_checked():
                            try:
                                handle = r.evaluate_handle(
                                    "el => el.id ? document.querySelector(`label[for='${el.id}']`) : "
                                    "el.closest('li,div')?.querySelector('label')"
                                )
                                lbl = handle.as_element()
                                cv = lbl.inner_text().strip().lower() if lbl else ""
                            except Exception:
                                pass
                            break
                    pending.append((q, "radio", radios, cv)); seen_qs.add(q)
                    continue

                # LinkedIn custom Yes/No selectable — always collect; track selected label
                selectable = group.query_selector_all(
                    "[data-test-text-selectable-option], "
                    "li[class*='selectable'], "
                    "button[class*='selectable']"
                )
                if selectable:
                    cv = ""
                    for opt in selectable:
                        if (
                            "selected" in (opt.get_attribute("class") or "").lower() or
                            opt.get_attribute("aria-selected") == "true" or
                            opt.get_attribute("data-test-text-selectable-option__selected") == "true"
                        ):
                            try:
                                cv = (
                                    opt.get_attribute("data-test-text-selectable-option__label") or
                                    opt.get_attribute("aria-label") or
                                    opt.inner_text()
                                ).lower().strip()
                            except Exception:
                                pass
                            break
                    pending.append((q, "selectable", selectable, cv)); seen_qs.add(q)
            except Exception:
                continue

        if not pending:
            return 0

        def _needs_update(current_val: str, ai_ans: str, ftype: str, q_lower: str) -> bool:
            """Return True if the field needs to be updated with the AI answer."""
            if not current_val:
                return True   # empty — always fill
            if not ai_ans:
                return False  # AI gave nothing — don't overwrite
            cv, aa = current_val.strip().lower(), ai_ans.strip().lower()
            # Numeric fields: compare digits only
            if ftype in ("number", "text") and any(kw in q_lower for kw in (
                "year", "how many", "number of", "experience", "salary",
                "compensation", "rate", "wage", "expected", "desired", "pay"
            )):
                cv_d = "".join(c for c in cv if c.isdigit())
                aa_d = "".join(c for c in aa if c.isdigit())
                return bool(aa_d) and cv_d != aa_d
            # Text: skip if answers are essentially the same
            if ftype == "text":
                return not (cv == aa or aa in cv or cv in aa)
            # Radio / selectable: compare yes/no or label text
            if ftype in ("radio", "selectable"):
                return not (aa in cv or cv in aa)
            # Select: compare option text
            if ftype == "select":
                return not (aa in cv or cv in aa)
            return False   # textarea: already guarded at collection time

        # One batch AI call for all questions
        qs = [q for (q, _, _, _) in pending]
        answers = answer_questions_batch(
            qs, resume_path,
            job_title=job_title, company=company, platform="LinkedIn",
            job_description=job_desc
        )

        for (q, ftype, el, current_val) in pending:
            try:
                ans = answers.get(q, smart_fallback(q))
                if not _needs_update(current_val, ans, ftype, q.lower()):
                    print(f"    Q: {q[:60]} → ✓ already correct ({current_val[:30]})")
                    continue
                print(f"    Q: {q[:60]} → {ans[:40]}"
                      + (f"  (was: {current_val[:20]})" if current_val else ""))

                if ftype == "number":
                    digits = "".join(c for c in ans if c.isdigit() or c == ".").rstrip(".") or "0"
                    el.click()
                    el.evaluate("e => e.select()")
                    el.fill(digits)
                    el.press("Tab")
                    _fire_change(el)
                    filled += 1

                elif ftype == "text":
                    # Year/experience questions expect pure numbers — strip text like "4 years" → "4"
                    if any(kw in q.lower() for kw in ("year", "how many", "number of", "experience",
                                                         "salary", "compensation", "rate", "wage",
                                                         "expected", "desired", "pay")):
                        clean_ans = "".join(c for c in ans if c.isdigit() or c == ".").rstrip(".") or "0"
                    else:
                        clean_ans = ans[:200]
                    el.click()
                    el.evaluate("e => e.select()")
                    el.fill(clean_ans)
                    el.press("Tab")
                    _fire_change(el)
                    filled += 1

                elif ftype == "textarea":
                    el.click()
                    el.fill(ans)
                    _fire_change(el)
                    filled += 1

                elif ftype == "select":
                    opts = el.query_selector_all("option")
                    best = _best_option(opts, ans)
                    if best:
                        el.select_option(label=best)
                        human_delay(0.2, 0.4)
                        _fire_change(el)
                        filled += 1
                        print(f"    Selected: '{best}'")
                    else:
                        print(f"    No option matched for: {q[:50]}")

                elif ftype == "radio":
                    al = ans.lower()
                    done = False

                    def _find_label(radio_el):
                        """Find associated label using JS template literal — safe with special-char IDs."""
                        try:
                            handle = radio_el.evaluate_handle(
                                "el => el.id ? document.querySelector(`label[for='${el.id}']`) : "
                                "el.closest('li,div')?.querySelector('label')"
                            )
                            return handle.as_element()
                        except Exception:
                            return None

                    def _click_radio(radio_el) -> None:
                        """JS-click the label (or input) — bypasses pointer-event interception."""
                        lbl = _find_label(radio_el)
                        target = lbl if lbl else radio_el
                        try:
                            target.evaluate("el => el.click()")
                        except Exception:
                            try:
                                radio_el.evaluate("el => el.click()")
                            except Exception:
                                pass

                    def _label_text(radio_el) -> str:
                        lbl = _find_label(radio_el)
                        try:
                            return lbl.inner_text().strip().lower() if lbl else ""
                        except Exception:
                            return ""

                    # Try to match label text
                    for r in el:
                        lt = _label_text(r)
                        if lt and (lt in al or al in lt):
                            _click_radio(r); _fire_change(r); filled += 1; done = True; break
                    if not done:
                        # Default: pick "No" for sponsorship/visa questions, "Yes" otherwise
                        wants_no = any(w in q.lower() for w in (
                            "sponsor", "visa", "authorization", "require", "citizen"
                        ))
                        target_word = "no" if wants_no else "yes"
                        for r in el:
                            lt = _label_text(r)
                            if target_word in lt:
                                _click_radio(r); _fire_change(r); filled += 1; done = True; break
                        if not done and el:
                            _click_radio(el[0]); _fire_change(el[0]); filled += 1

                elif ftype == "selectable":
                    # LinkedIn custom Yes/No buttons (data-test-text-selectable-option)
                    al = ans.lower()
                    done = False
                    wants_no = any(w in q.lower() for w in (
                        "sponsor", "visa", "require", "citizen", "authorization"
                    ))
                    # Try to match by label text attribute first
                    for opt in el:
                        label_attr = (
                            opt.get_attribute("data-test-text-selectable-option__label") or
                            opt.get_attribute("aria-label") or ""
                        ).lower()
                        if label_attr and (label_attr in al or al in label_attr):
                            try:
                                opt.evaluate("el => el.click()")
                                filled += 1; done = True; break
                            except Exception:
                                pass
                    if not done:
                        target_word = "no" if wants_no else "yes"
                        for opt in el:
                            label_attr = (
                                opt.get_attribute("data-test-text-selectable-option__label") or
                                opt.get_attribute("aria-label") or
                                opt.inner_text()
                            ).lower()
                            if target_word in label_attr:
                                try:
                                    opt.evaluate("el => el.click()")
                                    filled += 1; done = True; break
                                except Exception:
                                    pass
                    if not done and el:
                        try:
                            el[0].evaluate("el => el.click()")
                            filled += 1
                        except Exception:
                            pass

                human_delay(0.2, 0.5)

            except Exception as e:
                print(f"    Fill error on '{q[:40]}': {e}")
                continue

    except Exception as e:
        print(f"  fill_page error: {e}")

    if filled:
        print(f"  Filled {filled} field(s)")
    return filled


def run_linkedin_bot():
    print("\nStarting LinkedIn bot...")
    safe, reason = is_safe_run_time()
    if not safe:
        print(f"  ⏰ Not running: {reason}")
        return 0
    applied = 0

    with sync_playwright() as p:
        browser, context, page = make_stealth_context(p, headless=False)
        try:
            # ── LOGIN ─────────────────────────────────────────────────────────
            print("  Logging into LinkedIn...")
            try:
                page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"  ⚠️  Browser navigation failed ({e}) — please open LinkedIn manually in the browser")

            human_delay(3, 5)

            _logged_in_paths = ("/feed", "/mynetwork", "/jobs", "/home", "/dashboard", "/in/")

            def _is_logged_in() -> bool:
                try:
                    path = urlparse(page.url).path
                    return any(k in path for k in _logged_in_paths)
                except Exception:
                    return False

            def _wait_for_login(timeout_s: int = 120) -> bool:
                """Poll until LinkedIn shows a logged-in URL. Returns True if detected."""
                print(f"  ⏳ Waiting up to {timeout_s}s for you to log in...")
                for _ in range(timeout_s):
                    if stop_event.is_set():
                        return False
                    if _is_logged_in():
                        return True
                    time.sleep(1)
                return False

            if _is_logged_in():
                print("  Session active — already logged in!")
            else:
                human_delay(3, 5)

                if not _is_logged_in():
                    # Try to find and fill the login form automatically
                    email_el = None
                    for s in ["#username", "input[name='session_key']",
                              "input[autocomplete='username']", "input[type='email']",
                              "input[id*='email']", "input[placeholder*='Email']",
                              "input[placeholder*='email']", "input[type='text']", "input"]:
                        try:
                            el = page.query_selector(s)
                            if el and el.bounding_box():  # skip hidden inputs
                                email_el = el; break
                        except Exception:
                            pass

                    pass_el = None
                    for s in ["#password", "input[name='session_password']",
                              "input[autocomplete='current-password']", "input[type='password']"]:
                        try:
                            el = page.query_selector(s)
                            if el and el.bounding_box():  # skip hidden inputs
                                pass_el = el; break
                        except Exception:
                            pass

                    if email_el and pass_el:
                        human_fill(page, email_el, LINKEDIN_EMAIL)
                        micro_delay()
                        human_fill(page, pass_el, LINKEDIN_PASSWORD)
                        human_delay(0.5, 1)
                        submit_el = None
                        for s in ["button[type='submit']", "button[data-litms-control-urn*='login']",
                                  "button:has-text('Sign in')", "button:has-text('Log in')"]:
                            try:
                                el = page.query_selector(s)
                                if el:
                                    submit_el = el; break
                            except Exception:
                                pass
                        if submit_el:
                            submit_el.evaluate("el => el.click()")
                        else:
                            pass_el.press("Enter")
                        human_delay(6, 9)
                    else:
                        # Can't fill automatically — ask user to log in manually in the browser
                        print("  ⚠️  Login form not found — please log in manually in the browser")
                        if not _wait_for_login(120):
                            print("  ❌ Login timeout — stopping")
                            return 0

            # Handle verification / checkpoint pages
            if any(k in urlparse(page.url).path for k in ("checkpoint", "challenge", "check-in", "verification")):
                print("  ⚠️  Verification needed — complete it in the browser")
                if not _wait_for_login(300):
                    print("  ❌ Verification timeout — stopping")
                    return 0

            print("  Logged in!")
            last_action = time.time()

            # ── SEARCH ────────────────────────────────────────────────────────
            for search_title in SEARCH_TITLES:
                if applied >= MAX_PER_PLATFORM or stop_event.is_set():
                    break

                print(f"\n  Searching: {search_title}")
                url = (
                    "https://www.linkedin.com/jobs/search/?"
                    f"keywords={search_title.replace(' ', '%20')}"
                    "&location=United%20States"
                    "&f_AL=true"   # Easy Apply only
                    "&f_TPR=r86400"  # past 24 hours
                )
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                human_delay(3, 5)
                remove_filters(page)
                human_delay(1, 2)

                # Scroll to load all cards
                for _ in range(3):
                    page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
                    human_delay(1, 1.5)
                page.evaluate("window.scrollTo(0,0)")
                human_delay(1, 2)

                # Get job IDs from cards
                items = page.query_selector_all("li[data-occludable-job-id]")
                if not items:
                    items = page.query_selector_all(".job-card-container, .jobs-search-results__list-item")

                job_ids = []
                for item in items:
                    jid = item.get_attribute("data-occludable-job-id") or item.get_attribute("data-job-id") or ""
                    if jid.strip():
                        job_ids.append(jid.strip())

                print(f"  Found {len(job_ids)} job IDs")
                if not job_ids:
                    continue

                # ── PER JOB ───────────────────────────────────────────────────
                for job_id in job_ids:
                    if applied >= MAX_PER_PLATFORM or stop_event.is_set():
                        break

                    last_action = periodic_keep_alive(page, last_action)
                    job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"

                    # Close any leftover modal overlay before clicking the next card
                    try:
                        if page.query_selector(".artdeco-modal-overlay"):
                            for close_sel in [
                                "button[aria-label='Dismiss']",
                                "button.artdeco-modal__dismiss",
                                "button[data-test-dialog-close-btn]",
                            ]:
                                btn = page.query_selector(close_sel)
                                if btn:
                                    btn.evaluate("el => el.click()")
                                    human_delay(0.8, 1.2)
                                    break
                            else:
                                page.keyboard.press("Escape")
                                human_delay(0.8, 1.2)
                    except Exception:
                        pass

                    try:
                        # Scroll card into view then click it to load detail panel
                        card = page.query_selector(f"li[data-occludable-job-id='{job_id}']")
                        if card:
                            card.scroll_into_view_if_needed()
                            human_delay(0.5, 1)
                            card.click()
                            human_delay(2, 3)
                        else:
                            page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                            human_delay(2, 3)
                    except Exception as e:
                        print(f"  Could not open job {job_id}: {e}")
                        continue

                    try:
                        dismiss_popups(page)

                        # Wait for the detail panel to populate
                        try:
                            page.wait_for_selector(
                                ".job-details-jobs-unified-top-card__job-title, "
                                ".jobs-unified-top-card__job-title, "
                                "h1",
                                timeout=8000
                            )
                        except Exception:
                            pass

                        # Read title from the detail panel (right side)
                        job_title = get_text(page,
                            ".job-details-jobs-unified-top-card__job-title",
                            ".jobs-unified-top-card__job-title",
                            ".t-24.t-bold.inline",
                            ".job-details-jobs-unified-top-card__job-title a",
                            "h1.t-24",
                            "h1",
                        )
                        if not job_title:
                            print(f"  Could not read title for {job_id} — skipping")
                            continue

                        company = get_text(page,
                            ".job-details-jobs-unified-top-card__company-name a",
                            ".job-details-jobs-unified-top-card__company-name",
                            ".jobs-unified-top-card__company-name a",
                            ".jobs-unified-top-card__company-name",
                            ".job-details-jobs-unified-top-card__primary-description a",
                        ) or "Unknown"

                        print(f"  Checking: {job_title} @ {company}")

                        # Title filter
                        if not is_allowed(job_title):
                            continue

                        # Duplicate check
                        if already_applied(job_url, company, job_title):
                            print(f"  Already applied — skipping")
                            continue

                        # Job description + location
                        job_desc = get_text(page,
                            ".jobs-description__content",
                            ".jobs-description-content__text",
                            "#job-details",
                            ".job-view-layout .jobs-description",
                        ) or ""
                        location = get_text(page,
                            ".job-details-jobs-unified-top-card__bullet",
                            ".jobs-unified-top-card__bullet",
                            ".job-details-jobs-unified-top-card__primary-description",
                        ) or "Unknown"

                        # Easy Apply button — in the right-side detail panel
                        apply_btn = None
                        for sel in [
                            ".jobs-apply-button--top-card button",
                            ".jobs-s-apply button",
                            "button.jobs-apply-button",
                            ".jobs-unified-top-card__content--two-pane button.jobs-apply-button",
                            "button[data-control-name='jobdetails_topcard_inapply']",
                        ]:
                            try:
                                b = page.query_selector(sel)
                                if b:
                                    apply_btn = b
                                    break
                            except Exception:
                                continue

                        if not apply_btn:
                            print(f"  No apply button — skipping")
                            continue

                        btn_text = ""
                        try:
                            btn_text = apply_btn.inner_text().strip().lower()
                        except Exception:
                            pass

                        if "easy apply" not in btn_text:
                            print(f"  Not Easy Apply ({btn_text}) — skipping")
                            continue

                        # Tailor resume
                        role = match_role(job_title)
                        resume_path, resume_filename = process_resume(role, job_title, company, job_desc)

                        # Score check — skip scoring if description is empty (can't score)
                        if job_desc:
                            ok, score = should_apply(job_title, company, job_desc, resume_path, threshold=45)
                            if not ok:
                                print(f"  Score too low ({score}/100) — skipping")
                                continue
                        else:
                            score = 75  # assume good match if no description available

                        print(f"  ✅ Applying [{score}/100]: {job_title} @ {company}")

                        # Click Easy Apply — use JS click to avoid backdrop misfire
                        try:
                            apply_btn.evaluate("el => el.click()")
                        except Exception:
                            apply_btn.click()
                        human_delay(2, 3)

                        # ── MODAL LOOP ────────────────────────────────────────
                        submitted = False
                        consecutive_fill_fails = 0
                        for step in range(20):
                            if stop_event.is_set():
                                # Discard and exit cleanly
                                try:
                                    d = page.query_selector("button:has-text('Discard')") or \
                                        page.query_selector("button[aria-label='Dismiss']")
                                    if d: d.click()
                                except Exception:
                                    pass
                                break

                            human_delay(1, 2)
                            last_action = periodic_keep_alive(page, last_action)

                            # Close any "Save this application?" dialog — use X, not Discard
                            handle_modal_interruption(page)

                            # City / location fields — type then pick from autocomplete dropdown
                            for loc_sel in [
                                "input[id*='location']",
                                "input[aria-label*='Location']",
                                "input[aria-label*='location']",
                                "input[placeholder*='Location']",
                                "input[placeholder*='location']",
                                "input[id*='city']",
                                "input[aria-label*='City']",
                                "input[aria-label*='city']",
                                "input[placeholder*='City']",
                                "input[placeholder*='city']",
                            ]:
                                loc_el = page.query_selector(loc_sel)
                                if loc_el:
                                    try:
                                        if not loc_el.input_value():
                                            loc_el.click()
                                            loc_el.fill("")
                                            loc_el.type(CITY_STATE, delay=50)
                                            # Wait for autocomplete dropdown
                                            human_delay(1.0, 1.5)
                                            # Try all known LinkedIn autocomplete selectors
                                            picked = False
                                            for drop_sel in [
                                                ".basic-typeahead__selectable",
                                                "[role='option']",
                                                ".search-basic-typeahead__hit",
                                                "li[class*='typeahead']",
                                                "div[class*='autocomplete'] li",
                                                "ul[role='listbox'] li",
                                            ]:
                                                opts = page.query_selector_all(drop_sel)
                                                if opts:
                                                    opts[0].click()
                                                    picked = True
                                                    break
                                            if not picked:
                                                # No dropdown appeared — just press Enter
                                                loc_el.press("Enter")
                                            human_delay(0.3, 0.5)
                                    except Exception:
                                        pass
                                    break

                            # Phone
                            for phone_sel in [
                                "input[id*='phoneNumber-nationalNumber']",
                                "input[aria-label*='Mobile phone']",
                                "input[id*='phoneNumber']",
                                "input[name*='phone']",
                            ]:
                                phone_el = page.query_selector(phone_sel)
                                if phone_el:
                                    try:
                                        if not phone_el.input_value():
                                            phone_el.fill(PHONE)
                                    except Exception:
                                        pass
                                    break

                            # Resume upload
                            for upload_sel in [
                                "input[id*='jobs-document-upload-file-input-upload-resume']",
                                "input[type='file'][id*='upload-resume']",
                                "input[type='file']",
                            ]:
                                up = page.query_selector(upload_sel)
                                if up:
                                    try:
                                        up.set_input_files(resume_path)
                                        human_delay(1, 2)
                                    except Exception:
                                        pass
                                    break

                            # Fill questions
                            fill_page(page, resume_path, job_title, company, job_desc)
                            human_delay(0.5, 1)

                            def safe_click(btn):
                                """Click a modal button via JS to avoid backdrop misfire."""
                                try:
                                    btn.evaluate("el => el.click()")
                                except Exception:
                                    try: btn.click()
                                    except Exception: pass

                            # Submit?
                            sub = (page.query_selector("button[aria-label='Submit application']") or
                                   page.query_selector("button[data-live-test-easy-apply-submit-button]"))
                            if sub:
                                try:
                                    uf = page.query_selector("label[for='follow-company-checkbox']")
                                    if uf: uf.evaluate("el => el.click()")
                                except Exception:
                                    pass
                                safe_click(sub)
                                human_delay(2, 3)
                                dismiss_popups(page)
                                submitted = True
                                break

                            # Review?
                            rev = (page.query_selector("button[aria-label='Review your application']") or
                                   page.query_selector("button[data-live-test-easy-apply-review-button]"))
                            if rev:
                                safe_click(rev)
                                continue

                            # Next?
                            nxt = (page.query_selector("button[aria-label='Continue to next step']") or
                                   page.query_selector("button[data-live-test-easy-apply-next-button]"))
                            if nxt:
                                safe_click(nxt)
                                continue

                            # Errors — retry fill (max 3 times per step to prevent infinite loop)
                            if page.query_selector(".artdeco-inline-feedback--error, .artdeco-inline-feedback__message"):
                                consecutive_fill_fails += 1
                                if consecutive_fill_fails >= 3:
                                    print(f"  ⚠️  Stuck on step {step} after 3 fill retries — skipping job")
                                    try:
                                        d = page.query_selector("button:has-text('Discard')") or \
                                            page.query_selector("button[aria-label='Dismiss']")
                                        if d: d.click()
                                    except Exception:
                                        pass
                                    break
                                fill_page(page, resume_path, job_title, company, job_desc)
                                human_delay(1, 2)
                                for s in ["button[aria-label='Continue to next step']",
                                          "button[aria-label='Review your application']",
                                          "button[aria-label='Submit application']"]:
                                    rb = page.query_selector(s)
                                    if rb:
                                        safe_click(rb)
                                        break
                                continue
                            consecutive_fill_fails = 0

                            print(f"  No button on step {step} — giving up")
                            try:
                                d = page.query_selector("button:has-text('Discard')") or \
                                    page.query_selector("button[aria-label='Dismiss']")
                                if d: d.click()
                            except Exception:
                                pass
                            break

                        if submitted:
                            applied += 1
                            print(f"  🎉 Applied! ({applied}/{MAX_PER_PLATFORM})")
                            setup_job_folder(company, "LinkedIn", resume_path, job_title)
                            record_application(job_url, job_title, company, "LinkedIn", resume_filename, score)
                            log_application(
                                job_title=job_title, company=company,
                                platform="LinkedIn", url=job_url,
                                resume_filename=resume_filename,
                                job_type="Contract" if "contract" in job_desc.lower() else "Full-time",
                                location=location,
                                work_model="Remote" if "remote" in (job_desc + location).lower() else "Hybrid" if "hybrid" in (job_desc + location).lower() else "On-site",
                            )
                            human_delay(3, 6)
                        else:
                            print(f"  Could not complete — moving on")

                    except Exception as e:
                        print(f"  Error on {job_id}: {e}")
                        try:
                            dismiss_popups(page)
                        except Exception:
                            pass
                        continue

        finally:
            browser.close()

    print(f"\nDone! Applied to {applied} LinkedIn jobs.")
    return applied
