import sqlite3
from pathlib import Path
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from utils import SHEET_HEADER, normalize_company_name
from local_storage import JobDatabase

def migrate():
    db_path = Path("local_data") / "jobs.db"
    if not db_path.exists():
        print("Database not found.")
        return

    print(f"Connecting to {db_path}...")
    db = JobDatabase(str(db_path), SHEET_HEADER)
    all_rows = db.get_all_records()
    
    # 1. Build cache of company -> overview
    co_cache = {}
    for row in all_rows:
        company = row.get('Company Name', '').strip()
        co = row.get('Company overview', '').strip()
        if company and co:
            company_key = normalize_company_name(company)
            if company_key not in co_cache:
                co_cache[company_key] = co
            
    print(f"Built cache with {len(co_cache)} company overviews.")
    
    # 2. Update rows missing CO or fetch attempted status
    updates = 0
    cos_filled = 0
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    for idx, row in enumerate(all_rows, start=1):
        job_id = idx # SQLite row ID corresponds to list index + 1 in this simple setup
        company_name = row.get('Company Name', '').strip()
        company_key = normalize_company_name(company_name)
        current_co = row.get('Company overview', '').strip()
        current_attempted = row.get('CO fetch attempted', '').strip()
        
        needs_update = False
        new_co = current_co
        new_attempted = current_attempted
        
        # Fill missing CO from cache
        if not current_co and company_key in co_cache:
            new_co = co_cache[company_key]
            needs_update = True
            cos_filled += 1
            
        # Initialize missing fetch attempted status
        # If CO is already present, we mark it as attempted
        if not current_attempted:
            if new_co:
                new_attempted = 'TRUE'
            else:
                new_attempted = 'FALSE'
            needs_update = True
            
        if needs_update:
            cursor.execute(
                'UPDATE jobs SET "Company overview" = ?, "CO fetch attempted" = ? WHERE id = ?',
                (new_co, new_attempted, job_id)
            )
            updates += 1
            
    conn.commit()
    conn.close()
    
    print(f"Migration complete:")
    print(f"- Total rows processed: {len(all_rows)}")
    print(f"- Company overviews filled from cache: {cos_filled}")
    print(f"- Rows updated: {updates}")

if __name__ == "__main__":
    migrate()
