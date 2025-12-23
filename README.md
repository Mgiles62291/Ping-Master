# Ping Monitor Tray

Windows system tray app that pings devices and emails alerts when devices go down or come back online.

## Quick start (dev)
1. Install deps:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy config:
   ```bash
   copy config.example.json config.json
   ```
3. Run:
   ```bash
   python monitor.py
   ```

## Build (local)
```bash
pyinstaller --onefile --noconsole --add-data "config.json;." --add-data "icons;icons" monitor.py
```

## GitHub Releases (auto build)
This repo includes a GitHub Actions workflow that builds a Windows ZIP on release and attaches it to the GitHub Release assets.
