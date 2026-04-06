# bq-cr-gcs-git-architecture-frontend-admin-template

A reusable template for Hugo-based admin frontends that follow the BigQuery / Cloud Run / GCS / Git architecture.

## Architecture

```
Browser
  │
  ├── Read (static JSON data)
  │     └── GitHub Raw (your-org/your-data-repo)
  │           └── GCS fallback (your-gcs-data-bucket)
  │
  └── Write (create, update, delete)
        └── Backend API (Cloud Run)
              ├── Firebase Auth token verified
              ├── Operation applied to BigQuery
              └── Updated JSON published to GitHub + GCS
```

**Reads** are served from static JSON files published by the backend after each mutation. The frontend fetches from GitHub first and falls back to GCS.

**Writes** go to the backend API, which handles the database operation and republishes the static data files to both GitHub and GCS.

## Tech Stack

- **[Hugo](https://gohugo.io/)** — static site generator
- **Bootstrap 5** — UI framework
- **Firebase Auth (JS SDK)** — Google sign-in and ID token issuance
- **GitHub Pages** — hosting (deployed via GitHub Actions)
- **GitHub Raw / GCS** — static data sources for reads

## Using This Template

1. Create a new repo from this template.
2. Update `hugo.toml`: set `title`, `description`, and your backend/data source defaults.
3. Add your sections under `content/` (follow the `items/` example).
4. Add nav links in `themes/admin/layouts/partials/navbar.html`.
5. Copy the `themes/admin/layouts/_default/list.html` pattern to build section-specific pages.
6. Set GitHub Actions secrets/variables (see Configuration below).
7. Enable GitHub Pages in repo settings (source: GitHub Actions).

## Local Development

1. Copy `.env.example` to `.env` and fill in your Firebase config and backend URL.
2. Start the dev server:

```bash
source .env && \
  HUGO_PARAMS_FIREBASE_API_KEY=$HUGO_PARAMS_FIREBASE_API_KEY \
  HUGO_PARAMS_FIREBASE_AUTH_DOMAIN=$HUGO_PARAMS_FIREBASE_AUTH_DOMAIN \
  HUGO_PARAMS_FIREBASE_PROJECT_ID=$HUGO_PARAMS_FIREBASE_PROJECT_ID \
  HUGO_PARAMS_FIREBASE_STORAGE_BUCKET=$HUGO_PARAMS_FIREBASE_STORAGE_BUCKET \
  HUGO_PARAMS_FIREBASE_MESSAGING_SENDER_ID=$HUGO_PARAMS_FIREBASE_MESSAGING_SENDER_ID \
  HUGO_PARAMS_FIREBASE_APP_ID=$HUGO_PARAMS_FIREBASE_APP_ID \
  HUGO_PARAMS_BACKENDURL=$HUGO_PARAMS_BACKENDURL \
  HUGO_PARAMS_ALLOWED_EMAILS=$HUGO_PARAMS_ALLOWED_EMAILS \
  hugo server --port 1313
```

3. Open [http://localhost:1313](http://localhost:1313) and sign in with an allowed email.

## Configuration

All configuration is supplied via `HUGO_PARAMS_*` environment variables at build/serve time. See `.env.example` for the full list.

### GitHub Actions Variables (non-sensitive)

| Variable | Purpose |
|----------|---------|
| `GITHUB_PAGES_URL` | Full URL of the GitHub Pages site (e.g. `https://your-org.github.io/your-repo/`) |
| `HUGO_PARAMS_FIREBASE_AUTH_DOMAIN` | Firebase auth domain |
| `HUGO_PARAMS_FIREBASE_PROJECT_ID` | Firebase project ID |
| `HUGO_PARAMS_FIREBASE_STORAGE_BUCKET` | Firebase storage bucket |
| `HUGO_PARAMS_BACKENDURL` | Backend API base URL |
| `HUGO_PARAMS_ALLOWED_EMAILS` | Comma-separated list of admin emails |
| `HUGO_PARAMS_GCS_DATA_BUCKET` | GCS bucket name for static data fallback |
| `HUGO_PARAMS_GITHUB_DATA_REPO` | GitHub repo for static data (e.g. `org/repo`) |

### GitHub Actions Secrets (sensitive)

| Secret | Purpose |
|--------|---------|
| `HUGO_PARAMS_FIREBASE_API_KEY` | Firebase API key |
| `HUGO_PARAMS_FIREBASE_APP_ID` | Firebase app ID |
| `HUGO_PARAMS_FIREBASE_MESSAGING_SENDER_ID` | Firebase messaging sender ID |

## Adding a New Section

1. Create the content directory:
   ```bash
   mkdir -p content/my-section
   echo $'---\ntitle: "My Section"\n---' > content/my-section/_index.md
   ```
2. Add a nav link in `themes/admin/layouts/partials/navbar.html`.
3. Optionally create a custom layout at `themes/admin/layouts/my-section/list.html` (or rely on the default).
4. Update the `RESOURCE_PATH` constant in the page scripts to match your backend endpoint.
