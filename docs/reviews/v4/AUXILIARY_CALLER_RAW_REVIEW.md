# Auxiliary actual caller independent raw-source review

**Current decision: LOCAL AUXILIARY COMPONENT REVIEW PASS; DOCUMENT PATH P1 CLOSED.** Ordinary implementation fix; no architecture/HARD approval Gate. Reviewer changed no product source or Git. This is a bounded knowledge/recovery/evidence caller review, not Phase 0 or full C1.

## P1: document path scope is checked before a later unbound reopen

The model recovery wrapper resolves and checks the proposed path under workspace attachments/data/intake, then passes a pathname to the internal dispatcher. parse_document resolves/reopens that name later, and import_document reopens again for caching. The authorized bytes are not bound to an opened handle or safe snapshot.

Independent real-file and R1 fault injection swaps attachments/request.txt for a symlink to a temporary file outside the workspace at the dispatcher boundary after admission. The actual importer returns PASS and persists OUTSIDE_PRIVATE_REVIEW_CANARY, the outside file URI and its hash in SOURCE_DOCUMENT. Evidence: auxiliary-document-path-race.json. Only scratch data was used. This demonstrates a concurrent local-writer/path-replacement window; it does not claim a remote user can edit runtime source.

Repair the model boundary with secure anchored file access and bounded immutable bytes/snapshot, then parse and cache those same bytes. Preserve original verified provenance separately. Rechecking resolve immediately before a pathname read still leaves the same race. Existing trusted internal import services may retain their approved wider binding behavior, as requested; the model entry must not reopen an untrusted mutable path after scope admission.

## Supported source properties

All three TypeScript auxiliary bridges now pass actual Session/message/call IDs. MissionSessionOwner current() and exact Host tool part/input verification run under the shared coordinator. Copied task/session/attempt/logical identity fields reject. Knowledge scope is derived from the active R1 Goal execution_scope, with exact project/environment/version required and external scope/role mismatch rejected. Model-supplied role cannot widen retrieval. Planner knowledge invocation is denied; recovery requires Requirement Analyst. Mutation paths observe pending control fences.

Knowledge candidate review and link retain the existing domain adapters. Candidate writes are source-fact-backed and do not establish execution eligibility. Review still reads local human approval, checks digest and canonical passing execution evidence, and leaves G6 HOLD. Endpoint scope precheck precedes review/link. Evidence uses expected_input=raw payload for the raw-schema tool, then applies existing router and bounded Mission file checks. TypeScript offset/limit are optional so defaults are applied after exact original argument verification instead of altering raw Host input.

## Validation and limits

Initial independent new test suite: 5 tests, 4 passed, 1 error, 9.068s. Error is test lookup of nonexistent extension name g3_testing_intelligence after successful import; use the actual G3 constant to inspect persisted facts. This is a fixture lookup failure, not proof of import failure. Root is correcting it.

Independent human-review negative and candidate-only retrieval results are recorded in auxiliary-knowledge-human-gate.json. These use actual temporary R1 and local input files with a labeled Host transport fixture; no bank or real-model PASS is claimed. Full post-repair test/review is still required before sealing this component.

## Guarded-byte repair independent recheck

Original path-replacement finding is closed. Independent evidence `auxiliary-document-path-recheck.json` replays both boundaries: replacing the attachment with an external symlink before secure open returns OSError with no R1 changes; replacing it after the guarded read preserves BOUND_ORIGINAL_BYTES in the parsed fact and byte-identical cache. The outside canary no longer enters R1.

Latest independent auxiliary suite: **9 tests / OK / 10.053s**. The incorrect test extension name was fixed to the real G3 constant. Additional cases cover pre-open substitution, post-read replacement, same-revision changed-byte rejection and a five-MiB binary input, proving the reader did not silently inherit General's smaller file limit.

Source review: POSIX opens relative to guarded parent descriptors with NOFOLLOW/NONBLOCK and verifies a regular, single-link file. Windows retains existing directory guards and a non-reparse regular-file guard which denies delete/write sharing while opening and reading the descriptor. Both paths enforce the independent 20 MiB document bound and detect changed size/mtime/identity. This review ran on macOS; the Windows branch is source-reviewed and still needs actual Windows evidence for this added consumer. The previously passed General broker implementation was reused without alteration.

Parsing and cache now consume the same immutable raw bytes. TXT/MD/JSON still use UTF-8/JSON parsing, DOCX uses BytesIO and bounded OOXML, pypdf uses BytesIO, and external pdftotext receives a private temporary snapshot written from those bytes. Source locator and digest remain attached to the admitted original source. Internal approved import_document remains available and delegates to the same byte parser. Same source/revision with changed bytes/source kind fails explicitly; replay of identical source bytes remains supported. No parse-time reopen of the model-supplied original pathname remains.

Knowledge approval code is unchanged by this repair. The independent candidate→missing approval negative evidence remains valid: execution_eligible false, G6 HOLD, missing review denied, no new events, and candidate excluded from task retrieval. No new demonstrated P0/P1 was found in this bounded recheck. Full C1, HumanGate work, real Host and Windows qualification are separate; this is a local component seal only.
