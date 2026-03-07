# Indian Land Allotment Research

A Flask application for researching the history of Indian allotment land dispossession — from the allotment era through termination. Integrates three primary datasets: 239,845 BLM allotment patents, 10,976 Federal Register forced fee claims, and historical land surveys from the Wilson Report (1934) and Murray Memorandum (1958).

Built at the [Institute for Advanced Technology in the Humanities](https://www.iath.virginia.edu/), University of Virginia, as part of the [Indian Land Allotment Research](https://land-sales.iath.virginia.edu/) project.

## The Data

### Federal Register Claims (1983)
In 1983, the Bureau of Indian Affairs published two Federal Register notices listing Indian allotment claims. These documented allotments where fee patents had been issued without the allottee's consent ("forced fee patents"), as well as secretarial transfers.

- **9,649** forced fee patent claims
- **1,327** secretarial transfers
- ~7,110 linked to BLM patent records; ~2,539 unlinked

**The Federal Register is the sole authoritative source for forced fee counts.** The BLM `forced_fee` flag inflates numbers through one-to-many patent matching and must not be used for this purpose.

### BLM Allotment Patents
**239,845** General Land Office patent records from the Bureau of Land Management, covering trust patents, fee patents, and other allotment-related patents across all tribes.

### Wilson Report (1934)
The Wilson Report documented the state of **212 Indian reservations** as of 1934, when the Indian Reorganization Act ended general allotment. Records original reservation areas, allotments made, and **23.2 million acres alienated** through sales and fee patents — the cumulative land loss of the allotment era.

### Murray Memorandum (1947–1957)
The Murray Memorandum documented a second wave of land loss during the termination era. Across **52 BIA agencies**, individual Indian trust land fell from **15.9 million acres (1947) to 12.6 million (1957)** — a net loss of 3.3 million acres through 18,546 trust removal transactions.

## Features

### Search and Browse
- **Claims search** — Filter by allottee name, allotment number, tribe, claim type, date range. Server-side pagination.
- **Patent search** — Browse 239,845 BLM patents with filters for name, tribe, state, authority type, date.
- **Individual claim pages** — FR data, linked BLM patents, trust-to-fee conversion details, PLSS land descriptions.
- **Tribe landing pages** — Summary statistics, timeline charts, and sortable claims tables for each of 57 tribes.
- **CSV downloads** — Export filtered results for claims or patents.
- **GLO record links** — Direct links to BLM General Land Office patent images.

### Visualizations
- **Trust-to-Fee Conversion (Sankey)** — How patents moved between trust and fee status, with FR forced fee claims as a sub-flow. Wilson baseline and Murray termination-era cards per tribe.
- **All Patents Timeline** — Distribution of 239,845 patents by year, with forced fee toggle and Murray Memorandum overlay (acres removed from trust, 1948–1957).
- **1934 Reservation Baseline** — Wilson Report land composition charts, alienation rates vs. FR claims, and Murray termination-era comparison showing two waves of land loss.
- **Claims by Reservation** — Scatter and bar charts comparing fee patents vs. FR claims per tribe.
- **Forced Fee Timeline** — FR claims by year with policy era context.

## Requirements

- Python 3
- PostgreSQL with the `allotment_research` database
- Flask, psycopg2

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask psycopg2-binary
```

## Configuration

The database connection defaults to `dbname=allotment_research user=cwm6W`. Override with the `DATABASE_URL` environment variable:

```bash
export DATABASE_URL="dbname=allotment_research user=your_user host=localhost"
```

## Running

```bash
source venv/bin/activate
python3 app.py
```

The app runs on http://127.0.0.1:5001 by default.

## Database Tables

| Table | Rows | Description |
|-------|------|-------------|
| `federal_register_claims` | 10,976 | 1983 Federal Register forced fee claims and secretarial transfers |
| `blm_allotment_patents` | 239,845 | Full BLM patent mirror from ArcGIS |
| `forced_fee_patents_rails` | 17,560 | Hand-verified claim-to-patent linkages |
| `trust_fee_linkages` | 29,229 | Trust-to-fee patent conversion records |
| `wilson_table_vi` | 212 | Wilson Report 1934 reservation baseline data |
| `murray_comparative` | 52 | Murray Memorandum 1947 vs 1957 land by agency |
| `murray_transactions` | 520 | Murray trust removal transaction counts by agency and year |
| `murray_trust_removal` | 83 | Murray trust land removed by area office and year |
| `murray_agency_removal` | 41 | Murray total acres removed by agency |
| `murray_lands_acquired` | 23 | Federal lands acquired since 1930 |
| `parcels_patents_by_tribe` | 401,811 | PLSS legal land descriptions |
| `fee_patents` / `trust_patents` | 88,537 / 95,353 | Older BLM patent tables (legacy) |
