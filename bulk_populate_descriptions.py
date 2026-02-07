import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path so imports work when run from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    SHEET_HEADER,
    extract_job_id,
    fetch_job_details_bulk_via_apify,
    normalize_company_name,
    match_job_to_apify_result,
)
from local_storage import JobDatabase


def verify_apify_connectivity():
    """Initial verification test to confirm Apify works"""
    print("Step 1: Verifying Apify connectivity and usage limits...")
    # Use a known public LinkedIn job ID or just one from the DB
    test_job_id = "4132338561" # Example ID
    
    try:
        results = fetch_job_details_bulk_via_apify([test_job_id])
        if not results:
            # If fetch_job_details_bulk_via_apify returned [] but didn't raise
            # it might be due to APIFY_AVAILABLE being False or just no results.
            # We want to be explicit here.
            from utils import APIFY_AVAILABLE
            if not APIFY_AVAILABLE:
                print("CRITICAL ERROR: Apify usage limit exceeded or API token invalid.")
                sys.exit(1)
            else:
                print("Warning: Apify returned no results for test ID, but connectivity seems OK.")
        else:
            print(f"Apify verification successful! Fetched details for job ID: {test_job_id}")
    except Exception as e:
        print(f"CRITICAL ERROR during Apify verification: {e}")
        sys.exit(1)

def run_migration():
    load_dotenv()
    
    db_path = Path("local_data") / "jobs.db"
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    # 1. Verification Test
    verify_apify_connectivity()

    print("\nStep 2: Starting bulk description population...")
    db = JobDatabase(str(db_path), SHEET_HEADER)
    all_rows = db.get_all_records()
    
    # Find jobs missing descriptions
    jobs_to_process = []
    for row in all_rows:
        description = row.get('Job Description', '').strip()
        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()
        
        if not description and job_url and company_name:
            job_id = extract_job_id(job_url)
            if job_id:
                jobs_to_process.append({
                    'job_url': job_url,
                    'company': company_name,
                    'job_id': job_id,
                    'title': row.get('Job Title', '')
                })

    if not jobs_to_process:
        print("No jobs found missing descriptions.")
        return

    print(f"Found {len(jobs_to_process)} jobs missing descriptions.")
    
    # Process in batches
    # Note: Import from pipeline.constants if this becomes a shared constant
    batch_size = 100  # Number of job descriptions to fetch per batch
    total_updated = 0
    
    for i in range(0, len(jobs_to_process), batch_size):
        batch = jobs_to_process[i:i + batch_size]
        batch_ids = [job['job_id'] for job in batch]
        
        print(f"\nProcessing batch {i // batch_size + 1} ({len(batch)} jobs)...")
        
        fetched_details = fetch_job_details_bulk_via_apify(batch_ids)
        
        if not fetched_details:
            print("Failed to fetch details for this batch. Stopping migration.")
            break
            
        # Match Apify results back to our jobs by comparing job title and company name
        # The Apify actor returns: { "job_info": { "title": ..., "description": ... }, "company_info": { "name": ... } }
        # We match using case-insensitive substring matching on title and company name
        for item in fetched_details:
            # Try to find which job this belongs to
            job_info = item.get('job_info', {})
            desc = job_info.get('description', '')
            if not desc:
                continue
            
            # Find the match in our batch using shared matching function
            match = None
            for job in batch:
                if match_job_to_apify_result(job, item):
                    match = job
                    break
            
            if match:
                # Update DB
                updates = {'Job Description': desc, 'CO fetch attempted': 'TRUE'}
                company_info = item.get('company_info', {})
                co_desc = company_info.get('description', '')
                if co_desc:
                    updates['Company overview'] = co_desc
                
                db.update_job_by_key(match['job_url'], match['company'], updates)
                total_updated += 1
                print(f"  Updated: {match['title']} @ {match['company']}")

        time.sleep(2) # Brief delay between batches
        
    print(f"\nBulk population complete!")
    print(f"Total jobs processed: {len(jobs_to_process)}")
    print(f"Total jobs updated: {total_updated}")

if __name__ == "__main__":
    run_migration()
