$ErrorActionPreference = 'Stop'
$root = "$env:RUNNER_TEMP\rc7-final-payloads"
New-Item -ItemType Directory -Force $root | Out-Null
"PFC_RC7_PAYLOAD_ROOT=$root" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append

$nodeHome = Split-Path -Parent (Get-Command node).Source
$mvnCmd = (Get-Command mvn).Source
$mvnHome = Split-Path -Parent (Split-Path -Parent $mvnCmd)
"PFC_RC7_BUILD_NODE_DIR=$nodeHome" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"PFC_RC7_BUILD_JDK_DIR=$env:JAVA_HOME" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"PFC_RC7_BUILD_MAVEN_DIR=$mvnHome" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append

python -m pip install --disable-pip-version-check pytest requests python-docx openpyxl python-pptx pypdf "numpy<2" "onnxruntime<1.20" "opencv-python-headless<4.11" rapidocr-onnxruntime
if ($LASTEXITCODE -ne 0) { throw 'Python runtime dependency installation failed' }
python -c "import pytest,docx,openpyxl,pptx,pypdf,cv2,onnxruntime,rapidocr_onnxruntime; print('PYTHON_DOCUMENT_VISION_OK')"
if ($LASTEXITCODE -ne 0) { throw 'Python document/vision provider smoke failed' }

$pluginRoot = "$root\dsh-plugins"
New-Item -ItemType Directory -Force $pluginRoot | Out-Null
npm init -y --prefix $pluginRoot | Out-Null
$required = @(
  'dsh-routing-suite',
  '@wxg-prc-cpg/browser-skill-dsh-plugin',
  'dsh-context',
  'dsh-plugin-bridge',
  '@nanmicoder/dsh-agent-teams'
)
foreach ($pkg in $required) {
  npm install --prefix $pluginRoot --legacy-peer-deps --no-audit --no-fund "$pkg@latest"
  if ($LASTEXITCODE -ne 0) { throw "Required DSH plugin install failed: $pkg" }
}
$diagnostic = '@perrylink/dsh-plugin-doctor'
npm install --prefix $pluginRoot --legacy-peer-deps --no-audit --no-fund "$diagnostic@latest"
$doctorState = if ($LASTEXITCODE -eq 0) { 'BUNDLED_DIAGNOSTIC' } else { 'OPTIONAL_NOT_RESOLVED' }
$optional = @('dsh-vision-router','dsh-plugin-anydoc','dsh-memento','dsh-error-handling')
$optionalState = @{ $diagnostic = $doctorState }
foreach ($pkg in $optional) {
  npm install --prefix $pluginRoot --legacy-peer-deps --no-audit --no-fund "$pkg@latest"
  $optionalState[$pkg] = if ($LASTEXITCODE -eq 0) { 'BUNDLED_DISABLED_BY_DEFAULT' } else { 'OPTIONAL_NOT_RESOLVED' }
}
$optionalState | ConvertTo-Json | Set-Content -Encoding utf8 "$pluginRoot\OPTIONAL_PLUGIN_STATE.json"
"PFC_RC7_BUILD_DSH_PLUGINS_DIR=$pluginRoot" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append

$execRoot = "$root\node-execution"
New-Item -ItemType Directory -Force $execRoot | Out-Null
npm init -y --prefix $execRoot | Out-Null
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1'
$env:GITNEXUS_SKIP_OPTIONAL_GRAMMARS='1'
npm install --prefix $execRoot --legacy-peer-deps --no-audit --no-fund playwright@latest gitnexus@latest
if ($LASTEXITCODE -ne 0) { throw 'Playwright/GitNexus vendor install failed' }
node -e "require('$($execRoot.Replace('\','/'))/node_modules/playwright'); console.log('PLAYWRIGHT_NODE_OK')"
if ($LASTEXITCODE -ne 0) { throw 'Playwright Node import failed' }
"PFC_RC7_BUILD_EXECUTION_NODE_DIR=$execRoot" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append

$headers = @{ 'User-Agent'='rc7-final-turnkey-builder'; 'Accept'='application/vnd.github+json' }
function Get-LatestRelease([string]$repo) {
  $rel = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$repo/releases/latest"
  if ($rel.draft -or $rel.prerelease) { throw "$repo latest release is not stable" }
  return $rel
}
function Get-ReleaseAsset([string]$repo,[string]$pattern,[string]$name) {
  $rel = Get-LatestRelease $repo
  $asset = $rel.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
  if (-not $asset) { throw "$name release asset missing ($pattern)" }
  return @{ release=$rel; asset=$asset }
}

$cgRel = Get-LatestRelease 'codegraph-ai/CodeGraph'
$cgAsset = $cgRel.assets | Where-Object { $_.name -eq 'codegraph-server-win32-x64.exe' } | Select-Object -First 1
if (-not $cgAsset) { throw 'CodeGraph Windows x64 release asset missing' }
$expected = [string]$cgAsset.digest
if (-not $expected.StartsWith('sha256:')) { throw 'CodeGraph release digest missing' }
$expected = $expected.Substring(7).ToLowerInvariant()
$cgTarget = "$root\codegraph-server-win32-x64.exe"
Invoke-WebRequest -Headers $headers -Uri $cgAsset.browser_download_url -OutFile $cgTarget
$actual = (Get-FileHash -Algorithm SHA256 $cgTarget).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "CodeGraph digest mismatch expected=$expected actual=$actual" }
"PFC_RC7_BUILD_CODEGRAPH_BIN=$cgTarget" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
"PFC_RC7_BUILD_CODEGRAPH_VERSION=$($cgRel.tag_name)" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
"PFC_RC7_BUILD_CODEGRAPH_SHA256=$expected" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

$index = Invoke-RestMethod -Uri 'https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json'
$stable = $index.channels.Stable
$chromeDl = $stable.downloads.chrome | Where-Object { $_.platform -eq 'win64' } | Select-Object -First 1
if (-not $chromeDl.url) { throw 'Chrome for Testing win64 payload missing' }
$browserRoot = "$root\browser"
$chromeZip = "$root\chrome-win64.zip"
Invoke-WebRequest -Uri $chromeDl.url -OutFile $chromeZip
Expand-Archive -Path $chromeZip -DestinationPath $browserRoot -Force
$browserDir = Join-Path $browserRoot 'chrome-win64'
$chrome = Join-Path $browserDir 'chrome.exe'
if (-not (Test-Path $chrome)) { throw 'Chrome executable missing' }
$chromeDigest = (Get-FileHash -Algorithm SHA256 $chrome).Hash.ToLowerInvariant()
"PFC_RC7_BUILD_BROWSER_DIR=$browserDir" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
"PFC_RC7_BUILD_BROWSER_VERSION=$($stable.version)" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
"PFC_RC7_BUILD_BROWSER_SHA256=$chromeDigest" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

$bsReleases = Invoke-RestMethod -Headers $headers -Uri 'https://api.github.com/repos/Tencent/BrowserSkill/releases?per_page=30'
$cliRel = $bsReleases | Where-Object { -not $_.draft -and -not $_.prerelease -and $_.tag_name -like 'cli-v*' } | Select-Object -First 1
$cliAsset = $cliRel.assets | Where-Object { $_.name -like '*x86_64-pc-windows-msvc.zip' } | Select-Object -First 1
if (-not $cliAsset) { throw 'BrowserSkill Windows CLI release missing' }
$bskZip="$root\bsk.zip"; $bskRoot="$root\browserskill"
Invoke-WebRequest -Uri $cliAsset.browser_download_url -OutFile $bskZip
Expand-Archive $bskZip $bskRoot -Force
if (-not (Get-ChildItem $bskRoot -Recurse -Filter bsk.exe | Select-Object -First 1)) { throw 'bsk.exe missing' }
"PFC_RC7_BUILD_BROWSER_SKILL_DIR=$bskRoot" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
$extRel = $bsReleases | Where-Object { -not $_.draft -and $_.tag_name -like 'ext-v*' } | Select-Object -First 1
if (-not $extRel) { throw 'BrowserSkill extension release missing' }
$extAsset = $extRel.assets | Where-Object { $_.name -like '*.zip' } | Select-Object -First 1
if (-not $extAsset) { throw 'BrowserSkill extension zip missing' }
$extZip="$root\bsk-ext.zip"; $extRoot="$root\browserskill-extension"
Invoke-WebRequest -Uri $extAsset.browser_download_url -OutFile $extZip
Expand-Archive $extZip $extRoot -Force
if (-not (Get-ChildItem $extRoot -Recurse -File | Select-Object -First 1)) { throw 'BrowserSkill extension payload empty' }
"PFC_RC7_BUILD_BROWSER_SKILL_EXTENSION_DIR=$extRoot" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

$m2 = "$root\maven-repository"
$mvnProj = "$root\maven-seed"
New-Item -ItemType Directory -Force "$mvnProj\src\test\java\rc7" | Out-Null
@'
<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion><groupId>rc7</groupId><artifactId>seed</artifactId><version>1</version><properties><maven.compiler.source>8</maven.compiler.source><maven.compiler.target>8</maven.compiler.target></properties><dependencies><dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.11.4</version><scope>test</scope></dependency></dependencies><build><plugins><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.5.2</version></plugin><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-failsafe-plugin</artifactId><version>3.5.2</version></plugin><plugin><groupId>org.jacoco</groupId><artifactId>jacoco-maven-plugin</artifactId><version>0.8.12</version></plugin></plugins></build></project>
'@ | Set-Content -Encoding utf8 "$mvnProj\pom.xml"
'package rc7; import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; class SeedTest { @Test void ok(){ assertEquals(2,1+1); } }' | Set-Content -Encoding utf8 "$mvnProj\src\test\java\rc7\SeedTest.java"
mvn -q -f "$mvnProj\pom.xml" "-Dmaven.repo.local=$m2" test
if ($LASTEXITCODE -ne 0) { throw 'Maven JUnit seed failed' }
mvn -q -f "$mvnProj\pom.xml" "-Dmaven.repo.local=$m2" dependency:go-offline
if ($LASTEXITCODE -ne 0) { throw 'Maven offline bootstrap seed failed' }
"PFC_RC7_BUILD_M2_DIR=$m2" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

$allureObj = Get-ReleaseAsset 'allure-framework/allure2' 'allure-*.zip' 'Allure'
$allureZip="$root\allure.zip"; $allureOut="$root\allure-out"
Invoke-WebRequest -Uri $allureObj.asset.browser_download_url -OutFile $allureZip
Expand-Archive $allureZip $allureOut -Force
$allureBat = Get-ChildItem $allureOut -Recurse -Filter allure.bat | Select-Object -First 1
if (-not $allureBat) { throw 'allure.bat missing' }
"PFC_RC7_BUILD_ALLURE_DIR=$($allureBat.Directory.Parent.FullName)" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

$k6Obj = Get-ReleaseAsset 'grafana/k6' '*windows-amd64.zip' 'k6'
$k6Zip="$root\k6.zip"; $k6Out="$root\k6-out"
Invoke-WebRequest -Uri $k6Obj.asset.browser_download_url -OutFile $k6Zip
Expand-Archive $k6Zip $k6Out -Force
$k6Exe = Get-ChildItem $k6Out -Recurse -Filter k6.exe | Select-Object -First 1
if (-not $k6Exe) { throw 'k6.exe missing' }
"PFC_RC7_BUILD_K6_DIR=$($k6Exe.Directory.FullName)" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

$zapObj = Get-ReleaseAsset 'zaproxy/zaproxy' '*Crossplatform.zip' 'ZAP'
$zapZip="$root\zap.zip"; $zapOut="$root\zap-out"
Invoke-WebRequest -Uri $zapObj.asset.browser_download_url -OutFile $zapZip
Expand-Archive $zapZip $zapOut -Force
$zapBat = Get-ChildItem $zapOut -Recurse -Filter zap.bat | Select-Object -First 1
if (-not $zapBat) { throw 'zap.bat missing' }
"PFC_RC7_BUILD_ZAP_DIR=$($zapBat.Directory.FullName)" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

$rgObj = Get-ReleaseAsset 'BurntSushi/ripgrep' '*x86_64-pc-windows-msvc.zip' 'ripgrep'
$rgZip="$root\rg.zip"; $rgOut="$root\rg-out"
Invoke-WebRequest -Uri $rgObj.asset.browser_download_url -OutFile $rgZip
Expand-Archive $rgZip $rgOut -Force
$rgExe = Get-ChildItem $rgOut -Recurse -Filter rg.exe | Select-Object -First 1
if (-not $rgExe) { throw 'rg.exe missing' }
"PFC_RC7_BUILD_RIPGREP_DIR=$($rgExe.Directory.FullName)" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

Write-Host 'FINAL_PAYLOAD_ASSEMBLY_READY'
