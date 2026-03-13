# Cloud Run Deployment Cheat Sheet

## Project Info
- **GCP Project:** lunar-mercury-397321 (federal-register-forced-fee)
- **Region:** us-east1
- **Service:** federal-register-app
- **Live URL:** https://federal-register-app-996830241007.us-east1.run.app
- **Cloud SQL instance:** allotment-db (PostgreSQL 15, db-f1-micro)
- **Database:** allotment_research
- **DB user:** appuser / allotment-app-2026

## Auto-Deploy (CI/CD)
Pushes to `main` on `cwmmwc/federal-register-forced-fee` automatically build and deploy via Cloud Build.

```bash
git push origin main   # triggers auto-deploy
```

Check build status:
```bash
gcloud builds list --region=us-east1 --limit=5
gcloud builds log <BUILD_ID> --region=us-east1
```

## Manual Deploy
```bash
gcloud run deploy federal-register-app \
  --source . \
  --region us-east1 \
  --allow-unauthenticated
```

## View Logs
```bash
# Stream live logs
gcloud run services logs tail federal-register-app --region=us-east1

# Recent logs
gcloud run services logs read federal-register-app --region=us-east1 --limit=50
```

## Service Management
```bash
# Check service status
gcloud run services describe federal-register-app --region=us-east1

# List revisions
gcloud run revisions list --service=federal-register-app --region=us-east1

# Roll back to a previous revision
gcloud run services update-traffic federal-register-app \
  --to-revisions=<REVISION_NAME>=100 --region=us-east1
```

## Database Access
```bash
# Connect via Cloud SQL Auth Proxy (install: brew install cloud-sql-proxy)
cloud-sql-proxy lunar-mercury-397321:us-east1:allotment-db &
psql "host=127.0.0.1 dbname=allotment_research user=appuser password=allotment-app-2026"

# Or use gcloud
gcloud sql connect allotment-db --user=appuser --database=allotment_research
```

## Re-import Database
```bash
# Dump local DB
pg_dump -d allotment_research --no-owner --no-acl -f /tmp/allotment_research.sql

# Compress and upload
gzip -k /tmp/allotment_research.sql
gcloud storage buckets create gs://allotment-db-import-tmp --location=us-east1
gcloud storage cp /tmp/allotment_research.sql.gz gs://allotment-db-import-tmp/

# Grant access and import
SA=$(gcloud sql instances describe allotment-db --format='value(serviceAccountEmailAddress)')
gcloud storage buckets add-iam-policy-binding gs://allotment-db-import-tmp \
  --member="serviceAccount:$SA" --role=roles/storage.objectViewer
gcloud sql import sql allotment-db gs://allotment-db-import-tmp/allotment_research.sql.gz \
  --database=allotment_research --quiet

# Clean up
gcloud storage rm -r gs://allotment-db-import-tmp
```

## Environment Variables
Set on the Cloud Run service:
- `DATABASE_URL` — Cloud SQL connection string (via Unix socket)

Update env vars:
```bash
gcloud run services update federal-register-app --region=us-east1 \
  --set-env-vars "KEY=value"
```

## Costs
- **Cloud Run:** Free tier = 2M requests/month, 360K vCPU-seconds. Scales to zero.
- **Cloud SQL (db-f1-micro):** ~$9/month (always on). This is the main cost.
- **Cloud Build:** Free tier = 120 build-minutes/day.

## Console Links
- Cloud Run: https://console.cloud.google.com/run/detail/us-east1/federal-register-app?project=lunar-mercury-397321
- Cloud SQL: https://console.cloud.google.com/sql/instances/allotment-db?project=lunar-mercury-397321
- Cloud Build: https://console.cloud.google.com/cloud-build/builds?project=lunar-mercury-397321
