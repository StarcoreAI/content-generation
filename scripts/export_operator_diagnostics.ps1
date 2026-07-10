$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $projectRoot "operator_logs"
[void](New-Item -ItemType Directory -Path $logDir -Force)

$RetentionDays = 14
if ($env:GEO_OPERATOR_LOG_RETENTION_DAYS) {
    try {
        $RetentionDays = [Math]::Max(1, [int]$env:GEO_OPERATOR_LOG_RETENTION_DAYS)
    } catch {
        $RetentionDays = 14
    }
}

$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff -and @(".log", ".zip") -contains $_.Extension.ToLowerInvariant() } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$workDir = Join-Path $logDir "diagnostic-$timestamp"
$zipPath = Join-Path $logDir "GEO-diagnostic-$timestamp.zip"
$envPath = Join-Path $workDir "environment.txt"
$copiedLogsDir = Join-Path $workDir "logs"

if (Test-Path -LiteralPath $workDir) {
    Remove-Item -LiteralPath $workDir -Recurse -Force
}
[void](New-Item -ItemType Directory -Path $workDir -Force)
[void](New-Item -ItemType Directory -Path $copiedLogsDir -Force)

function Add-Line {
    param([string]$Value = "")
    Add-Content -LiteralPath $envPath -Value $Value -Encoding UTF8
}

function Add-CommandOutput {
    param(
        [string]$Label,
        [string]$Command
    )
    Add-Line ""
    Add-Line "## $Label"
    try {
        $output = Invoke-Expression $Command 2>&1 | Out-String
        Add-Line ($output.Trim())
    } catch {
        Add-Line ("ERROR: {0}" -f $_.Exception.Message)
    }
}

Add-Line "GEO operator diagnostics"
Add-Line ("created_at={0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Add-Line ("project_root={0}" -f $projectRoot)
Add-Line ("log_dir={0}" -f $logDir)
Add-Line ("log_retention_days={0}" -f $RetentionDays)
$crawlerRootEnv = ""
if ($env:GEO_NODE_CRAWLER_ROOT) {
    $crawlerRootEnv = $env:GEO_NODE_CRAWLER_ROOT
}
Add-Line ("GEO_NODE_CRAWLER_ROOT={0}" -f $crawlerRootEnv)

$crawlerRoot = ""
try {
    $resolver = Join-Path $projectRoot "scripts\resolve_node_crawler_root.ps1"
    $crawlerRoot = (& powershell -NoProfile -ExecutionPolicy Bypass -File $resolver 2>&1 | Out-String).Trim()
} catch {
    $crawlerRoot = "ERROR: " + $_.Exception.Message
}

Add-Line ("resolved_crawler_root={0}" -f $crawlerRoot)
if ($crawlerRoot -and -not $crawlerRoot.StartsWith("ERROR:")) {
    Add-Line ("crawler_package_json_exists={0}" -f (Test-Path -LiteralPath (Join-Path $crawlerRoot "package.json")))
    Add-Line ("crawler_adapter_index_exists={0}" -f (Test-Path -LiteralPath (Join-Path $crawlerRoot "src\adapters\index.js")))
    Add-Line ("playwright_module_exists={0}" -f (Test-Path -LiteralPath (Join-Path $crawlerRoot "node_modules\playwright")))
    $browserRoot = Join-Path $crawlerRoot "ms-playwright"
    $chromiumExe = Get-ChildItem -LiteralPath $browserRoot -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue |
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName "chrome-win64\chrome.exe")) -or
            (Test-Path -LiteralPath (Join-Path $_.FullName "chrome-win\chrome.exe"))
        } |
        Select-Object -First 1
    Add-Line ("playwright_browsers_path={0}" -f $browserRoot)
    Add-Line ("playwright_browser_root_exists={0}" -f (Test-Path -LiteralPath $browserRoot))
    Add-Line ("playwright_chromium_exists={0}" -f ($null -ne $chromiumExe))
    Add-Line ("storage_dir_exists={0}" -f (Test-Path -LiteralPath (Join-Path $crawlerRoot "storage")))
}

Add-CommandOutput "python --version" "python --version"
Add-CommandOutput "node --version" "node --version"
Add-CommandOutput "npm --version" "npm --version"
Add-CommandOutput "npx --version" "npx --version"

Get-ChildItem -LiteralPath $logDir -File -Filter "*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 20 |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $copiedLogsDir -Force }

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path (Join-Path $workDir "*") -DestinationPath $zipPath -Force
Remove-Item -LiteralPath $workDir -Recurse -Force

Write-Host "[GEO] Diagnostic package created:"
Write-Host "[GEO] $zipPath"
Write-Host "[GEO] Please send this zip file to support."
