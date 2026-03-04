# Quickstart — Getting Back to Work

## Where things are

- **Project directory:** `~/Documents/UVA/UVa 2025-26/federal-register-app`
- **GitHub repo:** https://github.com/cwmmwc/federal-register-forced-fee
- **Database:** `allotment_research` (local PostgreSQL, 10,976 claims)
- **Database dump:** `allotment_research.sql` (110MB, in the project directory)

## Start the app

```bash
cd ~/Documents/UVA/UVa\ 2025-26/federal-register-app
source venv/bin/activate
python3 app.py
```

Then open http://127.0.0.1:5001/ in your browser.

## If port 5001 is busy

```bash
lsof -ti:5001 | xargs kill
python3 app.py
```

## Resume Claude Code

```bash
cd ~/Documents/UVA/UVa\ 2025-26/federal-register-app
claude
```

Then type `/resume` to pick up the previous conversation.

## What's been built

- Search page with name/tribe/allotment/date/claim-type filters
- Individual claim pages with linked BLM patents, trust-fee conversions, PLSS parcels
- Tribe landing pages with stats, charts, sortable tables
- Timeline visualization
- About page with policy era context
- CSV downloads
- GLO record links (SER, MV, IF, STA, IA doc classes)
- 9,649 forced fee patent claims + 1,327 secretarial transfers imported

## What's still on the to-do list

- Fuzzy name search (trigram matching for spelling variants)
- Timeline policy-era vertical annotation lines (needs Chart.js annotation plugin)
- Wilson Report / Murray Memorandum cross-links
- Federal Register page image links
- Deployment to IATH server (Gunicorn/WSGI)
