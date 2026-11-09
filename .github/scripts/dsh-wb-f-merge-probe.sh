#!/usr/bin/env bash
# F independent pre-merge experiment: zero remote writes, exact reviewed SHAs.
# Conflicts are expected evidence that separately green PRs are not integrated.
set -euo pipefail
A=5dc514c50d6ae89dcd0c606cea949dda9e0e53fc
B=704c86aaf9b2c5a9b9b4088648ccd0c50204f2f8
C=e9094bf5267ebc840ffae6bf3e8a707380ecaf7f
D=f0b7faeb22f9bf03d2487061a8f81a2776a5213d
E=bee612b2dd94a6040404db4b9a4a5fd816e136dd
git config user.name "WB-F Independent QA"
git config user.email "qa-bot@users.noreply.github.com"
git checkout --detach "$A"
git switch -c wb-f-synthetic-aggregate
for pair in "B:$B" "C:$C" "D:$D" "E:$E"; do
  name="${pair%%:*}"
  sha="${pair#*:}"
  echo "::group::F synthetic merge $name $sha"
  if git -c merge.renames=true merge --no-edit --no-ff "$sha"; then
    echo "F_MERGE_OK group=$name sha=$sha integration_head=$(git rev-parse HEAD)"
  else
    echo "::error::F_PREMERGE_CONFLICT group=$name sha=$sha"
    git diff --name-only --diff-filter=U
    git status --short
    git merge --abort || true
    exit 2
  fi
  echo "::endgroup::"
done
echo "F_SYNTHETIC_INTEGRATION_MERGE_ONLY head=$(git rev-parse HEAD); NOT REAL API/UI/R1 QA"
