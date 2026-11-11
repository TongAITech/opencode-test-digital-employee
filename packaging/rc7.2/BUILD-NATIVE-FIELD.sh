#!/usr/bin/env bash
# Build one native RC7.2 Linux/macOS package on its matching host architecture.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
SYSTEM="$(uname -s)"
MACHINE="$(uname -m)"
case "$SYSTEM:$MACHINE" in
  Linux:x86_64) PLATFORM=linux; ARCH=x86_64; TRIPLE=x64; BSK_TRIPLE=x86_64-unknown-linux-musl; RG_TRIPLE=x86_64-unknown-linux-musl; K6_ASSET=k6-v1.8.2-linux-amd64.tar.gz; K6_SHA=37620781d35406ebf402397a6c5cf4adb62d175cb052ff45325ae0b860527063; CG_ASSET=codegraph-server-linux-x64; CG_SHA=15ef4a714bb163284a00dfdad88a244280659c4b240328c38953cfcd4bfbffba; BSK_SHA=8a6d503a07748fc8f5f4a9d262564dea011bf860c8294032f9fb84b10c006d8a; RG_SHA=33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c ;;
  Linux:aarch64) PLATFORM=linux; ARCH=arm64; TRIPLE=arm64; BSK_TRIPLE=aarch64-unknown-linux-musl; RG_TRIPLE=aarch64-unknown-linux-musl; K6_ASSET=k6-v1.8.2-linux-arm64.tar.gz; K6_SHA=8b4e55024ffc8ed7ed4caabca054dfb5bafe16e7ee4235de57d01bf58d69e0d7; CG_ASSET=codegraph-server-linux-arm64; CG_SHA=32555d4c70c8dcbf8edcd88629348c995706daedaa89302623eaa9cae35f2495; BSK_SHA=c54a6af6ca9eb3abaee523427796817deb139b847cb76e8335da6804f35c441c; RG_SHA=800b1e7206afe799dfb5a6901f23147cfaabe0e52210538100f61e86e1740915 ;;
  Darwin:x86_64) PLATFORM=darwin; ARCH=x86_64; TRIPLE=x64; BSK_TRIPLE=x86_64-apple-darwin; RG_TRIPLE=x86_64-apple-darwin; K6_ASSET=k6-v1.8.2-macos-amd64.zip; K6_SHA=3309d7ef81283055f32cd4ad516e33cf8fcbcd33c3c2edbd82a135864fd9becf; CG_ASSET=codegraph-server-darwin-x64; CG_SHA=f6a0af8cdf8d8d5ee30a60a728b32659ccd1e4619bc7c9b14963698cdf519e16; BSK_SHA=1bcf15c2235437fe2c8931a7e915430be16ce02b39eb49a071fce97750b3a8c0; RG_SHA=af7825fcc69a2afc7a7aea55fc9af90e26421d8f20fe59df32e233c0b8a231c1 ;;
  Darwin:arm64) PLATFORM=darwin; ARCH=arm64; TRIPLE=arm64; BSK_TRIPLE=aarch64-apple-darwin; RG_TRIPLE=aarch64-apple-darwin; K6_ASSET=k6-v1.8.2-macos-arm64.zip; K6_SHA=2ce3ed837e9a7c7b1b7a594ff72861bbf9d94d5930ca6611bd6f1ef5a08f7d0a; CG_ASSET=codegraph-server-darwin-arm64; CG_SHA=a4f70942f9283ff2327a711ccf777cfa932187503c8945067aa6a21c82bc5f3b; BSK_SHA=8b9fb14a8f6231b2c11ed5494d45224a1860e2a85245a78d16995de50f2bd659; RG_SHA=3750b2e93f37e0c692657da574d7019a101c0084da05a790c83fd335bad973e4 ;;
  *) echo "NATIVE_PLATFORM_UNSUPPORTED:$SYSTEM:$MACHINE" >&2; exit 2 ;;
esac

DIST="${RUNNER_TEMP:-/tmp}/rc72-native-dist"
TOOLS="${RUNNER_TEMP:-/tmp}/rc72-native-input"
mkdir -p "$DIST" "$TOOLS"
rm -rf "$TOOLS"
mkdir -p "$TOOLS"
RUNTIME="$TOOLS/runtime"
mkdir -p "$RUNTIME"
download() {
  local url="$1" dest="$2" expected="$3"
  curl -fL --retry 4 --retry-delay 2 "$url" -o "$dest"
  local actual
  if command -v sha256sum >/dev/null 2>&1; then actual="$(sha256sum "$dest" | awk '{print $1}')"; else actual="$(shasum -a 256 "$dest" | awk '{print $1}')"; fi
  [[ "$actual" == "$expected" ]] || { echo "NATIVE_ASSET_SHA256_MISMATCH:$dest expected=$expected actual=$actual" >&2; exit 4; }
}
unpack_tar() { mkdir -p "$2"; tar -xzf "$1" -C "$2"; }
unpack_zip() { mkdir -p "$2"; unzip -q "$1" -d "$2"; }

# Linux native shared libraries are qualified in Rocky Linux 9, matching glibc 2.34.
if [[ "$PLATFORM" == "linux" ]]; then
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y curl-minimal ca-certificates tar xz unzip gzip git findutils which file \
      alsa-lib atk at-spi2-atk cups-libs libXcomposite libXdamage libXext libXfixes \
      libXrandr libXtst libXcursor libXrender libXScrnSaver libxkbcommon libxcb \
      libX11 libX11-xcb libdrm mesa-libgbm gtk3 nss nspr pango cairo libxshmfence \
      libuuid dbus-libs libstdc++ libgcc libatomic mesa-libGL >/dev/null
  fi
fi

# uv-managed CPython is copied into an isolated package-owned runtime.
export UV_INSTALL_DIR="$TOOLS/uv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$UV_INSTALL_DIR:$PATH"
[[ -x "$UV_INSTALL_DIR/uv" ]] || { echo "NATIVE_UV_INSTALL_FAILED:$UV_INSTALL_DIR" >&2; exit 2; }
"$UV_INSTALL_DIR/uv" --version
uv python install 3.11.18
PYBIN="$(uv python find 3.11.18 --managed-python)"
PYROOT="$(dirname "$(dirname "$PYBIN")")"
uv pip install --break-system-packages --python "$PYBIN" \
  "pip==25.2" "pytest==8.3.5" "requests==2.34.2" "openpyxl==3.1.5" \
  "python-docx==1.2.0" "python-pptx==1.0.2" "pypdf==7.0.1" "pillow==12.0.0" \
  "numpy==1.26.4" "onnxruntime==1.20.1" "opencv-python-headless==4.10.0.84" \
  "rapidocr-onnxruntime==1.4.4"
"$PYBIN" -B -c "import sys,requests,pytest,openpyxl,docx,pptx,pypdf,PIL,numpy,onnxruntime,cv2,rapidocr_onnxruntime;print('NATIVE_PYTHON_OCR_CV_PASS',sys.version)"

# Node.js 24.9.0, native platform archive and official SHASUMS verification.
NODE_VERSION=24.9.0
NODE_ARCHIVE="node-v${NODE_VERSION}-${PLATFORM}-${TRIPLE}.tar.xz"
curl -fL "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" -o "$TOOLS/SHASUMS256.txt"
NODE_SHA="$(awk -v name="$NODE_ARCHIVE" '$2==name {print $1}' "$TOOLS/SHASUMS256.txt")"
[[ "$NODE_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "NODE_OFFICIAL_SHA256_MISSING" >&2; exit 4; }
download "https://nodejs.org/dist/v${NODE_VERSION}/$NODE_ARCHIVE" "$TOOLS/$NODE_ARCHIVE" "$NODE_SHA"
mkdir -p "$TOOLS/node"
tar -xJf "$TOOLS/$NODE_ARCHIVE" -C "$TOOLS/node" --strip-components=1
NODE_ROOT="$TOOLS/node"
NODEBIN="$NODE_ROOT/bin/node"
"$NODEBIN" --version | grep -x "v${NODE_VERSION}"
export PATH="$NODE_ROOT/bin:$PATH"

# BrowserSkill 0.4.1 is pinned to the four native release assets.
BSK_URL="https://github.com/Tencent/BrowserSkill/releases/download/cli-v0.4.1/bsk-v0.4.1-${BSK_TRIPLE}.tar.gz"
download "$BSK_URL" "$TOOLS/bsk.tar.gz" "$BSK_SHA"
unpack_tar "$TOOLS/bsk.tar.gz" "$TOOLS/bsk"
BSK_BIN="$(find "$TOOLS/bsk" -type f -name bsk -print -quit)"
[[ -n "$BSK_BIN" ]] || { echo "NATIVE_BSK_BINARY_MISSING" >&2; exit 3; }
chmod +x "$BSK_BIN"
"$BSK_BIN" --version | grep -F '0.4.1'

EXT_URL="https://github.com/Tencent/BrowserSkill/releases/download/ext-v0.4.1/browser-skill-extension-v0.4.1-chrome.zip"
download "$EXT_URL" "$TOOLS/bsk-extension.zip" 75e38414e732679b7fe7616de9f3bb80dbb9cfcc55d9cab2566dbcebb4cd9b51
unpack_zip "$TOOLS/bsk-extension.zip" "$TOOLS/extension"
EXT_MANIFEST="$(find "$TOOLS/extension" -type f -name manifest.json -print -quit)"
[[ -n "$EXT_MANIFEST" ]] || { echo "NATIVE_BSK_EXTENSION_MISSING" >&2; exit 3; }
EXT_ROOT="$(dirname "$EXT_MANIFEST")"

# Playwright package and Chromium are installed for this runner's native architecture.
NODE_EXEC="$TOOLS/node-execution"
mkdir -p "$NODE_EXEC"
npm install --prefix "$NODE_EXEC" --save-exact --omit=dev --ignore-scripts --no-audit --no-fund "playwright@1.65.0" "pnpm@10.24.0"
[[ -f "$NODE_EXEC/node_modules/pnpm/bin/pnpm.cjs" ]] || { echo "NATIVE_OFFLINE_PNPM_MISSING" >&2; exit 3; }
export PLAYWRIGHT_BROWSERS_PATH="$TOOLS/pw-browsers"
"$NODEBIN" "$NODE_EXEC/node_modules/playwright/cli.js" install chromium
BROWSER_ROOT="$TOOLS/pw-browsers"

# Native CodeGraph 0.21.0.
download "https://github.com/codegraph-ai/CodeGraph/releases/download/v0.21.0/$CG_ASSET" "$TOOLS/$CG_ASSET" "$CG_SHA"
chmod +x "$TOOLS/$CG_ASSET"
"$TOOLS/$CG_ASSET" --help >/dev/null

# ripgrep 15.2.0 native archive.
RG_ARCHIVE="ripgrep-15.2.0-$RG_TRIPLE.tar.gz"
download "https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/$RG_ARCHIVE" "$TOOLS/$RG_ARCHIVE" "$RG_SHA"
unpack_tar "$TOOLS/$RG_ARCHIVE" "$TOOLS/rg"
RG_BIN="$(find "$TOOLS/rg" -type f -name rg -print -quit)"
[[ -n "$RG_BIN" ]] || { echo "NATIVE_RIPGREP_MISSING" >&2; exit 3; }
chmod +x "$RG_BIN"
"$RG_BIN" --version | grep -F 'ripgrep 15.2.0'

# k6 1.8.2 native archive.
download "https://github.com/grafana/k6/releases/download/v1.8.2/$K6_ASSET" "$TOOLS/$K6_ASSET" "$K6_SHA"
if [[ "$K6_ASSET" == *.zip ]]; then unpack_zip "$TOOLS/$K6_ASSET" "$TOOLS/k6"; else unpack_tar "$TOOLS/$K6_ASSET" "$TOOLS/k6"; fi
K6_BIN="$(find "$TOOLS/k6" -type f -name k6 -print -quit)"
[[ -n "$K6_BIN" ]] || { echo "NATIVE_K6_MISSING" >&2; exit 3; }
chmod +x "$K6_BIN"
"$K6_BIN" version >/dev/null

# Allure 2.46.2 is a platform-independent Java distribution.
download "https://github.com/allure-framework/allure2/releases/download/2.46.2/allure-2.46.2.tgz" "$TOOLS/allure.tgz" 83021e2c02e9a3487df249ef7bbf51c1b9f23b722bd288c6d1785609303e0df8
unpack_tar "$TOOLS/allure.tgz" "$TOOLS/allure"
ALLURE_BIN="$(find "$TOOLS/allure" -type f -path '*/bin/allure' -print -quit)"
[[ -n "$ALLURE_BIN" ]] || { echo "NATIVE_ALLURE_MISSING" >&2; exit 3; }
ALLURE_ROOT="$(dirname "$(dirname "$ALLURE_BIN")")"
find "$TOOLS/allure" -type f \( -iname '*.bat' -o -iname '*.cmd' -o -iname '*.ps1' -o -iname '*.exe' -o -iname '*.dll' \) -delete

# OWASP ZAP 2.17.0 native Linux archive; macOS uses the cross-platform Java distribution.
if [[ "$PLATFORM" == "linux" ]]; then
  download "https://github.com/zaproxy/zaproxy/releases/download/v2.17.0/ZAP_2.17.0_Linux.tar.gz" "$TOOLS/zap.tar.gz" efe799aaa3627db683b43f00c9c210aea0b75c00cc8f0a0f0434d12bb3ddde5a
  unpack_tar "$TOOLS/zap.tar.gz" "$TOOLS/zap"
else
  download "https://github.com/zaproxy/zaproxy/releases/download/v2.17.0/ZAP_2.17.0_Crossplatform.zip" "$TOOLS/zap.zip" 94c8f767b1c2e94f0db66b3ae56514d5e3f5a728ee1b6c798e0c8fe2d61fbff0
  unpack_zip "$TOOLS/zap.zip" "$TOOLS/zap"
fi
ZAP_BIN="$(find "$TOOLS/zap" -type f -name zap.sh -print -quit)"
[[ -n "$ZAP_BIN" ]] || { echo "NATIVE_ZAP_LAUNCHER_MISSING" >&2; exit 3; }
chmod +x "$ZAP_BIN"
find "$TOOLS/zap" -type f \( -iname '*.bat' -o -iname '*.cmd' -o -iname '*.ps1' -o -iname '*.exe' -o -iname '*.dll' \) -delete
ZAP_BIN="$(find "$TOOLS/zap" -type f -name zap.sh -print -quit)"
[[ -n "$ZAP_BIN" ]] || { echo "NATIVE_ZAP_LAUNCHER_MISSING_AFTER_PLATFORM_FILTER" >&2; exit 3; }

# Eclipse Temurin 17.0.21+9, exact native architecture and pinned upstream asset SHA256.
if [[ "$PLATFORM" == "linux" ]]; then JDK_OS=linux; else JDK_OS=mac; fi
if [[ "$ARCH" == "x86_64" ]]; then JDK_ARCH=x64; else JDK_ARCH=aarch64; fi
case "$JDK_OS:$JDK_ARCH" in
  linux:x64) JDK_SHA=8b9b611d917e3dfd8419d3566b5949226f69b052fed7e109c1368add1dfe8711 ;;
  linux:aarch64) JDK_SHA=3e4eca7ead088f080af1476007decf010a240a1eb4e1e78c54fa32fbcc347084 ;;
  mac:x64) JDK_SHA=868f5c672b3389fdbe48e44f94ae170f01668b1401360944fc7159d7cc9772cc ;;
  mac:aarch64) JDK_SHA=78b08c7f5a0598242d5719c022e19479cb4a3aa45c37c19726a757a469ed1c15 ;;
  *) echo "NATIVE_TEMURIN_PLATFORM_UNSUPPORTED" >&2; exit 2 ;;
esac
JDK_ARCHIVE="OpenJDK17U-jdk_${JDK_ARCH}_${JDK_OS}_hotspot_17.0.21_9.tar.gz"
JDK_URL="https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.21%2B9/$JDK_ARCHIVE"
download "$JDK_URL" "$TOOLS/jdk.tar.gz" "$JDK_SHA"
unpack_tar "$TOOLS/jdk.tar.gz" "$TOOLS/java"
JAVA_BIN="$(find "$TOOLS/java" -path '*/bin/java' -print -quit)"
[[ -n "$JAVA_BIN" ]] || { echo "NATIVE_JDK17_MISSING" >&2; exit 3; }
JAVA_ROOT="$(dirname "$(dirname "$JAVA_BIN")")"
export JAVA_HOME="$JAVA_ROOT"
export PATH="$JAVA_ROOT/bin:$PATH"
"$JAVA_BIN" -version 2>&1 | grep -E 'version "17\.'

# Maven 3.9.16 with Apache-published SHA512.
MAVEN_VERSION=3.9.16
MAVEN_ARCHIVE="apache-maven-$MAVEN_VERSION-bin.tar.gz"
MAVEN_BASE="https://archive.apache.org/dist/maven/maven-3/$MAVEN_VERSION/binaries"
curl -fL "$MAVEN_BASE/$MAVEN_ARCHIVE" -o "$TOOLS/$MAVEN_ARCHIVE"
curl -fL "$MAVEN_BASE/$MAVEN_ARCHIVE.sha512" -o "$TOOLS/$MAVEN_ARCHIVE.sha512"
MAVEN_EXPECTED="$(tr -d '[:space:]' < "$TOOLS/$MAVEN_ARCHIVE.sha512")"
if command -v sha512sum >/dev/null 2>&1; then MAVEN_ACTUAL="$(sha512sum "$TOOLS/$MAVEN_ARCHIVE" | awk '{print $1}')"; else MAVEN_ACTUAL="$(shasum -a 512 "$TOOLS/$MAVEN_ARCHIVE" | awk '{print $1}')"; fi
[[ "$MAVEN_ACTUAL" == "$MAVEN_EXPECTED" ]] || { echo "MAVEN_SHA512_MISMATCH" >&2; exit 4; }
unpack_tar "$TOOLS/$MAVEN_ARCHIVE" "$TOOLS/maven"
MAVEN_ROOT="$(find "$TOOLS/maven" -mindepth 1 -maxdepth 1 -type d -name "apache-maven-*" -print -quit)"
find "$MAVEN_ROOT" -type f \( -iname '*.bat' -o -iname '*.cmd' -o -iname '*.ps1' -o -iname '*.exe' -o -iname '*.dll' \) -delete
[[ -x "$MAVEN_ROOT/bin/mvn" ]] || { echo "NATIVE_MAVEN_MISSING" >&2; exit 3; }

# Seed an offline Maven repository with JUnit, Surefire, Failsafe and JaCoCo.
M2="$TOOLS/maven-repository"
SEED="$TOOLS/maven-seed"
mkdir -p "$SEED/src/test/java/rc7"
cat > "$SEED/pom.xml" <<'POM'
<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>rc7</groupId><artifactId>offline-seed</artifactId><version>1</version><properties><maven.compiler.source>8</maven.compiler.source><maven.compiler.target>8</maven.compiler.target></properties><dependencies><dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.11.4</version><scope>test</scope></dependency></dependencies><build><plugins><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.5.2</version></plugin><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-failsafe-plugin</artifactId><version>3.5.2</version></plugin><plugin><groupId>org.jacoco</groupId><artifactId>jacoco-maven-plugin</artifactId><version>0.8.12</version></plugin></plugins></build></project>
POM
cat > "$SEED/src/test/java/rc7/SeedTest.java" <<'JAVA'
package rc7; import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; class SeedTest { @Test void ok(){ assertEquals(2,1+1); } }
JAVA
"$MAVEN_ROOT/bin/mvn" -q -f "$SEED/pom.xml" "-Dmaven.repo.local=$M2" test
"$MAVEN_ROOT/bin/mvn" -q -f "$SEED/pom.xml" "-Dmaven.repo.local=$M2" dependency:go-offline
"$MAVEN_ROOT/bin/mvn" -q -o -f "$SEED/pom.xml" "-Dmaven.repo.local=$M2" test

# Required DSH plugin payload; no registry is needed at field install time.
"$PYBIN" -m rc7_release.plugin_payload acquire --repo-root . | tee "$TOOLS/plugin-core-acquire.json"
"$PYBIN" -m rc7_release.rc72_native_additional_plugins acquire --repo-root . | tee "$TOOLS/plugin-additions-acquire.json"
"$PYBIN" -m rc7_release.rc72_native_additional_plugins inspect --repo-root . | tee "$TOOLS/plugin-additions-inspect.json"
"$PYBIN" - "$ROOT/rc7_release/vendor/dsh-optional-plugins-payload.manifest.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1],encoding="utf-8"))
if m.get("status")!="PASS" or m.get("missing"):
    raise SystemExit("DSH_OPTIONAL_PLUGINS_NOT_ALL_BUNDLED")
print("DSH_OPTIONAL_PLUGIN_FOUR_REQUIRED_PASS")
PY
# The error-handling Skill is a distinct (non-npm) MIT-licensed asset.
git clone --depth 1 https://github.com/qufei1993/skills-hub.git "$TOOLS/error-handling-source"
git -C "$TOOLS/error-handling-source" fetch --depth=1 origin a8cee8831f288376b8cc5d7d0d28485a03911c1e
git -C "$TOOLS/error-handling-source" checkout --detach a8cee8831f288376b8cc5d7d0d28485a03911c1e
test -f "$TOOLS/error-handling-source/skills/dsh-error-handling/SKILL.md"
mkdir -p "$ROOT/rc7_release/vendor"
cp -R "$TOOLS/error-handling-source/skills/dsh-error-handling" "$ROOT/rc7_release/vendor/dsh-error-handling-skill"


# Official native Node.js archives include Windows CMD/PowerShell shims for cross-platform distribution.
# Strip those only from the copied native Node and npm/pnpm/Playwright tool directories.
# The later stage gate independently rejects any remaining nonnative file or nested archive entry.
find "$NODE_ROOT" "$NODE_EXEC" -type f \\
  \\( -iname '*.cmd' -o -iname '*.bat' -o -iname '*.ps1' -o -iname '*.exe' -o -iname '*.dll' -o -iname '*.msi' -o -iname '*.pdb' \\) -delete

# Tool versions and source evidence are recorded before packaging.
"$JAVA_BIN" -version 2>"$TOOLS/java-version.txt"
"$MAVEN_ROOT/bin/mvn" -version > "$TOOLS/maven-version.txt"
"$ALLURE_BIN" --version > "$TOOLS/allure-version.txt"
"$K6_BIN" version > "$TOOLS/k6-version.txt"
"$RG_BIN" --version > "$TOOLS/rg-version.txt"
if "$TOOLS/$CG_ASSET" --version > "$TOOLS/codegraph-version.txt" 2>&1; then :; else "$TOOLS/$CG_ASSET" --help > "$TOOLS/codegraph-version.txt" 2>&1; fi
"$TOOLS/$CG_ASSET" --help > "$TOOLS/codegraph-help.txt"
"$ZAP_BIN" -version > "$TOOLS/zap-version.txt" 2>&1 || true
"$BSK_BIN" --version > "$TOOLS/bsk-version.txt"
"$NODEBIN" --version > "$TOOLS/node-version.txt"
"$PYBIN" --version > "$TOOLS/python-version.txt"

# Build one platform/architecture-specific sealed package.
STAGE="$TOOLS/stage"
mkdir -p "$STAGE"
SOURCE_COMMIT="${GITHUB_SHA:-$(git rev-parse HEAD)}"
export PFC_RC72_TOOL_VERSIONS_JSON="$("$PYBIN" - "$TOOLS" <<'PY'
import json,sys,pathlib
r=pathlib.Path(sys.argv[1])
names=("python-version.txt","node-version.txt","bsk-version.txt","java-version.txt","maven-version.txt","allure-version.txt","k6-version.txt","rg-version.txt","zap-version.txt","codegraph-version.txt")
print(json.dumps({n.removesuffix("-version.txt"): (r/n).read_text(errors="replace").strip() for n in names},sort_keys=True))
PY
)"
"$PYBIN" -m rc7_release.rc72_native_field_portable stage \
  --repo-root "$ROOT" --output "$STAGE" --source-commit "$SOURCE_COMMIT" \
  --python-root "$PYROOT" --node-root "$NODE_ROOT" --bsk-cli "$BSK_BIN" \
  --browser-root "$BROWSER_ROOT" --extension-root "$EXT_ROOT" --node-execution-root "$NODE_EXEC" \
  --java-root "$JAVA_ROOT" --maven-root "$MAVEN_ROOT" --maven-repository "$M2" \
  --allure-root "$ALLURE_ROOT" --k6-binary "$K6_BIN" --zap-root "$(dirname "$(dirname "$ZAP_BIN")")" \
  --ripgrep-binary "$RG_BIN" --codegraph-binary "$TOOLS/$CG_ASSET" \
  | tee "$TOOLS/stage-evidence.json"

PACKAGE_NAME="PFC-AITest-DSH-RC7.2-$([ "$PLATFORM" = linux ] && echo LINUX || echo MACOS)-$([ "$ARCH" = x86_64 ] && echo X86_64 || echo ARM64)-FIELD"
PACKAGE="$STAGE/$PACKAGE_NAME"
"$PYBIN" -m rc7_release.rc72_native_field_portable verify --package-root "$PACKAGE" --expected-source-commit "$SOURCE_COMMIT" | tee "$TOOLS/clean-identity.json"
PFC_RC72_NATIVE_PROBE_ONLY=1 bash "$PACKAGE/packaging/rc7.2/AITEST.sh" --verify-only | tee "$TOOLS/launcher-probe.txt"
"$PACKAGE/workspace-template/runtime/node/bin/node" -e '
const {chromium}=require(process.argv[1]);
(async()=>{const b=await chromium.launch({headless:true,args:process.platform==="linux"?["--no-sandbox"]:[]});const p=await b.newPage();await p.goto("data:text/html,<title>RC72 Native Offline</title>");if(await p.title()!=="RC72 Native Offline")throw Error("NATIVE_CHROMIUM_SMOKE_FAILED");await b.close();console.log("NATIVE_PLAYWRIGHT_CHROMIUM_OFFLINE_PASS")})().catch(e=>{console.error(e);process.exit(1)});
' "$PACKAGE/workspace-template/runtime/node-execution/node_modules/playwright" | tee "$TOOLS/browser-smoke.txt"
"$PACKAGE/workspace-template/runtime/k6/k6" version >/dev/null
"$PACKAGE/workspace-template/runtime/ripgrep/rg" --version | grep -F 'ripgrep 15.2.0'
"$PACKAGE/workspace-template/runtime/code-intelligence/codegraph/$CG_ASSET" --help >/dev/null
"$PACKAGE/workspace-template/runtime/java/bin/java" -version >/dev/null 2>&1
"$PACKAGE/workspace-template/runtime/maven/bin/mvn" -version >/dev/null
"$PACKAGE/workspace-template/runtime/python/bin/python3" -B -c "import requests,pytest,openpyxl,docx,pptx,pypdf,PIL,numpy,onnxruntime,cv2,rapidocr_onnxruntime;print('NATIVE_PACKAGE_PYTHON_IMPORTS_PASS')"
"$PACKAGE/workspace-template/runtime/maven/bin/mvn" -q -o \
  -s "$PACKAGE/packaging/rc7/maven-offline-settings.xml" \
  "-Dmaven.repo.local=$PACKAGE/workspace-template/runtime/maven-repository" \
  -f "$SEED/pom.xml" test
"$PACKAGE/workspace-template/runtime/allure/bin/allure" --version >/dev/null
"$PACKAGE/workspace-template/runtime/zap/$(basename "$(dirname "$ZAP_BIN")")/zap.sh" -version >/dev/null 2>&1 || true

ARCHIVE="$DIST/RC72-NATIVE-FIELD-$([ "$PLATFORM" = linux ] && echo LINUX || echo MACOS)-$([ "$ARCH" = x86_64 ] && echo X86_64 || echo ARM64)-${SOURCE_COMMIT:0:12}.tar.gz"
mkdir -p "$DIST"
"$PYBIN" -m rc7_release.rc72_native_field_portable archive --package-root "$PACKAGE" --output "$ARCHIVE" | tee "$TOOLS/archive-evidence.json"
cp "$TOOLS/stage-evidence.json" "$TOOLS/clean-identity.json" "$TOOLS/launcher-probe.txt" "$TOOLS/browser-smoke.txt" "$TOOLS/archive-evidence.json" "$DIST/"
cp "$TOOLS"/*-version.txt "$DIST/"
echo "NATIVE_FIELD_ARTIFACT_READY=$ARCHIVE"
