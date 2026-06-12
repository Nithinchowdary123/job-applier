import os
import sys
from datetime import datetime
from config import PLATFORMS, JOBS_FOLDER

def print_banner():
    print("""
╔══════════════════════════════════════════════╗
║       Sree Nithin — Job Application Bot      ║
║         LinkedIn + Dice Auto Applier         ║
╚══════════════════════════════════════════════╝
""")

def check_resumes():
    from config import RESUMES
    print("📂 Checking resume files...")
    all_good = True
    for role, path in RESUMES.items():
        full_path = os.path.expanduser(f"~/job-applier/{path}")
        if os.path.exists(full_path):
            print(f"  ✅ {role}: {path}")
        else:
            print(f"  ❌ MISSING — {role}: {full_path}")
            all_good = False
    return all_good

def check_tracker():
    from config import TRACKER_PATH
    print("\n📊 Checking Excel tracker...")
    if os.path.exists(TRACKER_PATH):
        print(f"  ✅ Found: {TRACKER_PATH}")
        return True
    else:
        print(f"  ❌ MISSING: {TRACKER_PATH}")
        print(f"  ℹ️  Make sure your tracker is on the Desktop")
        return False

def setup_folders():
    os.makedirs(JOBS_FOLDER, exist_ok=True)
    print(f"\n📁 Job folders will be saved to: {JOBS_FOLDER}")

def run():
    print_banner()

    print(f"🕐 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 Platforms: {', '.join(PLATFORMS).upper()}\n")

    # Pre-flight checks
    resumes_ok = check_resumes()
    tracker_ok = check_tracker()
    setup_folders()

    if not resumes_ok:
        print("\n❌ Some resume files are missing. Please fix and try again.")
        sys.exit(1)

    if not tracker_ok:
        print("\n⚠️  Tracker not found but continuing anyway — applications won't be logged.")
        input("Press Enter to continue or Ctrl+C to cancel...")

    print("\n" + "="*50)
    print("🚀 Starting applications...")
    print("="*50)

    total = 0

    if "linkedin" in PLATFORMS:
        try:
            from linkedin import run_linkedin_bot
            count  = run_linkedin_bot()
            total += count
        except Exception as e:
            print(f"\n❌ LinkedIn bot error: {e}")

    if "dice" in PLATFORMS:
        try:
            from dice import run_dice_bot
            count  = run_dice_bot()
            total += count
        except Exception as e:
            print(f"\n❌ Dice bot error: {e}")

    print("\n" + "="*50)
    print(f"🎉 ALL DONE! Total applications submitted: {total}")
    print(f"🕐 Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Check your tracker: {os.path.expanduser('~/Desktop/Salesforce_Job_Application_Tracker.xlsx')}")
    print(f"📁 Job folders: {JOBS_FOLDER}")
    print("="*50 + "\n")

if __name__ == "__main__":
    run()