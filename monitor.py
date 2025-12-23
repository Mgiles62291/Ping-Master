import json
import time
import subprocess
import threading
import smtplib
from email.message import EmailMessage
from pystray import Icon, Menu, MenuItem
from PIL import Image
import os
import sys

# Base directory works for both source run and PyInstaller onefile EXE
BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ICON_GREEN = os.path.join(BASE_DIR, "icons", "green.ico")
ICON_RED = os.path.join(BASE_DIR, "icons", "red.ico")

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def send_email(email_cfg: dict, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = email_cfg["from"]
    msg["To"] = email_cfg["to"]
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(email_cfg["smtp_server"], int(email_cfg["smtp_port"])) as server:
        server.starttls()
        server.login(email_cfg["from"], email_cfg["password"])
        server.send_message(msg)

def ping(host: str) -> bool:
    # Windows uses -n, others use -c
    param = "-n" if os.name == "nt" else "-c"
    result = subprocess.run(
        ["ping", param, "1", host],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0

def main():
    if not os.path.exists(CONFIG_FILE):
        # Friendly failure if user forgets config.json
        raise SystemExit(
            "Missing config.json next to the EXE/script.\n"
            "Copy config.example.json to config.json, then edit it."
        )

    config = load_config(CONFIG_FILE)
    devices = config.get("devices", {})
    check_interval = int(config.get("check_interval", 30))
    email_cfg = config.get("email", {})

    status = {}  # name -> bool (up/down)
    icon_holder = {"icon": None}

    def monitor_loop():
        while True:
            any_down = False

            for name, ip in devices.items():
                is_up = ping(ip)

                if name not in status:
                    status[name] = is_up
                else:
                    # DOWN transition
                    if status[name] and not is_up:
                        send_email(
                            email_cfg,
                            f"🚨 DOWN: {name}",
                            f"{name} ({ip}) is NOT responding to ping."
                        )
                    # UP transition
                    if (not status[name]) and is_up:
                        send_email(
                            email_cfg,
                            f"✅ UP: {name}",
                            f"{name} ({ip}) is responding again."
                        )
                    status[name] = is_up

                if not is_up:
                    any_down = True

            # Update tray icon
            try:
                icon_holder["icon"].icon = Image.open(ICON_RED if any_down else ICON_GREEN)
                icon_holder["icon"].title = "Ping Monitor (Issue)" if any_down else "Ping Monitor (OK)"
            except Exception:
                # Avoid crashing monitoring loop due to icon reload issues
                pass

            time.sleep(check_interval)

    def quit_app(icon, item):
        icon.stop()
        os._exit(0)

    def send_status_email(icon, item):
        lines = []
        for name, ip in devices.items():
            state = "UP" if status.get(name, False) else "DOWN"
            lines.append(f"{name} ({ip}): {state}")
        send_email(email_cfg, "📊 Ping Monitor Status", "\n".join(lines))

    menu = Menu(
        MenuItem("Send Status Email", send_status_email),
        MenuItem("Exit", quit_app)
    )

    tray_icon = Icon(
        "PingMonitor",
        Image.open(ICON_GREEN),
        "Ping Monitor (OK)",
        menu
    )
    icon_holder["icon"] = tray_icon

    threading.Thread(target=monitor_loop, daemon=True).start()
    tray_icon.run()

if __name__ == "__main__":
    main()
