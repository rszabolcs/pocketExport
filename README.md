# Pocket Article Exporter

This toolset allows you to export your entire saved Pocket article collection before the service shuts down.

## Features

* 🔐 Authenticated access using cookies and consumer key
* 💾 All metadata from the Pocket API is stored
* 📁 Article content is fetched via GraphQL and stored in deep nested directories by ID
* 💥 Handles API rate limits (429), authorization failures (403), and transient errors (50x)
* 🧠 Persistent progress tracking in JSON file (`progress.json`)

## Requirements

* Python 3.11+
* Environment variables (in `.env`):

```env
POCKET_COOKIE="OptanonConsent=...; a_widget_t=..."
AUTH_BEARER=eyJ0e... (JWT-like token)
CONSUMER_KEY=94110-... (from Pocket developer site)
```

## Project Structure

* `get_access_token` — get Pocket API access token

## Usage

1. Populate `.env` with cookies and keys from your logged-in session
2. Run `get_access_token.py` first to obtain your Pocket API access token.
   This script will guide you through the authorization process in your browser.

## Note

This tool relies on Pocket's internal GraphQL API and is meant for personal archival purposes only. It may break without notice if the Pocket infrastructure changes.

---

## Disclaimer

This software is provided as-is, without any warranty, express or implied.
I take no responsibility and cannot be held liable for any damage, data loss, or other harm caused by the use, misuse, or malfunction of this software.
Use it entirely at your own risk.

This is a non-professional, quick-and-dirty solution written solely for myself and for fun, as a rapid response to the announcement that Pocket is shutting down.
It is not intended for production use or for others.
