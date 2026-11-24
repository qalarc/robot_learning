#!/usr/bin/env bash
# Publish this repo to GitHub under the qalarc org, public, with teammates to follow.
#
#   bash scripts/publish_github.sh
#
# Needs a working `gh auth login` once (repo creation uses the API; pushes use SSH,
# which already works on this machine). Idempotent: skips steps already done.
set -e
cd "$(dirname "$0")/.."

ORG=qalarc
NAME=robot_learning
SLUG="$ORG/$NAME"

if ! gh auth status >/dev/null 2>&1; then
  echo "gh not authenticated — run:  gh auth login -h github.com   (then re-run this)" >&2
  exit 1
fi

if gh repo view "$SLUG" >/dev/null 2>&1; then
  echo "repo $SLUG exists"
else
  gh repo create "$SLUG" --public \
    --description "Robots that learn from their own runs and fail less — Alloy × OpenAI Physical AI Hackathon 2026" \
    --source . --remote origin --push
  echo "created + pushed $SLUG"
fi

git remote get-url origin >/dev/null 2>&1 || git remote add origin "git@github.com:$SLUG.git"
git push -u origin main
echo
echo "Share:    https://github.com/$SLUG"
echo "Add team: gh api -X PUT repos/$SLUG/collaborators/USERNAME -f permission=push"
