# slab-cracker-frontend-admin

Admin frontend for **Slab Cracker** — a tool for identifying high-quality PSA 9 graded cards that are strong candidates for re-submission to achieve a PSA 10 grade.

## Mission

Buy smart, re-slab smarter. Slab Cracker helps collectors:

1. **Capture reference scans** of PSA 10 / BGS Black Label cards as the "perfect" baseline
2. **Analyze PSA 9 scans** by fetching official certification images from PSA
3. **Compare and rank** PSA 9 cards against known 10s using image similarity (Siamese Network / Contrastive Learning)
4. **Track common defects** (centering, edges, corners, surface) to filter out cards with hard-to-fix issues
5. **Decide** which PSA 9s are the best candidates for re-grading

## Architecture

```
Browser (Admin)
  |
  |-- Read (static JSON data)
  |     +-- GitHub Raw (FutureGadgetCollections/slab-cracker-data)
  |           +-- GCS fallback (slab-cracker-data bucket)
  |
  +-- Write (submit certs, trigger analysis)
        +-- Backend API (Cloud Run)
              |-- Firebase Auth token verified
              |-- PSA cert scans fetched & stored
              |-- Image comparison via ML model (Siamese Network)
              |-- Results written to BigQuery
              +-- Updated JSON published to GitHub + GCS
```

## Multi-Repo Setup

This is a **four-repo project**. All repos are siblings under the same parent directory:

```
FutureGadgetCollections/
  slab-cracker-frontend-admin/    <-- Admin frontend (this repo)
  slab-cracker-backend/           <-- Backend API + ML pipeline + Cloud Run jobs
  slab-cracker-frontend-public/   <-- Public frontend (read-only results, no auth)
  slab-cracker-data/              <-- JSON data files published by backend
```

Run `./setup.sh` after cloning this repo to clone all sibling repos.

## Tech Stack

- **[Hugo](https://gohugo.io/)** -- static site generator
- **Bootstrap 5** -- UI framework
- **Firebase Auth (JS SDK)** -- Google sign-in and ID token issuance
- **GitHub Pages** -- hosting (deployed via GitHub Actions)
- **GitHub Raw / GCS** -- static data sources for reads

## GCP Infrastructure

| Resource | Details |
|----------|---------|
| GCP Project | `slab-cracker` (separate project) |
| Cloud Run service (API) | `slab-cracker-api` -- `us-central1` |
| Cloud Run job (scan fetcher) | `psa-scan-fetcher` -- `us-central1` |
| Cloud Run job (image analysis) | `slab-analysis` -- `us-central1` |
| GCS bucket | `slab-cracker-data` -- card scans + JSON snapshots |
| BigQuery | dataset: `grading` (cert data, scores, defects) |
| Firebase project | `slab-cracker-auth` |

> Cross-project data: If pricing data from `collection-market-tracker` is needed, the slab-cracker service account will be granted read access to those BigQuery datasets.

## Local Development

1. Copy `.env.example` to `.env` and fill in your Firebase config and backend URL.
2. Start the dev server:

```bash
set -a && source .env && set +a && hugo server
```

3. Open [http://localhost:1313](http://localhost:1313) and sign in with an allowed email.

## Configuration

All configuration is supplied via `HUGO_PARAMS_*` environment variables at build/serve time. See `.env.example` for the full list.

### GitHub Actions Variables (non-sensitive)

| Variable | Purpose |
|----------|---------|
| `GITHUB_PAGES_URL` | Full URL of the GitHub Pages site |
| `HUGO_PARAMS_FIREBASE_AUTH_DOMAIN` | Firebase auth domain |
| `HUGO_PARAMS_FIREBASE_PROJECT_ID` | Firebase project ID |
| `HUGO_PARAMS_FIREBASE_STORAGE_BUCKET` | Firebase storage bucket |
| `HUGO_PARAMS_BACKENDURL` | Backend API base URL |
| `HUGO_PARAMS_ALLOWED_EMAILS` | Comma-separated list of admin emails |
| `HUGO_PARAMS_GCS_DATA_BUCKET` | GCS bucket for static data fallback |
| `HUGO_PARAMS_GITHUB_DATA_REPO` | GitHub repo for static data |

### GitHub Actions Secrets (sensitive)

| Secret | Purpose |
|--------|---------|
| `HUGO_PARAMS_FIREBASE_API_KEY` | Firebase API key |
| `HUGO_PARAMS_FIREBASE_APP_ID` | Firebase app ID |
| `HUGO_PARAMS_FIREBASE_MESSAGING_SENDER_ID` | Firebase messaging sender ID |
