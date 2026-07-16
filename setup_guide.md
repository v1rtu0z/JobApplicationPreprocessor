### Project Setup Guide for New Users

To set up the Job Application Preprocessor on a new machine, follow these steps:

#### 1. Environment Setup
*   **Python**: Ensure Python 3.10 or higher is installed.
*   **Dependencies**: Install the required Python libraries:
    ```bash
    pip install -r requirements.txt
    ```
    Or manually:
    ```bash
    pip install flask apify_client google-genai html2text python-dotenv streamlit pandas PyYAML PyPDF2 pdfminer.six PyJWT
    ```

#### 2. Configuration (`.env` file)
Create a `.env` file in the project root with the following keys:
*   `GEMINI_API_KEY`: Your Google AI Studio API key.
*   `BACKUP_GEMINI_API_KEY`: (Optional) A backup Gemini API key for rate limit fallback.
*   `GEMINI_MODEL`: The Gemini model to use (default: `gemini-2.0-flash`).
*   `GEMINI_RPM`: (Optional) Max Gemini requests per minute; default `0` = unlimited. Set a positive value only if you need a local cap (free tier is typically ~5 RPM).
*   `GEMINI_RPD`: (Optional) Max Gemini requests per day (rolling 24h); default `0` = unlimited. Set a positive value only if you need a local cap (free tier is typically ~25 RPD).
*   `APIFY_API_TOKEN`: Your Apify API token.
*   `SERVER_URL` and `API_KEY`: Resume/cover-letter server URL and auth secret (set in `.env`; not shown in dashboard settings).
*   `CHECK_SUSTAINABILITY`: Set to `true` or `false` to toggle sustainability analysis.
*   `TELEGRAM_BOT_TOKEN`: (Optional) Bot token from [@BotFather](https://t.me/BotFather) (`/newbot`) — enables phone notifications when an application is ready.
*   `TELEGRAM_CHAT_ID`: (Optional) Your numeric Telegram user chat ID. Send `/start` to your bot after the app is running; the bot replies with your ID (use yours, not the bot's). Also stored in `local_data/telegram_chat_id.txt`.

**Telegram setup (optional):** Message @BotFather → `/newbot` → copy token into `TELEGRAM_BOT_TOKEN` → restart the app → open your bot in Telegram → `/start` → copy the chat ID into `TELEGRAM_CHAT_ID` (or rely on the auto-saved file). You can also edit these in the dashboard **Settings → App config (.env)** tab.

**Gemini API and rate limiting:** Job analysis is done locally in batches (one API call per several jobs) to reduce usage. Cover letter and resume tailoring still use the server (`SERVER_URL`). All Gemini-backed work goes through an optional local rate gate. By default there is **no local RPM/RPD cap** (the app relies on Google’s API quotas and key fallback). Set `GEMINI_RPM` / `GEMINI_RPD` only if you want an explicit local throttle.

#### 3. Local Storage
The project uses local SQLite storage for job data. All job information is stored in `local_data/jobs.db`. The directory structure is created automatically on first run:
- `local_data/jobs.db` - SQLite database with all job data
- `local_data/resumes/` - Generated tailored resumes (PDF)
- `local_data/cover_letters/` - Generated cover letters (TXT)

#### 4. Personalization Files
Customize these files to tailor the AI's analysis to your profile:
*   **`resume_data.json`**: Update with your structured education, experience, and skills. This is auto-generated from your PDF resume on first run if `RESUME_PDF_PATH` is set in `.env`.
*   **`additional_details.txt`**: Add your career goals, salary expectations, location preferences, and any specific constraints.
*   **`job_preferences.yaml`**: This file is automatically created on the first run using `job_preferences.yaml.example` as a template (or with defaults). You can edit it to customize job title skip keywords, location priorities, sustainability criteria, and cached search parameters. Duplicates are automatically removed when the file is saved.

#### 5. Verify Setup
Run the setup checker to ensure everything is configured correctly:
```bash
python check_setup.py
```

#### 6. Running the Application
*   **Main processor**: `python main.py` - Runs the job collection and analysis loop
*   **Dashboard**: `streamlit run dashboard.py` - Web UI to view and manage jobs

#### 7. Packaged app (exe)
When you run the application as a packaged executable (e.g. built with PyInstaller), or the first time you run `python main.py` without an existing configuration, a **setup page** opens in your browser. You do not need to create or edit a `.env` file by hand:

*   Enter your **Apify API token**, **Gemini API key**, **server URL**, **API key**, and **email address** in the form.
*   The setup page includes links to create an Apify account, create an Apify API key, and get a Gemini API key. Use these if you do not have keys yet.
*   **Apify free tier**: Apify gives $5 in free platform credits every month. The app uses Apify for LinkedIn job listings, job details, and company overviews. With $5 you can typically process on the order of thousands of job listings and hundreds of company/job-detail enrichments per month (exact numbers depend on Apify pricing). Check your usage in the Apify console so you are not surprised when the app pauses Apify after the monthly cap.
*   You can optionally attach your **resume (PDF)**, paste **additional details** text, and upload **job preferences (YAML)**. Use **Validate** to test your API keys before saving.
*   After you click **Save configuration**, the app writes a `.env` file and optional files to the application directory. You can then close the browser tab and run the application again (or it may continue automatically). No manual .env setup is required.
