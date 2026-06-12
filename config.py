import os
from dotenv import load_dotenv

# Load .env file if present
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ========== YOUR INFO ==========
FIRST_NAME = "Sree Nithin"
LAST_NAME  = "M"
EMAIL      = "sreenithinmsfdev@gmail.com"
PHONE      = "940-231-4234"
CITY       = "Fulshear"
STATE      = "Texas"
ZIP        = "77441"
CITY_STATE = "Fulshear, Texas"

# ========== API KEY ==========
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ========== AI MODE ==========
AI_MODE = os.getenv("AI_MODE", "premium")  # "free" = Ollama local | "premium" = Anthropic API

# ========== YOUR 4 RESUMES ==========
# For Business Analyst roles, AI will transform the Dev resume automatically
RESUMES = {
    "Salesforce Developer":        "resumes/Sree NithinSF Dev.pdf",
    "Salesforce Admin":            "resumes/SreeNithin SF Admin.pdf",
    "Salesforce Business Analyst": "resumes/Sree NithinSF Dev.pdf",
    "Agentforce Developer":        "resumes/SreeNithin Dev AgentForce.pdf",
}

# ========== JOB PREFERENCES ==========
JOB_TITLES = [
    "Salesforce Developer",
    "Salesforce Admin",
    "Salesforce Business Analyst",
    "Agentforce Developer",
]
JOB_TYPES  = ["Full-time", "Contract"]
POSTED     = "today"

# ========== PLATFORM LOGINS ==========
LINKEDIN_EMAIL    = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

DICE_EMAIL        = os.getenv("DICE_EMAIL", "")
DICE_PASSWORD     = os.getenv("DICE_PASSWORD", "")

# Indeed removed for now — adding after first week

# ========== LIMITS ==========
MAX_PER_PLATFORM = 20   # 20 LinkedIn + 20 Dice = 40 max per day

# ========== SAFE RUN WINDOW ==========
# Bot only runs Mon–Fri, 9am–6pm Central time to avoid bot-detection flags
BOT_RUN_DAYS   = [0, 1, 2, 3, 4]   # 0=Mon, 4=Fri (no weekends)
BOT_RUN_START  = 9                   # 9am Central
BOT_RUN_END    = 18                  # 6pm Central

# ========== MATCH SCORE THRESHOLD ==========
# Only apply to jobs where score_job() returns >= this value (0-100)
MATCH_THRESHOLD = 70

# ========== STEALTH MODE ==========
# True = use stealth browser context with human-like delays (recommended)
# False = plain Playwright (faster but more detectable)
STEALTH_MODE = True

# ========== ACTIVE PLATFORMS ==========
PLATFORMS = ["linkedin", "dice"]   # add "indeed" here later when ready

# ========== PATHS ==========
TRACKER_PATH   = os.path.expanduser("~/Desktop/Salesforce_Job_Application_Tracker.xlsx")
JOBS_FOLDER    = os.path.expanduser("~/Desktop/Job Applications")
RESUME_BACKUP  = os.path.expanduser("~/job-applier/resumes")
OUTPUT_RESUMES = os.path.expanduser("~/job-applier/output_resumes")

# ========== RESUME AI EDITING RULES ==========
RESUME_EDITS = {
    "Salesforce Developer": [
        "rewrite_bullets",
        "update_summary",
        "add_skills",
    ],
    "Salesforce Admin": [
        "rewrite_bullets",
        "update_summary",
        "add_skills",
    ],
    "Salesforce Business Analyst": [
        "rewrite_bullets",
        "update_summary",
        "add_skills",
        "transform_to_ba",
    ],
    "Agentforce Developer": [
        "rewrite_bullets",
        "update_summary",
        "add_skills",
    ],
}

# ========== JOB FOLDER STRUCTURE ==========
FOLDER_FORMAT    = "{company}_{platform}"
RESUME_FORMAT    = "SreeNithin_{job_title}_{company}.pdf"
QUESTIONS_FORMAT = "Interview_Questions_{company}.pdf"
