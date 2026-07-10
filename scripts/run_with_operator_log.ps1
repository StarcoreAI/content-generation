param(
    [Parameter(Mandatory = $true)]
    [string]$Name,

    [Parameter(Mandatory = $true)]
    [string]$ScriptPath,

    [string[]]$ScriptArgs = @()
)

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

$safeName = $Name -replace "[^A-Za-z0-9._-]", "-"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDir "$safeName-$timestamp.log"

Write-Host "[GEO] log file: $logFile"
Write-Host "[GEO] old operator logs expire after $RetentionDays days."

$env:GEO_OPERATOR_LOG_ACTIVE = "1"
$env:GEO_OPERATOR_NO_PAUSE = "1"

$commandLine = '"' + $ScriptPath + '" --logged'
foreach ($arg in $ScriptArgs) {
    $commandLine += ' "' + ($arg -replace '"', '\"') + '"'
}

& cmd.exe /d /c $commandLine 2>&1 | Tee-Object -FilePath $logFile
$exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] command failed."
    Write-Host "[GEO] Please send this log file to support:"
    Write-Host "[GEO] $logFile"
}

exit $exitCode
