# Federal Register Forced Fee App — Development Guide

## What This Is
Flask web app for researching Indian allotment land dispossession. Replaces a legacy PHP search at land-sales.iath.virginia.edu. Built at IATH, University of Virginia.

## Running
```bash
cd federal-register-app
source venv/bin/activate
python3 app.py  # runs on http://localhost:5001
```

## Stack
- **Backend:** Flask + psycopg2, Python 3
- **Database:** PostgreSQL `allotment_research` (local, user=cwm6W)
- **Frontend:** Bootstrap 5, jQuery, DataTables (server-side), Chart.js
- **Virtualenv:** `./venv/`

## Architecture
Single-file Flask app (`app.py`) with Jinja2 templates. No ORM — raw SQL with psycopg2. All tables use server-side DataTables pagination via JSON API endpoints.

### Two parallel sections

**Claims section** (original) — 10,976 Federal Register claims from two 1983 publications:
- `/` — Claims search (DataTables + filters)
- `/claim/<id>` — Claim detail with linked patents
- `/api/search` — JSON API for claims DataTables
- `/api/search/csv` — CSV download

**Patents section** (added March 2026) — 239,845 BLM allotment patents:
- `/patents` — Patent search (DataTables + filters for name/tribe/state/type/date)
- `/patent/<objectid>` — Patent detail with PLSS land description
- `/api/patents` — JSON API for patents DataTables
- `/api/patents/csv` — CSV download
- `/patents/timeline` — Stacked bar chart (fee vs trust, forced fee toggle)
- `/api/patents/timeline` — JSON API for timeline

**Map (integrated Leaflet SPA):**
- `/map` — Interactive allotment patent map (Leaflet + Esri Feature Service, standalone template)

**Other pages:**
- `/tribes` — Tribe list with claim counts
- `/tribe/<slug>` — Individual tribe page with timeline
- `/timeline` — Forced fee claims timeline (original)
- `/about` — About page

### Cross-links
- Claim detail → BLM patent: "View full BLM record" link (via accession_number lookup in blm_allotment_patents)
- Patent detail → Claim: alert banner linking to Federal Register claim (via forced_fee_patents_rails)

## Key Database Tables
See `DATABASE.md` for full schemas.

- `federal_register_claims` (10,976 rows) — FR claims. PK: id
- `forced_fee_patents_rails` (17,560 rows) — hand-verified claim-to-patent linkages from Rails admin
- `blm_allotment_patents` (239,845 rows) — full BLM patent mirror from ArcGIS. PK: objectid
- `fee_patents` (88,537) / `trust_patents` (95,353) — older BLM patent tables (still used for claim detail fallback)
- `trust_fee_linkages` (29,229) — trust→fee conversion records
- `parcels_patents_by_tribe` (401,811) — PLSS legal descriptions

### Claims → Patents join
```sql
LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
AND fr.allottee_name = ffp.fedreg_allottee
```

### Patent authority categories (defined in app.py)
- **FEE_AUTHORITIES:** Indian Fee Patent (and variants), Indian Homestead Fee Patent, Indian Trust to Fee
- **TRUST_AUTHORITIES:** Indian Trust Patent (and variants), Indian Allotment - General, Indian Partition, etc.
- **Forced fee:** See rule below — always use Federal Register claims, never BLM flag.

## RULE: Forced Fee Numbers Must Come From the Federal Register
The sole authoritative source for forced fee counts is the `federal_register_claims` table (9,649 forced fee claims, 1,327 secretarial transfers). NEVER use the BLM `forced_fee` flag (`WHERE forced_fee = 'True'`) to count or label forced fee patents. The BLM flag is inflated because the one-to-many join between FR claims and BLM patents marks BOTH trust and fee patents for the same allotment, roughly doubling the count. For example, Blackfeet: FR says 1,241 forced fee claims; BLM flag yields 2,886 — the latter is wrong.

When showing forced fee data:
- Count from `federal_register_claims` WHERE `claim_type ILIKE '%FORCED FEE%'`
- Label as "FR forced fee claims" (these are CLAIMS — a subset of all trust-to-fee conversions)
- Never say "forced fee patents" based on the BLM flag
- Never conflate FR claims with the total number of trust-to-fee conversions

## Templates
Most extend `base.html`. Navigation: Claims | Patents | Map | Tribes | Visualizations (dropdown) | About | Main Site.
Exception: `map.html` is standalone (does not extend `base.html`) — it has its own thin nav bar and full-viewport layout for the Leaflet map SPA. Map assets live in `static/map/js/` and `static/map/css/`.

## Patterns to Follow
- Server-side DataTables: route returns page HTML, `/api/` route returns JSON with draw/recordsTotal/recordsFiltered/data
- URL filter persistence: read from URL params on page load, update URL on search
- CSV export: same filters as search, streamed via `io.StringIO`
- Tribe slugs: `slugify()` / `unslugify_tribe()` in app.py
- GLO links: `glo_url(accession, doc_class)` builds glorecords.blm.gov URLs
- Allotment map: integrated at `/map` route, cross-linked with `url_for('allotment_map', tribe=..., accession=...)`

## Environment
- Main site: https://land-sales.iath.virginia.edu/
