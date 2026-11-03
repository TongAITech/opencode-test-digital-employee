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
writing evidence outside the sealed package. A separate manually dispatched
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
