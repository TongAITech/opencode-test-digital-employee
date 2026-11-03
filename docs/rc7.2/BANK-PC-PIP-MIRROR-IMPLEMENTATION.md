# Bank PC user-level pip mirror implementation

The mandatory [contract](BANK-PC-PIP-MIRROR-CONTRACT.md) is being implemented.
The product reuses the existing real Windows user's `pip.ini`; it does not ask
the user to recreate that mirror configuration in the portable package.

## Implemented path

`bank_pc_pip_mirror_probe.py` resolves the real Windows roaming profile using the
known-folder API, independently of an isolated Worker's APPDATA. Normal pip
execution preserves the existing user environment and configuration discovery.
Hidden APPDATA fails unless the caller explicitly requests an audited bridge to
that same original user file. NUL/empty/unapproved configuration overrides fail.
The bridge references the original file; it does not copy its contents.

Every pip invocation uses the fixed package-local Python with user-site imports
disabled. Pip itself is not run in isolated mode. Real `pip --version`,
`pip config debug`, `pip config list -v` and actual install-parser/file-parser
observations establish provenance and effective settings. The configured user
index, extra indexes and trusted hosts must agree with effective pip settings.
The existing approved user file supplies the expected index; Field policy may
add an exact URL or digest constraint without requiring a duplicate config.

Field configuration supplies the qualification distribution spec and import
module. An actual no-cache, ignore-installed wheel resolution/install writes to
a new RC7.2-owned target. Download origins must match the approved index/explicit
policy; bank-configured extra indexes remain explicit policy. The same package
interpreter immediately imports from that target and checks the distribution
and module locations. Host Python/pip/site-packages cannot substitute.

Source identity and the transported ZIP bind the actual Python executable, pip
module and executing probe source. The archive digest is computed, and raw pip
configuration/install output remains in private evidence; exported records carry
hashes rather than mirror credential values. This subgate does not grant Q7,
overall Field or BANK_FINAL.

## Observed engineering evidence

Exact source `60c13be61283624b824fc079489b74669c610efd`, Windows run
`41606174266`: SUCCESS. Downloaded evidence confirms clean extraction after
original staging removal, package-local pip 26.2.2, real Windows user configuration
discovery, actual owned HTTP-mirror wheel download/install, and import from the
new target. Explicit bridging also passed. Six actual negative checks refused
hidden APPDATA, NUL config override, wrong effective index, missing mirror
package, successful host pip with package pip absent, and a host-only import.
All evidence is engineering simulation; bank-mirror Field fact remains unproven.

An earlier run `41605571519` failed on pip 26's changed internal config storage;
reading actual file parsers corrected it. It was not counted as a pass.

## Clean extraction and bank entry

The complete portable-build workflow now runs the same mirror probe against its
actual clean-extracted full package and source archive using an owned Windows
user-config/mirror simulation. That integrated new-source run is still required.

The bank entry is `packaging/rc7.2/BANK-PIP-MIRROR-CHECK.cmd`. Supply:

- `--archive` with the transferred package ZIP;
- `--bank-pip-field-config` with a bank-local JSON file containing `spec` and
  `module` chosen from the bank mirror;
- `--pip-evidence-root` with a writable private bank evidence directory.

`--bridge-user-config` is available for an intentionally isolated caller; it
cannot point to another configuration. The entry preserves APPDATA, USERPROFILE
and pip settings and invokes clean-package qualification plus the actual mirror
subgate. A Field request with missing configuration fails before qualification.
Overall Field/BANK_FINAL flags remain false because other Field gates are separate.

## Still open

Canonical Field/R1 admission and final BANK_FINAL aggregation still need the
native mirror gate's result as a mandatory verified input. Clean extraction
wiring alone does not close that requirement. Real bank PC evidence must come
from the bank's existing approved mirror and chosen qualification dependency.
No CI fixture result is bank Field evidence. C12 portable-completion and
BANK_FINAL claims remain blocked until the full contract is satisfied.

References: [pip configuration](https://pip.pypa.io/en/stable/topics/configuration/),
[pip installation](https://pip.pypa.io/en/stable/cli/pip_install/).
