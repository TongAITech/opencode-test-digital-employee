# Engineering Source Governance

## Identity

The canonical source identity is computed from every tracked repository file except `SOURCE_BASELINE_MANIFEST.json` itself.

Algorithm:

1. SHA-256 each file byte-for-byte.
2. Create records `<sha256>  <POSIX-relative-path>`.
3. Sort records lexicographically by path.
4. UTF-8 encode records joined by `\n`, with exactly one final `\n`.
5. SHA-256 the resulting byte stream.

Git commit SHA remains the Engineering Source Truth. This content identity is an additional reproducible artifact identity.

## Runtime payloads

Portable Python, Chromium, CodeGraph and other large binaries are not source truth. They are pinned by `runtime-lock.json`, verified at assembly time, and injected into the derived offline package.

## Bank boundary

Never commit PFC/KYB SUT source, bank requirements/data, credentials, cookies, auth artifacts, CAT/DB data, coverage exports, browser profiles, or mutable runtime databases.
