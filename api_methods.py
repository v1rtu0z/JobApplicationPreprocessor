import base64
import json
import os
import random
import time
from pathlib import Path
from typing import Optional, Any

import jwt
import requests
from PyPDF2 import PdfReader
from pdfminer.high_level import extract_text as extract_text_miner
from pdfminer.layout import LAParams, LTTextBox, LTTextLine
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import PDFPageAggregator
from dotenv import load_dotenv

try:
    from tkinter import Tk, filedialog
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False

from utils import get_user_name
from config import _get_job_filters

load_dotenv()

SERVER_URL = os.getenv("SERVER_URL")
EXTENSION_SECRET_KEY = os.getenv("API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BACKUP_GEMINI_API_KEY = os.getenv("BACKUP_GEMINI_API_KEY")
RESUME_PDF_PATH = os.getenv("RESUME_PDF_PATH")

# Constants
JWT_TOKEN_EXPIRY_SAFETY_MARGIN = 60  # Subtract 60 seconds from token expiry for safety margin
DEFAULT_TOKEN_EXPIRY_SECONDS = 3600  # Default token expiry if not found in JWT (1 hour)

# Cache for JWT token and resume JSON
_jwt_token: Optional[str] = None
_token_expiry: float = 0


def _is_token_expired() -> bool:
    """Check if the current JWT token is expired"""
    return time.time() >= _token_expiry


def _authenticate() -> Optional[str]:
    """Authenticate with the server to get a JWT token"""
    global _jwt_token, _token_expiry

    try:
        response = requests.post(
            f"{SERVER_URL}/authenticate",
            json={"client_secret": EXTENSION_SECRET_KEY},
            headers={'Content-Type': 'application/json'}
        )

        if response.status_code == 429:
            print("Rate limit exceeded during authentication")
            return None

        if not response.ok:
            print(f"Authentication failed with status: {response.status_code}")
            return None

        data = response.json()
        _jwt_token = data['token']

        # Decode JWT to get expiry using PyJWT library
        # Note: We skip signature verification since we trust our own server
        # Subtract safety margin for buffer time
        try:
            decoded = jwt.decode(_jwt_token, options={"verify_signature": False})
            _token_expiry = decoded.get('exp', time.time() + DEFAULT_TOKEN_EXPIRY_SECONDS) - JWT_TOKEN_EXPIRY_SAFETY_MARGIN
        except jwt.DecodeError as e:
            print(f"Warning: Failed to decode JWT token: {e}. Using default expiry.")
            _token_expiry = time.time() + DEFAULT_TOKEN_EXPIRY_SECONDS - JWT_TOKEN_EXPIRY_SAFETY_MARGIN

        return _jwt_token

    except Exception as e:
        print(f"Error during authentication: {e}")
        return None


def _get_auth_headers() -> dict:
    """Get authorization headers with valid JWT token"""
    global _jwt_token

    if not _jwt_token or _is_token_expired():
        token = _authenticate()
        if not token:
            raise Exception("Failed to authenticate with the server")
        _jwt_token = token

    return {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {_jwt_token}'
    }


def _make_api_request_with_fallback(url: str, payload: dict) -> dict | None:
    """
    Make API request with primary and backup Gemini API keys.

    Strategy:
    1. Try primary key once
    2. If 429, try backup key once
    3. If both fail with 429, return None to skip this operation

    Args:
        url: API endpoint URL
        payload: Request payload (will be modified with api_key)

    Returns:
        Response JSON data or None if both keys hit rate limits

    Raises:
        Exception: For non-429 errors
    """
    keys_to_try = [
        ("primary", GEMINI_API_KEY),
        ("backup", BACKUP_GEMINI_API_KEY)
    ]

    for key_name, current_key in keys_to_try:
        if not current_key:
            continue  # Skip if key not configured
            
        try:
            current_payload = payload.copy()
            current_payload["gemini_api_key"] = current_key

            headers = _get_auth_headers()
            response = requests.post(url, json=current_payload, headers=headers)

            # Handle 502 with single retry
            if response.status_code == 502:
                time.sleep(random.uniform(2, 4))
                response = requests.post(url, json=current_payload, headers=headers)

            # Handle rate limiting - move to next key
            if response.status_code == 429:
                print("\n" + "!" * 40)
                print(f"RATE LIMIT: {key_name} key hit rate limit (429).")
                print("!" * 40 + "\n")
                continue  # Try next key

            # Handle other HTTP errors
            if not response.ok:
                # Only print error for non-404 errors (404s are expected for optional endpoints)
                if response.status_code != 404:
                    error_msg = f"API request failed: {response.status_code} - {response.text}"
                    print(f"ERROR: {error_msg}")
                    # For 5xx errors, we might want to retry, but for now just return None
                    # 4xx errors (except 404) are client errors and shouldn't be retried
                    if 500 <= response.status_code < 600:
                        print(f"  Server error ({response.status_code}), will try backup key if available")
                return None

            # Success!
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Network error on {key_name} key: {e}")
            continue  # Try next key

    # All keys exhausted (either rate limited or network errors)
    print("CRITICAL: All Gemini API keys exhausted (rate limited or network errors).")
    print("Skipping this operation. The app will continue but some steps may be skipped.")
    # Raise a specific exception so callers can detect rate limit situations
    raise Exception("Rate limit: All Gemini API keys exhausted")


def create_resume_json_from_pdf(pdf_path: str) -> dict:
    """
    Call the /get-resume-json endpoint to convert a PDF resume to JSON.
    """
    if not os.path.exists(pdf_path):
        print(f"CRITICAL ERROR: Resume PDF not found at: {pdf_path}")
        print("Please check RESUME_PDF_PATH in your .env file.")
        raise FileNotFoundError(f"Resume PDF not found at: {pdf_path}")

    print(f"Converting resume PDF to JSON: {pdf_path}")
    
    # Extract text from PDF
    try:
        # Using pdfminer.six for better text extraction (similar to PDF.js used by the user)
        # We mimic the provided TS logic: join items with spaces to avoid line-break issues
        rsrcmgr = PDFResourceManager()
        laparams = LAParams()
        device = PDFPageAggregator(rsrcmgr, laparams=laparams)
        interpreter = PDFPageInterpreter(rsrcmgr, device)
        
        pages_text = []
        with open(pdf_path, 'rb') as fp:
            for page in PDFPage.get_pages(fp):
                interpreter.process_page(page)
                layout = device.get_result()
                page_items = []
                for obj in layout:
                    if isinstance(obj, (LTTextBox, LTTextLine)):
                        page_items.append(obj.get_text().strip())
                pages_text.append(" ".join(page_items))
        
        pdf_text = " ".join(pages_text)
        
        # If extraction produced almost no text, try a simpler extract_text_miner
        if len(pdf_text.strip()) < 10:
            print("Advanced extraction too short, trying extract_text_miner...")
            pdf_text = extract_text_miner(pdf_path)

        # If still too short, try PyPDF2 as fallback
        if len(pdf_text.strip()) < 10:
            print("pdfminer.six extraction too short, trying PyPDF2...")
            reader = PdfReader(pdf_path)
            pdf_text = ""
            for page in reader.pages:
                extracted_text = page.extract_text()
                if extracted_text:
                    pdf_text += extracted_text + "\n"
        
        # Final check
        if len(pdf_text.strip()) < 10:
            raise ValueError("Extracted text is too short, possible empty or image-based PDF")
            
    except Exception as e:
        print(f"Warning: PDF text extraction failed or returned insufficient data: {e}")
        print("Falling back to reading as text...")
        with open(pdf_path, 'r', encoding='utf-8', errors='ignore') as f:
            pdf_text = f.read()

    payload = {
        "resume_content": pdf_text,
        'model_name': os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
    }
    
    headers = _get_auth_headers()
    response = requests.post(
        f"{SERVER_URL}/get-resume-json",
        json=payload,
        headers=headers
    )
    
    if not response.ok:
        raise Exception(f"Failed to convert resume PDF to JSON: {response.status_code} - {response.text}")
    
    data = response.json()
    resume_data = data.get('resume_data')
    
    if not resume_data:
        raise Exception("API returned success but no resume_data found in response")
        
    # Save it for later use
    with open('./resume_data.json', 'w', encoding='utf-8') as f:
        json.dump(resume_data, f, indent=2, ensure_ascii=False)
    
    print("Successfully created resume_data.json")
    return resume_data


def create_resume_json_from_text(text: str, output_path: str = "./resume_data.json") -> dict:
    """
    Call the /get-resume-json endpoint to convert free text (e.g. additional details)
    into structured resume JSON. Validates that personal.full_name is present.
    """
    text = (text or "").strip()
    if len(text) < 20:
        raise ValueError("Text is too short; provide at least a few sentences (e.g. experience, skills, name).")

    payload = {
        "resume_content": text,
        "model_name": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    }
    headers = _get_auth_headers()
    response = requests.post(
        f"{SERVER_URL}/get-resume-json",
        json=payload,
        headers=headers,
    )
    if not response.ok:
        raise Exception(f"Failed to generate resume from text: {response.status_code} - {response.text}")

    data = response.json()
    resume_data = data.get("resume_data")
    if not resume_data:
        raise Exception("API returned no resume_data")

    # Validate schema: at least personal.full_name required by get_user_name()
    if not (resume_data.get("personal") or {}).get("full_name"):
        raise Exception("Generated resume missing personal.full_name; please include your name in the text.")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(resume_data, f, indent=2, ensure_ascii=False)
    print(f"Successfully created {output_path} from text.")
    return resume_data


def get_resume_json() -> dict:
    """
    Read resume from resume_data.json and add additional details.
    """
    try:
        # Check if resume_data.json exists, if not try to create it from PDF
        if not os.path.exists('./resume_data.json'):
            pdf_path = RESUME_PDF_PATH
            if not pdf_path:
                if TKINTER_AVAILABLE:
                    print("RESUME_PDF_PATH not found in .env. Please select your resume PDF file...")
                    root = Tk()
                    root.withdraw()  # Hide the main tkinter window
                    root.attributes('-topmost', True)  # Bring to front
                    pdf_path = filedialog.askopenfilename(
                        title="Select your resume PDF",
                        filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
                    )
                    root.destroy()
                else:
                    # Fallback to command-line input if tkinter is not available
                    print("RESUME_PDF_PATH not found in .env and tkinter is not available.")
                    print("Please provide the path to your resume PDF file:")
                    pdf_path = input("Resume PDF path: ").strip()
                    # Remove quotes if user pasted a quoted path
                    if pdf_path.startswith('"') and pdf_path.endswith('"'):
                        pdf_path = pdf_path[1:-1]
                    if pdf_path.startswith("'") and pdf_path.endswith("'"):
                        pdf_path = pdf_path[1:-1]
                
                if not pdf_path:
                    raise FileNotFoundError("No resume PDF selected and RESUME_PDF_PATH not set in .env")

            resume_data = create_resume_json_from_pdf(pdf_path)
        else:
            # Read the JSON file directly
            with open('./resume_data.json', 'r', encoding='utf-8') as f:
                resume_data = json.load(f)

        # Add additional details to resume JSON if file exists
        additional_details_path = './additional_details.txt'
        if os.path.exists(additional_details_path):
            with open(additional_details_path, 'r') as f:
                additional_details = f.read()
            resume_data['additional_details'] = additional_details
        else:
            print(f"Notice: {additional_details_path} not found. Personalized analysis might be limited.")

        return resume_data

    except json.JSONDecodeError as e:
        print(f"Error parsing resume JSON: {e}")
        raise
    except Exception as e:
        print(f"Error reading resume data: {e}")
        raise


def get_job_analysis(resume_json, job_details: dict) -> str:
    """
    Analyze a job posting against the resume.

    Args:
        resume_json: The resume JSON data
        job_details: Dict containing company_name, job_title, job_description, 
                    job_url, location, posted_date

    Returns:
        Job analysis text

    Raises:
        Exception: For 429 rate limit errors (non-critical, can continue)
        Exception: For all other errors (critical, should break flow)
    """
    try:
        # Prepare job_specific_context (everything except job_description)
        job_specific_context = {
            'company_name': job_details.get('company_name', ''),
            'job_title': job_details.get('job_title', ''),
            'location': job_details.get('location', ''),
            'job_url': job_details.get('job_url', ''),
            'company_overview': job_details.get('company_overview')
        }

        # Load settings
        model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

        payload = {
            "job_posting_text": job_details.get('job_description', ''),
            "job_specific_context": json.dumps(job_specific_context),
            "resume_json_data": json.dumps(resume_json),
            "model_name": model_name
        }

        data = _make_api_request_with_fallback(
            f"{SERVER_URL}/analyze-job-posting",
            payload
        )

        if data is None:
            raise Exception("API request failed - skipping this operation")

        return data['job_analysis']

    except Exception as e:
        # Check if it's a rate limit error (non-critical, should trigger short wait)
        error_str = str(e)
        if "Rate limit" in error_str or "429" in error_str:
            raise Exception("Rate limit exceeded - Gemini API 429")
        # All other errors are critical
        print(f"Critical error analyzing job: {e}")
        raise


def get_tailored_resume(
        resume_json,
        job_details: dict,
        current_resume_data: str = None,
        retry_feedback: str = None
) -> tuple[str, str, bytes]:
    """
    Generate a tailored resume for a job posting.

    Args:
        resume_json: The resume JSON data
        job_details: Dict containing company_name, job_title, job_description, 
                    job_url, location, posted_date
        current_resume_data: Current resume JSON (for retry)
        retry_feedback: Feedback for improving the resume (for retry)

    Returns:
        Tuple of (tailored_resume_json_str, filename, pdf_bytes)

    Raises:
        Exception: For any error (no retries except for rate limits via fallback mechanism)
    """
    user_name = get_user_name(resume_json).replace(' ', '_')

    # Generate filename from job details
    company = job_details.get('company_name', 'Company').replace(' ', '_')
    filename = f"{user_name}_resume_{company}.pdf"

    # Load settings
    filters = _get_job_filters()
    general_settings = filters.get('general_settings', {})
    theme = general_settings.get('resume_theme', 'engineeringclassic')
    model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

    payload = {
        "job_posting_text": job_details.get('job_description', ''),
        "resume_json_data": json.dumps(resume_json),
        "filename": filename,
        "theme": theme,
        "model_name": model_name,
        **({"current_resume_data": current_resume_data} if current_resume_data else {}),
        **({"retry_feedback": retry_feedback} if retry_feedback else {})
    }

    data = _make_api_request_with_fallback(
        f"{SERVER_URL}/tailor-resume",
        payload
    )

    if data is None:
        raise Exception("API request failed - skipping this operation")

    # Decode base64 PDF
    pdf_bytes = base64.b64decode(data['pdf_base64_string'])
    tailored_json_str = json.dumps(data['tailored_resume_json'])

    return tailored_json_str, filename, pdf_bytes


def save_resume_to_downloads(pdf_bytes: bytes, filename: str) -> str:
    """
    Save PDF bytes to ~/Downloads folder.

    Returns:
        Full path to the saved file
    """
    downloads_path = Path.home() / "Downloads"
    downloads_path.mkdir(exist_ok=True)

    file_path = downloads_path / filename

    with open(file_path, 'wb') as f:
        f.write(pdf_bytes)

    return str(file_path)


def get_tailored_cl(resume_json, job_details: dict, current_content: str = None, retry_feedback: str = None) -> str:
    """
    Get tailored cover letter, with optional retry capability

    Args:
        resume_json: The resume JSON data
        job_details: Job details dictionary
        current_content: Current cover letter content (for retry)
        retry_feedback: Feedback for improving the cover letter (for retry)

    Returns:
        Cover letter content as string

    Raises:
        Exception: For any error (no retries except for rate limits via fallback mechanism)
    """
    # Prepare job_specific_context (everything except job_description)
    job_specific_context = {
        'company_name': job_details.get('company_name', ''),
        'job_title': job_details.get('job_title', ''),
        'location': job_details.get('location', ''),
        'posted_date': job_details.get('posted_date', ''),
        'job_url': job_details.get('job_url', '')
    }

    # Load settings
    model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

    payload = {
        "job_posting_text": job_details.get('job_description', ''),
        "job_specific_context": json.dumps(job_specific_context),
        "current_content": current_content,
        "retry_feedback": retry_feedback,
        "resume_json_data": json.dumps(resume_json),
        "model_name": model_name
    }

    data = _make_api_request_with_fallback(
        f"{SERVER_URL}/generate-cover-letter",
        payload
    )

    if data is None:
        raise Exception("API request failed - skipping this operation")

    return data['content']


def get_search_parameters(resume_json: dict) -> list[dict]:
    """
    Generate search parameters for LinkedIn jobs based on resume and additional details.
    Uses Gemini API directly to generate search parameters.
    """
    try:
        import google.genai as genai
        from utils import rate_limit
        
        # Load additional details if they exist
        additional_details = ""
        additional_details_path = 'additional_details.txt'
        if os.path.exists(additional_details_path):
            with open(additional_details_path, 'r') as f:
                additional_details = f.read()
        else:
            print(f"Warning: {additional_details_path} not found. LLM results may be less personalized.")

        model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
        filters = _get_job_filters()
        default_location = (filters.get('default_search_location') or '').strip()
        location_line = f"\nDefault job search location (use when not specified in additional details): {default_location}\n" if default_location else ""

        # Build prompt for generating search parameters
        prompt = f"""Based on the following resume and additional details, generate a list of search parameters for LinkedIn job searches.
The goal is to find jobs that are a good fit for the user's background and preferences.

Resume:
{json.dumps(resume_json, indent=2)}

Additional Details:
{additional_details}{location_line}

Return a JSON list of objects. Each object should have:
- keywords: string (e.g., "Software Engineer", "Project Manager", "Data Scientist")
- location: string (e.g., "Remote", "London", "United States", "New York")
- remote: string (one of: "onsite", "remote", "hybrid") - default to "remote" if not specified
- experienceLevel: string (one of: "internship", "entry", "associate", "mid_senior", "director", "executive") - infer from resume
- date_posted: string (one of: "month", "week", "day") - default to "week"
- limit: integer (number of results, default to 100)

Provide 3-5 diverse search queries that cover:
1. Different job titles/roles the user is qualified for based on their experience
2. Location preferences mentioned in their resume or additional details
3. Appropriate experience levels based on their career stage

You must respond with ONLY a JSON array, no other text. Example format:
[
  {{
    "keywords": "Software Engineer",
    "location": "Remote",
    "remote": "remote",
    "experienceLevel": "mid_senior",
    "date_posted": "week",
    "limit": 100
  }},
  {{
    "keywords": "Senior Developer",
    "location": "United States",
    "remote": "hybrid",
    "experienceLevel": "mid_senior",
    "date_posted": "week",
    "limit": 100
  }}
]"""

        # Try with primary key, then backup key
        api_keys = [
            ('primary', GEMINI_API_KEY),
            ('backup', BACKUP_GEMINI_API_KEY)
        ]

        for key_name, api_key in api_keys:
            if not api_key:
                if key_name == 'primary':
                    print("Warning: GEMINI_API_KEY not found, trying backup...")
                    continue
                else:
                    print("Warning: Both Gemini API keys not found. Cannot generate search parameters.")
                    return []
            
            try:
                client = genai.Client(api_key=api_key)
                
                # Apply rate limiting
                rate_limit()
                
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                
                response_text = response.text.strip()
                
                # Remove markdown code blocks if present
                cleaned = response_text.replace('```json', '').replace('```', '').strip()
                
                # Try to parse as JSON
                try:
                    search_params = json.loads(cleaned)
                    
                    # Validate it's a list
                    if not isinstance(search_params, list):
                        print(f"Warning: Expected JSON array, got {type(search_params)}. Skipping search parameter generation.")
                        return []
                    
                    # Validate each entry has required fields
                    validated_params = []
                    for param in search_params:
                        if isinstance(param, dict):
                            # Ensure all required fields are present with defaults
                            validated_param = {
                                'keywords': param.get('keywords', ''),
                                'location': param.get('location', ''),
                                'remote': param.get('remote', 'remote'),
                                'experienceLevel': param.get('experienceLevel', 'mid_senior'),
                                'date_posted': param.get('date_posted', 'week'),
                                'limit': param.get('limit', 100)
                            }
                            # Only add if keywords and location are provided
                            if validated_param['keywords'] and validated_param['location']:
                                validated_params.append(validated_param)
                    
                    if validated_params:
                        print(f"Generated {len(validated_params)} search parameter sets using {key_name} Gemini key.")
                        return validated_params
                    else:
                        print("Warning: No valid search parameters generated from LLM response.")
                        return []
                        
                except json.JSONDecodeError as e:
                    # Try to extract JSON from the response if it's wrapped in text
                    import re
                    json_match = re.search(r'\[.*\]', cleaned, re.DOTALL)
                    if json_match:
                        try:
                            search_params = json.loads(json_match.group(0))
                            if isinstance(search_params, list) and search_params:
                                print(f"Generated {len(search_params)} search parameter sets using {key_name} Gemini key.")
                                return search_params
                        except (json.JSONDecodeError, ValueError) as parse_error:
                            # Failed to parse extracted JSON, continue to next attempt
                            print(f"Warning: Failed to parse extracted JSON: {parse_error}")
                            pass
                    
                    if key_name == 'primary':
                        print(f"Error parsing JSON response from {key_name} key: {e}")
                        print("Trying backup key...")
                        continue
                    else:
                        print(f"Error parsing JSON response from {key_name} key: {e}")
                        return []
                
            except Exception as e:
                if key_name == 'primary':
                    print(f"Error with {key_name} Gemini key: {e}")
                    print("Trying backup key...")
                    continue
                else:
                    print(f"Error with {key_name} Gemini key: {e}")
                    return []
        
        # Both keys failed
        print("Warning: Failed to generate search parameters with both Gemini keys.")
        return []

    except Exception as e:
        print(f"Error generating search parameters: {e}")
        return []


def bulk_filter_jobs(job_titles: list[dict], resume_json: dict, max_retries: int = 3) -> dict:
    """
    Evaluate job titles against the resume and filter out poor fits.
    Also identifies generalizable skip keywords for future use.

    Args:
        job_titles: List of dicts with 'title' and 'company'
        resume_json: Resume data
        max_retries: Maximum retry attempts with exponential backoff

    Returns:
        Dict containing 'filtered_titles' (list) and 'new_filters' (dict)
    """
    import google.genai as genai

    user_name_val = get_user_name(resume_json)

    # Prepare the prompt
    prompt = f"""You are helping {user_name_val} filter job opportunities.

Resume JSON:
{json.dumps(resume_json, indent=2)}

Here are {len(job_titles)} job opportunities. 

CONTEXT:
We are building an iterative keyword-based filtering system to save costs on future searches. 
1. Identify specific job titles that are clearly NOT a good fit.
2. Identify generalizable "skip keywords" (substrings) for titles and company names that should ALWAYS be filtered out in the future.

CRITERIA FOR FILTERING:
1. Wrong technology stack or role requirements compared to the resume
2. Wrong role type (e.g., mismatch between desired level or functional area)
3. Wrong domain or industry that is clearly incompatible with the candidate's goals

JOB DATA (JSON):
{json.dumps(job_titles, indent=2)}

Respond with ONLY a JSON object in this exact format:
{{
  "filtered_titles": ["exact job title 1", "exact job title 2"],
  "new_filters": {{
    "job_title_skip_keywords": ["keyword1", "keyword2"],
    "company_skip_keywords": ["unwanted company 1"]
  }}
}}

If ALL jobs are good fits, return: {{"filtered_titles": [], "new_filters": {{"job_title_skip_keywords": [], "company_skip_keywords": []}}}}
"""

    # Try with primary key, then backup key
    api_keys = [
        ('primary', GEMINI_API_KEY),
        ('backup', BACKUP_GEMINI_API_KEY)
    ]

    for key_name, api_key in api_keys:
        if not api_key:
            if key_name == 'primary':
                print(f"  Warning: Primary Gemini API key not found, trying backup...")
                continue
            else:
                raise Exception("Both Gemini API keys not found")

        # Load settings
        model_name = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')

        # Exponential backoff retry logic for current key
        for attempt in range(max_retries):
            try:
                # Configure Gemini client
                client = genai.Client(api_key=api_key)

                # Call Gemini API with rate limiting
                from utils import rate_limit
                rate_limit()

                # Calculate tokens (rough estimation)
                # print(f"  Prompt tokens: {len(prompt) / 4}") 

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )

                # Parse response
                response_text = response.text.strip()
                # Clean markdown if present
                cleaned = response_text.replace('```json', '').replace('```', '').strip()
                result = json.loads(cleaned)

                filtered = result.get('filtered_titles', [])
                new_filters = result.get('new_filters', {})

                print(f"  Bulk filter ({key_name} key): {len(filtered)}/{len(job_titles)} jobs marked for filtering")
                if any(new_filters.values()):
                    print(f"  Discovered {sum(len(v) for v in new_filters.values())} new filter keywords")

                return result

            except Exception as e:
                error_str = str(e)

                # If rate limit on this key, try next key immediately
                if '429' in error_str or 'quota' in error_str.lower() or 'rate limit' in error_str.lower():
                    print(f"  Rate limit hit on {key_name} key, trying next key...")
                    break  # Break retry loop, move to next key

                # For other errors, retry with exponential backoff
                wait_time = (2 ** attempt) * random.uniform(1, 2)

                if attempt < max_retries - 1:
                    print(f"  Bulk filter attempt {attempt + 1} failed ({key_name} key): {e}")
                    print(f"  Retrying in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                else:
                    # Last attempt with this key failed
                    print(f"  All attempts failed with {key_name} key: {e}")
                    if key_name == 'backup':
                        # This was the last key, raise error
                        raise Exception(f"Bulk filtering failed after {max_retries} retries with both keys: {e}")
                    # Otherwise, break to try backup key
                    break

    # If we get here, both keys failed
    raise Exception("Bulk filtering failed with both primary and backup API keys")