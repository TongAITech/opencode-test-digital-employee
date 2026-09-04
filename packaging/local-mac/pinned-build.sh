#!/bin/bash
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
case "$(uname -m)" in
  arm64|aarch64)
    export PFC_MAC_CHROME_SHA256="01a23ef9501b2745e0c2944c2e583207e6f6132d8d91c3a87ff65b5079e438ef"
    ;;
  x86_64|amd64|x64)
    export PFC_MAC_CHROME_SHA256="69bcc853db975a2380767e9ff36da17f1d7b782fbbe191a210f676d2d5967d3e"
    ;;
  *)
    printf '[LOCAL MAC PINNED BUILD FAIL] unsupported architecture: %s\n' "$(uname -m)" >&2
    exit 1
    ;;
esac

exec "$HERE/local-mac.sh" build "$@"
