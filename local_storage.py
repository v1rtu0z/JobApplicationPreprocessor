import re
import sqlite3
from pathlib import Path
from typing import Any


class JobDatabase:
    """
    SQLite database for storing job application data.
    
    Note: This is a single-threaded application, so no thread locks are needed.
    SQLite connections are created with check_same_thread=False for compatibility.
    """
    
    def __init__(self, db_path: str, columns: list[str]):
        """
        Initialize the job database.
        
        Args:
            db_path: Path to the SQLite database file
            columns: List of column names for the jobs table
        """
        self.db_path = Path(db_path)
        self.columns = columns
        self._ensure_database_exists()
    
    def _get_connection(self):
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _ensure_database_exists(self):
        """Ensure SQLite database exists with proper schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Create jobs table if it doesn't exist
        columns_sql = ', '.join([f'"{col}" TEXT' for col in self.columns])
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {columns_sql}
            )
        ''')
        
        # Add any missing columns (schema migration)
        cursor.execute("PRAGMA table_info(jobs)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        for col in self.columns:
            if col not in existing_columns:
                cursor.execute(f'ALTER TABLE jobs ADD COLUMN "{col}" TEXT')
        
        conn.commit()
        
        # Create indexes for frequently queried columns
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_job_url ON jobs("Job URL")')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_company_name ON jobs("Company Name")')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_job_url_company ON jobs("Job URL", "Company Name")')
            conn.commit()
        except Exception:
            pass  # Index creation might fail if columns don't exist yet
        
        # Fix ID gaps if any
        cursor.execute("SELECT COUNT(*), MAX(id) FROM jobs")
        count, max_id = cursor.fetchone()
        if count and count > 0 and max_id != count:
            print(f"Fixing ID gaps in {self.db_path}...")
            self._realign_ids(cursor)
            conn.commit()
            
        conn.close()

    def _realign_ids(self, cursor):
        """Re-number all IDs sequentially from 1."""
        columns = ', '.join([f'"{col}"' for col in self.columns])
        cursor.execute(f"CREATE TEMPORARY TABLE jobs_backup AS SELECT {columns} FROM jobs ORDER BY id")
        cursor.execute("DELETE FROM jobs")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='jobs'")
        cursor.execute(f"INSERT INTO jobs ({columns}) SELECT {columns} FROM jobs_backup")
        cursor.execute("DROP TABLE jobs_backup")
    
    def get_all_jobs(self) -> list[dict[str, str]]:
        """Get all jobs as a list of dictionaries."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            columns = ', '.join([f'"{col}"' for col in self.columns])
            cursor.execute(f'SELECT id, {columns} FROM jobs ORDER BY id')
            
            jobs = []
            for row in cursor.fetchall():
                job = {'_id': row[0]}  # Include internal ID
                for i, col in enumerate(self.columns):
                    value = row[i + 1]
                    job[col] = str(value) if value is not None else ''
                jobs.append(job)
            return jobs
        finally:
            conn.close()
    
    def count(self) -> int:
        """Get the total number of jobs."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM jobs')
            return cursor.fetchone()[0]
        finally:
            conn.close()
    
    def add_jobs(self, jobs: list[dict[str, str]]):
        """
        Add multiple jobs to the database.
        
        Args:
            jobs: List of job dictionaries with column names as keys
        """
        if not jobs:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        columns = ', '.join([f'"{col}"' for col in self.columns])
        placeholders = ', '.join(['?' for _ in self.columns])
        insert_sql = f'INSERT INTO jobs ({columns}) VALUES ({placeholders})'
        
        for job in jobs:
            values = [str(job.get(col, '')) if job.get(col) is not None else '' for col in self.columns]
            cursor.execute(insert_sql, values)
        
        conn.commit()
        conn.close()
    
    def add_jobs_from_rows(self, rows: list[list[str]]):
        """
        Add multiple jobs from row data (list of values matching column order).
        
        Args:
            rows: List of lists, where each inner list contains values in column order
        """
        if not rows:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        columns = ', '.join([f'"{col}"' for col in self.columns])
        placeholders = ', '.join(['?' for _ in self.columns])
        insert_sql = f'INSERT INTO jobs ({columns}) VALUES ({placeholders})'
        
        for row in rows:
            # Pad row to match column count
            padded = list(row) + [''] * (len(self.columns) - len(row))
            padded = padded[:len(self.columns)]
            padded = [str(v) if v is not None else '' for v in padded]
            cursor.execute(insert_sql, padded)
        
        conn.commit()
        conn.close()
    
    def update_job(self, job_id: int, updates: dict[str, str]):
        """
        Update a single job by its ID.
        
        Args:
            job_id: The job's database ID
            updates: Dictionary of column_name -> new_value
        """
        if not updates:
            return
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            set_clause = ", ".join([f'"{k}" = ?' for k in updates.keys()])
            values = [str(v) if v is not None else '' for v in updates.values()]
            cursor.execute(f'UPDATE jobs SET {set_clause} WHERE id = ?', values + [job_id])
            conn.commit()
        finally:
            conn.close()
    
    def update_job_by_key(self, job_url: str, company: str, updates: dict[str, str]) -> int:
        """
        Update a job by its URL and company name.
        
        Args:
            job_url: The job URL
            company: The company name
            updates: Dictionary of column_name -> new_value
            
        Returns:
            Number of rows affected
        """
        if not updates:
            return 0
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            set_clause = ", ".join([f'"{k}" = ?' for k in updates.keys()])
            values = [str(v) if v is not None else '' for v in updates.values()]
            cursor.execute(
                f'UPDATE jobs SET {set_clause} WHERE "Job URL" = ? AND "Company Name" = ?',
                values + [job_url, company]
            )
            row_count = cursor.rowcount
            conn.commit()
            return row_count
        finally:
            conn.close()
    
    def bulk_update(self, updates: list[tuple]):
        """
        Update multiple jobs efficiently.
        
        Args:
            updates: List of (job_id, updates_dict) tuples
        """
        if not updates:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        for job_id, update_dict in updates:
            if update_dict:
                set_clause = ", ".join([f'"{k}" = ?' for k in update_dict.keys()])
                values = [str(v) if v is not None else '' for v in update_dict.values()]
                cursor.execute(f'UPDATE jobs SET {set_clause} WHERE id = ?', values + [job_id])
        
        conn.commit()
        conn.close()
    
    def bulk_update_by_key(self, updates: list[tuple]):
        """
        Update multiple jobs efficiently using job URL and company name.
        
        Args:
            updates: List of (job_url, company_name, updates_dict) tuples
        """
        if not updates:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        for job_url, company_name, update_dict in updates:
            if update_dict:
                set_clause = ", ".join([f'"{k}" = ?' for k in update_dict.keys()])
                values = [str(v) if v is not None else '' for v in update_dict.values()]
                cursor.execute(
                    f'UPDATE jobs SET {set_clause} WHERE "Job URL" = ? AND "Company Name" = ?',
                    values + [job_url, company_name]
                )
        
        conn.commit()
        conn.close()
    
    def sort_by(self, sort_specs: list[tuple]):
        """
        Sort jobs by specified columns.
        
        Args:
            sort_specs: List of (column_name, ascending) tuples
                Example: [('Fit score enum', False), ('Location Priority', True)]
        """
        if not sort_specs:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Build ORDER BY clause
        numeric_columns = {'Location Priority', 'Fit score enum'}
        order_clauses = []
        
        for col_name, ascending in sort_specs:
            direction = 'ASC' if ascending else 'DESC'
            if col_name in numeric_columns:
                order_clauses.append(f'CAST(COALESCE("{col_name}", "0") AS INTEGER) {direction}')
            else:
                order_clauses.append(f'"{col_name}" {direction}')
        
        order_by = ', '.join(order_clauses)
        columns = ', '.join([f'"{col}"' for col in self.columns])
        
        # Re-sort by creating temp table and re-inserting
        cursor.execute(f'CREATE TEMPORARY TABLE jobs_sorted AS SELECT {columns} FROM jobs ORDER BY {order_by}')
        cursor.execute('DELETE FROM jobs')
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='jobs'")
        cursor.execute(f'INSERT INTO jobs ({columns}) SELECT {columns} FROM jobs_sorted')
        cursor.execute('DROP TABLE jobs_sorted')
        
        conn.commit()
        conn.close()
    
    def get_column_index(self, column_name: str) -> int:
        """Get the index of a column by name (0-indexed)."""
        return self.columns.index(column_name)

    # =========================================================================
    # Legacy compatibility methods (for gradual migration)
    # =========================================================================
    
    @property
    def header(self) -> list[str]:
        """Legacy: Return column names (for compatibility)."""
        return self.columns
    
    def get_all_records(self) -> list[dict[str, str]]:
        """Legacy: Alias for get_all_jobs() without _id field."""
        jobs = self.get_all_jobs()
        # Remove internal _id from results
        return [{k: v for k, v in job.items() if k != '_id'} for job in jobs]
    
    def append_rows(self, rows: list[list[str]]):
        """Legacy: Alias for add_jobs_from_rows()."""
        self.add_jobs_from_rows(rows)
    
    def get_all_values(self) -> list[list[str]]:
        """Legacy: Get all rows as list of lists including header."""
        jobs = self.get_all_records()
        result = [self.columns]
        for job in jobs:
            result.append([job.get(col, '') for col in self.columns])
        return result
    
    def row_values(self, row: int) -> list[str]:
        """Legacy: Get values from a specific row (1-indexed, row 1 = header)."""
        if row == 1:
            return self.columns
        
        # Get all jobs ordered by ID to maintain consistent row ordering
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            columns = ', '.join([f'"{col}"' for col in self.columns])
            cursor.execute(f'SELECT id, {columns} FROM jobs ORDER BY id')
            all_rows = cursor.fetchall()
            
            # Row 1 is header, so row 2 is first data row (index 0 in all_rows)
            row_index = row - 2
            if row_index < 0 or row_index >= len(all_rows):
                return []
            
            row_data = all_rows[row_index]
            # Skip the id column (index 0), return only data columns
            return [str(row_data[i + 1]) if row_data[i + 1] is not None else '' for i in range(len(self.columns))]
        finally:
            conn.close()
    
    def update_cell(self, row: int, col: int, value: str):
        """Legacy: Update a single cell (1-indexed row/col, row 1 = header)."""
        if row < 2:
            raise ValueError("Cannot update header row")
        
        job_id = row - 1
        col_name = self.columns[col - 1]
        self.update_job(job_id, {col_name: value})
    
    def update_record_by_fields(self, filter_dict: dict[str, str], update_dict: dict[str, str]) -> int:
        """Legacy: Update records matching filter criteria."""
        if not filter_dict or not update_dict:
            return 0
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            set_clause = ", ".join([f'"{k}" = ?' for k in update_dict.keys()])
            where_clause = " AND ".join([f'"{k}" = ?' for k in filter_dict.keys()])
            values = [str(v) if v is not None else '' for v in update_dict.values()]
            values += [str(v) if v is not None else '' for v in filter_dict.values()]
            cursor.execute(f'UPDATE jobs SET {set_clause} WHERE {where_clause}', values)
            row_count = cursor.rowcount
            conn.commit()
            return row_count
        finally:
            conn.close()
    
    def batch_update(self, updates: list[dict[str, Any]], value_input_option: str | None = None):
        """
        Legacy: Batch update with A1 notation (for compatibility).
        
        Args:
            updates: List of {'range': 'A2', 'values': [['value']]} dicts
            value_input_option: Ignored (gspread compatibility)
        """
        if not updates:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        for update in updates:
            range_str = update['range']
            values = update['values']
            
            # Parse A1 notation
            match = re.match(r'([A-Z]+)(\d+)', range_str)
            if not match:
                continue
            
            col_letter = match.group(1)
            row_num = int(match.group(2))
            
            # Convert column letter to index
            col_idx = 0
            for char in col_letter:
                col_idx = col_idx * 26 + (ord(char.upper()) - ord('A') + 1)
            
            if col_idx < 1 or col_idx > len(self.columns) or row_num < 2:
                continue
            
            job_id = row_num - 1
            
            for row_offset, value_row in enumerate(values):
                current_job_id = job_id + row_offset
                for col_offset, val in enumerate(value_row):
                    current_col_idx = col_idx + col_offset
                    if current_col_idx <= len(self.columns):
                        col_name = self.columns[current_col_idx - 1]
                        cursor.execute(
                            f'UPDATE jobs SET "{col_name}" = ? WHERE id = ?',
                            (str(val) if val is not None else '', current_job_id)
                        )
        
        conn.commit()
        conn.close()
    
    def sort(self, *sort_specs):
        """
        Legacy: Sort with column indices and 'asc'/'des' strings.
        
        Args:
            *sort_specs: Tuples of (column_index, order) where order is 'asc' or 'des'
        """
        converted = []
        for col_idx, order in sort_specs:
            col_name = self.columns[col_idx - 1]
            ascending = order != 'des'
            converted.append((col_name, ascending))
        self.sort_by(converted)


# Alias for backward compatibility
LocalSheet = JobDatabase


# =========================================================================
# File storage functions
# =========================================================================

def ensure_local_directories():
    """Ensure local storage directories exist."""
    base_dir = Path('local_data')
    resumes_dir = base_dir / 'resumes'
    cover_letters_dir = base_dir / 'cover_letters'
    
    resumes_dir.mkdir(parents=True, exist_ok=True)
    cover_letters_dir.mkdir(parents=True, exist_ok=True)
    
    return base_dir, resumes_dir, cover_letters_dir


def save_resume_local(pdf_bytes: bytes, filename: str) -> str:
    """Save PDF bytes to local resumes directory."""
    _, resumes_dir, _ = ensure_local_directories()
    file_path = resumes_dir / filename
    
    with open(file_path, 'wb') as f:
        f.write(pdf_bytes)
    
    return str(Path("local_data") / "resumes" / filename)


def save_cover_letter_local(cover_letter_text: str, filename: str) -> str:
    """Save cover letter text to local cover_letters directory."""
    _, _, cover_letters_dir = ensure_local_directories()
    
    if not filename.endswith('.txt'):
        filename = f"{filename}.txt"
    
    file_path = cover_letters_dir / filename
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(cover_letter_text)
    
    return str(Path("local_data") / "cover_letters" / filename)


def delete_resume_local(resume_path: str):
    """Delete a resume file from local directory."""
    if not resume_path:
        return
    
    path_obj = Path(resume_path)
    if resume_path.startswith('./'):
        file_path = path_obj
    elif resume_path.startswith('local_data/'):
        file_path = Path('.') / path_obj
    else:
        file_path = path_obj
    
    try:
        if file_path.exists():
            file_path.unlink()
            print(f"Deleted local resume: {file_path}")
    except Exception as e:
        print(f"Error deleting local resume {resume_path}: {e}")


def get_local_file_path(user_name: str, company_name: str, file_type: str = 'resume') -> str:
    """Generate a local file path based on job details."""
    sanitized_user = user_name.replace(' ', '_')
    sanitized_company = company_name.replace(' ', '_')
    
    if file_type == 'resume':
        return f"{sanitized_user}_resume_{sanitized_company}.pdf"
    elif file_type == 'cover_letter':
        return f"{sanitized_user}_cover_letter_{sanitized_company}.txt"
    else:
        raise ValueError(f"Unknown file_type: {file_type}")
