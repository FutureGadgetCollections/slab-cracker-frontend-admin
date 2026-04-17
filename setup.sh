#!/usr/bin/env bash
# Clone all sibling repos for the slab-cracker project.
# Run from this repo's root directory.

set -euo pipefail

ORG="FutureGadgetCollections"
PARENT="$(cd "$(dirname "$0")/.." && pwd)"

repos=(
  "slab-cracker-backend"
  "slab-cracker-frontend"
  "slab-cracker-data"
  # slab-cracker-frontend-public is deprecated (superseded by slab-cracker-frontend)
  # and no longer cloned by default. Clone manually if needed for historical reference.
)

for repo in "${repos[@]}"; do
  target="$PARENT/$repo"
  if [ -d "$target" ]; then
    echo "$repo: already present, pulling latest..."
    git -C "$target" pull --ff-only 2>/dev/null || echo "  (pull skipped — may have local changes)"
  else
    echo "Cloning $repo..."
    git clone "https://github.com/$ORG/$repo" "$target"
  fi
done

echo ""
echo "All repos ready under $PARENT/"
