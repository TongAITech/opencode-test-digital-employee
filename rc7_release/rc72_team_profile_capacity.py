"""R4-07 safe 32-member capacity application to a CLONED DSH profile.

DO NOT mutate the protected bank web profile, append a duplicate plugin row,
or pass a partial --patch entry: DSH patch replacement drops the other config
keys. Only edit an unambiguous YAML block already belonging to the real
NanmiCoder AgentTeams plugin in the isolated, attested runtime clone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from rc7_runtime.rc72_agentteams_capacity import NANMICODER_PLUGIN, TeamCapacityPolicy
from . import dsh_plugins, dsh_runtime_profile


class TeamProfileCapacityError(RuntimeError):
    pass


_ROW = re.compile(r"^( *)(?:- )id: ['\"]?agent-teams['\"]?(?:[ \t]*#.*)?$")
_FIELD = re.compile(r"^( *)config:[ \t]*(?:#.*)?$")
_NAME = re.compile(r"^( *)name:[ \t]*['\"]@nanmicoder/dsh-agent-teams['\"](?:[ \t]*#.*)?$")
_MEMBER = re.compile(r"^( *)(maxMembers):[ \t]*([0-9]+)([ \t]*(?:#.*)?)$")


def _digest(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _rewrite_exact_agentteams_row(source: str, members: int) -> str:
    """Whitespace-preserving safe edit; never reserialize a credentialled YAML."""
    if not isinstance(source, str) or len(source) > 2_000_000 or "\t" in source:
        raise TeamProfileCapacityError("R4_PROFILE_PATCH_UNSAFE_FORMAT")
    if not source or "\r" in source:
        raise TeamProfileCapacityError("R4_PROFILE_PATCH_UNSAFE_LINE_ENDING")
    lines = source.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines)
            if _ROW.fullmatch(line.rstrip("\n"))]
    if len(hits) != 1:
        raise TeamProfileCapacityError("R4_PROFILE_AGENTTEAMS_ROW_NOT_UNIQUE")
    i = hits[0]
    indent = len(lines[i]) - len(lines[i].lstrip(" "))
    end = len(lines)
    for n in range(i + 1, len(lines)):
        stripped = lines[n].strip()
        if not stripped or stripped.startswith("#"):
            continue
        spaces = len(lines[n]) - len(lines[n].lstrip(" "))
        if spaces <= indent:
            end = n
            break
    # Bind the ID to the exact installed plugin rather than a same-ID impostor.
    names = [j for j in range(i + 1, end)
             if lines[j].lstrip().startswith('name:')
             and len(lines[j]) - len(lines[j].lstrip(' ')) == indent + 2]
    if len(names) != 1 or not _NAME.fullmatch(lines[names[0]].rstrip("\n")):
        raise TeamProfileCapacityError("R4_PROFILE_AGENTTEAMS_NAME_NOT_APPROVED")
    config = [j for j in range(i + 1, end)
              if lines[j].lstrip().startswith("config:")
              and len(lines[j]) - len(lines[j].lstrip(" ")) == indent + 2]
    if len(config) > 1:
        raise TeamProfileCapacityError("R4_PROFILE_PLUGIN_CONFIG_AMBIGUOUS")
    if config and not _FIELD.fullmatch(lines[config[0]].rstrip("\n")):
        raise TeamProfileCapacityError("R4_PROFILE_PLUGIN_CONFIG_INLINE_OR_DYNAMIC")
    if not config:
        # Preserve every previous plugin row/key, including model/provider,
        # role grants and custom tool policy. Only add this one scalar.
        lines.insert(i + 1, (" " * (indent + 2)) + "config:\n" +
                     (" " * (indent + 4)) + f"maxMembers: {members}\n")
        return "".join(lines)
    c = config[0]
    next_field = end
    for j in range(c + 1, end):
        stripped = lines[j].strip()
        if not stripped or stripped.startswith("#"):
            continue
        spaces = len(lines[j]) - len(lines[j].lstrip(" "))
        if spaces <= indent + 2:
            next_field = j
            break
    member_lines = []
    for j in range(c + 1, next_field):
        if lines[j].lstrip().startswith("maxMembers:"):
            member_lines.append(j)
    if len(member_lines) > 1:
        raise TeamProfileCapacityError("R4_PROFILE_MEMBER_FIELD_DUPLICATED")
    if member_lines:
        j = member_lines[0]
        match = _MEMBER.fullmatch(lines[j].rstrip("\n"))
        if not match or len(match.group(1)) != indent + 4:
            raise TeamProfileCapacityError("R4_PROFILE_MEMBER_FIELD_NOT_PLAIN_INTEGER")
        if int(match.group(3)) < 1:
            raise TeamProfileCapacityError("R4_PROFILE_MEMBER_CAP_INVALID")
        lines[j] = (" " * (indent + 4)) + f"maxMembers: {members}" + match.group(4) + "\n"
    else:
        lines.insert(c + 1, (" " * (indent + 4)) + f"maxMembers: {members}\n")
    return "".join(lines)


def apply_cloned_profile_capacity(*, runtime_profile="rc7.2-bank", base_profile="web",
                                  policy=None):
    policy = policy if policy is not None else TeamCapacityPolicy()
    if type(policy) is not TeamCapacityPolicy:
        raise TeamProfileCapacityError("R4_CAPACITY_POLICY_REQUIRED")
    dsh_runtime_profile._safe_runtime_name(runtime_profile)
    if base_profile not in dsh_plugins.protected_profiles():
        raise TeamProfileCapacityError("R4_PROTECTED_BASE_PROFILE_REQUIRED")
    base = dsh_runtime_profile._runtime_profile_path(base_profile)
    target = dsh_runtime_profile._runtime_profile_path(runtime_profile)
    marker = target / dsh_runtime_profile.PROFILE_MARKER
    if (not base.is_dir() or not target.is_dir() or base.is_symlink()
            or target.is_symlink() or marker.is_symlink() or not marker.is_file()):
        raise TeamProfileCapacityError("R4_ISOLATED_CLONE_OR_ORIGIN_MISSING")
    before = dsh_runtime_profile.profile_snapshot(base_profile)
    try:
        origin = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise TeamProfileCapacityError("R4_CLONE_ORIGIN_INVALID") from None
    if (origin.get("schema_version") != dsh_runtime_profile.PROFILE_SCHEMA
            or origin.get("base_profile") != base_profile
            or origin.get("runtime_profile") != runtime_profile
            or origin.get("base_digest") != before["digest"]):
        raise TeamProfileCapacityError("R4_CLONE_ORIGIN_DRIFT")

    package = target / "node_modules" / "@nanmicoder" / "dsh-agent-teams" / "package.json"
    config = target / "cordis.patch.yml"
    if package.is_symlink() or config.is_symlink() or not package.is_file() or not config.is_file():
        raise TeamProfileCapacityError("R4_AGENTTEAMS_PLUGIN_OR_CONFIG_MISSING")
    try:
        installed = json.loads(package.read_text(encoding="utf-8"))
        raw = config.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeError):
        raise TeamProfileCapacityError("R4_AGENTTEAMS_SOURCE_INVALID") from None
    if (installed.get("name") != NANMICODER_PLUGIN
            or not isinstance(installed.get("version"), str)
            or not installed["version"].strip()):
        raise TeamProfileCapacityError("R4_INSTALLED_AGENTTEAMS_IDENTITY_INVALID")
    changed = _rewrite_exact_agentteams_row(raw, policy.team_member_capacity)
    if changed != raw:
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n",
                    prefix=".rc72-team-capacity-", suffix=".tmp",
                    dir=str(target), delete=False) as output:
                temp = Path(output.name)
                output.write(changed)
                output.flush()
                os.fsync(output.fileno())
            if config.is_symlink():
                raise TeamProfileCapacityError("R4_PROFILE_SYMLINK_RACE")
            os.replace(str(temp), str(config))
        finally:
            if temp is not None and temp.exists():
                temp.unlink()
    after = dsh_runtime_profile.profile_snapshot(base_profile)
    if after["digest"] != before["digest"]:
        raise TeamProfileCapacityError("R4_PROTECTED_PROFILE_CHANGED")
    return {
        "status": "SOURCE_CONFIG_APPLIED_NOT_RUNTIME_VERIFIED",
        "plugin": NANMICODER_PLUGIN,
        "installed_version": installed["version"],
        "runtime_profile": runtime_profile,
        "team_member_capacity": policy.team_member_capacity,
        "max_active_workers": policy.max_active_workers,
        "clone_config_sha256": _digest(changed),
        "protected_source_unchanged": True,
        "field_verified": False,
        "bank_final": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="R4 isolated DSH Team capacity 32")
    parser.add_argument("--runtime-profile", default="rc7.2-bank")
    parser.add_argument("--base-profile", default="web")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        report = apply_cloned_profile_capacity(
            runtime_profile=args.runtime_profile, base_profile=args.base_profile)
    except (TeamProfileCapacityError, dsh_runtime_profile.DshRuntimeProfileError) as exc:
        report = {"status": "HOLD", "reason": str(exc),
                  "field_verified": False, "bank_final": False}
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    return 0 if report["status"] == "SOURCE_CONFIG_APPLIED_NOT_RUNTIME_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
