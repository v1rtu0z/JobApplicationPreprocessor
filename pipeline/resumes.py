"""Resume and cover letter generation/regeneration and local file cleanup."""

import utils
from api_methods import get_tailored_resume, get_tailored_cl


def delete_resume_local(resume_path: str):
    """Delete a resume from local storage."""
    if not resume_path:
        return
    from local_storage import delete_resume_local as delete_local
    delete_local(resume_path)


def process_cover_letter(sheet, row, resume_json) -> bool:
    """Process cover letter generation/regeneration for a job. Returns True if work was done."""
    job_url = row.get('Job URL', '')
    company_name = row.get('Company Name', '')
    job_title = row.get('Job Title', '')
    job_details = {
        'company_name': company_name,
        'job_title': job_title,
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
    }

    if row.get('CL feedback') and row.get('CL feedback addressed') != 'TRUE':
        print(f"Regenerating cover letter with feedback for: {job_title} @ {company_name}")
        try:
            current_cl = row.get('Tailored cover letter (to be humanized)', '')
            feedback = row.get('CL feedback')
            tailored_cl = get_tailored_cl(resume_json, job_details, current_cl, feedback)
            from local_storage import save_cover_letter_local, get_local_file_path
            from utils import get_user_name
            user_name = get_user_name(resume_json).replace(' ', '_')
            company_name_safe = company_name.replace(' ', '_')
            filename = get_local_file_path(user_name, company_name_safe, 'cover_letter')
            save_cover_letter_local(tailored_cl, filename)
            updates = {
                'Tailored cover letter (to be humanized)': tailored_cl,
                'CL feedback addressed': 'TRUE'
            }
            sheet.update_job_by_key(job_url, company_name, updates)
            print(f"Regenerated cover letter for: {job_title}")
            return True
        except Exception as e:
            error_str = str(e)
            if 'Rate limit' in error_str or '429' in error_str:
                utils.mark_gemini_rate_limit_hit()
                print(f"Gemini rate limit hit regenerating cover letter: {job_title} @ {company_name}")
            else:
                print(f"Error regenerating cover letter: {e}")
        return False

    if not row.get('Tailored cover letter (to be humanized)'):
        print(f"Generating cover letter for: {job_title} @ {company_name}")
        try:
            tailored_cl = get_tailored_cl(resume_json, job_details)
            from local_storage import save_cover_letter_local, get_local_file_path
            from utils import get_user_name
            user_name = get_user_name(resume_json).replace(' ', '_')
            company_name_safe = company_name.replace(' ', '_')
            filename = get_local_file_path(user_name, company_name_safe, 'cover_letter')
            save_cover_letter_local(tailored_cl, filename)
            sheet.update_job_by_key(job_url, company_name, {'Tailored cover letter (to be humanized)': tailored_cl})
            print(f"Generated cover letter for: {job_title}")
            return True
        except Exception as e:
            error_str = str(e)
            if 'Rate limit' in error_str or '429' in error_str:
                utils.mark_gemini_rate_limit_hit()
                print(f"Gemini rate limit hit generating cover letter: {job_title} @ {company_name}")
            else:
                print(f"Error generating cover letter: {e}")
    return False


def process_resume(sheet, row, resume_json) -> bool:
    """Process resume generation/regeneration for a job. Returns True if work was done."""
    job_url = row.get('Job URL', '')
    company_name = row.get('Company Name', '')
    job_title = row.get('Job Title', '')
    job_details = {
        'company_name': company_name,
        'job_title': job_title,
        'job_description': row.get('Job Description', ''),
        'location': row.get('Location', ''),
    }

    if row.get('Resume feedback') and row.get('Resume feedback addressed') != 'TRUE':
        print(f"Regenerating resume with feedback for: {job_title} @ {company_name}")
        try:
            current_resume_json = row.get('Tailored resume json', '')
            feedback = row.get('Resume feedback')
            tailored_json_str, filename, pdf_bytes = get_tailored_resume(
                resume_json, job_details, current_resume_json, feedback
            )
            from local_storage import save_resume_local
            resume_path = save_resume_local(pdf_bytes, filename)
            updates = {
                'Tailored resume url': resume_path,
                'Tailored resume json': tailored_json_str,
                'Resume feedback addressed': 'TRUE'
            }
            sheet.update_job_by_key(job_url, company_name, updates)
            print(f"Regenerated resume for: {job_title}")
            return True
        except Exception as e:
            error_str = str(e)
            if 'Rate limit' in error_str or '429' in error_str:
                utils.mark_gemini_rate_limit_hit()
                print(f"Gemini rate limit hit regenerating resume: {job_title} @ {company_name}")
            else:
                print(f"Error regenerating resume: {e}")
        return False

    if not row.get('Tailored resume url'):
        print(f"Generating tailored resume for: {job_title} @ {company_name}")
        try:
            tailored_json_str, filename, pdf_bytes = get_tailored_resume(resume_json, job_details)
            from local_storage import save_resume_local
            resume_path = save_resume_local(pdf_bytes, filename)
            updates = {
                'Tailored resume url': resume_path,
                'Tailored resume json': tailored_json_str
            }
            sheet.update_job_by_key(job_url, company_name, updates)
            print(f"Generated tailored resume for: {job_title}")
            return True
        except Exception as e:
            error_str = str(e)
            if 'Rate limit' in error_str or '429' in error_str:
                utils.mark_gemini_rate_limit_hit()
                print(f"Gemini rate limit hit generating resume: {job_title} @ {company_name}")
            else:
                print(f"Error generating tailored resume: {e}")
    return False


def process_resumes_and_cover_letters(sheet, resume_json, target_jobs=None):
    """Process resumes and cover letters for good fit jobs. Returns count processed."""
    print("\n" + "=" * 60)
    print("PROCESSING LOOP: Generating resumes and cover letters")
    print("=" * 60 + "\n")

    all_rows = sheet.get_all_records()
    processed_count = 0

    for row in all_rows:
        if not row.get('Job Title'):
            break

        job_url = row.get('Job URL', '').strip()
        company_name = row.get('Company Name', '').strip()

        if target_jobs is not None:
            if (job_url, company_name) not in target_jobs:
                continue

        fit_score = row.get('Fit score')
        if fit_score not in ['Good fit', 'Very good fit']:
            continue

        if row.get('Applied') == 'TRUE' or row.get('Bad analysis') == 'TRUE' or row.get('Job posting expired') == 'TRUE':
            resume_url = row.get('Tailored resume url')
            if resume_url:
                delete_resume_local(resume_url)
                sheet.update_job_by_key(job_url, company_name, {
                    'Tailored resume url': '',
                    'Tailored resume json': ''
                })
            continue

        cl_done = process_cover_letter(sheet, row, resume_json)
        resume_done = process_resume(sheet, row, resume_json)
        if cl_done or resume_done:
            processed_count += 1

    print(f"\nProcessing loop completed. Processed {processed_count} jobs.")
    return processed_count
