$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ("[GEO] {0}" -f $Message)
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-CheckedCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $projectRoot,
        [int]$TimeoutSeconds = 0
    )

    $oldLocation = Get-Location
    try {
        Set-Location -LiteralPath $WorkingDirectory
        Write-Host ("[GEO] > {0} {1}" -f $FilePath, ($Arguments -join " "))
        if ($TimeoutSeconds -gt 0) {
            $job = Start-Job -ScriptBlock {
                param($JobWorkingDirectory, $JobFilePath, $JobArguments)
                Set-Location -LiteralPath $JobWorkingDirectory
                & $JobFilePath @JobArguments 2>&1
                $code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
                if ($code -ne 0) {
                    throw ("Command failed with exit code {0}: {1} {2}" -f $code, $JobFilePath, ($JobArguments -join " "))
                }
            } -ArgumentList $WorkingDirectory, $FilePath, $Arguments

            $startedAt = Get-Date
            $nextNoticeAt = $startedAt.AddSeconds(60)
            while ($true) {
                $finished = Wait-Job $job -Timeout 5
                Receive-Job $job
                if ($finished) {
                    break
                }
                $now = Get-Date
                if ($now -ge $nextNoticeAt) {
                    $elapsed = [int]($now - $startedAt).TotalSeconds
                    Write-Host ("[GEO] still working after {0}s: {1} {2}" -f $elapsed, $FilePath, ($Arguments -join " "))
                    $nextNoticeAt = $now.AddSeconds(60)
                }
                if (($now - $startedAt).TotalSeconds -ge $TimeoutSeconds) {
                    Stop-Job $job -ErrorAction SilentlyContinue
                    Remove-Job $job -Force -ErrorAction SilentlyContinue
                    throw ("Command timed out after {0} seconds: {1} {2}" -f $TimeoutSeconds, $FilePath, ($Arguments -join " "))
                }
            }

            Receive-Job $job
            if ($job.State -eq "Failed") {
                $reason = $job.ChildJobs[0].JobStateInfo.Reason
                Remove-Job $job -Force -ErrorAction SilentlyContinue
                throw $reason
            }
            Remove-Job $job -Force -ErrorAction SilentlyContinue
            return
        }

        & $FilePath @Arguments
        $code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
        if ($code -ne 0) {
            throw ("Command failed with exit code {0}: {1} {2}" -f $code, $FilePath, ($Arguments -join " "))
        }
    } finally {
        Set-Location $oldLocation
    }
}

function Update-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = @($machinePath, $userPath) -join ";"
}

function Install-WingetPackage {
    param(
        [string]$PackageId,
        [string]$DisplayName
    )

    if (-not (Test-Command "winget")) {
        throw "winget was not found. Install Python 3.12 and Node.js LTS manually, then run setup_operator_windows.bat again."
    }

    Write-Step ("Installing {0} with winget" -f $DisplayName)
    Invoke-CheckedCommand "winget" @(
        "install",
        "--id", $PackageId,
        "--exact",
        "--source", "winget",
        "--accept-package-agreements",
        "--accept-source-agreements"
    )
    Update-ProcessPath
}

function Test-PythonReady {
    if (-not (Test-Command "python")) {
        return $false
    }
    try {
        & python --version | Out-Host
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Test-NodeReady {
    if (-not (Test-Command "node")) {
        return $false
    }
    try {
        & node --version | Out-Host
        return $true
    } catch {
        return $false
    }
}

function Assert-PackageFile {
    param(
        [string]$Path,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw ("Operator package is incomplete: missing {0}.`nMissing path: {1}`nDownload the latest operator package again instead of running npm or Playwright install manually." -f $Description, $Path)
    }
}

function Get-PackagedChromium {
    param([string]$BrowserRoot)
    if (-not (Test-Path -LiteralPath $BrowserRoot)) {
        return $null
    }
    Get-ChildItem -LiteralPath $BrowserRoot -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue |
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName "chrome-win64\chrome.exe")) -or
            (Test-Path -LiteralPath (Join-Path $_.FullName "chrome-win\chrome.exe"))
        } |
        Select-Object -First 1
}

function Resolve-CrawlerRoot {
    $resolver = Join-Path $projectRoot "scripts\resolve_node_crawler_root.ps1"
    $result = & powershell -NoProfile -ExecutionPolicy Bypass -File $resolver
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($result)) {
        throw "Node crawler folder was not found. Put geo_v2-pro and ai-search-crawler in the same parent folder, then run setup again."
    }
    return [string]$result
}

Write-Step "Checking project files"
$requiredFiles = @(
    "start_local_crawl_worker.bat",
    "stop_local_crawl_worker.bat",
    "scripts\first_login_all_platforms.bat",
    "scripts\local_crawl_worker.py",
    "scripts\node_auth_preflight.mjs",
    "scripts\local_worker_control_panel.ps1",
    "scripts\stop_local_crawl_worker.ps1",
    "scripts\resolve_node_crawler_root.ps1"
)
foreach ($relativePath in $requiredFiles) {
    $fullPath = Join-Path $projectRoot $relativePath
    if (-not (Test-Path -LiteralPath $fullPath)) {
        throw ("Missing required file: {0}" -f $relativePath)
    }
}

Write-Step "Checking Python"
if (-not (Test-PythonReady)) {
    Install-WingetPackage "Python.Python.3.12" "Python 3.12"
}
if (-not (Test-PythonReady)) {
    throw "Python is still not available. Reopen this folder in a new terminal and run setup_operator_windows.bat again."
}

Write-Step "Checking Node.js"
if (-not (Test-NodeReady)) {
    Install-WingetPackage "OpenJS.NodeJS.LTS" "Node.js LTS"
}
if (-not (Test-NodeReady)) {
    throw "Node.js is still not available. Reopen this folder in a new terminal and run setup_operator_windows.bat again."
}

Write-Step "Detecting Node crawler folder"
$crawlerRoot = Resolve-CrawlerRoot
Write-Host ("[GEO] crawler root: {0}" -f $crawlerRoot)

$packageJson = Join-Path $crawlerRoot "package.json"
if (-not (Test-Path -LiteralPath $packageJson)) {
    throw ("Missing Node crawler package.json: {0}" -f $packageJson)
}

Write-Step "Checking packaged Node dependencies"
Assert-PackageFile (Join-Path $crawlerRoot "node_modules\playwright\package.json") "node_modules\playwright"
Assert-PackageFile (Join-Path $crawlerRoot "node_modules\playwright-core\package.json") "node_modules\playwright-core"
Write-Host "[GEO] packaged node_modules are ready."

Write-Step "Checking packaged Playwright Chromium"
$browserRoot = Join-Path $crawlerRoot "ms-playwright"
$chromiumDir = Get-PackagedChromium $browserRoot
if ($null -eq $chromiumDir) {
    throw ("Operator package is incomplete: missing packaged Playwright Chromium.`nExpected path like: {0}`nDownload the latest operator package again instead of running npx playwright install manually." -f (Join-Path $browserRoot "chromium-*\chrome-win64\chrome.exe"))
}
Write-Host ("[GEO] PLAYWRIGHT_BROWSERS_PATH will be: {0}" -f $browserRoot)
Write-Host ("[GEO] packaged Chromium: {0}" -f $chromiumDir.FullName)

Write-Step "Preparing storage folder"
$storageDir = Join-Path $crawlerRoot "storage"
if (-not (Test-Path -LiteralPath $storageDir)) {
    [void](New-Item -ItemType Directory -Path $storageDir -Force)
}
Write-Host ("[GEO] STORAGE_STATE_PATH will be: {0}" -f (Join-Path $storageDir "state.json"))

Write-Step "Setup complete"
Write-Host "[GEO] The setup launcher will start platform login next."
Write-Host "[GEO] Daily use after that: run start_local_crawl_worker.bat."
Write-Host "[GEO] The worker will ask for cloud username and password every time."
