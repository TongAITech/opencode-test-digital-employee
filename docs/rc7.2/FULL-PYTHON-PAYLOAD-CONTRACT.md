# Full inherited Python payload and offline capability

The RC7.1-equivalent portable package must carry its document and OCR providers.
The previous materializer installed only Pillow/OpenCV and wrote a cv2/Pillow
marker; that did not establish DOCX/XLSX/PPTX/PDF or an OCR engine. The materializer
now acquires the inherited complete dependency set, including requests, pytest,
python-docx, openpyxl, python-pptx, pypdf, NumPy, ONNX Runtime and RapidOCR, with the
inherited compatibility bounds. Resolved versions are recorded, not inferred.

`python_full_capability_probe.py` runs as a standalone program under the copied
interpreter with `-I`. It checks that both the interpreter and every provider
module resolve inside the supplied runtime root, denies Python socket network
connections, performs actual DOCX/XLSX/PPTX/PDF roundtrips, and initializes and
executes OCR inference on a generated local image. Missing local model/runtime
files cannot be supplied by an allowed network download during this probe.
A stale previous marker is removed before acquisition, and cv2/Pillow-only
markers or mismatched interpreter/root evidence are refused. This is engineering
payload capability evidence and grants no Field/BANK_FINAL authority.

The full portable preparation also reruns the probe after clean extraction,
writing evidence outside the sealed package. A separate dedicated-branch or manually dispatched
Windows workflow copies the runtime, archives it, removes staging and validates
clean extraction under a path with spaces. This smaller archive is an internal
Python-component test fixture, never the user-requested complete product package.
It provides component evidence only; the complete RC7.1-equivalent payload,
all-source qualification, product startup and Field toolkit remain mandatory.

Local dependency acquisition in this construction environment encountered TLS
connection failures through its configured proxy and direct PyPI/mirror probes.
No actual offline OCR PASS is claimed from that failed acquisition. The Windows
component workflow and eventual full clean-package run must provide the actual
matching-platform evidence. Contract tests only establish fail-closed behavior;
they do not substitute for the real copied-runtime probe.

## Actual Windows component qualification

Workflow 41595427225 at source
`90601b1dec5853c24718ba89d6ba1af018555296` completed successfully. The downloaded
`actual-offline-capability.json` was inspected: copied interpreter under the
clean-extraction path with spaces, network_allowed=false, all four format
roundtrips, actual OCR inference with one recognized region, and all eleven
provider distributions with actual versions. Staging was deleted before this
probe. The boundary record explicitly has full_product_package=false and
Field/BANK_FINAL=false. This is actual Windows component evidence; full final
package clean-unpack qualification must still execute the same probe on its own
resolved payload and source. Local TLS acquisition failure is not recast as a
local successful run.

## Mandatory bank Windows user-level pip mirror capability

The offline capability above proves the copied interpreter and already-carried providers; it does **not** by itself prove that the final bank package can add a dependency through the bank pip mirror.

RC7.2 therefore also adopts [BANK-PC-PIP-MIRROR-CONTRACT.md](BANK-PC-PIP-MIRROR-CONTRACT.md) as a mandatory implementation and qualification contract.

On the target bank Windows PC the approved internal pip mirror is configured at Windows user level, normally `%APPDATA%\pip\pip.ini`. The final portable package must carry a working package-local `pip`, invoke it only through the package-local interpreter, preserve or explicitly bridge discovery of the real user-level pip configuration, perform a real bank-mirror install into an RC7.2-owned path, and prove same-interpreter import from that path.

The existing `python_full_capability_probe.py -I` offline-provider check remains valid for its original purpose, but it is not a substitute for `BANK_PC_PIP_MIRROR_GATE`. The pip-mirror gate must not use pip isolation or environment rewriting that suppresses the approved Windows user-level configuration.

Until the implementation, negative tests, final-package clean-unpack invocation and real bank Field evidence required by `BANK_PC_PIP_MIRROR_GATE` exist, C12 portable completion and BANK_FINAL remain fail-closed.
