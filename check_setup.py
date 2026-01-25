import os
import sys
from dotenv import load_dotenv

def check_setup():
    print("🔍 Starting Job Application Preprocessor Setup Check...\n")
    
    # 1. Check Python version
    print(f"🐍 Python Version: {sys.version.split()[0]} - {'OK' if sys.version_info >= (3, 10) else 'WARNING: Python 3.10+ recommended'}")
    
    # 2. Check Dependencies
    dependencies = [
        ('apify_client', 'apify-client'),
        ('google.genai', 'google-genai'),
        ('html2text', 'html2text'),
        ('linkedin_scraper', 'linkedin-scraper'),
        ('selenium', 'selenium'),
        ('dotenv', 'python-dotenv'),
        ('streamlit', 'streamlit'),
        ('pandas', 'pandas'),
    ]
    
    print("\n📦 Checking Dependencies:")
    missing_deps = []
    for module, package in dependencies:
        try:
            __import__(module)
            print(f"  ✅ {package} is installed")
        except ImportError:
            print(f"  ❌ {package} is MISSING")
            missing_deps.append(package)
            
    if missing_deps:
        print(f"\n👉 Please run: pip install {' '.join(missing_deps)}")

    # 3. Check .env file
    print("\n📄 Checking .env file:")
    if os.path.exists('.env'):
        print("  ✅ .env file found")
        load_dotenv()
        required_vars = ['EMAIL_ADDRESS', 'GEMINI_API_KEY', 'APIFY_API_TOKEN', 'SERVER_URL']
        for var in required_vars:
            if os.getenv(var):
                print(f"  ✅ {var} is set")
            else:
                print(f"  ❌ {var} is MISSING in .env")
    else:
        print("  ❌ .env file NOT FOUND")

    # 4. Check Local Storage Directory
    print("\n💾 Checking Local Storage:")
    local_data_path = os.path.join('.', 'local_data')
    if os.path.exists(local_data_path):
        print("  ✅ local_data directory exists")
        db_path = os.path.join(local_data_path, 'jobs.db')
        if os.path.exists(db_path):
            print("  ✅ jobs.db database found")
        else:
            print("  ℹ️ jobs.db not found (will be created on first run)")
    else:
        print("  ℹ️ local_data directory not found (will be created on first run)")

    # 5. Check Personalization files
    print("\n👤 Checking Personalization Files:")
    resume_found = os.path.exists('resume_data.json')
    if resume_found:
        print("  ✅ resume_data.json found")
    else:
        resume_pdf = os.getenv("RESUME_PDF_PATH")
        if resume_pdf and os.path.exists(resume_pdf):
            print(f"  ✅ resume_data.json missing but will be created from: {resume_pdf}")
        elif resume_pdf:
            print(f"  ❌ resume_data.json missing and RESUME_PDF_PATH file NOT FOUND: {resume_pdf}")
        else:
            print("  ❌ resume_data.json missing and RESUME_PDF_PATH not set in .env")

    for f in ['additional_details.txt']:
        if os.path.exists(f):
            print(f"  ✅ {f} found")
        else:
            print(f"  ❌ {f} MISSING")

    print("\n✨ Setup check complete!")

if __name__ == "__main__":
    check_setup()
