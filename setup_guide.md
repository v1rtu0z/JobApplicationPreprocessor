### Project Setup Guide for New Users

To set up the Job Application Preprocessor on a new machine, follow these steps:

#### 1. Environment Setup
*   **Python**: Ensure Python 3.10 or higher is installed.
*   **Dependencies**: Install the required Python libraries:
    ```bash
    pip install apify_client google-genai gspread html2text linkedin_scraper selenium python-dotenv google-auth-oauthlib google-api-python-client
    ```
*   **Browser & WebDriver**: Install Google Chrome and the corresponding `chromedriver` for Selenium operations.

#### 2. Configuration (`.env` file)
Create a `.env` file in the project root with the following keys:
*   `EMAIL_ADDRESS`: Your email address.
*   `GEMINI_API_KEY`: Your Google AI Studio API key.
*   `APIFY_API_TOKEN`: Your Apify API token.
*   `SERVER_URL`: The URL for the CV rendering server.
*   `CHECK_SUSTAINABILITY`: Set to `true` or `false` to toggle sustainability analysis.
*   `CRAWL_LINKEDIN`: Set to `false` if you are primarily using Apify for job collection.

#### 3. Google Cloud & Sheets Integration (Simplified!)
The project requires access to Google Sheets and Google Drive. You can use one of two methods:

**Method A: Service Account (Recommended for ease of use)**
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable the **Google Sheets API** and **Google Drive API**.
3. Navigate to **APIs & Services > Credentials**.
4. Click **Create Credentials > Service Account**.
5. After creating it, click on the service account email, go to the **Keys** tab, and **Add Key > Create new key (JSON)**.
6. Download the file and rename it to `service_account.json` in the project root.
7. **Crucial**: Open your Google Sheet and "Share" it with the service account email address (found in the JSON file).

**Method B: OAuth Desktop (Standard method)**
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Google Sheets API** and **Google Drive API**.
3. Navigate to **APIs & Services > Credentials**.
4. Click **Create Credentials > OAuth client ID** (Application type: **Desktop app**).
5. Download the JSON, rename it to `credentials.json` in the project root.
6. On the first run, a browser will open for you to authorize the app.

#### 4. Personalization Files
Customize these files to tailor the AI's analysis to your profile:
*   **`resume_data.json`**: Update with your structured education, experience, and skills.
*   **`additional details.txt`**: Add your career goals, salary expectations, location preferences, and any specific constraints.

#### 5. Verify Setup
Run the setup checker to ensure everything is configured correctly:
```bash
python check_setup.py
```
