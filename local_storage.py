import csv
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


class LocalSheet:
    """
    A local CSV-based implementation that mimics gspread's Sheet interface.
    Stores job data in CSV format with the same column structure as Google Sheets.
    """
    
    def __init__(self, csv_path: str, header: List[str]):
        """
        Initialize LocalSheet with CSV file path and header.
        
        Args:
            csv_path: Path to the CSV file
            header: List of column names (header row)
        """
        self.csv_path = Path(csv_path)
        self.header = header
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """Ensure CSV file exists with proper header."""
        if not self.csv_path.exists():
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                f.write("sep=,\n")
                writer = csv.writer(f)
                writer.writerow(self.header)
        else:
            # Verify header matches
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                line = f.readline()
                if line.strip() == "sep=,":
                    reader = csv.reader(f)
                else:
                    # No sep=, line, reset to start
                    f.seek(0)
                    reader = csv.reader(f)
                
                existing_header = next(reader, None)
                if existing_header != self.header:
                    print(f"Warning: CSV header mismatch. Expected {len(self.header)} columns, found {len(existing_header) if existing_header else 0}")
    
    def get_all_records(self) -> List[Dict[str, str]]:
        """
        Get all rows as a list of dictionaries.
        Returns empty list if file is empty or only has header.
        """
        records = []
        if not self.csv_path.exists():
            return records
        
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            line = f.readline()
            if line.strip() != "sep=,":
                f.seek(0)
            
            reader = csv.DictReader(f)
            for row in reader:
                # Convert empty strings to empty strings (keep as is)
                records.append({k: v for k, v in row.items()})
        
        return records
    
    def append_rows(self, rows: List[List[str]]):
        """
        Append rows to the CSV file.
        
        Args:
            rows: List of lists, where each inner list represents a row
        """
        with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            for row in rows:
                # Ensure row has same length as header
                padded_row = row + [''] * (len(self.header) - len(row))
                writer.writerow(padded_row[:len(self.header)])
    
    def append_row(self, row: List[str]):
        """Append a single row to the CSV file."""
        self.append_rows([row])
    
    def update_cell(self, row: int, col: int, value: str):
        """
        Update a single cell.
        
        Args:
            row: Row number (1-indexed, where 1 is header)
            col: Column number (1-indexed)
        """
        records = self.get_all_records()
        
        # Convert to 0-indexed
        row_idx = row - 2  # -2 because row 1 is header, row 2 is first data row
        
        if row_idx < 0:
            raise ValueError(f"Row {row} is header row, cannot update")
        
        if row_idx >= len(records):
            # Pad with empty rows if needed
            while len(records) <= row_idx:
                records.append({col: '' for col in self.header})
        
        col_name = self.header[col - 1]  # Convert to 0-indexed
        records[row_idx][col_name] = str(value) if value is not None else ''
        
        self._write_all_records(records)
    
    def batch_update(self, updates: List[Dict[str, Any]], value_input_option: Optional[str] = None):
        """
        Batch update multiple cells.
        
        Args:
            updates: List of dicts with 'range' and 'values' keys
                Example: [{'range': 'A2', 'values': [['value']]}]
            value_input_option: Ignored for local storage (kept for compatibility)
        """
        records = self.get_all_records()
        
        for update in updates:
            range_str = update['range']
            values = update['values']
            
            # Parse A1 notation (e.g., 'A2', 'B5')
            match = re.match(r'([A-Z]+)(\d+)', range_str)
            if not match:
                print(f"Warning: Could not parse range '{range_str}', skipping")
                continue
            
            col_letter = match.group(1)
            row_num = int(match.group(2))
            
            # Convert column letter to index (A=1, B=2, etc.)
            col_idx = self._column_letter_to_index(col_letter)
            
            if col_idx < 1 or col_idx > len(self.header):
                print(f"Warning: Column {col_letter} ({col_idx}) out of range, skipping")
                continue
            
            # Update cell(s)
            row_idx = row_num - 2  # -2 because row 1 is header
            
            if row_idx < 0:
                print(f"Warning: Cannot update header row (row {row_num}), skipping")
                continue
            
            # Ensure records list is large enough
            while len(records) <= row_idx:
                records.append({col: '' for col in self.header})
            
            col_name = self.header[col_idx - 1]
            
            # Handle multiple values (for ranges like A2:B2)
            if values:
                for i, value_row in enumerate(values):
                    if i == 0:
                        # First value goes to the specified cell
                        records[row_idx][col_name] = str(value_row[0]) if value_row else ''
                    else:
                        # Additional values go to subsequent columns
                        if col_idx + i <= len(self.header):
                            next_col_name = self.header[col_idx + i - 1]
                            records[row_idx][next_col_name] = str(value_row[0]) if value_row else ''
        
        self._write_all_records(records)
    
    def sort(self, *sort_specs):
        """
        Sort rows by specified columns.
        
        Args:
            *sort_specs: Tuples of (column_index, order) where order is 'asc' or 'des'
                Example: sort((5, 'des'), (3, 'asc'))
        """
        records = self.get_all_records()
        
        if not records:
            return
        
        # Build list of key functions for multi-level sorting
        key_functions = []
        for col_idx, order in sort_specs:
            col_name = self.header[col_idx - 1]  # Convert to 0-indexed
            
            def make_key_func(name, direction):
                def key_func(record):
                    value = record.get(name, '')
                    # Handle numeric values for enum columns
                    try:
                        num_value = int(value) if value else 0
                        # Negate for descending order
                        return -num_value if direction == 'des' else num_value
                    except ValueError:
                        # String comparison - for descending, use reversed comparison
                        if direction == 'des':
                            # Use a wrapper that will be sorted in reverse
                            return (1, value)  # 1 indicates descending
                        else:
                            return (0, value)  # 0 indicates ascending
                return key_func
            
            key_functions.append(make_key_func(col_name, order))
        
        # Sort using multiple keys
        def multi_key(record):
            return tuple(f(record) for f in key_functions)
        
        records.sort(key=multi_key)
        
        self._write_all_records(records)
    
    def row_values(self, row: int) -> List[str]:
        """
        Get values from a specific row.
        
        Args:
            row: Row number (1-indexed, where 1 is header)
        
        Returns:
            List of cell values
        """
        if row == 1:
            return self.header
        
        records = self.get_all_records()
        row_idx = row - 2  # -2 because row 1 is header
        
        if row_idx < 0 or row_idx >= len(records):
            return []
        
        record = records[row_idx]
        return [record.get(col, '') for col in self.header]
    
    def _write_all_records(self, records: List[Dict[str, str]]):
        """Write all records back to CSV file."""
        with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
            f.write("sep=,\n")
            writer = csv.DictWriter(f, fieldnames=self.header)
            writer.writeheader()
            writer.writerows(records)
    
    def _column_letter_to_index(self, col_letter: str) -> int:
        """
        Convert column letter (A, B, C, ..., Z, AA, AB, ...) to 1-indexed column number.
        
        Args:
            col_letter: Column letter(s) (e.g., 'A', 'B', 'AA')
        
        Returns:
            1-indexed column number
        """
        result = 0
        for char in col_letter:
            result = result * 26 + (ord(char.upper()) - ord('A') + 1)
        return result


# File storage functions

def ensure_local_directories():
    """Ensure local storage directories exist."""
    base_dir = Path('local_data')
    resumes_dir = base_dir / 'resumes'
    cover_letters_dir = base_dir / 'cover_letters'
    
    resumes_dir.mkdir(parents=True, exist_ok=True)
    cover_letters_dir.mkdir(parents=True, exist_ok=True)
    
    return base_dir, resumes_dir, cover_letters_dir


def save_resume_local(pdf_bytes: bytes, filename: str) -> str:
    """
    Save PDF bytes to local resumes directory.
    
    Args:
        pdf_bytes: PDF file bytes
        filename: Filename for the resume
    
    Returns:
        Relative path to the saved file
    """
    _, resumes_dir, _ = ensure_local_directories()
    
    file_path = resumes_dir / filename
    
    with open(file_path, 'wb') as f:
        f.write(pdf_bytes)
    
    # Return relative path
    return str(Path("local_data") / "resumes" / filename)


def save_cover_letter_local(cover_letter_text: str, filename: str) -> str:
    """
    Save cover letter text to local cover_letters directory.
    
    Args:
        cover_letter_text: Cover letter content as string
        filename: Filename for the cover letter (without extension)
    
    Returns:
        Relative path to the saved file
    """
    _, _, cover_letters_dir = ensure_local_directories()
    
    # Ensure filename has .txt extension
    if not filename.endswith('.txt'):
        filename = f"{filename}.txt"
    
    file_path = cover_letters_dir / filename
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(cover_letter_text)
    
    # Return relative path
    return str(Path("local_data") / "cover_letters" / filename)


def delete_resume_local(resume_path: str):
    """
    Delete a resume file from local directory.
    
    Args:
        resume_path: Path to the resume file (can be relative or absolute, or Google Drive URL)
    """
    if not resume_path:
        return
    
    # If it's a Google Drive URL, skip (shouldn't happen in local mode, but be safe)
    if 'drive.google.com' in resume_path:
        return
    
    # Handle relative paths
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
    """
    Generate a local file path based on job details.
    
    Args:
        user_name: User's name (sanitized)
        company_name: Company name (sanitized)
        file_type: 'resume' or 'cover_letter'
    
    Returns:
        Filename (not full path)
    """
    sanitized_user = user_name.replace(' ', '_')
    sanitized_company = company_name.replace(' ', '_')
    
    if file_type == 'resume':
        return f"{sanitized_user}_resume_{sanitized_company}.pdf"
    elif file_type == 'cover_letter':
        return f"{sanitized_user}_cover_letter_{sanitized_company}.txt"
    else:
        raise ValueError(f"Unknown file_type: {file_type}")
