# Local Mac Offline Validation

The only entry is `local-mac.sh`.

## 1. Build the offline package

Run this once on an online Mac with the same architecture as the target Mac:

```bash
cd packaging/local-mac
./local-mac.sh build
```

Optional output directory:

```bash
PFC_MAC_OUTPUT_DIR="$HOME/Downloads" ./local-mac.sh build
```

The build step is the **only** step allowed to download/install dependencies.
It produces `PFC-LOCAL-MAC-R1R4-<arch>-<sha>.tar.gz` plus `.sha256`.

## 2. Verify and install offline

Move both generated files to the target Mac, then verify before extraction:

```bash
shasum -a 256 -c PFC-LOCAL-MAC-R1R4-*.tar.gz.sha256
tar -xzf PFC-LOCAL-MAC-R1R4-*.tar.gz
cd PFC-LOCAL-MAC-R1R4-*
./local-mac.sh install
```

The installer also recomputes the package-internal runtime tree identity before
provisioning the workspace.

Default install root:

```text
$HOME/OpenCode-Digital-Employee-Local-Validation
```

Override with `PFC_LOCAL_VALIDATION_ROOT`.

## 3. Bind the local PFC

```bash
cd "$HOME/OpenCode-Digital-Employee-Local-Validation"
./local-mac.sh bind /absolute/path/to/local/PFC
```

Binding records only the local PFC filesystem root. Credentials are not persisted.

## 4. Doctor / start / status / stop

```bash
./local-mac.sh doctor
./local-mac.sh start
./local-mac.sh status
./local-mac.sh stop
```

`start` launches bundled OpenCode 1.18.3 and the package-owned G2.1 control loop.
The endpoint is returned by the runtime command.

## Truth boundary

This package does not create a second product truth. R1 Event Stream remains the
sole durable runtime truth. Local PFC is a validation target, not bank source
truth.
