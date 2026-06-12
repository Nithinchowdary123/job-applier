"""
job_scorer.py
─────────────
AI-powered job relevance scorer.
Computes a 0-100 match score between a job posting and the candidate's profile.
Only jobs scoring >= MATCH_THRESHOLD (default 70) are applied to.

Score components:
  - Title match         (30 pts) — exact/partial keyword overlap
  - Skills match        (40 pts) — required skills found in resume
  - Seniority fit       (20 pts) — level alignment (no director/architect)
  - Location/work model (10 pts) — remote-friendly or correct location
"""
from __future__ import annotations

import re
from ai_agent import ask_ai, read_resume_text
from config import RESUMES

# ── Seniority blocklist ───────────────────────────────────────────────────────
SENIOR_BLOCKED = [
    "director", "vp ", "vice president", "principal", "cto", "cio",
    "chief", "head of", "solution architect", "technical architect",
    "enterprise architect", "staff engineer", "technical lead", "tech lead",
    "distinguished", "fellow",
]

# ── Salesforce keyword universe ───────────────────────────────────────────────
SF_KEYWORDS = {
    "salesforce", "sfdc", "apex", "lwc", "lightning", "flow", "soql",
    "agentforce", "data cloud", "marketing cloud", "service cloud",
    "sales cloud", "experience cloud", "einstein", "omnistudio",
    "vlocity", "mulesoft", "tableau", "cpq", "field service",
    "crm", "administrator", "admin", "developer", "business analyst",
}

# ── Default threshold ─────────────────────────────────────────────────────────
MATCH_THRESHOLD = 70   # score must be >= this to apply


def _title_score(job_title: str) -> int:
    """
    30 pts: how well does the job title match target Salesforce roles?
    """
    t = job_title.lower()

    # Hard block on senior/exec titles
    for blocked in SENIOR_BLOCKED:
        if blocked in t:
            return 0

    score = 0
    if "salesforce" in t or "sfdc" in t:
        score += 20
    if any(k in t for k in ("developer", "dev", "engineer")):
        score += 5
    if any(k in t for k in ("admin", "administrator")):
        score += 5
    if any(k in t for k in ("analyst", "business analyst", "ba")):
        score += 5
    if "agentforce" in t:
        score += 10

    return min(score, 30)


def _seniority_score(job_title: str, job_description: str) -> int:
    """
    20 pts: penalise if the role is clearly above mid-level.
    Only hard-blocks on the TITLE — descriptions often mention senior colleagues
    ("report to technical lead") which caused false 0s on valid jobs.
    """
    title_lower = job_title.lower()

    for blocked in SENIOR_BLOCKED:
        if blocked in title_lower:
            return 0

    # Check description only for explicit years-of-experience signals
    desc_lower = job_description.lower()
    senior_signals = ["10+ years", "8+ years", "7+ years", "15+ years",
                      "staff-level", "principal-level", "vp-level"]
    for sig in senior_signals:
        if sig in desc_lower:
            return 5

    return 20


def _location_score(job_description: str) -> int:
    """
    10 pts: prefer remote / US-based jobs.
    """
    if not job_description or len(job_description) < 100:
        return 7  # can't tell — give benefit of the doubt
    desc = job_description.lower()
    if "remote" in desc:
        return 10
    if "hybrid" in desc:
        return 7
    # On-site is acceptable but not preferred
    return 4


def _skills_score_heuristic(job_description: str, resume_path: str) -> int:
    """
    40 pts: keyword-match Salesforce skills between JD and resume.
    Fast, no API call required.
    """
    resume_text = read_resume_text(resume_path).lower()
    jd_lower    = job_description.lower()

    # Find SF keywords mentioned in the JD
    jd_keywords = {kw for kw in SF_KEYWORDS if kw in jd_lower}
    if not jd_keywords:
        # If description is empty/short, give partial credit (can't penalise missing data)
        if len(job_description) < 100:
            return 20
        # JD present but no SF keywords — likely non-Salesforce job
        return 5

    # Count how many of those keywords appear in the resume
    matched = sum(1 for kw in jd_keywords if kw in resume_text)
    ratio   = matched / len(jd_keywords) if jd_keywords else 0
    return int(ratio * 40)


def score_job(job_title: str, company: str,
              job_description: str, resume_path: str,
              use_ai: bool = False) -> int:
    """
    Compute a 0-100 relevance score for a job posting.

    Parameters
    ----------
    job_title       : Job title from the listing
    company         : Company name
    job_description : Full JD text
    resume_path     : Path to the resume to compare against
    use_ai          : If True, use an AI call for skills section (more accurate,
                      costs tokens). Default False uses fast heuristic.

    Returns
    -------
    int: 0-100 score
    """
    t_score   = _title_score(job_title)
    sen_score = _seniority_score(job_title, job_description)
    loc_score = _location_score(job_description)

    if t_score == 0 or sen_score == 0:
        # Immediate block — don't waste tokens on skills check
        return 0

    if use_ai:
        sk_score = _skills_score_ai(job_title, job_description, resume_path)
    else:
        sk_score = _skills_score_heuristic(job_description, resume_path)

    total = t_score + sk_score + sen_score + loc_score
    return min(total, 100)


def _skills_score_ai(job_title: str, job_description: str,
                     resume_path: str) -> int:
    """
    AI-powered skills match (costs 1 API call).
    Returns 0-40 points.
    """
    resume_text = read_resume_text(resume_path)
    prompt = f"""Score the skills match between this job and the candidate's resume.

JOB TITLE: {job_title}
JOB DESCRIPTION (first 1500 chars):
{job_description[:1500]}

RESUME (first 1500 chars):
{resume_text[:1500]}

Rate ONLY the skills match on a scale 0-40 where:
  40 = candidate has all required skills
  20 = candidate has about half the required skills
  0  = candidate has almost none of the required skills

Reply with a single integer 0-40. Nothing else."""
    try:
        raw   = ask_ai(prompt, max_tokens=10).strip()
        score = int(re.search(r"\d+", raw).group())
        return max(0, min(40, score))
    except Exception:
        return _skills_score_heuristic(job_description, resume_path)


def should_apply(job_title: str, company: str,
                 job_description: str, resume_path: str,
                 threshold: int = MATCH_THRESHOLD,
                 use_ai: bool = False) -> tuple[bool, int]:
    """
    Decide whether to apply to a job.

    Returns
    -------
    (apply: bool, score: int)
    """
    score = score_job(job_title, company, job_description,
                      resume_path, use_ai=use_ai)
    return score >= threshold, score
