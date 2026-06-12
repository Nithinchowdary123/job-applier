# Job Applier Bot

## Run
```bash
python3 app.py        # Web UI → http://127.0.0.1:8080
python3 main.py       # CLI mode
```

## Stack
- Browser: Playwright sync API, Chromium
- AI: `ai_agent.py` → Anthropic `claude-haiku-4-5` (Q&A) / Ollama Mistral (free mode)
- PDF: PyMuPDF (`fitz`) — surgery on original PDF, not from scratch
- Web UI: Flask + Flask-SocketIO on port 8080
- Tracking: openpyxl → `~/Desktop/Salesforce_Job_Application_Tracker.xlsx`
- Python 3.9

## Key Files
| File | Purpose |
|------|---------|
| `config.py` | All settings, loads creds from `.env` |
| `ai_agent.py` | `answer_questions_batch()` — 1 API call for all form questions; `_resume_cache` in memory |
| `resume_tailor.py` | Copies original PDF, redacts 3 regions (summary/bullets/skills), writes AI text in-place |
| `linkedin.py` | LinkedIn Easy Apply — collects all questions first, then 1 batch API call |
| `dice.py` | Dice.com automation |
| `logger.py` | Excel tracker (20 fields per application) |
| `folder_manager.py` | `~/Desktop/Job Applications/[Company]_[Platform]/` |

## Credentials
- All in `.env` — never in source code
- `AI_MODE=premium` (Anthropic) or `AI_MODE=free` (Ollama)
- Max 25 apps per platform (`MAX_PER_PLATFORM`)

## Resume Mapping
- Salesforce Developer → `resumes/Sree NithinSF Dev.pdf`
- Salesforce Admin → `resumes/SreeNithin SF Admin.pdf`
- Salesforce BA → Dev resume (AI transforms to BA tone)
- Agentforce Developer → `resumes/SreeNithin Dev AgentForce.pdf`

## Output Paths
- Tailored PDFs: `~/job-applier/output_resumes/SreeNithin_[Title]_[Company].pdf`
- Job folders: `~/Desktop/Job Applications/[Company]_[Platform]/`

## What's Not Done Yet
- `cover_letter.py` and `interview_questions.py` generate but are never saved to job folders
- Indeed bot not implemented (placeholder in config)
- AI mode toggle in `app.py` writes to `config.py` directly — should write to `.env`
