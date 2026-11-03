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

## Native R1 execution and mandatory admission

`NativeBankPipMirrorService` now records signed source/package/archive/policy/
user-config intent before invoking the fixed native qualifier. The controller
keeps the signing authority; it is never passed to pip. The returned result is
signed separately and binds all private command/report hashes. Cold audit checks
both signatures, the original IN_FLIGHT history, immutable input bindings,
contiguous versions/attempts, current archive/policy/source and retained evidence.
An unobserved or unsigned result cannot become PASS. Authenticated returned
results support metadata-only recovery without another install; unknown work
never replays. Only explicitly requested retries of returned failures may create
new attempts, bounded to three. Changed inputs are failures before success signing.

Pip subprocesses preserve Windows user/config/proxy/certificate settings while
excluding unrelated controller/model credentials. The actual pip main parser is
checked before any pip CLI command, so `PIP_PYTHON`/configured interpreter
redirection cannot invoke host Python. File-specific pip parsers preserve its
native configuration encoding. Output uses UTF-8 and records Python/pip/platform
versions; no user-level mirror settings are recreated.

Q7 admission and Field Mission start now require this exact native provider and
an audited BANK_FIELD execution from the same release/source/ledger. The proof
must match the admission. Missing providers, detached PASS labels, engineering
receipts, changed evidence and wrong contexts fail before MissionNode effects.
Admission and bootstrap hold the participating ledger lock while verifying.
The driver passes this owned provider through; cold reconstruction must rebind
all services to the same fresh TruthRuntime. Read-only status needs no provider
or Worker configuration and registers the new receipt schema before R1 replay.

Legacy RC7/RC7.1 final launchers and report formats explicitly refuse RC7.2
packages. They cannot bypass the native ReleaseBatch final boundary or the user
pip mirror gate. The native RC7.2 terminal/final aggregation remains separate
product construction; this refusal is not a completed final implementation.

## Updated verification and remaining work

Windows run `41613462379` at exact source
`8c4530344e9dda4ae73878a626a093ab82fd7c2c` completed SUCCESS: 60 tests, no failures
or skips. Downloaded proof confirms Chinese/spaced extraction paths, actual
Python 3.11.9/pip 26.2.2, seven real negative checks (including host-interpreter
redirection), an actual native R1 execution receipt, and read-only reentry with
no repeated mirror request. Generic hosted execution remains ENGINEERING and
cannot satisfy BANK_FIELD. The whole-package verification flag is false for
that component fixture; it is not complete-package acceptance.

Local native-admission checks passed 80 tests. The original full product route
also passed (707.52 seconds): 28 original Cases, 78 L3 obligations, original
seven-level expectations retained and no repeated business effects on reentry.
That is engineering route evidence with synthetic trusted prior Field
prerequisites, not actual bank Field evidence. Those prerequisite fixtures are
excluded from the portable package and introduce no production bypass switch.
Cold downstream recovery checks separately passed 20 tests in 105.83 seconds.

The current bank command measures capability from the extracted package. The
production runtime factory must bind the native observer/controller authority
and surface its canonical execution to the unified ReleaseBatch entry; this
user flow and terminal/final release aggregation remain open with the other
frozen design items. Real bank PC evidence must use the bank's approved mirror
and selected dependency after transfer. C12/BANK_FINAL closure is not claimed.

References: [pip configuration](https://pip.pypa.io/en/stable/topics/configuration/),
[pip installation](https://pip.pypa.io/en/stable/cli/pip_install/).
