from config import FIRST_NAME, LAST_NAME, EMAIL, PHONE
from ai_agent import ask_ai

def generate_cover_letter(job_title, company, job_description, resume_text):
    print(f"  ✍️  Generating cover letter for {job_title} at {company}...")

    prompt = f"""You are an expert cover letter writer specializing in Salesforce roles.

Candidate info:
- Name: {FIRST_NAME} {LAST_NAME}
- Email: {EMAIL}
- Phone: {PHONE}

Resume summary:
{resume_text}

Job title: {job_title}
Company: {company}

Job description:
{job_description}

Write a compelling, personalized cover letter for this specific job.

Rules:
- 3 short paragraphs max — keep it concise and punchy
- Paragraph 1: Why this role at this specific company excites them
- Paragraph 2: 2-3 specific achievements from their resume that match the JD
- Paragraph 3: Short closing, call to action
- Use a professional but confident tone
- Do NOT use generic phrases like "I am writing to express my interest"
- Do NOT repeat the entire resume — pick the most relevant highlights
- Address it to "Hiring Manager" since we don't know the name
- End with: {FIRST_NAME} {LAST_NAME} | {EMAIL} | {PHONE}

Return ONLY the cover letter text, nothing else."""

    return ask_ai(prompt, max_tokens=1000)