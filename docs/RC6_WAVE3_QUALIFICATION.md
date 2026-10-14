# RC6 Wave 3 Qualification Contract

Wave 3 turns bank environment facts into a canonical runtime registry so missions stop rediscovering repositories, databases, routes, authentication and environments.

## Runtime invariants

- Historical v194/field facts are migrated once with provenance and are idempotent by source id.
- Every fact has one of `READY`, `STALE`, `NEEDS_BINDING`, `INVALID`.
- Missions perform bounded freshness reconciliation against canonical facts rather than replacing them with guesses.
- Drift changes a fact to `STALE` with expected/observed details.
- Secret values are not stored in the registry; only local credential/secret references are allowed.
- Execution requires a deterministic `TargetIdentity`.
- A target binds release id, deployment mode, environment, four repository revisions, frontend route, gateway route, three application databases, 4A, CAT and account profile.
- Repository release/revision mismatches fail closed.
- Environment deployed-release mismatch fails closed.
- DB/route/auth/CAT/account facts must be `READY` and belong to the same environment.
- `REMOTE_DEPLOYMENT` does not infer that localhost services must be running.

## Qualification scenarios

1. One-time historical migration is idempotent.
2. Matching freshness observation keeps a fact `READY`; revision drift makes it `STALE`.
3. Secret values are rejected while `credential_ref` is accepted.
4. A coherent FAT1 remote target is deterministic and does not require localhost services.
5. `NEEDS_BINDING` database blocks target construction.
6. Stale repository blocks target construction.
7. Environment release mismatch blocks target construction.
8. Missing route binding blocks target construction.
9. All Wave 1/2 tests remain green.

Qualification command:

```bash
python -m unittest discover -s tests -v
```

Wave 3 can freeze only after the committed source passes GitHub Actions and run/head evidence is recorded in `RC6_CONSTRUCTION_STATUS.md`.
