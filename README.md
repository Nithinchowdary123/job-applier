# 🤖 Job Application Bot — Automated Salesforce Job Applier

A fully automated job application bot that applies to Salesforce roles on **LinkedIn Easy Apply** and **Dice.com** — powered by Claude AI.

One click. It does the rest.

---

## What It Does

1. Opens a real browser and logs into LinkedIn & Dice automatically
2. Searches for Salesforce jobs (Developer, Admin, Business Analyst, Agentforce)
3. Filters out irrelevant titles (Director, Manager, non-Salesforce, etc.)
4. Reads the job description and picks the best matching resume
5. Uses Claude AI to tailor the resume for that specific job
6. Scores the job match — skips if score is too low
7. Fills out the entire application form using AI-generated answers
8. Corrects any wrong pre-filled answers
9. Submits the application
10. Saves a tailored resume + dedicated folder for every job
11. Logs everything to an Excel tracker on your Desktop

---

## Tech Stack

| Tool | Purpose |
|------|---------|
| Python 3.9 | Core language |
| Playwright | Browser automation |
| Anthropic Claude API | Resume tailoring + form Q&A |
| PyMuPDF (fitz) | PDF editing |
| Flask + SocketIO | Web dashboard UI |
| openpyxl / pandas | Excel job tracker |
| SQLite | Duplicate application tracking |

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/Nithinchowdary123/job-applier.git
cd job-applier
```

### 2. Install dependencies
```bash
pip3 install -r requirements.txt
playwright install chromium
```

### 3. Configure credentials
```bash
cp .env.example .env
```
Fill in your `.env` with your LinkedIn, Dice, and Anthropic API credentials.

### 4. Add your resumes
Place your resume PDFs in the `resumes/` folder:
```
resumes/
  Sree NithinSF Dev.pdf         # Salesforce Developer
  SreeNithin SF Admin.pdf       # Salesforce Admin
  SreeNithin Dev AgentForce.pdf # Agentforce Developer
```

### 5. Run

**Web UI (recommended)**
```bash
python3 app.py
# Open http://127.0.0.1:8080
```

**CLI mode**
```bash
python3 main.py
```

---

## Web Dashboard

- One-click buttons: LinkedIn, Dice, or both platforms
- Live log stream showing every action in real time
- Recent applications table with status
- AI mode toggle (Free Ollama / Premium Claude)

---

## Resume Mapping

| Role | Resume Used |
|------|------------|
| Salesforce Developer | SF Dev resume |
| Salesforce Admin | SF Admin resume |
| Salesforce Business Analyst | Dev resume — AI transforms to BA tone |
| Agentforce Developer | AgentForce resume |

---

## AI Modes

| Mode | Model | Cost |
|------|-------|------|
| Free | Ollama Mistral (local) | $0 |
| Premium | Claude Haiku 4.5 | ~$0.01/application |

---

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web UI + bot runner |
| `linkedin.py` | LinkedIn Easy Apply automation |
| `dice.py` | Dice.com automation |
| `ai_agent.py` | AI Q&A — 1 batch API call per form page |
| `resume_tailor.py` | PDF surgery — redacts and rewrites resume sections |
| `job_scorer.py` | ATS-style scoring to decide whether to apply |
| `stealth.py` | Human-like browser behavior (delays, mouse movement) |
| `config.py` | All settings loaded from `.env` |
| `logger.py` | Excel tracker — 20 fields per application |
| `folder_manager.py` | Creates `~/Desktop/Job Applications/[Company]_[Platform]/` |

---

## Output

- **Tailored PDFs:** `~/job-applier/output_resumes/SreeNithin_[Title]_[Company].pdf`
- **Job folders:** `~/Desktop/Job Applications/[Company]_[Platform]/`
- **Excel tracker:** `~/Desktop/Salesforce_Job_Application_Tracker.xlsx`

---

## Notes

- Applies up to 20 jobs per platform per run
- Skips jobs already applied to (SQLite dedup)
- Runs Mon–Fri 9am–6pm Central by default (configurable)
- Anti-detection: realistic mouse movement, human typing speed, random delays

---

## Disclaimer

This bot is for personal use only. Use responsibly and in accordance with each platform's terms of service.

---

Built by [Sree Nithin](https://github.com/Nithinchowdary123)
