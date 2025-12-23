# Ping Monitor Tray

Windows system tray app that pings devices and emails alerts when devices go down or come back online.

## Run (development)
```bash
pip install -r requirements.txt
copy config.example.json config.json
python monitor.py
```

## GitHub Releases
This repo includes a GitHub Actions workflow that builds a Windows ZIP on **Release → Published** and attaches it to the release assets.
