# RC7.2 bank Windows user-level pip mirror contract

Status: **MANDATORY CONSTRUCTION / C12 + BANK_FINAL BLOCKER**

This contract is part of the RC7.2 portable Python and bank Field boundary. It is not an operator workaround and must be implemented by the product/qualification path before RC7.2 can claim complete portable delivery.

## Bank environment fact

On the target bank Windows PC, the internal pip mirror is already configured at the Windows **user level**, normally through:

`%APPDATA%\pip\pip.ini`

RC7.2 must reuse this existing user-level configuration. The user must not be required to recreate the mirror configuration inside the RC7.2 package.

## Required product behavior

The final RC7.2 portable package SHALL:

1. carry a package-local Python interpreter with a working `pip` module;
2. invoke pip through the package-local interpreter, for example `python\python.exe -m pip`, never by trusting `python` or `pip` found on host `PATH`;
3. preserve access to the real Windows user profile values needed by pip configuration discovery, including the effective `%APPDATA%` path;
4. allow package-local pip to discover and consume the existing user-level `%APPDATA%\pip\pip.ini` mirror configuration;
5. preserve the configured internal `index-url`, `trusted-host` and other required enterprise pip settings without copying secrets or machine-specific configuration into the sealed package;
6. refuse to substitute a host Python/pip/site-packages installation as proof;
7. keep installed qualification content inside an RC7.2-owned path and prove that the same package-local interpreter can import it.

If RC7.2 runtime isolation changes `HOME`, `USERPROFILE`, `APPDATA`, `PIP_CONFIG_FILE`, `PYTHONHOME`, `PYTHONPATH`, DSH home, worker home, or related environment state, the implementation MUST either preserve Windows user-level pip config discovery or explicitly bridge the original user-level pip configuration into the pip subprocess. The bridge must be auditable and must not silently replace the bank mirror with public PyPI.

The pip mirror qualification path MUST NOT use pip `--isolated`, `PIP_CONFIG_FILE` pointing to a null/empty file, or another mechanism that intentionally suppresses the Windows user-level pip configuration.

## BANK_PC_PIP_MIRROR_GATE

This gate is mandatory for the final bank Field qualification and is a blocking input to C12 / portable-package completion / BANK_FINAL.

### G1 — package-local pip exists

Run with the final extracted package interpreter:

`<package-python> -m pip --version`

PASS requires the command to succeed and the reported interpreter/pip paths to resolve inside the current RC7.2 package/runtime boundary.

### G2 — Windows user-level pip configuration is actually discovered

Run at minimum:

`<package-python> -m pip config debug`

and

`<package-python> -m pip config list -v`

PASS requires evidence that the effective Windows user-level pip configuration is discovered from the current user profile (normally `%APPDATA%\pip\pip.ini`) and that the expected internal mirror configuration is effective. Sensitive mirror values may be redacted in published evidence, but the verifier must compare the effective value before redaction.

A temporary command-line `--index-url` alone is not proof that the user-level configuration was read.

### G3 — real bank-mirror resolution/install

Using the same package-local interpreter, perform an actual install of a qualification dependency that is known to exist in the bank mirror. The package/spec SHALL be supplied by bank Field configuration rather than hard-coded to a public-only package.

The install MUST:

- use the effective user-level internal mirror configuration;
- perform a real resolver/download/install operation against the bank mirror;
- avoid public PyPI fallback unless bank policy explicitly configures that behavior;
- write the qualification installation only to an RC7.2-owned writable qualification path or package-local extension path;
- record the resolved distribution name/version and installation path.

A cache-only import, an already-present distribution, or a mocked pip result is not sufficient proof.

### G4 — same-interpreter import proof

Immediately after G3, the same package-local interpreter MUST import the installed qualification distribution/module from the RC7.2-owned installation path and record at minimum:

- `sys.executable`;
- `sys.prefix`;
- effective package root;
- imported module `__file__` (or equivalent distribution location);
- resolved distribution/version;
- effective user pip config source;
- target installation directory.

The imported module must not resolve from system Python, user Python, Conda, another virtual environment, or another RC7.2 extraction.

### G5 — negative host-substitution checks

Qualification MUST fail closed when any of the following is deliberately introduced:

- host `pip.exe` succeeds while package-local `python -m pip` is missing/broken;
- `%APPDATA%` is replaced so the real user-level config becomes invisible without an explicit audited bridge;
- `PIP_CONFIG_FILE` suppresses or replaces the approved user-level configuration unexpectedly;
- install/import resolves into host site-packages;
- the effective index is not the approved bank mirror;
- the package-local pip cannot install a new dependency from the mirror.

## Evidence contract

The final gate evidence SHALL be generated from the same final package/source being qualified and bind at least:

- source commit SHA;
- package/archive digest;
- package extraction root;
- package-local Python executable path and version;
- pip version and pip module location;
- current Windows user-profile / `%APPDATA%` identity needed for config discovery (path may be redacted in exported evidence while retaining an integrity-bound raw record);
- pip configuration source files considered and the effective approved mirror identity;
- qualification package/spec;
- resolver/install result and resolved version;
- installation destination;
- same-interpreter import location;
- timestamp and gate result.

The evidence MUST distinguish engineering/CI simulation from the real bank Field run. CI may prove the contract and negative behavior, but only the bank PC can establish the actual bank-mirror Field fact.

## Portable-package policy

Normal RC7.2 startup SHOULD continue to ship its fixed runtime dependencies already prepared, so every startup does not reinstall dependencies. The bank user-level pip mirror capability exists for:

- missing/corrupt dependency recovery;
- new Plugin/Skill dependencies;
- new Tool/Provider dependencies;
- controlled Field upgrades or troubleshooting.

A bootstrap wheel reserve may still be carried as an emergency recovery aid, but a complete offline wheelhouse is not the primary bank dependency source when the approved bank pip mirror is available.

## Construction instruction

The active `work/rc7.2` construction MUST implement this contract, not merely document it. At minimum construction must add:

1. a package-local pip capability/provenance probe;
2. a Windows user-level pip config discovery probe;
3. a real mirror install + same-interpreter import qualification path configurable for the bank Field package/spec;
4. negative tests for host-pip substitution and hidden/overridden `%APPDATA%` / `PIP_CONFIG_FILE` cases;
5. C12/BANK_FINAL fail-closed wiring so this gate cannot be omitted when bank Field qualification is requested;
6. final-package clean-unpack qualification invoking the same gate from the final extracted package.

Until those implementation and qualification paths exist, `BANK_PC_PIP_MIRROR_GATE` is **OPEN**, and RC7.2 MUST NOT claim complete C12 portable delivery or BANK_FINAL.
