#!/usr/bin/env bash
# One-time RC7.2 GitHub Actions queue cleanup outside GitHub Actions runners.
# Requires a GitHub Codespace token with Actions: write for this repository.
set -euo pipefail
repo="TongAITech/opencode-test-digital-employee"
log="/tmp/rc72-ci-cancel.log"
exec > >(tee -a "$log") 2>&1
echo "=== RC7.2 CI queue rescue ==="
echo "Repository: $repo"
echo "Scope: work/rc7.2 and work/rc7.2-* ONLY (never RC8 or main)"
if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: GitHub CLI is unavailable in this Codespace"; exit 2
fi
if ! gh auth status -h github.com >/dev/null 2>&1; then
  echo "ERROR: Codespace GitHub auth unavailable"; exit 2
fi
tempdir="$(mktemp -d)"
trap 'rm -rf "$tempdir"' EXIT
get_active() {
  local target="$1" status
  : > "$target"
  for status in queued pending waiting requested in_progress; do
    echo "Scanning status: $status"
    if ! gh api --paginate "repos/$repo/actions/runs?status=$status&per_page=100" --jq '.workflow_runs[] | select((.head_branch // "") | test("^work/rc7\\.2($|-)")) | .id' >> "$target"; then
      echo "ERROR: API listing failed for status $status"; return 1
    fi
  done
  sort -nu -o "$target" "$target"
}
get_active "$tempdir/initial"
initial="$(wc -l < "$tempdir/initial" | tr -d ' ')"
echo "Initial RC7.2 active runs: $initial"
if [[ "$initial" == 0 ]]; then
  echo "Nothing to cancel."; exit 0
fi
accepted=0
errors=0
while IFS= read -r runid; do
  [[ -n "$runid" ]] || continue
  if gh api --method POST "repos/$repo/actions/runs/$runid/cancel" >/dev/null; then
    accepted=$((accepted+1))
    echo "Cancellation accepted: $runid"
  else
    errors=$((errors+1))
    echo "WARNING: cancellation request failed: $runid"
  fi
done < "$tempdir/initial"
echo "Initial cancellation accepted: $accepted; errors: $errors"
sleep 15
get_active "$tempdir/still_active"
remaining="$(wc -l < "$tempdir/still_active" | tr -d ' ')"
echo "Still active after grace period: $remaining"
if [[ "$remaining" -gt 0 ]]; then
  echo "Attempting official force-cancel endpoint for runs still active..."
  while IFS= read -r runid; do
    [[ -n "$runid" ]] || continue
    if gh api --method POST "repos/$repo/actions/runs/$runid/force-cancel" >/dev/null; then
      echo "Force cancellation accepted: $runid"
    else
      echo "WARNING: force cancellation failed: $runid"
    fi
  done < "$tempdir/still_active"
  sleep 8
fi
get_active "$tempdir/final"
final="$(wc -l < "$tempdir/final" | tr -d ' ')"
echo "=== FINAL ==="
echo "Active at start: $initial"
echo "Cancellation accepted: $accepted"
echo "Active still remaining: $final"
echo "Log saved at: $log"
if [[ "$final" -gt 0 ]]; then
  echo "Some workflow runs remain active. GitHub may have an API-side stuck queue; contact GitHub Support if force-cancel fails."
  exit 1
fi
echo "RC7.2 CI queue is clear as of the final API check."
