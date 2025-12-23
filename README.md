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


## If it looks like it 'doesn't open'
This app runs in the **system tray** (near the clock). Check hidden tray icons.
It also writes logs to `PingMonitor.log` next to the EXE.


## Configuration UI + CSV
Run the EXE, then right-click the tray icon → **Configure...**

### CSV format
Use either headers:

```
name,ip
Gate Controller,192.168.1.50
Camera Switch,192.168.1.20
```

Or no headers (first two columns are name,ip).
