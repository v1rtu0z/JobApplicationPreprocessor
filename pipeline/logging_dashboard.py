"""Log capture and dashboard auto-launch."""

import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime

from .constants import ACTIVITY_LOG_PATH, DASHBOARD_LAUNCH_DELAY_SEC, DASHBOARD_URL


class _Tee:
    """Writes to both the original stream and the log file so the dashboard can show activity.

    Console output is unchanged. Complete lines written to the activity log are prefixed with a
    local timestamp so the dashboard Activity view is easier to read.
    """

    def __init__(self, stream, log_file):
        self._stream = stream
        self._file = log_file
        self._buf = ""

    def write(self, data):
        self._stream.write(data)
        self._stream.flush()
        if self._file is None or not data:
            return
        try:
            self._buf += data
            while True:
                nl = self._buf.find("\n")
                if nl < 0:
                    break
                line = self._buf[:nl]
                self._buf = self._buf[nl + 1 :]
                if line:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._file.write(f"[{ts}] {line}\n")
                else:
                    self._file.write("\n")
            self._file.flush()
        except OSError:
            pass

    def flush(self):
        self._stream.flush()
        if self._file is not None:
            try:
                if self._buf:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._file.write(f"[{ts}] {self._buf}")
                    self._buf = ""
                self._file.flush()
            except OSError:
                pass

    def isatty(self):
        return getattr(self._stream, "isatty", lambda: False)()


def _setup_log_capture():
    """Tee stdout and stderr to local_data/activity.log so the dashboard can display logs."""
    ACTIVITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_file = open(ACTIVITY_LOG_PATH, "a", encoding="utf-8")
    except OSError:
        return
    sys.stdout = _Tee(sys.__stdout__, log_file)
    sys.stderr = _Tee(sys.__stderr__, log_file)


def _has_jobs_to_show(db) -> bool:
    """Return True if the database has at least one job (so the dashboard has something to show)."""
    try:
        rows = db.get_all_records()
        return bool(rows) and any(row.get("Job Title") for row in rows)
    except Exception:
        return False


def _launch_dashboard_once(db, launched_flag: dict) -> None:
    """If there are jobs and the dashboard has not been launched yet, start Streamlit and open the browser."""
    if launched_flag.get("launched"):
        return
    if not _has_jobs_to_show(db):
        return
    launched_flag["launched"] = True
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dashboard_script = os.path.join(project_dir, "dashboard.py")
    if not os.path.isfile(dashboard_script):
        return
    try:
        subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", dashboard_script, "--server.headless", "true"],
            cwd=project_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(DASHBOARD_LAUNCH_DELAY_SEC)
        webbrowser.open(DASHBOARD_URL)
        print("\nDashboard opened in your browser. View and manage your job applications there.\n")
    except Exception as e:
        print(f"Could not auto-open dashboard: {e}. Run manually: streamlit run dashboard.py\n")
