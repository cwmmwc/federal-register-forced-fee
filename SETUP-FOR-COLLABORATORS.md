# Setup Instructions for Collaborators

## Prerequisites

- **Python 3** (3.10 or later recommended)
- **PostgreSQL** (14 or later recommended)
- **Git**

## 1. Clone the repo

```bash
git clone https://github.com/cwmmwc/federal-register-forced-fee.git
cd federal-register-forced-fee
```

## 2. Restore the database

You should have received the `allotment_research.sql` dump file separately (110MB — too large for the git repo).

```bash
createdb allotment_research
psql -d allotment_research < allotment_research.sql
```

Verify it worked:

```bash
psql -d allotment_research -c "SELECT count(*) FROM federal_register_claims;"
```

You should see 10,976 rows.

## 3. Set your database connection

If your PostgreSQL username is different from `cwm6W`, set the `DATABASE_URL` environment variable:

```bash
export DATABASE_URL="dbname=allotment_research user=YOUR_USERNAME"
```

Or to make it persistent, create a `.env` file (already in `.gitignore`):

```
DATABASE_URL=dbname=allotment_research user=YOUR_USERNAME
```

Then add this to the top of `app.py` if using `.env`:

```python
from dotenv import load_dotenv
load_dotenv()
```

And install python-dotenv: `pip install python-dotenv`

## 4. Create the Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask psycopg2-binary
```

## 5. Run the app

```bash
source venv/bin/activate
python3 app.py
```

Open http://127.0.0.1:5001/ in your browser.

## Key database tables

| Table | Rows | Description |
|-------|------|-------------|
| `federal_register_claims` | 10,976 | Claims from the 1983 Federal Register notices (9,649 forced fee + 1,327 secretarial transfers) |
| `forced_fee_patents_rails` | 17,560 | Hand-verified linkages between claims and BLM patents |
| `fee_patents` | 88,537 | BLM fee patent records |
| `trust_patents` | 95,353 | BLM trust patent records |
| `trust_fee_linkages` | 29,229 | Trust-to-fee patent conversion records |
| `parcels_patents_by_tribe` | 401,811 | PLSS legal land descriptions |
| `tribes` | 908 | Tribe name lookup |

## Troubleshooting

**Port 5001 is in use:**
```bash
lsof -ti:5001 | xargs kill
python3 app.py
```

**psycopg2 won't install:**
Try `pip install psycopg2-binary` instead of `psycopg2`. On some systems you may need `libpq-dev` or the PostgreSQL development headers.

**Database connection refused:**
Make sure PostgreSQL is running: `brew services start postgresql` (macOS) or `sudo systemctl start postgresql` (Linux).
