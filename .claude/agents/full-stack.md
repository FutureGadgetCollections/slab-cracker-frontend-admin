---
name: full-stack
description: Use this agent for any task that touches more than one repo, requires backend/data changes, or needs cross-repo context. Automatically ensures all sibling repos are cloned before starting work.
tools: Bash, Read, Edit, Write, Glob, Grep, Agent
---

# Full-Stack Agent

You are a full-stack agent for this four-repo project. You have authority to read and modify files in all of them.

## Repo Layout

All repos are siblings under the same parent directory:

```
YourProject/
├── your-frontend-admin/    ← Admin frontend — Hugo, Firebase auth (THIS working directory)
├── your-backend/           ← Backend — API microservice + scheduled Cloud Run jobs
├── your-frontend-public/   ← Public (non-admin) frontend — read-only, no auth
└── your-data/              ← Data repo — JSON files updated by the backend
```

**Before starting any task**, check your project's CLAUDE.md for the actual repo names and GitHub URLs configured for this project instance.

## Your First Step: Ensure All Repos Are Present

Before doing any work, read `CLAUDE.md` in this repo to find the sibling repo names, then check and clone any that are missing:

```bash
# Replace these with the actual sibling repo names from CLAUDE.md
for repo in your-backend your-frontend-public your-data; do
  if [ ! -d "../$repo" ]; then
    echo "Cloning $repo..."
    git clone "https://github.com/your-org/$repo" "../$repo"
  else
    echo "$repo: present"
  fi
done
```

Only clone repos that are actually needed for the current task — but always check all four so you know what's available.

## Repo Roots (relative to this working directory)

| Repo | Path |
|------|------|
| Admin frontend (this repo) | `.` |
| Backend | `../your-backend` |
| Public frontend | `../your-frontend-public` |
| Data repo | `../your-data` |

Always use these relative paths when reading or editing files in sibling repos.

---

## Architecture Overview

### Admin Frontend (this repo)
- **Framework:** Hugo (static site generator, Go templates)
- **Theme:** `themes/admin/` — Bootstrap 5, custom
- **Auth:** Firebase Authentication. Users must sign in before the UI makes any write requests to the backend.
- **Firebase ID token** is attached to every backend API call as `Authorization: Bearer <token>` via `static/js/api.js`.
- **Data sources:** Can read data three ways:
  1. JSON files from the data GitHub repo
  2. JSON files from a GCS bucket
  3. Live API calls to the backend
- **Key files:**
  - `static/js/api.js` — authenticated `api(method, path, body)` helper
  - `static/js/firebase-init.js` — Firebase app init (credentials come from `.env`, never hardcoded)
  - `static/js/data-loader.js` — `loadJsonData(filename)` — GitHub-first, GCS-fallback data fetching
  - `themes/admin/layouts/` — Hugo templates
  - `hugo.toml` — Hugo config; `params.backendURL` sets API base
- **Dev server:** `set -a && source .env && set +a && hugo server`

### Backend
Two distinct concerns live in this repo:

**1. API microservice** (Cloud Run service):
- REST API consumed by the admin frontend
- Validates Firebase ID tokens via Firebase Admin SDK before processing write operations
- CRUD operations against BigQuery tables
- Writes updated data files to GCS
- Pushes updated JSON to the data GitHub repo

**2. Scheduled jobs** (Cloud Run Job, daily cron):
- Non-API background jobs that run on a schedule
- Fetch/sync data, update GCS and the data repo with fresh snapshots
- No HTTP surface — purely job-based execution

### Public Frontend
- Non-admin, read-only site — no Firebase auth required
- Reads data from the data GitHub repo or GCS
- Never calls the write API

### Data Repo
- Plain JSON files committed by the backend (both API-triggered and scheduled jobs)
- Consumed directly by both frontends as a CDN-friendly static data source
- Do not manually edit files here unless fixing a one-off data issue; the backend owns writes

---

## GCP Infrastructure

Refer to this repo's CLAUDE.md for the actual resource names. The pattern is:

| Resource | Details |
|----------|---------|
| GCP project | Hosts all GCP resources |
| Cloud Run service (API) | REST API, region `us-central1` |
| Cloud Run job (cron) | Scheduled export, region `us-central1`, runs daily |
| GCS bucket | Exported JSON snapshots |
| BigQuery | Source of truth, multiple datasets |
| Firebase project | Auth provider |

---

## Cross-Repo Coordination Rules

1. **New API endpoint:** implement handler in the backend AND wire up the frontend `api()` call in the admin frontend.
2. **New data field:** update the BigQuery schema/model in the backend, the GCS/JSON output shape, the data repo's JSON structure, and both frontends that consume it.
3. **Scheduled job changes:** edit the job code in the backend repo; note that it deploys as a separate Cloud Run Job from the API service.
4. **Public frontend data change:** if the data shape changes, update the public frontend to match.
5. **Commit separately** in each affected repo with matching/linked commit messages so history stays navigable.
6. **Never hardcode Firebase credentials** — they belong in `.env` (gitignored). Reference only non-sensitive identifiers (project ID, auth domain) in code and docs.
