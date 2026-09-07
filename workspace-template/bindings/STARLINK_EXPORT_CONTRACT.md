# Starlink approved export binding

The supported offline adapter is `APPROVED_EXPORT`. Live Starlink remains
`BANK_BINDING_REQUIRED` until the bank supplies its authenticated integration.
A successfully parsed fixture/export never means bank field validation passed.

Use the launcher's import action to select an export and record its human
approval. Hosted agent tools only read an existing local binding; they cannot
supply their own inline approval. Do not put passwords, cookies, OTPs or tokens
in either file. Use the bank's login screen for authentication.

The UTF-8 export JSON requires `project_id`, `release_id`, `revision`,
`observed_at` (ISO timestamp with timezone), `requirements` (array, each entry
has `requirement_id`) and `repositories` (array). Empty arrays explicitly mean
no supplied data. Optional SST references and release metadata are preserved.

The local `bindings/starlink.json` records `adapter: APPROVED_EXPORT`,
`source_system: STARLINK`, `binding_id`, `revision`, `project_id`, `release_id`,
`approved_by`, `approval_ref`, `approved_at`, `valid_until` and
`expected_sha256`. The last field hashes the exact export bytes. Times include
a timezone. Approval must already be effective and unexpired. A changed export
requires a newly approved hash and new immutable binding/release revisions.

The adapter verifies the file hash, project, release, approval and expiry
before recording Current Release and its approval in the existing G3 Event
facts of the canonical R1 spine. Original export path and hash are provenance;
Current Release, Requirement SST and runtime/deployment facts remain distinct.
The model must never infer a live Starlink connection from an approved file.

Requirement attachments support UTF-8 TXT/MD/JSON, DOCX text/tables, and PDF text
using bundled pypdf or local pdftotext. Encrypted/image-only PDF requires an
approved readable export. Raw documents remain hashed source bytes; parsed
content is durable R1/G3 source truth pending governed BR/SR/TR analysis.

BR/SR/TR artifacts have immutable IDs/revisions, exact source document refs,
exact parent revision refs, and explicit CODE/API/PAGE refs. SR requires BR;
TR requires SR. A revision does not silently repoint existing descendants.
R3.1 receives the same artifact IDs as obligations and the explicit lineage
and surface relations; downstream G3 case design and G4 evidence retain those
canonical identities. Relations are design traceability, not actual coverage.
All recovery stays within Architecture v7; G6 remains HOLD.
