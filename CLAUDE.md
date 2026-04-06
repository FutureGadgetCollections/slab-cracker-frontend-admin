# bq-cr-gcs-git-architecture-frontend-admin-template

## Project Overview

This is the **admin frontend** in the BigQuery / Cloud Run / GCS / Git four-repo architecture — a Hugo-based site that lets authorized users browse and manage data via a Firebase-authenticated UI.

This template is the admin frontend component of a four-repo project. All four repos work together and should be cloned as siblings under the same parent directory.

## Repository Structure

This is a **four-repo project**. All repos should be cloned as siblings under the same parent directory:

```
YourProject/
├── your-frontend-admin/    ← Admin frontend — Hugo, Firebase auth (this repo)
├── your-backend/           ← Backend — REST API + scheduled Cloud Run jobs
├── your-frontend-public/   ← Public (non-admin) frontend — read-only, no auth
└── your-data/              ← Data repo — JSON files auto-updated by the backend
```

| Repo | Role |
|------|------|
| `your-frontend-admin` | Admin frontend — authenticated CRUD UI (this repo) |
| `your-backend` | REST API microservice + scheduled jobs |
| `your-frontend-public` | Public frontend — read-only, no auth |
| `your-data` | Static JSON data files committed by the backend |

## Architecture

### This Repo — Admin Frontend
- **Framework:** [Hugo](https://gohugo.io/) — static site generator with Go templates
- **Theme:** Custom theme (`themes/admin/`) — minimal Bootstrap 5 layout
- **Auth:** Firebase Authentication. Users must sign in before the UI sends any write requests.
- **Data sources:** The admin frontend can read data three ways:
  1. JSON files from the data GitHub repo (primary)
  2. JSON files from a GCS bucket (fallback)
  3. Live API calls to the backend (for writes and immediate reads)
- **Backend communication:** All write requests include a Firebase ID token as `Authorization: Bearer <token>`. The `api()` helper in `static/js/api.js` handles token attachment automatically.

### Backend
Two concerns in one repo:
1. **API microservice** — REST API consumed by this admin frontend; validates Firebase tokens; reads/writes BigQuery; updates GCS and the data repo
2. **Scheduled jobs** — Cloud Run Jobs (no HTTP surface) that run on a schedule to sync/update data

### Public Frontend
- Read-only, no Firebase auth
- Reads from the data repo or GCS only — never calls the write API

### Data Repo
- Plain JSON files committed by the backend (API-triggered or scheduled)
- Do not manually edit; the backend owns writes here

## GCP Infrastructure

Update these placeholders with your actual resource names:

| Resource | Placeholder | Details |
|----------|-------------|---------|
| GCP project | `your-gcp-project` | The project hosting all GCP resources |
| Cloud Run service | `your-api-service`, `us-central1` | REST API |
| Cloud Run job | `your-data-sync-job`, `us-central1` | Daily scheduled export |
| GCS bucket | `your-data-bucket` | Exported JSON snapshots |
| BigQuery | dataset: `your_dataset` | Source of truth |
| Firebase project | `your-firebase-project` | Auth provider |

## Key Files (This Repo)

| Path | Purpose |
|------|---------|
| `hugo.toml` | Hugo config — `params.backendURL` sets the API base |
| `themes/admin/layouts/` | Hugo templates (baseof, list, index) |
| `themes/admin/layouts/partials/` | head, navbar, footer, scripts partials |
| `static/js/firebase-init.js` | Firebase app init + global `authSignOut()` |
| `static/js/api.js` | Authenticated `api(method, path, body)` helper |
| `static/js/app.js` | Global `showToast()` utility |
| `static/js/data-loader.js` | `loadJsonData(filename)` — GitHub-first, GCS-fallback data fetching |
| `static/css/app.css` | Minimal style overrides on top of Bootstrap 5 |
| `content/items/_index.md` | Example section — copy to add new sections |
| `.env.example` | Template for Firebase + backend env vars |

## Auth Flow

1. User lands on the site and signs in via Firebase Auth (Google sign-in or email/password).
2. Firebase issues an ID token.
3. The frontend attaches the token as `Authorization: Bearer <token>` on all backend requests.
4. The backend validates the token via the Firebase Admin SDK before processing write operations.
5. Access is further restricted to an allowlist of authorized emails (`ALLOWED_EMAILS`), enforced on both frontend and backend.

**Never hardcode Firebase credentials** — they belong in `.env` (gitignored). Reference only non-sensitive identifiers (project ID, auth domain) in code and docs.

## Development Notes

- Hugo config lives in `hugo.toml`
- Firebase config goes in `.env` — never commit this file (already in `.gitignore`)
- Environment variables are injected as `HUGO_PARAMS_*` and map to `.Site.Params.*` in templates
- To add a new CRUD section: create `content/<section>/_index.md`, add a nav link in `navbar.html`, and optionally add `themes/admin/layouts/<section>/list.html`
- The default `list.html` provides a working CRUD template — update `RESOURCE_PATH` to your backend endpoint

## Running the Dev Server

**Always** source `.env` first — Hugo does not auto-read `.env` files:

```bash
set -a && source .env && set +a && hugo server
```

## Cross-Repo Coordination Rules

1. **New API endpoint:** implement the handler in the backend AND wire up the `api()` call here.
2. **New data field:** update the BigQuery schema/model in the backend, the GCS/JSON output shape, the data repo's JSON structure, and both frontends that consume it.
3. **Scheduled job changes:** edit the job code in the backend repo; note that it deploys as a separate Cloud Run Job from the API service.
4. **Public frontend data change:** if the data shape changes, update the public frontend to match.
5. **Commit separately** in each affected repo with matching/linked commit messages so history stays navigable.
6. **Never hardcode Firebase credentials** — use environment variables. Reference only non-sensitive identifiers in code and docs.

## Custom Agents

A `full-stack` sub-agent is defined in `.claude/agents/full-stack.md`. It:
- Checks all four sibling repos and clones any that are missing
- Has full context on every repo's role, data flow, and GCP infrastructure
- Handles tasks that span multiple repos simultaneously

Claude Code will invoke it automatically for cross-repo tasks, or you can ask for it explicitly.
