import os
import shutil
from config import JOBS_FOLDER

def create_job_folder(company, platform, job_title=""):
    # Use job_title as fallback when company is unknown so folders don't overwrite each other
    if not company or company.lower() == "unknown":
        label = job_title or "Unknown"
    else:
        label = company
    safe_label    = label.replace(" ", "_").replace("/", "_")
    safe_platform = platform.capitalize()
    folder_name   = f"{safe_label}_{safe_platform}"
    folder_path   = os.path.join(JOBS_FOLDER, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    print(f"  📁 Created folder: {folder_name}")
    return folder_path

def save_resume_to_folder(resume_filepath, folder_path):
    filename = os.path.basename(resume_filepath)
    dest     = os.path.join(folder_path, filename)
    shutil.copy2(resume_filepath, dest)
    print(f"  📄 Resume copied to job folder")
    return dest

def setup_job_folder(company, platform, resume_filepath, job_title=""):
    folder_path = create_job_folder(company, platform, job_title)
    save_resume_to_folder(resume_filepath, folder_path)
    return folder_path