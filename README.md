# Ping Monitor Tray (No Icons)

Windows system tray app that pings devices and emails alerts when devices go down or come back online.

This version **does not use any icon files** — the tray icon is generated in-memory.

## Run (development)
```bash
pip install -r requirements.txt
copy config.example.json config.json
python monitor.py
```

## GitHub Releases
A GitHub Actions workflow builds a Windows ZIP on **Release → Published** and attaches it to the release assets.
