import os
import fitz
from config import FIRST_NAME, LAST_NAME
from ai_agent import ask_ai

def generate_questions(job_title, company, job_description):
    print(f"  ❓ Generating interview questions for {job_title} at {company}...")

    prompt = f"""You are an expert Salesforce interview coach.

Job title: {job_title}
Company: {company}

Job description:
{job_description}

Generate the top 20 most likely vendor/interview questions for this specific role and company.

Format exactly like this for each question:

Q1. [Question here]
Answer: [Detailed, specific answer a strong Salesforce candidate would give. Include real Salesforce terminology, features, and examples.]

Rules:
- Make questions specific to the job description
- Mix behavioral and technical questions
- Include at least 5 Salesforce-specific technical questions
- Include at least 3 scenario-based questions
- Answers should be 3-5 sentences, detailed and impressive
- Use real Salesforce product names: Flows, Apex, LWC, SOQL, Agentforce, Data Cloud etc

Return ONLY the 20 questions and answers, nothing else."""

    return ask_ai(prompt, max_tokens=4000)

def save_questions_as_pdf(questions_text, company, folder_path):
    os.makedirs(folder_path, exist_ok=True)
    safe_company = company.replace(" ", "_")
    filename     = f"Interview_Questions_{safe_company}.pdf"
    filepath     = os.path.join(folder_path, filename)

    doc    = fitz.open()
    page   = doc.new_page()
    margin = 50
    y      = margin
    max_width = page.rect.width - 2 * margin

    page.insert_text((margin, y), f"Top 20 Interview Questions — {company}", fontsize=14, fontname="helv", color=(0, 0, 0))
    y += 24
    page.insert_text((margin, y), f"Prepared for: {FIRST_NAME} {LAST_NAME}", fontsize=10, fontname="helv", color=(0.3, 0.3, 0.3))
    y += 20
    page.draw_line((margin, y), (page.rect.width - margin, y), color=(0.7, 0.7, 0.7), width=0.5)
    y += 16

    for line in questions_text.split("\n"):
        if line.strip() == "":
            y += 8
            continue

        is_question = line.startswith("Q") and "." in line[:4]
        fontsize    = 11 if is_question else 10
        color       = (0, 0, 0) if is_question else (0.2, 0.2, 0.2)

        if is_question:
            y += 6

        words     = line.split()
        curr_line = ""
        for word in words:
            test = curr_line + " " + word if curr_line else word
            if len(test) * (fontsize * 0.55) > max_width:
                if y > page.rect.height - margin:
                    page = doc.new_page()
                    y    = margin
                page.insert_text((margin, y), curr_line, fontsize=fontsize, fontname="helv", color=color)
                y        += fontsize + 4
                curr_line = word
            else:
                curr_line = test

        if curr_line:
            if y > page.rect.height - margin:
                page = doc.new_page()
                y    = margin
            page.insert_text((margin, y), curr_line, fontsize=fontsize, fontname="helv", color=color)
            y += fontsize + 4

    doc.save(filepath)
    doc.close()
    print(f"  ✅ Interview questions saved: {filename}")
    return filepath

def process_questions(job_title, company, job_description, folder_path):
    questions_text = generate_questions(job_title, company, job_description)
    filepath       = save_questions_as_pdf(questions_text, company, folder_path)
    return filepath