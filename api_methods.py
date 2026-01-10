import base64
import json
import os
import random
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

from utils import get_user_name

load_dotenv()

SERVER_URL = os.getenv("SERVER_URL")
EXTENSION_SECRET_KEY = os.getenv("API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BACKUP_GEMINI_API_KEY = os.getenv("BACKUP_GEMINI_API_KEY")

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

        # Decode JWT to get expiry (simple approach - subtract 60s for safety)
        # For production, consider using PyJWT library
        import base64
        payload = _jwt_token.split('.')[1]
        # Add padding if needed
        payload += '=' * (4 - len(payload) % 4)
        decoded = json.loads(base64.b64decode(payload))
        _token_expiry = decoded.get('exp', time.time() + 3600) - 60

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

    # Try primary key first
    for use_primary in [True, False]:
        try:
            current_key = GEMINI_API_KEY if use_primary else BACKUP_GEMINI_API_KEY
            key_name = "primary" if use_primary else "backup"

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
                print(f"Rate limit hit on {key_name} key")
                if not use_primary:  # This was the backup key (last attempt)
                    print("Both API keys rate limited. Skipping this operation.")
                    return None
                continue  # Try backup key

            # Handle other HTTP errors
            if not response.ok:
                error_msg = f"API request failed: {response.status_code} - {response.text}"
                print(f"ERROR: {error_msg}")
                return None

            # Success!
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Network error on {key_name} key: {e}")
            if not use_primary:  # This was the backup key (last attempt)
                raise Exception(f"Network error: {e}")
            continue  # Try backup key

    # Both keys failed with 429
    return None


# TODO: Add a fallback to the API call in case that resume json data isn't available
def get_resume_json() -> dict:
    """
    Read resume from resume_data.json and add additional details.
    """
    try:
        # Read the JSON file directly
        with open('./resume_data.json', 'r') as f:
            resume_data = json.load(f)

        # Add additional details to resume JSON
        try:
            with open('./additional details.txt', 'r') as f:
                additional_details = f.read()
            resume_data['additional_details'] = additional_details
        except FileNotFoundError:
            raise RuntimeError("additional_details.txt not found")

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

        payload = {
            "job_posting_text": job_details.get('job_description', ''),
            "job_specific_context": json.dumps(job_specific_context),
            "resume_json_data": json.dumps(resume_json),
            "model_name": "gemini-2.5-flash"
        }

        data = _make_api_request_with_fallback(
            f"{SERVER_URL}/analyze-job-posting",
            payload
        )

        if data is None:
            raise Exception("API request failed - skipping this operation")

        return data['job_analysis']

    except Exception as e:
        # Check if it's a rate limit error (non-critical)
        if "Rate limit exceeded" in str(e):
            raise Exception("Rate limit exceeded - 429 error")
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

    payload = {
        "job_posting_text": job_details.get('job_description', ''),
        "resume_json_data": json.dumps(resume_json),
        "filename": filename,
        "theme": "engineeringclassic",
        "model_name": "gemini-2.5-flash",
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

    payload = {
        "job_posting_text": job_details.get('job_description', ''),
        "job_specific_context": json.dumps(job_specific_context),
        "current_content": current_content,
        "retry_feedback": retry_feedback,
        "resume_json_data": json.dumps(resume_json),
        "model_name": "gemini-2.5-flash"
    }

    data = _make_api_request_with_fallback(
        f"{SERVER_URL}/generate-cover-letter",
        payload
    )

    if data is None:
        raise Exception("API request failed - skipping this operation")

    return data['content']


def bulk_filter_jobs(job_titles: list[str], resume_json: dict, max_retries: int = 3) -> list[str]:
    """
    Send batch of job titles to Gemini for bulk filtering.

    Args:
        job_titles: List of job titles to evaluate
        resume_json: Resume data
        max_retries: Maximum retry attempts with exponential backoff

    Returns:
        List of job titles that should be filtered out (Very poor fit)

    Raises:
        Exception: If all retries fail
    """
    import google.genai as genai

    user_name = get_user_name(resume_json)

    # Prepare the prompt
    prompt = f"""You are helping {user_name} filter job opportunities.

Resume JSON:
{json.dumps(resume_json, indent=2)}

Here are {len(job_titles)} job titles. Return ONLY the job titles that are clearly NOT a good fit based on:
1. Wrong technology stack (e.g., Java, React, .NET when candidate has Python/Django focus)
2. Wrong role type (e.g., Manager, Sales, Frontend when candidate wants Backend)
3. Wrong domain (e.g., Mobile, WordPress, Web Design)

Job Titles:
{chr(10).join(f"{i + 1}. {title}" for i, title in enumerate(job_titles))}

Respond with ONLY a JSON object in this exact format:
{{"filtered_titles": ["exact job title 1", "exact job title 2"]}}

If ALL jobs are good fits, return: {{"filtered_titles": []}}
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

        # Exponential backoff retry logic for current key
        for attempt in range(max_retries):
            try:
                # Configure Gemini client
                client = genai.Client(api_key=api_key)

                # Call Gemini API with rate limiting
                from utils import rate_limit
                rate_limit()

                response = client.models.generate_content(
                    model='gemini-2.0-flash-exp',
                    contents=prompt
                )

                # Parse response
                response_text = response.text.strip()
                # Clean markdown if present
                cleaned = response_text.replace('```json', '').replace('```', '').strip()
                result = json.loads(cleaned)

                filtered = result.get('filtered_titles', [])

                print(f"  Bulk filter ({key_name} key): {len(filtered)}/{len(job_titles)} jobs marked for filtering")
                return filtered

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