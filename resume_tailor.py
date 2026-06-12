"""
resume_tailor.py
─────────────────
Strategy:
  1. Score all PDFs in ~/Desktop/4/ against the job description
  2. Extract text from the best-scoring PDF
  3. Use AI to tailor the Professional Summary to the specific job
  4. Render a clean, professional PDF from scratch (no symbols, no layout issues)
  5. Save to output_resumes/ with a job-specific filename
"""
from __future__ import annotations
import os, re
import fitz  # PyMuPDF
from config import OUTPUT_RESUMES, RESUMES, FIRST_NAME, LAST_NAME, EMAIL, PHONE, CITY_STATE

DESKTOP_FOLDER = os.path.expanduser("~/Desktop/4")

# Letter page dimensions (points)
PAGE_W, PAGE_H = 612, 792
MARGIN_L, MARGIN_R = 55, 55
MARGIN_T, MARGIN_B = 50, 45
TEXT_W = PAGE_W - MARGIN_L - MARGIN_R

SF_KEYWORDS = [
    "salesforce", "sfdc", "apex", "lwc", "lightning", "flow", "soql", "sosl",
    "agentforce", "data cloud", "marketing cloud", "service cloud", "sales cloud",
    "experience cloud", "einstein", "omnistudio", "vlocity", "mulesoft", "tableau",
    "cpq", "field service", "crm", "administrator", "admin", "developer",
    "business analyst", "rest", "soap", "api", "integration", "trigger",
    "batch", "queueable", "visualforce", "aura", "slds", "platform events",
    "change data capture", "cdc", "copado", "git", "ci/cd", "devops",
    "shield", "oauth", "mfa", "data loader", "bulk api", "metadata",
    "validation rule", "workflow", "process builder", "approval process",
]


# ── PDF text extraction ───────────────────────────────────────────────────────

def _blocks_to_text(doc: fitz.Document) -> str:
    """Extract text sorted by y-coordinate so multi-column PDFs parse correctly."""
    lines = []
    for page in doc:
        blocks = page.get_text("blocks")
        blocks.sort(key=lambda b: (b[1], b[0]))  # sort by y then x
        for block in blocks:
            lines.append(block[4])
    return "\n".join(lines)


def _read_pdf_text(path: str) -> str:
    try:
        doc = fitz.open(path)
        return _blocks_to_text(doc).lower()
    except Exception as e:
        print(f"  Could not read {os.path.basename(path)}: {e}")
        return ""


def read_resume_text(path: str) -> str:
    """Public wrapper — returns original-case y-sorted text for AI prompts."""
    try:
        doc = fitz.open(path)
        return _blocks_to_text(doc)
    except Exception:
        return ""


# ── ATS scoring ───────────────────────────────────────────────────────────────

def _score_resume_vs_jd(resume_text: str, job_description: str) -> int:
    if not resume_text or not job_description:
        return 0
    jd_lower = job_description.lower()
    jd_keywords = [kw for kw in SF_KEYWORDS if kw in jd_lower]
    if not jd_keywords:
        return 50
    matched = sum(1 for kw in jd_keywords if kw in resume_text)
    return min(int((matched / len(jd_keywords)) * 100), 100)


def _get_pdfs_from_folder(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".pdf")]


def _fallback_resume(role: str) -> str:
    values = list(RESUMES.values())
    default = values[0] if values else ""
    path = os.path.expanduser(f"~/job-applier/{RESUMES.get(role, default)}")
    return path if (default and os.path.exists(path)) else ""


def pick_best_resume(job_description: str, role: str) -> tuple[str, str, int]:
    candidates = _get_pdfs_from_folder(DESKTOP_FOLDER)
    if candidates:
        scores = [(s := _score_resume_vs_jd(_read_pdf_text(p), job_description), p) for p in candidates]
        scores.sort(reverse=True)
        print("  📄 Resume ATS scores:")
        for sc, p in scores:
            marker = " <- selected" if p == scores[0][1] else ""
            print(f"       {os.path.basename(p)}: {sc}/100{marker}")
        return scores[0][1], os.path.basename(scores[0][1]), scores[0][0]
    fallback = _fallback_resume(role)
    if fallback:
        print(f"  📄 Desktop/4/ empty — using fallback: {os.path.basename(fallback)}")
        return fallback, os.path.basename(fallback), 0
    raise FileNotFoundError("No resume found in ~/Desktop/4/ or resumes/")


# ── Resume section parser ─────────────────────────────────────────────────────

SECTION_MARKERS = [
    "PROFESSIONAL SUMMARY", "CORE COMPETENCIES", "PROFESSIONAL EXPERIENCE",
    "CERTIFICATIONS", "EDUCATION", "ADDITIONAL INFORMATION",
]


def _parse_sections(text: str) -> dict[str, str]:
    """Split resume text into named sections."""
    sections: dict[str, str] = {}
    current = "HEADER"
    buf: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        matched = next((m for m in SECTION_MARKERS if m in line.upper()), None)
        if matched:
            sections[current] = "\n".join(buf).strip()
            current = matched
            buf = []
        else:
            buf.append(raw_line)

    sections[current] = "\n".join(buf).strip()
    return sections


def _clean(text: str) -> str:
    """Remove emoji / symbol characters, keep ASCII + common punctuation."""
    # Preserve en-dash / em-dash as plain hyphen before stripping non-ASCII
    cleaned = text.replace('\u2013', ' - ').replace('\u2014', ' - ')
    # Remove remaining non-ASCII
    cleaned = re.sub(r'[^\x00-\x7F]+', '', cleaned)
    # Collapse multiple spaces / blank lines
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


# ── AI summary tailoring ──────────────────────────────────────────────────────

def _extract_metrics(resume_sections: dict[str, str]) -> str:
    """Pull quantified achievement lines from experience section."""
    exp = resume_sections.get("PROFESSIONAL EXPERIENCE", "")
    metrics = []
    for line in exp.splitlines():
        s = line.strip()
        # Keep lines that contain a number/percentage (likely an achievement metric)
        if s and re.search(r'\d+[%+kx]?|\d+\.\d+%', s):
            clean = s.lstrip("•-·+").strip()
            if clean:
                metrics.append(clean)
    return "\n".join(metrics[:10])  # top 10 metric lines


def _tailor_summary(original_summary: str, job_title: str,
                    job_description: str, resume_sections: dict[str, str] | None = None) -> str:
    """Ask AI to rewrite the summary for this specific job. Falls back to original."""
    try:
        from ai_agent import ask_ai
        metrics_block = ""
        if resume_sections:
            metrics = _extract_metrics(resume_sections)
            if metrics:
                metrics_block = f"""
KEY METRICS FROM RESUME (use 1-2 relevant ones naturally if they fit the job — never force them):
{metrics}
"""
        prompt = f"""Rewrite this Salesforce professional's summary for the job below.
Keep it 3-4 sentences. Professional tone. No symbols, no emojis, plain text only.
Highlight the most relevant skills from the job description.
If any of the key metrics below are relevant to this role, weave 1-2 of them in naturally — do NOT force numbers that don't fit.

ORIGINAL SUMMARY:
{original_summary}

JOB TITLE: {job_title}

JOB DESCRIPTION (first 800 chars):
{job_description[:800]}
{metrics_block}
Return ONLY the rewritten summary paragraph. Nothing else."""
        result = ask_ai(prompt, max_tokens=350).strip()
        if len(result) > 80:
            return _clean(result)
    except Exception:
        pass
    return _clean(original_summary)


# ── PDF renderer ──────────────────────────────────────────────────────────────

def _new_page(doc: fitz.Document) -> tuple[fitz.Page, float]:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    return page, float(MARGIN_T)


def _draw_rule(page: fitz.Page, y: float) -> float:
    page.draw_line((MARGIN_L, y), (PAGE_W - MARGIN_R, y), color=(0.4, 0.4, 0.4), width=0.5)
    return y + 6


def _text_height(font_size: float, lines: int = 1) -> float:
    return font_size * 1.35 * lines


def _insert(page: fitz.Page, y: float, text: str, size: float,
            bold: bool = False, color=(0, 0, 0), indent: float = 0) -> float:
    """Insert wrapped text, return new y position."""
    font = "hebo" if bold else "helv"
    x = MARGIN_L + indent
    rect = fitz.Rect(x, y, PAGE_W - MARGIN_R, y + _text_height(size) * 10)
    rc = page.insert_textbox(rect, text, fontsize=size, fontname=font, color=color, align=0)
    # rc < 0 means text was clipped — but we handle overflow via page breaks in caller
    used_h = max(_text_height(size), _text_height(size) * (text.count("\n") + 1))
    # Estimate actual height from character count
    chars_per_line = int(TEXT_W / (size * 0.55))
    wrapped_lines = max(1, -(-len(text) // max(chars_per_line, 1)))  # ceiling div
    return y + _text_height(size) * wrapped_lines


def _render_clean_pdf(sections: dict[str, str], out_path: str,
                      job_title: str, company: str) -> None:
    doc = fitz.open()
    page, y = _new_page(doc)

    def check_space(needed: float) -> tuple[fitz.Page, float]:
        nonlocal page, y
        if y + needed > PAGE_H - MARGIN_B:
            page, y = _new_page(doc)
        return page, y

    # ── HEADER ────────────────────────────────────────────────────────────────
    name = f"{FIRST_NAME} {LAST_NAME}".upper()
    page.insert_textbox(
        fitz.Rect(MARGIN_L, y, PAGE_W - MARGIN_R, y + 40),
        name, fontsize=22, fontname="hebo", color=(0, 0, 0), align=0
    )
    y += 32

    title_line = "Salesforce Developer | Administrator | Agentforce Specialist"
    page.insert_textbox(
        fitz.Rect(MARGIN_L, y, PAGE_W - MARGIN_R, y + 24),
        title_line, fontsize=11, fontname="hebo", color=(0, 0, 0), align=0
    )
    y += 18

    contact = f"{PHONE}  |  {EMAIL}"
    page.insert_textbox(
        fitz.Rect(MARGIN_L, y, PAGE_W - MARGIN_R, y + 22),
        contact, fontsize=10, fontname="helv", color=(0.15, 0.15, 0.6), align=0
    )
    y += 18
    y = _draw_rule(page, y)

    def section_header(title: str) -> None:
        nonlocal y
        y += 6
        check_space(28)
        page.insert_textbox(
            fitz.Rect(MARGIN_L, y, PAGE_W - MARGIN_R, y + 26),
            title, fontsize=12, fontname="hebo", color=(0, 0, 0), align=0
        )
        y += 18
        y = _draw_rule(page, y)

    def body_text(text: str, indent: float = 0, size: float = 10) -> None:
        nonlocal y
        if not text.strip():
            return
        lines = text.strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                y += 4
                continue
            check_space(_text_height(size) + 2)
            chars_per_line = int((TEXT_W - indent) / (size * 0.55))
            wrapped = _wrap_text(line, chars_per_line)
            for wline in wrapped:
                check_space(_text_height(size))
                page.insert_textbox(
                    fitz.Rect(MARGIN_L + indent, y, PAGE_W - MARGIN_R, y + _text_height(size) * 2),
                    wline, fontsize=size, fontname="helv", color=(0, 0, 0), align=0
                )
                y += _text_height(size)

    def bold_line(text: str, size: float = 10) -> None:
        nonlocal y
        check_space(_text_height(size) + 2)
        page.insert_textbox(
            fitz.Rect(MARGIN_L, y, PAGE_W - MARGIN_R, y + _text_height(size) * 2),
            text.strip(), fontsize=size, fontname="hebo", color=(0, 0, 0), align=0
        )
        y += _text_height(size)

    def bullet_line(text: str, size: float = 10) -> None:
        nonlocal y
        text = text.strip().lstrip("-•·").strip()
        if not text:
            return
        chars_per_line = int((TEXT_W - 14) / (size * 0.55))
        wrapped = _wrap_text(text, chars_per_line)
        for i, wline in enumerate(wrapped):
            check_space(_text_height(size))
            prefix = "-" if i == 0 else " "
            page.insert_textbox(
                fitz.Rect(MARGIN_L + 4, y, MARGIN_L + 14, y + _text_height(size) * 2),
                prefix, fontsize=size, fontname="helv", color=(0, 0, 0), align=0
            )
            page.insert_textbox(
                fitz.Rect(MARGIN_L + 14, y, PAGE_W - MARGIN_R, y + _text_height(size) * 2),
                wline, fontsize=size, fontname="helv", color=(0, 0, 0), align=0
            )
            y += _text_height(size)

    # ── PROFESSIONAL SUMMARY ──────────────────────────────────────────────────
    summary = _clean(sections.get("PROFESSIONAL SUMMARY", ""))
    if summary:
        section_header("PROFESSIONAL SUMMARY")
        body_text(summary)
        y += 4

    # ── CORE COMPETENCIES ─────────────────────────────────────────────────────
    comp = _clean(sections.get("CORE COMPETENCIES", ""))
    if comp:
        section_header("CORE COMPETENCIES")
        for line in comp.splitlines():
            line = line.strip()
            if not line:
                y += 2
                continue
            # Sub-category headings (bold) vs content lines
            if line.endswith(":") or (len(line) < 40 and not any(c in line for c in "•-/,")):
                bold_line(line, size=10)
            else:
                body_text(line, indent=8, size=10)
        y += 4

    # ── PROFESSIONAL EXPERIENCE ───────────────────────────────────────────────
    exp = _clean(sections.get("PROFESSIONAL EXPERIENCE", ""))
    if exp:
        section_header("PROFESSIONAL EXPERIENCE")

        # Merge standalone "(Contract)"/"(Full-time)" lines into preceding title line
        raw_lines = exp.splitlines()
        merged: list[str] = []
        for ln in raw_lines:
            s = ln.strip()
            if re.match(r'^\([\w\s/-]+\)$', s) and len(s) < 25 and merged:
                prev = merged[-1].strip()
                if "|" in prev and len(prev) < 100:
                    merged[-1] = merged[-1].rstrip() + " " + s
                    continue
            merged.append(ln)

        in_entry = False
        pending_bullet: str | None = None

        def _is_date_line(s: str) -> bool:
            return bool(
                re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', s)
                or (re.search(r'\d{4}', s) and ("|" in s or "Present" in s
                                                 or "Remote" in s or "Onsite" in s))
            )

        def _is_title_line(s: str) -> bool:
            return ("|" in s and len(s) < 110
                    and not _is_date_line(s)
                    and not re.match(r'^\d', s))

        def _flush_bullet() -> None:
            nonlocal pending_bullet
            if pending_bullet:
                bullet_line(pending_bullet)
                pending_bullet = None

        for line in merged:
            s = line.strip()
            if not s:
                _flush_bullet()
                y += 3
                continue
            # Skip orphaned lone bullet/plus markers from multi-column source
            if len(s) == 1 and s in "•-·+":
                continue

            if _is_title_line(s):
                _flush_bullet()
                in_entry = False
                y += 8
                # Reserve space for title + date + at least one bullet so the
                # job header never strands alone at the bottom of a page
                check_space(72)
                title_part, *rest = s.split("|", 1)
                title_part = title_part.strip()
                company_part = rest[0].strip() if rest else ""
                # Job title — bold, left
                page.insert_textbox(
                    fitz.Rect(MARGIN_L, y, PAGE_W - MARGIN_R - 160, y + 22),
                    title_part, fontsize=11, fontname="hebo", color=(0, 0, 0), align=0
                )
                # Company — right-aligned, dark gray
                if company_part:
                    page.insert_textbox(
                        fitz.Rect(MARGIN_L + 180, y, PAGE_W - MARGIN_R, y + 22),
                        company_part, fontsize=10, fontname="helv", color=(0.2, 0.2, 0.2), align=2
                    )
                y += _text_height(11) + 2

            elif _is_date_line(s):
                _flush_bullet()
                in_entry = True
                check_space(_text_height(9) + 4)
                page.insert_textbox(
                    fitz.Rect(MARGIN_L, y, PAGE_W - MARGIN_R, y + _text_height(9) * 2),
                    s, fontsize=9, fontname="helv", color=(0.2, 0.2, 0.55), align=0
                )
                y += _text_height(9) + 4

            elif in_entry:
                # Strip any leading bullet/plus chars from source
                clean_s = s.lstrip("•-·+").strip()
                if not clean_s:
                    continue
                if pending_bullet is None:
                    # Start new bullet
                    pending_bullet = clean_s
                elif clean_s[0].islower() or pending_bullet[-1] not in ".!?%":
                    # Continuation line — merge into current bullet
                    pending_bullet += " " + clean_s
                else:
                    # Previous bullet was complete — flush and start new
                    _flush_bullet()
                    pending_bullet = clean_s

            else:
                _flush_bullet()
                body_text(s)

        _flush_bullet()
        y += 4

    # ── CERTIFICATIONS ────────────────────────────────────────────────────────
    certs = _clean(sections.get("CERTIFICATIONS", ""))
    if certs:
        section_header("CERTIFICATIONS")
        for line in certs.splitlines():
            s = line.strip().lstrip("•-").strip()
            if s:
                bullet_line(s)
        y += 4

    # ── EDUCATION ─────────────────────────────────────────────────────────────
    edu = _clean(sections.get("EDUCATION", ""))
    if edu:
        section_header("EDUCATION")
        for line in edu.splitlines():
            s = line.strip()
            if not s:
                y += 2
                continue
            # Skip visual separator lines extracted from source PDF
            if re.match(r'^[-=]{3,}$', s):
                continue
            if any(kw in s for kw in ("Master", "Bachelor", "University", "College")):
                bold_line(s) if any(k in s for k in ("Master", "Bachelor")) else body_text(s)
            else:
                body_text(s)
        y += 4

    # ── ADDITIONAL INFORMATION ────────────────────────────────────────────────
    add = _clean(sections.get("ADDITIONAL INFORMATION", ""))
    # Always override location line with correct city and relocation note
    add = re.sub(r'Location:[^\n]*', 'Location: Houston, Texas (Open to relocate)', add)
    if "Location:" not in add:
        add = "Location: Houston, Texas (Open to relocate)\n" + add
    # Keep section together — check space for header + ~4 lines of content
    check_space(100)
    section_header("ADDITIONAL INFORMATION")
    body_text(add)

    doc.save(out_path)
    doc.close()


def _wrap_text(text: str, chars_per_line: int) -> list[str]:
    """Word-wrap text to fit within chars_per_line characters."""
    if len(text) <= chars_per_line:
        return [text]
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if len(test) <= chars_per_line:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


# ── Main entry point ──────────────────────────────────────────────────────────

def process_resume(role: str, job_title: str, company: str,
                   job_description: str) -> tuple[str, str]:
    """
    Pick best-scoring resume, tailor the summary via AI,
    render a clean professional PDF. Returns (filepath, filename).
    """
    os.makedirs(OUTPUT_RESUMES, exist_ok=True)

    src_path, src_name, ats_score = pick_best_resume(job_description, role)

    # Extract text from source PDF
    raw_text = read_resume_text(src_path)
    sections = _parse_sections(raw_text)

    # Tailor summary to this specific job via AI
    original_summary = sections.get("PROFESSIONAL SUMMARY", "")
    if job_description and original_summary:
        sections["PROFESSIONAL SUMMARY"] = _tailor_summary(
            original_summary, job_title, job_description, sections
        )

    # Build output filename
    safe_title   = re.sub(r"[^\w\s-]", "", job_title).replace(" ", "_")
    safe_company = re.sub(r"[^\w\s-]", "", company).replace(" ", "_")
    if safe_company.lower() in ("unknown", ""):
        out_filename = f"SreeNithin_{safe_title}.pdf"
    else:
        out_filename = f"SreeNithin_{safe_title}_{safe_company}.pdf"
    out_filepath = os.path.join(OUTPUT_RESUMES, out_filename)

    # Render clean PDF
    _render_clean_pdf(sections, out_filepath, job_title, company)
    print(f"  ✅ Resume generated: {out_filename} (ATS: {ats_score}/100 from {src_name})")

    return out_filepath, out_filename
