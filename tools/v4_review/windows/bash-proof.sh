#!/usr/bin/env bash
# Real Git Bash, real builtins, disposable files. No profile and no network tools.
root=$1; sid=$2; port=$3; exe=$4
if [[ -z ${BASH_VERSION:-} ]]; then exit 65; fi
printf 'BASH_ALLOWED' > "$root/notes/bash-note.txt" || exit 66
IFS= read -r diagnostic < "$root/read/diagnostic.txt" || [[ -n "$diagnostic" ]] || exit 67
[[ "$diagnostic" == 'DIAGNOSTIC_FIXTURE' ]] || exit 68
printf '{"interpreter":"GIT_BASH","bash_version":"%s","permitted_read":true,"permitted_write":true' "$BASH_VERSION" > "$root/notes/bash-result.json"
for key in protected outside readonly_write traversal case junction; do
 case "$key" in
  protected) path="$root/protected/runtime-spine.db";;
  outside) path="$root/outside/outside.txt";;
  readonly_write) path="$root/read/diagnostic.txt";;
  traversal) path="$root/notes/../protected/runtime-spine.db";;
  case) path="${root^^}/OUTSIDE/OUTSIDE.TXT";;
  junction) path="$root/notes/escape/runtime-spine.db";;
 esac
 if (printf 'BASH_UNAUTHORIZED' > "$path"); then denied=false; else denied=true; fi
 printf ',"%s":{"denied":%s}' "$key" "$denied" >> "$root/notes/bash-result.json"
done
for key in protected outside; do
 if [[ "$key" == protected ]]; then path="$root/protected/runtime-spine.db"; else path="$root/outside/outside.txt"; fi
 secret=''
 if { IFS= read -r secret || [[ -n "$secret" ]]; } < "$path"; then denied=false; else denied=true; fi
 printf ',"%s_read":{"denied":%s}' "$key" "$denied" >> "$root/notes/bash-result.json"
done
printf '}\n' >> "$root/notes/bash-result.json"
"$exe" --attack "$root" "$sid" "$port" bash-descendant
