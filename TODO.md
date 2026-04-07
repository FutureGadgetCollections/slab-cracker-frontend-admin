# Slab Cracker -- TODO

## Completed: Project Scaffolding

- [x] Update README.md with project mission and architecture
- [x] Update CLAUDE.md with project-specific config
- [x] Update hugo.toml with project title
- [x] Create setup.sh for sibling repos
- [x] Create sibling GitHub repos (backend, frontend-public, data)
- [x] Initialize sibling repos with CLAUDE.md and basic structure
- [x] Create .mcp.json for GCP tooling
- [x] Update full-stack agent with slab-cracker repo names
- [x] Build admin frontend pages (Submit Cert, Reference Cards, Analysis, Defects, Candidates)
- [x] Update navbar with all section links
- [x] Update home page with dashboard and quick-action buttons
- [x] Update .env.example with slab-cracker data sources
- [x] Initialize backend repo with Go API stubs
- [x] Initialize public frontend repo with Hugo scaffold
- [x] Initialize data repo with placeholder JSON files
- [x] Save project context to Claude memory

## Completed: Core Infrastructure

- [x] Set up GCP project (`fg-tcglabs`)
- [x] Create GCS bucket (`slab-cracker-scans`)
- [x] Create BigQuery dataset `grading` with `cert_scans` table
- [x] Reuse Firebase project (`collection-showcase-auth`) for Google sign-in
- [x] Set up `.env` with Firebase credentials for local dev
- [x] Implement real backend: BQ insert, GCS upload, list/filter/stats queries
- [x] Add manual image upload to submit page (front/back scans)
- [x] Align card identity (game, set_code, card_number) with market tracker for cross-project BQ joins
- [x] Add era, treatment, rarity, tcgplayer_id fields
- [x] GCS path structure: `{game}/{set_code}/{card_number}/{company}_{grade}/{cert}_front.jpg`
- [ ] Create remaining BQ tables: `analysis_results`, `defect_patterns`
- [ ] Grant cross-project access to collection-market-tracker BigQuery if needed

## Next Up: First Card to Catalog

- [ ] Catalog test cert: PSA 116358889 -- Pokemon, Scarlet & Violet era, sv09, card #184
  - Blocked: PSA rate-limited our cert lookup attempts

## Phase 2: PSA Cert Auto-Lookup

- [ ] Research PSA cert verification page/API (psacard.com returns 403, API returns 429)
  - PSA blocks direct scraping; may need Playwright like the TCGPlayer scraper
  - Investigate if PSA has a public API with rate limits or if an API key is needed
  - Consider scraping with delays to avoid rate limiting
- [ ] Build auto-lookup: given a cert number, fetch card name, set, year, grade from PSA
- [ ] Auto-fill form fields from PSA lookup before user confirms and catalogs
- [ ] Fetch front/back scans from PSA if available

## Phase 3: Reference Card Management

- [ ] Build CRUD for reference cards (PSA 10s / BGS Black Labels)
  - [ ] Backend endpoints for `reference_cards` table
  - [ ] Admin frontend page to add/manage reference cards
- [ ] For each reference card, fetch and store the "perfect" scans
- [ ] Group references by card identity (set, card number, variant)

## Phase 4: Image Comparison ML Pipeline

- [ ] Research and select approach:
  - [ ] Siamese Network for pairwise similarity scoring
  - [ ] Contrastive Learning for embedding-based ranking
  - [ ] Consider pre-trained vision models (ResNet, EfficientNet) as backbone
- [ ] Build training pipeline:
  - [ ] Collect training pairs (PSA 10 vs PSA 9, PSA 10 vs PSA 10)
  - [ ] Data augmentation for card images
  - [ ] Train Siamese Network on card scan pairs
- [ ] Build inference pipeline (Cloud Run job `slab-analysis`):
  - [ ] Load target PSA 9 scan
  - [ ] Compare against all reference 10s for that card
  - [ ] Output similarity score (0-1)
  - [ ] Write results to `analysis_results` table
- [ ] Serve results via API for frontend display

## Phase 5: Defect Analysis

- [ ] Research card grading criteria (PSA grading scale breakdown):
  - [ ] Centering (front and back)
  - [ ] Corners (sharpness, whitening)
  - [ ] Edges (chipping, roughness)
  - [ ] Surface (scratches, print defects, holo issues)
- [ ] Build defect detection modules:
  - [ ] Centering analysis (measure border ratios -- can be algorithmic, not ML)
  - [ ] Edge/corner analysis (image segmentation)
  - [ ] Surface defect detection (anomaly detection)
- [ ] Aggregate defect patterns per card:
  - [ ] "For Pokemon Base Set Charizard, 72% of PSA 9s fail on centering"
  - [ ] Use this to filter: if a card's most common 9-defect is centering, and the target has bad centering, skip it
- [ ] Write defect stats to `defect_patterns` table

## Phase 6: Ranking and Decision Support

- [ ] Build `resubmission_candidates` view:
  - [ ] Rank PSA 9s by similarity to PSA 10 references
  - [ ] Factor in defect analysis (penalize known-bad defect patterns)
  - [ ] Include confidence score for re-grade success
- [ ] Admin frontend dashboard:
  - [ ] Submit cert number flow
  - [ ] View analysis results with visual comparison
  - [ ] Ranked candidate list with scores
  - [ ] Filter by card, defect type, confidence level
- [ ] Public frontend:
  - [ ] Read-only view of aggregated stats
  - [ ] Card-level defect pattern summaries

## Phase 7: Deployment and Operations

- [ ] Deploy backend API to Cloud Run
- [ ] Deploy scan fetcher as Cloud Run job
- [ ] Deploy analysis pipeline as Cloud Run job
- [ ] Set up Cloud Scheduler for batch analysis runs
- [ ] Deploy admin frontend to GitHub Pages
- [ ] Deploy public frontend to GitHub Pages
- [ ] Set up monitoring and alerting

## Future Ideas

- [ ] Support BGS/CGC/SGC cert lookups (not just PSA)
- [ ] Price integration: show market price of 9 vs 10, calculate ROI of re-grading
- [ ] Batch mode: scan an entire set's worth of 9s and rank them
- [ ] Community features: share analysis results, crowdsource defect tagging
- [ ] Historical accuracy tracking: did our predictions match actual re-grade results?
