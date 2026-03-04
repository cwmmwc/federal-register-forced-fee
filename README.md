# Federal Register Claims Search

A Flask application for searching and browsing forced fee patent claims and secretarial transfers published in the Federal Register on March 31 and November 7, 1983. Built to replace the PHP search interface at [land-sales.iath.virginia.edu](https://land-sales.iath.virginia.edu/).

Part of the [Indian Land Allotment Research](https://land-sales.iath.virginia.edu/) project at the [Institute for Advanced Technology in the Humanities](https://iath.virginia.edu/), University of Virginia.

## The Data

In 1983, the Bureau of Indian Affairs published two Federal Register notices listing Indian allotment claims filed with the government. These notices documented allotments where fee patents had been issued without the allottee's consent ("forced fee patents"), as well as secretarial transfers.

The dataset contains **10,976 claims**:
- **9,649** forced fee patent claims
- **1,327** secretarial transfers

Of the forced fee patent claims, approximately **7,110** have been linked to BLM patent records in the General Land Office database. The remaining ~2,539 claims have not yet been matched to patent records.

## Features

- **Individual claim pages** — Each claim has its own page showing Federal Register data, linked BLM patents, trust-to-fee conversion details, and PLSS land descriptions
- **Tribe landing pages** — Summary statistics, timeline charts, and sortable/filterable claims tables for each of the 57 tribes in the dataset
- **Search and filter** — Search by allottee name, allotment number, tribe, claim type, and patent date range with server-side pagination
- **Timeline visualization** — Distribution of forced fee patents by year, filterable by tribe, with policy era context
- **CSV downloads** — Export filtered search results or per-tribe datasets
- **GLO record links** — Direct links to Bureau of Land Management General Land Office patent records
- **About page** — Historical context explaining forced fee patents, policy eras, and dataset limitations

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
| `federal_register_claims` | 10,976 | Primary claims from the 1983 Federal Register notices |
| `forced_fee_patents_rails` | 17,560 | Denormalized patent-to-claim linkages |
| `fee_patents` | 88,537 | BLM fee patent records |
| `trust_patents` | 95,353 | BLM trust patent records |
| `trust_fee_linkages` | 29,229 | Trust-to-fee patent conversion records |
| `parcels_patents_by_tribe` | 401,811 | PLSS legal land descriptions |
| `tribes` | 908 | Tribe name lookup |
