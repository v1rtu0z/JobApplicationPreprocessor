"""Dashboard constants and configuration."""
from pathlib import Path

# Auto-refresh and pagination
AUTO_REFRESH_INTERVAL = 60  # seconds
PAGE_SIZE = 25  # Fixed page size for pagination
UNDO_POPUP_TIMEOUT = 8  # seconds - auto-hide undo popup after this time

# Activity log (must match main.py ACTIVITY_LOG_PATH)
ACTIVITY_LOG_PATH = Path("local_data") / "activity.log"
ACTIVITY_LOG_TAIL_LINES = 500
ACTIVITY_AUTO_REFRESH_SEC = 5

# PDF preview cache
MAX_PDF_CACHE_SIZE = 10
