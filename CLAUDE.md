# slab-cracker-frontend-admin

## Project Overview

Hugo-based admin frontend for **Slab Cracker** — identifies high-quality PSA 9 graded cards that are strong candidates for re-submission to achieve a PSA 10. Deployed to GitHub Pages; reads static JSON from the data repo and writes via the backend API.

## Mission

The goal is to help collectors buy PSA 9 cards that have the best chance of upgrading to a PSA 10 on re-submission. The system:

1. Fetches official PSA certification scans for a given cert number
2. Compares PSA 9 scans against reference PSA 10 / BGS Black Label scans using ML (Siamese Network / Contrastive Learning)
3. Ranks PSA 9s by similarity to known 10s
4. Tracks common defects (centering, edges, corners, surface) to filter out poor candidates
5. Provides a confidence score for re-submission success

## Multi-Repo Setup

Run `./setup.sh` after cloning this repo to clone all sibling repos to the correct local paths.

## All Repositories

| Repo | GitHub | Local Path | Purpose |
|------|--------|-----------|---------|
| Frontend admin (this repo) | `FutureGadgetCollections/slab-cracker-frontend-admin` | `.` | Hugo admin UI -- submit certs, view analysis results |
| Backend | `FutureGadgetCollections/slab-cracker-backend` | `../slab-cracker-backend` | API + ML pipeline + Cloud Run jobs |
| Public frontend | `FutureGadgetCollections/slab-cracker-frontend-public` | `../slab-cracker-frontend-public` | Read-only results viewer, no auth |
| Data files | `FutureGadgetCollections/slab-cracker-data` | `../slab-cracker-data` | JSON published by backend; read by frontends |

## GCP Infrastructure

| Resource | Details |
|----------|---------|
| GCP Project | `slab-cracker` (dedicated project, separate from collection-market-tracker) |
| Cloud Run service (API) | `slab-cracker-api` -- `us-central1` |
| Cloud Run job (scan fetcher) | `psa-scan-fetcher` -- `us-central1` -- fetches cert scans from PSA |
| Cloud Run job (analysis) | `slab-analysis` -- `us-central1` -- runs image comparison ML pipeline |
| GCS bucket (scans) | `slab-cracker-scans` -- stores fetched card images |
| GCS bucket (data) | `slab-cracker-data` -- exported JSON snapshots |
| BigQuery | Project `slab-cracker` -- dataset: `grading` |
| Firebase project | `slab-cracker-auth` (Google sign-in; config goes in `.env`, never committed) |

> **Cross-project access:** Grant the slab-cracker service account `roles/bigquery.dataViewer` on `future-gadget-labs-483502` datasets `catalog` and `market_data` for price lookups.

## Cross-Project Joins (collection-market-tracker)

Card identity `(game, set_code, card_number)` is intentionally aligned with the market tracker's `catalog.single_cards` table. This enables direct cross-project joins for price data:

```sql
-- Get market prices for scanned cards
SELECT cs.cert_number, cs.grade, cs.role, sc.name, sc.rarity, tp.market_price
FROM `slab-cracker.grading.cert_scans` cs
JOIN `future-gadget-labs-483502.catalog.single_cards` sc
  ON cs.game = sc.game AND cs.set_code = sc.set_code AND cs.card_number = sc.card_number
LEFT JOIN `future-gadget-labs-483502.market_data.latest_tcgplayer_prices` tp
  ON sc.tcgplayer_id = tp.tcgplayer_id
```

Additional aligned fields: `era`, `treatment`, `rarity`, `tcgplayer_id`.

## Architecture

- **Framework:** [Hugo](https://gohugo.io/) -- static site generator with Go templates
- **Theme:** Custom theme (`themes/admin/`) -- Bootstrap 5 layout
- **Auth:** Firebase Authentication -- Google sign-in; ID token attached to all backend requests
- **Backend communication:** `api()` helper in `static/js/api.js` handles token attachment automatically
- **Data reads:** Static JSON from GitHub Raw (`slab-cracker-data`) with GCS fallback, via `static/js/data-loader.js`
- **Deployment:** GitHub Pages via GitHub Actions (`.github/workflows/deploy.yml`)

## Backend Architecture (slab-cracker-backend)

The backend has three concerns:

1. **API microservice** -- Cloud Run service (`slab-cracker-api`): handles REST endpoints for submitting PSA cert numbers, managing reference cards, viewing analysis results. Reads/writes BigQuery `grading` dataset.

2. **PSA scan fetcher** -- Cloud Run job (`psa-scan-fetcher`): Given a PSA cert number, fetches the official front/back scans from PSA's certification verification. Stores images in GCS `slab-cracker-scans` bucket. Can be triggered by the API or run as a batch job.

3. **Image analysis pipeline** -- Cloud Run job (`slab-analysis`): Runs the ML comparison pipeline:
   - Loads reference PSA 10 scans for a given card
   - Loads the target PSA 9 scan
   - Runs through Siamese Network / Contrastive Learning model
   - Produces similarity scores and defect analysis
   - Writes results to BigQuery `grading.analysis_results`

## GCS Scan Storage Structure

Card scans are stored in `slab-cracker-scans` organized by card identity and grade:

```
slab-cracker-scans/
  {game}/
    {set_code}/
      {card_number}/
        psa_10/
          {cert_number}_front.jpg
          {cert_number}_back.jpg
        psa_9/
          {cert_number}_front.jpg
          {cert_number}_back.jpg
        bgs_9.5/
          ...
```

Example: `pokemon/sv01/006/psa_10/12345678_front.jpg`

- **Card identity** = `(game, set_code, card_number)` -- aligns with market tracker's `catalog.single_cards` PK
- **card_number** slashes are replaced with dashes in paths (e.g., `025/198` -> `025-198`)
- **Grade folder** = `{company}_{grade}` (e.g., `psa_10`, `bgs_9.5`, `cgc_9`) -- avoids ambiguity with card numbers and separates by grading company
- **cert_number** in filename ensures uniqueness and traceability
- Each cert has exactly 2 files: `{cert}_front.jpg` and `{cert}_back.jpg`

### Roles

Each cert scan has a role that determines how it's used:
- **reference** -- baseline 10s used for comparison (PSA 10, BGS Black Label)
- **sample** -- known 9s used to build the distribution of what a 9 looks like
- **candidate** -- a 9 you're considering purchasing, to be ranked against references and samples

## BigQuery Tables (Planned)

### grading dataset

| Table | Grain | Purpose |
|-------|-------|---------|
| `cert_scans` | `(cert_number)` | All cataloged certs. Columns: cert_number, game, era, set_code, card_number, card_name, rarity, treatment, grading_company, grade, role (reference/sample/candidate), tcgplayer_id, gcs_front_path, gcs_back_path, scan_status, submitted_at. Card identity `(game, set_code, card_number)` aligns with market tracker's `catalog.single_cards` for cross-project joins. |
| `analysis_results` | `(cert_number, reference_cert_number)` | Pairwise comparison results -- similarity score, defect breakdown (centering, edges, corners, surface) |
| `defect_patterns` | `(game, set_code, card_id, defect_type)` | Aggregated defect statistics per card -- what commonly prevents a 10 |
| `resubmission_candidates` | `(cert_number)` | View/materialized: ranked list of PSA 9s with highest re-grade probability |

## Key Files (This Repo)

| Path | Purpose |
|------|---------|
| `hugo.toml` | Hugo config -- `params.backendURL` sets the API base |
| `themes/admin/layouts/` | Hugo templates (baseof, list, index) |
| `themes/admin/layouts/partials/` | head, navbar, footer, scripts partials |
| `static/js/firebase-init.js` | Firebase app init + global `authSignOut()` |
| `static/js/api.js` | Authenticated `api(method, path, body)` helper |
| `static/js/app.js` | Global `showToast()` utility |
| `static/js/data-loader.js` | `loadJsonData(filename)` -- GitHub-first, GCS-fallback data fetching |
| `static/css/app.css` | Minimal style overrides on top of Bootstrap 5 |
| `content/` | Hugo content sections |
| `.env.example` | Template for Firebase + backend env vars |
| `setup.sh` | Clone all sibling repos |

## Auth Flow

1. User lands on the site and signs in via Firebase Auth (Google sign-in).
2. Firebase issues an ID token.
3. The frontend attaches the token as `Authorization: Bearer <token>` on all backend requests.
4. The backend validates the token via the Firebase Admin SDK before processing.
5. Access is further restricted to an allowlist of authorized emails (`ALLOWED_EMAILS`).

**Never hardcode Firebase credentials** -- they belong in `.env` (gitignored).

## Development Notes

- Hugo config lives in `hugo.toml`
- Firebase config goes in `.env` -- never commit this file (already in `.gitignore`)
- Environment variables are injected as `HUGO_PARAMS_*` and map to `.Site.Params.*` in templates
- Dev server: `set -a && source .env && set +a && hugo server`

## Cross-Repo Coordination Rules

1. **New API endpoint:** implement the handler in the backend AND wire up the `api()` call here.
2. **New data field:** update the BigQuery schema in the backend, the GCS/JSON output shape, the data repo's JSON structure, and both frontends that consume it.
3. **ML model changes:** update the analysis job in the backend repo; note it deploys as a separate Cloud Run Job.
4. **Public frontend data change:** if the data shape changes, update the public frontend to match.
5. **Commit separately** in each affected repo with matching/linked commit messages.
6. **Never hardcode Firebase credentials** -- use environment variables.

## Custom Agents

A `full-stack` sub-agent is defined in `.claude/agents/full-stack.md`. It:
- Checks all four sibling repos and clones any that are missing
- Has full context on every repo's role, data flow, and GCP infrastructure
- Handles tasks that span multiple repos simultaneously
