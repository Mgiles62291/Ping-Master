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
import traceback
import csv
import ipaddress

# ---------------------------
# Optional: Windows popup on fatal errors / setup prompts
# ---------------------------
def show_error_popup(title: str, message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass

# Base directory works for both source run and PyInstaller onefile EXE
BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CONFIG_EXAMPLE = os.path.join(BASE_DIR, "config.example.json")
LOG_FILE = os.path.join(BASE_DIR, "PingMonitor.log")

# ---------------------------
# Logging
# ---------------------------
def log(msg: str) -> None:
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass

# ---------------------------
# Config + shared state
# ---------------------------
state_lock = threading.Lock()
devices = {}         # name -> ip
email_cfg = {}       # email settings dict
check_interval = 30  # seconds

def load_config_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config_file(cfg: dict) -> None:
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_FILE)

def ensure_config_exists() -> None:
    if os.path.exists(CONFIG_FILE):
        return
    if os.path.exists(CONFIG_EXAMPLE):
        try:
            with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as fsrc:
                data = fsrc.read()
            with open(CONFIG_FILE, "w", encoding="utf-8") as fdst:
                fdst.write(data)
            log("Created config.json from config.example.json")
        except Exception as e:
            log(f"Failed to create config.json: {e}")
            raise

def reload_config() -> None:
    global devices, email_cfg, check_interval
    cfg = load_config_file(CONFIG_FILE)

    new_devices = cfg.get("devices", {}) or {}
    new_email = cfg.get("email", {}) or {}
    new_interval = int(cfg.get("check_interval", 30))

    with state_lock:
        devices = dict(new_devices)
        email_cfg = dict(new_email)
        check_interval = max(5, new_interval)

# ---------------------------
# Email + ping
# ---------------------------
def send_email(subject: str, body: str) -> None:
    cfg = None
    with state_lock:
        cfg = dict(email_cfg)

    msg = EmailMessage()
    msg["From"] = cfg.get("from", "")
    msg["To"] = cfg.get("to", "")
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(cfg["smtp_server"], int(cfg["smtp_port"])) as server:
        server.starttls()
        server.login(cfg["from"], cfg["password"])
        server.send_message(msg)

def ping(host: str) -> bool:
    param = "-n" if os.name == "nt" else "-c"
    result = subprocess.run(
        ["ping", param, "1", host],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0

# ---------------------------
# Tray icons (generated in-memory)
# ---------------------------
def make_status_icon(rgb):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    cx, cy, r = 32, 32, 28
    for y in range(64):
        for x in range(64):
            dx, dy = x - cx, y - cy
            if dx*dx + dy*dy <= r*r:
                img.putpixel((x, y), (*rgb, 255))
    return img

ICON_OK = make_status_icon((0, 180, 0))
ICON_BAD = make_status_icon((200, 0, 0))

# ---------------------------
# CSV helpers
# ---------------------------
def _normalize_header(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "").replace("_", "")

def load_devices_from_csv(csv_path: str) -> dict:
    """
    Supports CSV with headers like:
      name,ip
      device,ipaddress
    Or no headers: first two columns treated as name,ip.
    """
    result = {}
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        sniffer = csv.Sniffer()
        sample = f.read(2048)
        f.seek(0)
        has_header = False
        try:
            has_header = sniffer.has_header(sample)
        except Exception:
            has_header = False

        if has_header:
            reader = csv.DictReader(f)
            # Find best columns
            field_map = {_normalize_header(k): k for k in (reader.fieldnames or [])}
            name_key = field_map.get("name") or field_map.get("device") or field_map.get("devicename")
            ip_key = field_map.get("ip") or field_map.get("ipaddress") or field_map.get("address")
            if not name_key or not ip_key:
                raise ValueError("CSV header must include name + ip columns (e.g., name,ip).")
            for row in reader:
                name = (row.get(name_key) or "").strip()
                ip = (row.get(ip_key) or "").strip()
                if not name or not ip:
                    continue
                # Validate IP
                ipaddress.ip_address(ip)
                result[name] = ip
        else:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 2:
                    continue
                name = (row[0] or "").strip()
                ip = (row[1] or "").strip()
                if not name or not ip:
                    continue
                ipaddress.ip_address(ip)
                result[name] = ip
    return result

def export_devices_to_csv(csv_path: str, devs: dict) -> None:
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "ip"])
        for name, ip in sorted(devs.items(), key=lambda x: x[0].lower()):
            writer.writerow([name, ip])

# ---------------------------
# Config UI (Tkinter)
# ---------------------------
def open_config_ui():
    """
    Opens a configuration window to manage devices + email settings.
    Allows import/export devices via CSV.
    """
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except Exception as e:
        show_error_popup("Ping Monitor", f"Failed to open UI (tkinter missing):\n{e}")
        return

    # Pull current config snapshot
    with state_lock:
        dev_snapshot = dict(devices)
        email_snapshot = dict(email_cfg)
        interval_snapshot = int(check_interval)

    root = tk.Tk()
    root.title("Ping Monitor - Configuration")
    root.geometry("820x560")

    # --- Top: interval + email settings ---
    top = ttk.Frame(root, padding=10)
    top.pack(fill="x")

    ttk.Label(top, text="Check interval (seconds):").grid(row=0, column=0, sticky="w")
    interval_var = tk.StringVar(value=str(interval_snapshot))
    ttk.Entry(top, textvariable=interval_var, width=10).grid(row=0, column=1, sticky="w", padx=(6, 20))

    # Email fields
    fields = [
        ("From", "from"),
        ("To", "to"),
        ("SMTP Server", "smtp_server"),
        ("SMTP Port", "smtp_port"),
        ("Password", "password"),
    ]
    email_vars = {}
    for i, (label, key) in enumerate(fields, start=0):
        r = 1 + (i // 2)
        c = (i % 2) * 3
        ttk.Label(top, text=label + ":").grid(row=r, column=c, sticky="w", pady=2)
        var = tk.StringVar(value=str(email_snapshot.get(key, "")))
        email_vars[key] = var
        ent = ttk.Entry(top, textvariable=var, width=32, show="*" if key == "password" else "")
        ent.grid(row=r, column=c + 1, sticky="w", padx=(6, 20), pady=2)

    # --- Middle: devices table ---
    mid = ttk.Frame(root, padding=(10, 0, 10, 10))
    mid.pack(fill="both", expand=True)

    ttk.Label(mid, text="Devices (name + IP):").pack(anchor="w")

    cols = ("name", "ip")
    tree = ttk.Treeview(mid, columns=cols, show="headings", height=12)
    tree.heading("name", text="Name")
    tree.heading("ip", text="IP Address")
    tree.column("name", width=360)
    tree.column("ip", width=200)
    tree.pack(fill="both", expand=True, pady=(6, 8))

    # Populate
    for n, ip in sorted(dev_snapshot.items(), key=lambda x: x[0].lower()):
        tree.insert("", "end", values=(n, ip))

    # Buttons row
    btns = ttk.Frame(mid)
    btns.pack(fill="x")

    def selected_item():
        sel = tree.selection()
        return sel[0] if sel else None

    def add_device():
        dlg = tk.Toplevel(root)
        dlg.title("Add Device")
        dlg.geometry("420x160")
        dlg.transient(root)
        dlg.grab_set()

        name_var = tk.StringVar()
        ip_var = tk.StringVar()

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Name:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=name_var, width=40).grid(row=0, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(frm, text="IP:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=ip_var, width=40).grid(row=1, column=1, sticky="w", padx=6, pady=6)

        def ok():
            name = name_var.get().strip()
            ip = ip_var.get().strip()
            if not name or not ip:
                messagebox.showerror("Error", "Name and IP are required.")
                return
            try:
                ipaddress.ip_address(ip)
            except Exception:
                messagebox.showerror("Error", "Invalid IP address.")
                return
            tree.insert("", "end", values=(name, ip))
            dlg.destroy()

        ttk.Button(frm, text="Add", command=ok).grid(row=2, column=1, sticky="e", pady=10)

    def edit_device():
        item = selected_item()
        if not item:
            messagebox.showinfo("Edit", "Select a device to edit.")
            return
        cur_name, cur_ip = tree.item(item, "values")

        dlg = tk.Toplevel(root)
        dlg.title("Edit Device")
        dlg.geometry("420x160")
        dlg.transient(root)
        dlg.grab_set()

        name_var = tk.StringVar(value=cur_name)
        ip_var = tk.StringVar(value=cur_ip)

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Name:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=name_var, width=40).grid(row=0, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(frm, text="IP:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=ip_var, width=40).grid(row=1, column=1, sticky="w", padx=6, pady=6)

        def ok():
            name = name_var.get().strip()
            ip = ip_var.get().strip()
            if not name or not ip:
                messagebox.showerror("Error", "Name and IP are required.")
                return
            try:
                ipaddress.ip_address(ip)
            except Exception:
                messagebox.showerror("Error", "Invalid IP address.")
                return
            tree.item(item, values=(name, ip))
            dlg.destroy()

        ttk.Button(frm, text="Save", command=ok).grid(row=2, column=1, sticky="e", pady=10)

    def remove_device():
        item = selected_item()
        if not item:
            messagebox.showinfo("Remove", "Select a device to remove.")
            return
        tree.delete(item)

    def import_csv():
        path = filedialog.askopenfilename(
            title="Import devices from CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            devs = load_devices_from_csv(path)
        except Exception as e:
            messagebox.showerror("Import failed", str(e))
            return

        # Replace table contents
        for child in tree.get_children():
            tree.delete(child)
        for n, ip in sorted(devs.items(), key=lambda x: x[0].lower()):
            tree.insert("", "end", values=(n, ip))
        messagebox.showinfo("Import", f"Imported {len(devs)} devices.")

    def export_csv():
        path = filedialog.asksaveasfilename(
            title="Export devices to CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return
        devs = {}
        for child in tree.get_children():
            n, ip = tree.item(child, "values")
            devs[str(n)] = str(ip)
        try:
            export_devices_to_csv(path, devs)
            messagebox.showinfo("Export", "CSV exported successfully.")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def save_all():
        # Build devices dict from table
        devs = {}
        for child in tree.get_children():
            n, ip = tree.item(child, "values")
            n = str(n).strip()
            ip = str(ip).strip()
            if not n or not ip:
                continue
            try:
                ipaddress.ip_address(ip)
            except Exception:
                messagebox.showerror("Error", f"Invalid IP for {n}: {ip}")
                return
            devs[n] = ip

        # Interval
        try:
            interval = int(interval_var.get().strip())
            if interval < 5:
                raise ValueError()
        except Exception:
            messagebox.showerror("Error", "Check interval must be an integer >= 5.")
            return

        new_email = {k: v.get().strip() for k, v in email_vars.items()}

        cfg = {
            "check_interval": interval,
            "email": new_email,
            "devices": devs
        }

        try:
            save_config_file(cfg)
            reload_config()  # apply immediately
            messagebox.showinfo("Saved", "Configuration saved.\n\nChanges apply immediately.")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    # Buttons layout
    ttk.Button(btns, text="Add", command=add_device).pack(side="left")
    ttk.Button(btns, text="Edit", command=edit_device).pack(side="left", padx=6)
    ttk.Button(btns, text="Remove", command=remove_device).pack(side="left", padx=6)

    ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=10)

    ttk.Button(btns, text="Import CSV", command=import_csv).pack(side="left")
    ttk.Button(btns, text="Export CSV", command=export_csv).pack(side="left", padx=6)

    ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=10)

    ttk.Button(btns, text="Save Config", command=save_all).pack(side="right")

    root.mainloop()

# ---------------------------
# Main monitoring app
# ---------------------------
def main():
    log("=== PingMonitor starting ===")
    log(f"Base dir: {BASE_DIR}")

    ensure_config_exists()

    if not os.path.exists(CONFIG_FILE):
        show_error_popup(
            "Ping Monitor setup",
            "config.json is missing.\n\n"
            "I created it from config.example.json.\n\n"
            "Click OK to open the Configuration window."
        )
        open_config_ui()
        return

    reload_config()

    with state_lock:
        if not devices:
            show_error_popup(
                "Ping Monitor setup",
                "No devices found in config.json.\n\nClick OK to open Configuration."
            )
            open_config_ui()

    status = {}  # name -> bool (up/down)
    icon_holder = {"icon": None}

    def monitor_loop():
        while True:
            # Snapshot config for this cycle
            with state_lock:
                devs = dict(devices)
                interval = int(check_interval)

            any_down = False

            for name, ip in devs.items():
                is_up = ping(ip)

                if name not in status:
                    status[name] = is_up
                else:
                    if status[name] and not is_up:
                        try:
                            send_email(
                                f"🚨 DOWN: {name}",
                                f"{name} ({ip}) is NOT responding to ping."
                            )
                            log(f"DOWN email sent: {name} {ip}")
                        except Exception as e:
                            log(f"Email send failed (DOWN): {e}")
                    if (not status[name]) and is_up:
                        try:
                            send_email(
                                f"✅ UP: {name}",
                                f"{name} ({ip}) is responding again."
                            )
                            log(f"UP email sent: {name} {ip}")
                        except Exception as e:
                            log(f"Email send failed (UP): {e}")
                    status[name] = is_up

                if not is_up:
                    any_down = True

            try:
                icon_holder["icon"].icon = ICON_BAD if any_down else ICON_OK
                icon_holder["icon"].title = "Ping Monitor (Issue)" if any_down else "Ping Monitor (OK)"
            except Exception as e:
                log(f"Tray update failed: {e}")

            time.sleep(interval)

    def quit_app(icon, item):
        log("Exiting by tray menu.")
        icon.stop()
        os._exit(0)

    def send_status_email(icon, item):
        with state_lock:
            devs = dict(devices)

        lines = []
        for name, ip in devs.items():
            state = "UP" if status.get(name, False) else "DOWN"
            lines.append(f"{name} ({ip}): {state}")
        try:
            send_email("📊 Ping Monitor Status", "\n".join(lines))
            log("Status email sent.")
        except Exception as e:
            log(f"Status email failed: {e}")
            show_error_popup("Ping Monitor", f"Failed to send status email.\n\n{e}")

    def open_log(icon, item):
        try:
            if os.path.exists(LOG_FILE):
                os.startfile(LOG_FILE)  # Windows
            else:
                show_error_popup("Ping Monitor", "Log file not found yet.")
        except Exception as e:
            log(f"Open log failed: {e}")

    def open_config(icon, item):
        threading.Thread(target=open_config_ui, daemon=True).start()

    menu = Menu(
        MenuItem("Configure...", open_config),
        MenuItem("Send Status Email", send_status_email),
        MenuItem("Open Log", open_log),
        MenuItem("Exit", quit_app),
    )

    tray_icon = Icon(
        "PingMonitor",
        ICON_OK,
        "Ping Monitor (OK)",
        menu
    )
    icon_holder["icon"] = tray_icon

    threading.Thread(target=monitor_loop, daemon=True).start()
    tray_icon.run()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        tb = traceback.format_exc()
        log("FATAL ERROR:\n" + tb)
        show_error_popup("Ping Monitor crashed", f"{e}\n\nDetails were written to:\n{LOG_FILE}")
        raise
