"""
ai_agent.py
───────────
Central AI layer for the job-applier bot.

Features added / improved:
  - In-memory resume cache (no re-read per question)
  - Batch question answering (1 API call per form page)
  - claude-haiku-4-5 for Q&A (20× cheaper than opus)
  - Knockout question detection (flags deal-breakers before submitting)
  - Unknown question logging to unanswered_questions.log
  - Resume text cleaning (strips junk from PDF extraction)
  - Retry with exponential back-off for both Anthropic and Ollama
"""
from __future__ import annotations

import re, os, requests
import anthropic
import fitz
from docx import Document
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import ANTHROPIC_API_KEY, AI_MODE

client_anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── In-memory resume cache ────────────────────────────────────────────────────
_resume_cache: dict[str, str] = {}


# ── Resume text cleaning ──────────────────────────────────────────────────────

def _clean_resume_text(raw: str) -> str:
    """
    Remove common PDF-extraction artifacts that confuse the AI:
      - Lone digits / page numbers on their own line
      - Repeated whitespace / non-breaking spaces
      - Control characters
      - Bullet unicode variants → plain hyphen
    """
    # Replace unicode bullets/dashes with plain ASCII
    raw = re.sub(r"[•·▪▸►‣⁃◦–—]", "-", raw)
    # Remove non-breaking spaces and control chars (keep newlines/tabs)
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\xa0]", " ", raw)
    # Collapse runs of whitespace within a line
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        # Drop lines that are only digits (page numbers) or very short junk
        if re.fullmatch(r"\d{1,3}", line):
            continue
        lines.append(line)
    # Collapse more than 2 consecutive blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return cleaned.strip()


def read_resume_text(resume_path: str) -> str:
    """
    Read resume text (PDF or DOCX), clean it, and cache it in memory.
    Accepts both absolute paths and paths relative to ~/job-applier/.
    """
    if resume_path in _resume_cache:
        return _resume_cache[resume_path]
    try:
        if os.path.isabs(resume_path):
            full_path = resume_path
        else:
            full_path = os.path.expanduser(f"~/job-applier/{resume_path}")

        if full_path.endswith(".pdf"):
            doc  = fitz.open(full_path)
            raw  = "\n".join(page.get_text() for page in doc)
        elif full_path.endswith(".docx"):
            doc  = Document(full_path)
            raw  = "\n".join(p.text for p in doc.paragraphs)
        else:
            raw  = ""
    except Exception:
        raw = ""

    text = _clean_resume_text(raw) if raw else ""
    if not text:
        print(f"  ⚠️  Could not read resume: {resume_path}")
    _resume_cache[resume_path] = text
    return text


# ── API wrappers with retry ───────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((anthropic.APIConnectionError, anthropic.RateLimitError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
)
def ask_anthropic(prompt: str, max_tokens: int = 1000) -> str:
    message = client_anthropic.messages.create(
        model="claude-haiku-4-5",   # fast + cheap for Q&A
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


@retry(
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    wait=wait_exponential(multiplier=1, min=3, max=20),
    stop=stop_after_attempt(3),
)
def ask_ollama(prompt: str) -> str:
    short_prompt = prompt[:2000]
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "mistral",
            "prompt": short_prompt,
            "stream": False,
            "options": {"num_predict": 500, "temperature": 0.3},
        },
        timeout=120,
    )
    if response.status_code == 200:
        return response.json()["response"]
    raise Exception(f"Ollama error: {response.status_code}")


def ask_ai(prompt: str, max_tokens: int = 1000) -> str:
    if AI_MODE == "free":
        return ask_ollama(prompt)
    return ask_anthropic(prompt, max_tokens)


# ── Knockout question detection ───────────────────────────────────────────────

# Questions that will auto-reject candidates who answer wrong
_KNOCKOUT_PATTERNS = [
    # Degree requirements
    (r"bachelor'?s?\s+degree", "Yes"),
    (r"master'?s?\s+degree",   "Yes"),
    # US work auth
    (r"legally\s+authorized",  "Yes"),
    (r"authorized\s+to\s+work","Yes"),
    (r"eligible\s+to\s+work",  "Yes"),
    # Sponsorship
    (r"require\s+sponsor",     "No"),
    (r"need\s+sponsor",        "No"),
    (r"visa\s+sponsor",        "No"),
    # Background check
    (r"background\s+check",    "Yes"),
    # Non-compete / conflicts
    (r"non.?compete",          "No"),
]

# Questions that are deal-breakers if answered "No" (candidate must confirm "Yes")
_MUST_YES = [
    r"legally\s+authorized",
    r"authorized\s+to\s+work",
    r"eligible\s+to\s+work",
]

# Questions that are deal-breakers if answered "Yes" (need for sponsorship)
_MUST_NO = [
    r"require\s+sponsor",
    r"need\s+sponsor",
    r"now\s+or\s+in\s+the\s+future.*sponsor",
]


def is_knockout_question(question: str) -> bool:
    """
    Return True if this question could disqualify the candidate
    if answered incorrectly — so we must get it exactly right.
    """
    q = question.lower()
    for pattern, _ in _KNOCKOUT_PATTERNS:
        if re.search(pattern, q):
            return True
    return False


def get_knockout_answer(question: str) -> str:
    """
    Return the safe, pre-defined answer for a known knockout question.
    Returns empty string if the question is not recognised.
    """
    q = question.lower()
    for pattern, answer in _KNOCKOUT_PATTERNS:
        if re.search(pattern, q):
            return answer
    return ""


def check_disqualifying(question: str, answer: str) -> bool:
    """
    Return True if the question+answer combination would disqualify us:
      - Must-Yes question answered "No"
      - Must-No question answered "Yes"
    """
    q = question.lower()
    a = answer.strip().lower()

    for pattern in _MUST_YES:
        if re.search(pattern, q) and a.startswith("no"):
            return True

    for pattern in _MUST_NO:
        if re.search(pattern, q) and a.startswith("yes"):
            return True

    return False


# ── Batch question answering ──────────────────────────────────────────────────

def answer_questions_batch(
    questions: list[str],
    resume_path: str,
    visa_status: str = "F1-OPT",
    job_title: str = "",
    company: str = "",
    platform: str = "",
    job_description: str = "",
) -> dict[str, str]:
    """
    Answer a list of form questions in a single API call.
    - Knockout questions get pre-defined safe answers (no API needed).
    - Answers that would disqualify are replaced with safe defaults.
    - Unknown questions that couldn't be matched are logged.

    Returns dict: {question_text -> answer_string}
    """
    if not questions:
        return {}

    results: dict[str, str] = {}

    # Step 1: Handle knockout questions without wasting API tokens
    remaining: list[str] = []
    for q in questions:
        ko_ans = get_knockout_answer(q)
        if ko_ans:
            results[q] = ko_ans
        else:
            remaining.append(q)

    # Step 2: Batch AI call for the rest
    if remaining:
        resume_text = read_resume_text(resume_path)   # cached — no disk I/O
        numbered    = "\n".join(f"{i+1}. {q}" for i, q in enumerate(remaining))

        jd_snippet = job_description[:600] if job_description else ""
        prompt = f"""You are filling out a job application form for a Salesforce professional. Answer EVERY question below.

CANDIDATE INFO:
- Name: Sree Nithin M
- Email: sreenithinmsfdev@gmail.com
- Phone: 940-231-4234
- City: Fulshear  |  State: Texas  |  ZIP: 77441
- Location: Fulshear, Texas (Greater Houston area)
- Visa: F1-OPT  |  Authorized to work in US: Yes  |  Needs sponsorship: No
- Open to: Remote, Hybrid, or Onsite

RESUME:
{resume_text[:2500]}

JOB DESCRIPTION (for context):
{jd_snippet}

QUESTIONS:
{numbered}

RULES:
- Answer each question on its own line as: <number>. <answer>
- Location / city+state questions → Fulshear, Texas
- City only questions → Fulshear
- State questions → Texas
- ZIP/postal code → 77441
- Visa/work authorization → F1-OPT
- Authorized to work in US → Yes
- Need sponsorship now or future → No
- Salary/compensation/rate → look for a salary range in the job description above; if found, pick a number in the upper-middle of that range. If no range is posted use: Developer/Agentforce=95000, Admin=80000, BA=90000. Return digits only — no $, no commas.
- Yes/No questions → Yes or No only
- Keep answers SHORT (1-5 words for simple, 1-2 sentences max for complex)

YEARS OF EXPERIENCE RULES:
- Technology explicitly in resume → count years it appears across all jobs
- Technology NOT in resume but closely related → conservative estimate of 1:
    * Marketing Cloud, Pardot → 1
    * OmniStudio, Vlocity → 1
    * Data Cloud, CDP → 1
    * CPQ, Billing → 1
    * MuleSoft → 1
    * Tableau, Einstein Analytics → 1
    * Field Service Lightning → 1
- Completely unrelated (SAP, Oracle, Java, .NET) → 0
- Never claim more than 4 years for anything not clearly in the resume

Return ONLY the numbered answers, nothing else."""

        try:
            raw = ask_ai(prompt, max_tokens=500)
            for line in raw.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                for sep in (". ", ") "):
                    if sep in line and line.split(sep)[0].isdigit():
                        idx    = int(line.split(sep)[0]) - 1
                        answer = sep.join(line.split(sep)[1:]).strip()
                        if 0 <= idx < len(remaining):
                            results[remaining[idx]] = answer
                        break
        except Exception:
            pass

    # Step 3: Fallback for any question still unanswered + log truly unknown ones
    for q in questions:
        if q not in results or not results[q]:
            fallback = smart_fallback(q)
            results[q] = fallback
            # Log questions we couldn't confidently answer
            if fallback == "0" and not any(
                kw in q.lower() for kw in ("year", "how many", "number")
            ):
                _log_unknown(q, job_title, company, platform)

    # Step 4: Safety check — ensure no disqualifying answer slipped through
    for q in questions:
        if check_disqualifying(q, results.get(q, "")):
            ko_ans = get_knockout_answer(q)
            results[q] = ko_ans if ko_ans else smart_fallback(q)

    return results


def _log_unknown(question: str, job_title: str, company: str, platform: str):
    """Log a question we couldn't confidently answer to the unanswered log."""
    try:
        from job_tracker import log_unanswered_question
        log_unanswered_question(question, job_title, company, platform)
    except Exception:
        pass   # never crash the bot just because logging failed


# ── Single-question helper (kept for backward compat) ─────────────────────────

def answer_application_question(
    question: str,
    resume_path: str,
    visa_status: str = "F1-OPT",
) -> str:
    """Single-question answer. Prefer answer_questions_batch() for multi-question forms."""
    answers = answer_questions_batch([question], resume_path, visa_status)
    return answers.get(question, smart_fallback(question))


# ── Rule-based fallback ───────────────────────────────────────────────────────

def smart_fallback(question: str) -> str:
    q = question.lower()
    if "year" in q and "experience" in q:
        sf_terms = {
            "salesforce", "sfdc", "crm", "apex", "lwc", "lightning", "flow",
            "soql", "agentforce", "data cloud", "marketing cloud",
            "service cloud", "sales cloud", "soap", "rest", "api",
            "sql", "javascript", "git", "agile", "scrum",
        }
        if any(t in q for t in sf_terms):
            return "4"
        return "0"
    if "visa" in q or "status" in q:            return "F1-OPT"
    if "authorized" in q or "legally" in q:     return "Yes"
    if "sponsor" in q:                          return "No"
    if "salary" in q or "rate" in q or "comp" in q: return "95000"  # AI handles with JD context; this is last-resort fallback
    if "notice" in q:                           return "2 weeks"
    if "relocat" in q:                          return "No"
    if "remote" in q and "willing" in q:        return "Yes"
    if "clearance" in q:                        return "No"
    if "gpa" in q:                              return "3.5"
    if "do you have" in q or "are you" in q or "have you" in q: return "Yes"
    if "how many" in q:                         return "0"
    return "0"
