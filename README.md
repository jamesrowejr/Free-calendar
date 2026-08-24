# Free Calendar

Personal Savannah-area discovery service for free and unusually good-value events.

## Hosted architecture

Railway runs `python server.py`. The service:

- serves the calendar UI;
- stores canonical events in SQLite;
- seeds the database from `data/events.json`;
- checks configured sources automatically every 6 hours;
- extracts schema.org `Event` data where available;
- keeps source-health records;
- maintains a special-interest signal watchlist for easy-to-miss animal events such as births, birthdays, debuts, reveals, keeper talks and encounters.

Oatland Island is intentionally monitored through multiple independent sources: its official calendar, official news feed, Friends of Oatland events and Friends of Oatland animal updates. Facebook remains a secondary/redundant source rather than the primary Oatland feed.

## Railway persistence

The database location is controlled by `DATA_DIR`. Without a Railway Volume it defaults to `runtime_data/` inside the service filesystem. For durable storage across redeployments, mount a Railway Volume at `/data` and set:

```
DATA_DIR=/data
```

The app will then keep discoveries, source history and watchlist signals across code deployments.

## API

- `GET /api/health`
- `GET /api/events`
- `GET /api/sources`
- `GET /api/signals`
- `GET /api/status`
- `POST /api/discovery/run`

## Local development

```powershell
python server.py
```

Then open `http://127.0.0.1:8000`.
