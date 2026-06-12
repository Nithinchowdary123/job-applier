"""
dice.py  — Dice.com job application bot
"""
from __future__ import annotations
import time, os, re, shutil
from playwright.sync_api import sync_playwright
from bot_state      import stop_event
from config         import DICE_EMAIL, DICE_PASSWORD, MAX_PER_PLATFORM, PHONE, OUTPUT_RESUMES
from resume_tailor  import process_resume
from folder_manager import setup_job_folder
from logger         import log_application
from ai_agent       import answer_questions_batch, smart_fallback, read_resume_text
from cover_letter   import generate_cover_letter
from job_tracker    import already_applied, record_application
from job_scorer     import should_apply
from stealth        import (
    make_stealth_context, human_delay, micro_delay,
    human_fill, human_move_and_click, periodic_keep_alive,
    is_safe_run_time,
)
import fitz  # PyMuPDF — for writing cover letter PDF


def _save_cover_letter_pdf(text: str, path: str) -> None:
    """Save cover letter text as a clean PDF using PyMuPDF."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    margin = 60
    y = margin
    font_size = 11
    line_height = font_size * 1.5

    for line in text.splitlines():
        # Word-wrap long lines
        words = line.split()
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            # Estimate width: ~6px per char at font_size 11
            if len(test) * (font_size * 0.55) > (595 - margin * 2):
                page.insert_text((margin, y), current, fontsize=font_size, color=(0, 0, 0))
                y += line_height
                current = word
                if y > 842 - margin:
                    page = doc.new_page(width=595, height=842)
                    y = margin
            else:
                current = test
        if current:
            page.insert_text((margin, y), current, fontsize=font_size, color=(0, 0, 0))
            y += line_height
        else:
            y += line_height * 0.5  # blank line gap
        if y > 842 - margin:
            page = doc.new_page(width=595, height=842)
            y = margin

    doc.save(path)
    doc.close()

SEARCH_TITLES = [
    "Salesforce Developer",
    "Salesforce Administrator",
    "Salesforce Business Analyst",
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


def get_job_links(page) -> list[str]:
    """Scrape all job detail links from the search results page."""
    links: set[str] = set()
    try:
        for el in page.query_selector_all("a[href*='/job-detail/']"):
            href = el.get_attribute("href") or ""
            if href:
                if not href.startswith("http"):
                    href = "https://www.dice.com" + href
                links.add(href.split("?")[0])  # strip query params
    except Exception:
        pass

    if not links:
        try:
            hrefs = page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href*="/job-detail/"]'))
                    .map(a => a.href.split('?')[0])
                    .filter((v,i,a) => a.indexOf(v)===i)
            """)
            links.update(hrefs)
        except Exception:
            pass

    return list(links)


def get_text(page, *selectors) -> str:
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


def get_company(page) -> str:
    # 1. JSON-LD structured data — most reliable (many job boards embed this)
    try:
        company = page.evaluate("""
            () => {
                for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                    try {
                        const d = JSON.parse(s.textContent);
                        const items = Array.isArray(d) ? d : [d];
                        for (const item of items) {
                            if (item['@type'] === 'JobPosting' && item.hiringOrganization?.name)
                                return item.hiringOrganization.name;
                        }
                    } catch(e) {}
                }
                return '';
            }
        """)
        if company and len(company) < 80:
            return company.strip()
    except Exception:
        pass

    # 2. Standard CSS selectors
    for sel in [
        "[data-cy='hiring-company-name']",
        "a[data-cy='employer-name-link']",
        ".employer-name",
        "[class*='companyName']",
        ".company-header-name",
        "[class*='employer']",
    ]:
        t = get_text(page, sel)
        if t and len(t) < 80:
            return t.strip()

    # 3. JS — pierce all shadow DOM components broadly
    try:
        t = page.evaluate("""
            () => {
                // Collect all shadow roots on the page and search inside them
                function pierceAll(root) {
                    const sels = [
                        '[data-cy="hiring-company-name"]', 'a[data-cy="employer-name-link"]',
                        '.employer-name', '[class*="companyName"]', '[class*="company-name"]',
                        '[class*="CompanyName"]', '[class*="employer"]'
                    ];
                    for (const s of sels) {
                        const el = root.querySelector(s);
                        if (el && el.textContent.trim().length < 80) return el.textContent.trim();
                    }
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) {
                            const r = pierceAll(el.shadowRoot);
                            if (r) return r;
                        }
                    }
                    return '';
                }
                return pierceAll(document);
            }
        """)
        if t and len(t) < 80:
            return t.strip()
    except Exception:
        pass

    # 4. Page title — Dice format: "Job Title at Company | Dice"
    try:
        title = page.title()
        if " at " in title:
            company = title.split(" at ", 1)[1].split("|")[0].split("-")[0].strip()
            if company and len(company) < 80:
                return company
    except Exception:
        pass

    # 5. og:title meta tag
    try:
        og = page.get_attribute('meta[property="og:title"]', "content") or ""
        if " at " in og:
            company = og.split(" at ", 1)[1].split("|")[0].strip()
            if company and len(company) < 80:
                return company
    except Exception:
        pass

    return "Unknown"


def get_description(page) -> str:
    for sel in [
        "div#jobDescription",
        "[data-cy='jobDescription']",
        "[data-testid='jobDescription']",
        ".job-description",
        "section.job-description",
        "div[class*='description']",
    ]:
        t = get_text(page, sel)
        if len(t) > 100:
            return t
    try:
        t = page.evaluate("""
            () => {
                // Try shadow DOM
                const wc = document.querySelector('dhi-jd-detail');
                if (wc && wc.shadowRoot) {
                    const el = wc.shadowRoot.querySelector('div');
                    if (el && el.innerText.length > 100) return el.innerText;
                }
                // Fallback: largest content div
                let best = '', bestLen = 0;
                document.querySelectorAll('div').forEach(d => {
                    if (d.children.length < 25 && d.innerText.length > bestLen) {
                        best = d.innerText; bestLen = d.innerText.length;
                    }
                });
                return best.length > 200 ? best : '';
            }
        """)
        if t and len(t) > 100:
            return t
    except Exception:
        pass
    return ""


def fill_page(page, resume_path: str, job_title: str, company: str, job_desc: str = "") -> int:
    filled   = 0
    pending  = []
    seen_qs: set[str] = set()   # dedup same question from multiple DOM groups
    try:
        groups = page.query_selector_all(
            "div[class*='form-group'], div[class*='question'], fieldset, "
            ".jobs-easy-apply-form-section__grouping"
        )
        for group in groups:
            try:
                label_el = group.query_selector("label, legend")
                q = label_el.inner_text().strip() if label_el else ""
                if not q or q in seen_qs:
                    continue

                num = group.query_selector("input[type='number']")
                if num:
                    try:
                        cv = num.input_value() or ""
                        pending.append((q, "number", num, cv)); seen_qs.add(q)
                    except Exception:
                        pass
                    continue

                txt = group.query_selector("input[type='text']")
                if txt:
                    try:
                        cv = txt.input_value() or ""
                        pending.append((q, "text", txt, cv)); seen_qs.add(q)
                    except Exception:
                        pass
                    continue

                ta = group.query_selector("textarea")
                if ta:
                    try:
                        cv = ta.input_value() or ""
                        if not cv:
                            pending.append((q, "textarea", ta, "")); seen_qs.add(q)
                    except Exception:
                        pass
                    continue

                sel = group.query_selector("select")
                if sel:
                    try:
                        cv = sel.input_value() or ""
                        if cv.lower().startswith("select"):
                            cv = ""
                        pending.append((q, "select", sel, cv)); seen_qs.add(q)
                    except Exception:
                        pass
                    continue

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
            except Exception:
                continue

        if not pending:
            return 0

        def _needs_update(current_val: str, ai_ans: str, ftype: str, q_lower: str) -> bool:
            if not current_val:
                return True
            if not ai_ans:
                return False
            cv, aa = current_val.strip().lower(), ai_ans.strip().lower()
            if ftype in ("number", "text") and any(kw in q_lower for kw in (
                "year", "how many", "number of", "experience", "salary",
                "compensation", "rate", "wage", "expected", "desired", "pay"
            )):
                cv_d = "".join(c for c in cv if c.isdigit())
                aa_d = "".join(c for c in aa if c.isdigit())
                return bool(aa_d) and cv_d != aa_d
            if ftype == "text":
                return not (cv == aa or aa in cv or cv in aa)
            if ftype in ("radio", "select"):
                return not (aa in cv or cv in aa)
            return False

        qs = [q for (q, _, _, _) in pending]
        answers = answer_questions_batch(qs, resume_path, job_title=job_title, company=company, platform="Dice", job_description=job_desc)

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
                    el.fill(digits); filled += 1
                elif ftype == "text":
                    if any(kw in q.lower() for kw in ("year", "how many", "number of", "experience",
                                                         "salary", "compensation", "rate", "wage",
                                                         "expected", "desired", "pay")):
                        clean_ans = "".join(c for c in ans if c.isdigit() or c == ".").rstrip(".") or "0"
                    else:
                        clean_ans = ans[:200]
                    el.fill(clean_ans); filled += 1
                elif ftype == "textarea":
                    el.fill(ans); filled += 1
                elif ftype == "select":
                    opts = el.query_selector_all("option")
                    al = ans.lower()
                    best = None
                    for opt in opts:
                        ot = opt.inner_text().strip()
                        if ot and "select" not in ot.lower() and (ot.lower() in al or al in ot.lower()):
                            best = ot; break
                    if not best:
                        for opt in opts:
                            ot = opt.inner_text().strip()
                            if ot and "select" not in ot.lower():
                                best = ot; break
                    if best:
                        el.select_option(label=best); filled += 1
                elif ftype == "radio":
                    al = ans.lower()
                    done = False
                    wants_no = any(w in q.lower() for w in (
                        "sponsor", "visa", "require", "citizen", "authorization"
                    ))

                    def _dice_label_text(radio_el) -> str:
                        try:
                            handle = radio_el.evaluate_handle(
                                "el => el.id ? document.querySelector(`label[for='${el.id}']`) : "
                                "el.closest('li,div')?.querySelector('label')"
                            )
                            lbl = handle.as_element()
                            return lbl.inner_text().strip().lower() if lbl else ""
                        except Exception:
                            return ""

                    def _dice_click_radio(radio_el) -> None:
                        try:
                            handle = radio_el.evaluate_handle(
                                "el => el.id ? document.querySelector(`label[for='${el.id}']`) : "
                                "el.closest('li,div')?.querySelector('label')"
                            )
                            lbl = handle.as_element()
                            target = lbl if lbl else radio_el
                            target.evaluate("el => el.click()")
                        except Exception:
                            try:
                                radio_el.evaluate("el => el.click()")
                            except Exception:
                                pass

                    for r in el:
                        lt = _dice_label_text(r)
                        if lt and (lt in al or al in lt):
                            _dice_click_radio(r); filled += 1; done = True; break
                    if not done:
                        target_word = "no" if wants_no else "yes"
                        for r in el:
                            lt = _dice_label_text(r)
                            if target_word in lt:
                                _dice_click_radio(r); filled += 1; done = True; break
                    if not done and el:
                        _dice_click_radio(el[0]); filled += 1
                human_delay(0.1, 0.3)
            except Exception:
                continue
    except Exception as e:
        print(f"  Fill error: {e}")
    if filled:
        print(f"  Filled {filled} field(s)")
    return filled


def run_dice_bot():
    print("\nStarting Dice bot...")
    safe, reason = is_safe_run_time()
    if not safe:
        print(f"  ⏰ Not running: {reason}")
        return 0
    applied = 0
    seen: set[str] = set()

    with sync_playwright() as p:
        browser, context, page = make_stealth_context(p, headless=False)
        try:
            # ── LOGIN ─────────────────────────────────────────────────────────
            print("  Logging into Dice...")
            page.goto("https://www.dice.com/dashboard/login", wait_until="domcontentloaded", timeout=60000)
            human_delay(3, 5)

            try:
                page.wait_for_selector("input[name='email']", timeout=15000)
                human_fill(page, page.query_selector("input[name='email']"), DICE_EMAIL)
                page.click("button[type='submit']")
                human_delay(2, 3)
                page.wait_for_selector("input[name='password']", timeout=15000)
                human_fill(page, page.query_selector("input[name='password']"), DICE_PASSWORD)
                page.click("button[type='submit']")
                human_delay(5, 8)
            except Exception as e:
                print(f"  Login issue: {e} — please log in manually")
                input("  Press Enter when logged in...")

            print("  Logged in!")
            last_action = time.time()

            # ── SEARCH LOOP ───────────────────────────────────────────────────
            for title in SEARCH_TITLES:
                if applied >= MAX_PER_PLATFORM or stop_event.is_set():
                    break

                print(f"\n  Searching: {title}")
                search_url = (
                    f"https://www.dice.com/jobs?q={title.replace(' ', '%20')}"
                    "&countryCode=US&radius=30&radiusUnit=mi"
                    "&page=1&pageSize=20&filters.postedDate=ONE_DAY"
                    "&filters.employmentType=FULLTIME%7CCONTRACT"
                    "&language=en"
                )
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                human_delay(4, 6)

                # Scroll to trigger lazy loading
                for _ in range(3):
                    page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
                    human_delay(1, 2)
                page.evaluate("window.scrollTo(0,0)")
                human_delay(1, 2)

                try:
                    page.wait_for_selector("a[href*='/job-detail/']", timeout=15000)
                except Exception:
                    print(f"  No jobs found — skipping")
                    continue

                links = [l for l in get_job_links(page) if l not in seen]
                print(f"  Found {len(links)} new jobs")
                if not links:
                    continue

                # ── PER JOB ───────────────────────────────────────────────────
                for job_url in links:
                    if applied >= MAX_PER_PLATFORM or stop_event.is_set():
                        break

                    seen.add(job_url)
                    last_action = periodic_keep_alive(page, last_action)

                    try:
                        try:
                            page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                        except Exception as nav_err:
                            if "closed" in str(nav_err).lower():
                                print("  Browser closed — stopping")
                                break
                            raise
                        human_delay(2, 4)

                        job_title = get_text(page, "h1") or ""
                        if not job_title:
                            print(f"  Could not read title — skipping")
                            continue

                        company = get_company(page)
                        print(f"  Checking: {job_title} @ {company}")

                        if not is_allowed(job_title):
                            continue

                        if already_applied(job_url, company, job_title):
                            print(f"  Already applied — skipping")
                            continue

                        job_desc = get_description(page)
                        work_model = "Remote" if "remote" in job_desc.lower() else "Hybrid" if "hybrid" in job_desc.lower() else "On-site"
                        job_type   = "Contract" if "contract" in job_desc.lower() else "Full-time"

                        # Find Apply button
                        apply_btn = None
                        for sel in [
                            "apply-button-wc",              # Dice web component
                            "button[data-cy='apply-button']",
                            "a[data-cy='apply-button']",
                            ".btn-apply",
                        ]:
                            try:
                                b = page.query_selector(sel)
                                if b:
                                    apply_btn = b; break
                            except Exception:
                                continue

                        if not apply_btn:
                            # Scan all buttons for "Apply"
                            try:
                                for b in page.query_selector_all("button, a"):
                                    txt = b.inner_text().strip().lower()
                                    if txt in ("apply now", "apply", "easy apply", "apply today"):
                                        apply_btn = b; break
                            except Exception:
                                pass

                        if not apply_btn:
                            print(f"  No apply button — skipping")
                            continue

                        # Tailor resume + score check
                        role = match_role(job_title)
                        resume_path, resume_filename = process_resume(role, job_title, company, job_desc)
                        if job_desc:
                            ok, score = should_apply(job_title, company, job_desc, resume_path, threshold=50)
                            if not ok:
                                print(f"  Score too low ({score}/100) — skipping")
                                continue
                        else:
                            score = 75  # no description available — assume good match

                        print(f"  ✅ Applying [{score}/100]: {job_title} @ {company}")

                        # Click apply — handle Dice's web component shadow DOM button
                        try:
                            clicked = page.evaluate("""
                                () => {
                                    const wc = document.querySelector('apply-button-wc');
                                    if (wc && wc.shadowRoot) {
                                        const btn = wc.shadowRoot.querySelector('button, a');
                                        if (btn) { btn.click(); return true; }
                                    }
                                    return false;
                                }
                            """)
                            if not clicked:
                                apply_btn.evaluate("el => el.click()")
                        except Exception:
                            human_move_and_click(page, apply_btn)
                        human_delay(2, 3)

                        # ── APPLY MODAL LOOP ──────────────────────────────────
                        submitted = False
                        resume_uploaded = False
                        cover_letter_done = False
                        last_page_sig = ""   # content signature for stuck detection
                        same_page_count = 0
                        for step in range(10):
                            if stop_event.is_set():
                                break

                            human_delay(1.5, 2.5)

                            # Stuck detection: Dice is a SPA so URL doesn't change between steps.
                            # Use first 300 chars of body text as the page signature instead.
                            try:
                                page_sig = (page.inner_text("body") or "")[:300]
                            except Exception:
                                page_sig = page.url
                            if page_sig == last_page_sig:
                                same_page_count += 1
                                if same_page_count >= 3:
                                    print(f"  Stuck on same page after {step} steps — giving up")
                                    break
                            else:
                                same_page_count = 0
                                last_page_sig = page_sig
                            last_action = periodic_keep_alive(page, last_action)

                            page_text = ""
                            try:
                                page_text = page.inner_text("body").lower()
                            except Exception:
                                pass

                            # ── STEP 1: Resume & Cover Letter page ────────────
                            if "resume & cover letter" in page_text or "resume" in page_text:
                                if not resume_uploaded:
                                    try:
                                        # Flow: click "..." in Resume section → click Replace →
                                        # macOS file dialog opens → press Escape to cancel it →
                                        # resume slot is now empty → set_input_files() to upload our PDF

                                        # Step A: Find and click the "..." button in the Resume section
                                        # Look for the dots button that is inside the resume card (above cover letter)
                                        dots_clicked = False
                                        resume_card = None
                                        for card_sel in [
                                            "div:has(h2:has-text('Resume'))",
                                            "div:has(p:has-text('Resume'))",
                                            "section:has-text('Resume')",
                                        ]:
                                            try:
                                                resume_card = page.query_selector(card_sel)
                                                if resume_card:
                                                    break
                                            except Exception:
                                                pass

                                        if resume_card:
                                            # Find dots button inside the resume card
                                            for dots_sel in [
                                                "button[aria-label*='option']",
                                                "button[aria-label*='more']",
                                                "button[aria-label*='More']",
                                                "button",
                                            ]:
                                                try:
                                                    dots = resume_card.query_selector(dots_sel)
                                                    if dots:
                                                        dots.evaluate("el => el.click()")
                                                        dots_clicked = True
                                                        print("  Clicked ... in Resume section")
                                                        break
                                                except Exception:
                                                    pass
                                        else:
                                            # Fallback: find first dots button on page (Resume card is always above Cover Letter)
                                            for btn in page.query_selector_all("button"):
                                                try:
                                                    txt = btn.inner_text().strip()
                                                    lbl = (btn.get_attribute("aria-label") or "").lower()
                                                    if txt in ("...", "•••", "⋯") or "option" in lbl or "more" in lbl:
                                                        # Check it's above the cover letter section by Y position
                                                        cover_el = page.query_selector("div:has-text('Cover letter'), div:has-text('Cover Letter')")
                                                        btn_y = btn.evaluate("el => el.getBoundingClientRect().top")
                                                        cover_y = cover_el.evaluate("el => el.getBoundingClientRect().top") if cover_el else 9999
                                                        if btn_y < cover_y:
                                                            btn.evaluate("el => el.click()")
                                                            dots_clicked = True
                                                            print("  Clicked ... (fallback) in Resume section")
                                                            break
                                                except Exception:
                                                    pass

                                        if dots_clicked:
                                            human_delay(0.8, 1.2)

                                            # Step B: Click Replace
                                            replace_btn = None
                                            for r_sel in [
                                                "button:has-text('Replace')",
                                                "li:has-text('Replace')",
                                                "[role='menuitem']:has-text('Replace')",
                                                "span:has-text('Replace')",
                                            ]:
                                                try:
                                                    replace_btn = page.query_selector(r_sel)
                                                    if replace_btn:
                                                        break
                                                except Exception:
                                                    pass

                                            if replace_btn:
                                                # Step C: Click Replace — this opens the macOS file picker
                                                # We intercept the file input BEFORE the dialog opens
                                                # by setting files directly on the hidden input
                                                with page.expect_file_chooser(timeout=5000) as fc_info:
                                                    replace_btn.evaluate("el => el.click()")
                                                file_chooser = fc_info.value
                                                file_chooser.set_files(resume_path)
                                                human_delay(2, 3)
                                                resume_uploaded = True
                                                print(f"  ✅ Resume replaced via file chooser: {os.path.basename(resume_path)}")
                                            else:
                                                print("  Replace button not found — pressing Escape")
                                                page.keyboard.press("Escape")
                                                resume_uploaded = True  # use profile resume
                                        else:
                                            print("  Could not find ... button — using profile resume")
                                            resume_uploaded = True

                                    except Exception as e:
                                        print(f"  Resume upload error: {e}")
                                        resume_uploaded = True  # don't retry, use profile resume

                                # ── Cover Letter upload (once per application) ──
                                if resume_uploaded and not cover_letter_done and "cover letter" in page_text:
                                    cover_letter_done = True  # set immediately to prevent re-running
                                    try:
                                        resume_text = read_resume_text(resume_path)
                                        cl_text = generate_cover_letter(job_title, company, job_desc, resume_text)
                                        if cl_text:
                                            safe_title   = re.sub(r"[^\w\s-]", "", job_title).replace(" ", "_")
                                            safe_company = re.sub(r"[^\w\s-]", "", company).replace(" ", "_")
                                            cl_filename  = f"CoverLetter_{safe_title}_{safe_company}.pdf" if safe_company.lower() not in ("unknown", "") else f"CoverLetter_{safe_title}.pdf"
                                            cl_path      = os.path.join(OUTPUT_RESUMES, cl_filename)
                                            _save_cover_letter_pdf(cl_text, cl_path)
                                            print(f"  ✅ Cover letter generated: {cl_filename}")

                                            # Upload: find all file inputs — cover letter is the 2nd one
                                            # Use set_input_files() directly (no file chooser dialog needed)
                                            file_inputs = page.query_selector_all("input[type='file']")
                                            cl_input = file_inputs[1] if len(file_inputs) >= 2 else None
                                            if cl_input:
                                                try:
                                                    cl_input.set_input_files(cl_path)
                                                    human_delay(1.5, 2.5)
                                                    print(f"  ✅ Cover letter uploaded")
                                                except Exception as e:
                                                    print(f"  Cover letter upload error: {e}")
                                            else:
                                                print(f"  No cover letter input found — saved to folder only")

                                            # Copy to job folder
                                            job_folder_path = os.path.expanduser(f"~/Desktop/Job Applications/{company.replace(' ', '_')}_Dice")
                                            if os.path.isdir(job_folder_path):
                                                shutil.copy2(cl_path, os.path.join(job_folder_path, cl_filename))
                                                print(f"  📄 Cover letter saved to job folder")
                                    except Exception as e:
                                        print(f"  Cover letter error: {e}")

                            # ── STEP 2: Review page ────────────────────────────
                            if "review your application" in page_text:
                                sub = None
                                for s_sel in [
                                    "button:has-text('Submit')",
                                    "button[data-cy='submit-button']",
                                    "button[type='submit']",
                                ]:
                                    try:
                                        sub = page.query_selector(s_sel)
                                        if sub:
                                            break
                                    except Exception:
                                        pass
                                if sub:
                                    print("  Submitting application...")
                                    sub.evaluate("el => el.click()")
                                    human_delay(2, 3)
                                    submitted = True
                                    break
                                else:
                                    print(f"  On review page but no Submit button found")

                            # Phone
                            ph = page.query_selector("input[name*='phone'], input[id*='phone']")
                            if ph:
                                try:
                                    if not ph.input_value():
                                        ph.fill(PHONE)
                                except Exception:
                                    pass

                            fill_page(page, resume_path, job_title, company, job_desc)

                            # Next button
                            nxt = None
                            for n_sel in [
                                "button[data-cy='next-button']",
                                "button:has-text('Next')",
                                "button:has-text('Continue')",
                            ]:
                                try:
                                    b = page.query_selector(n_sel)
                                    if b and b.is_visible():
                                        nxt = b; break
                                except Exception:
                                    pass
                            if nxt:
                                print(f"  Clicking Next (step {step + 1})")
                                nxt.evaluate("el => el.click()")
                                human_delay(2, 3)
                                continue

                            # Submit button (if on review page but not detected by page_text yet)
                            sub = None
                            for s_sel in [
                                "button:has-text('Submit')",
                                "button[data-cy='submit-button']",
                            ]:
                                try:
                                    b = page.query_selector(s_sel)
                                    if b and b.is_visible():
                                        sub = b; break
                                except Exception:
                                    pass
                            if sub:
                                print("  Submitting application...")
                                sub.evaluate("el => el.click()")
                                human_delay(2, 3)
                                submitted = True
                                break

                            print(f"  No button on step {step} — giving up")
                            break

                        if submitted:
                            applied += 1
                            print(f"  🎉 Applied! ({applied}/{MAX_PER_PLATFORM})")
                            setup_job_folder(company, "Dice", resume_path, job_title)
                            record_application(job_url, job_title, company, "Dice", resume_filename, score)
                            log_application(
                                job_title=job_title, company=company,
                                platform="Dice", url=job_url,
                                resume_filename=resume_filename,
                                job_type=job_type, location="United States",
                                work_model=work_model,
                            )
                            human_delay(3, 6)
                        else:
                            print(f"  Could not complete — moving on")

                    except Exception as e:
                        print(f"  Error: {e}")
                        continue

        finally:
            browser.close()

    print(f"\nDone! Applied to {applied} Dice jobs.")
    return applied
