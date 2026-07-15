#!/usr/bin/env python3
"""Install a systemd user service to run the pipeline on boot."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "job-application-preprocessor.service"


def main() -> int:
    if sys.platform != "linux":
        print("This installer supports Linux (systemd user services) only.")
        return 1

    root = Path(__file__).resolve().parents[1]
    venv_python = root / ".venv" / "bin" / "python"
    python_exec = venv_python if venv_python.is_file() else Path(sys.executable)

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / SERVICE_NAME

    env_file = root / ".env"
    env_line = f"EnvironmentFile={env_file}\n" if env_file.is_file() else ""

    unit_content = f"""[Unit]
Description=Job Application Preprocessor pipeline
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={python_exec} {root / "main.py"}
Restart=on-failure
RestartSec=30
TimeoutStopSec=30
KillMode=control-group
{env_line}Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""

    unit_path.write_text(unit_content, encoding="utf-8")
    print(f"Wrote {unit_path}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE_NAME], check=True)

    uid = os.getuid()
    print("\nService enabled and started.")
    print(f"  Status:  systemctl --user status {SERVICE_NAME}")
    print(f"  Logs:    journalctl --user -u {SERVICE_NAME} -f")
    print(f"  Stop:    systemctl --user stop {SERVICE_NAME}")
    print(f"  Disable: systemctl --user disable {SERVICE_NAME}")
    print(
        "\nFor boot without logging in, run once (requires sudo):\n"
        f"  sudo loginctl enable-linger {uid}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
