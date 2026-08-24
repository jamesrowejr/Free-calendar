# Free Calendar

Personal Savannah-area free/low-cost event calendar.

## Railway

This repository is configured for Railway. Railway starts the app with `python server.py`; the server binds to `0.0.0.0` and reads the `PORT` environment variable automatically.

Health check: `/api/health`

## Local development

```powershell
python server.py
```

Then open `http://127.0.0.1:8000`.
