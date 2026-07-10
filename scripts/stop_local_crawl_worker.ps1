$ErrorActionPreference = "Stop"

$patterns = @(
    'scripts[\\/]local_crawl_worker\.py',
    'node_auth_preflight\.mjs',
    'ai-search-crawler.*src[\\/]index\.js'
)

try {
    $allProcesses = @(Get-CimInstance Win32_Process)
} catch {
    Write-Host ("[ERROR] cannot read process list: {0}" -f $_.Exception.Message)
    Write-Host "[ERROR] close the worker window manually, or run this script in a normal PowerShell window."
    exit 1
}
$rootProcesses = @()
foreach ($process in $allProcesses) {
    $commandLine = [string]$process.CommandLine
    if (-not $commandLine) {
        continue
    }
    foreach ($pattern in $patterns) {
        if ($commandLine -match $pattern) {
            $rootProcesses += $process
            break
        }
    }
}

if (-not $rootProcesses) {
    Write-Host "[GEO] no local crawl worker process found."
    exit 0
}

$childrenByParent = @{}
$processById = @{}
foreach ($process in $allProcesses) {
    $processId = [int]$process.ProcessId
    $parentId = [int]$process.ParentProcessId
    $processById[$processId] = $process
    if (-not $childrenByParent.ContainsKey($parentId)) {
        $childrenByParent[$parentId] = New-Object System.Collections.Generic.List[object]
    }
    $childrenByParent[$parentId].Add($process)
}

$seenProcessIds = @{}
$orderedProcessIds = New-Object System.Collections.Generic.List[int]

function Add-ProcessTree {
    param([int]$TargetProcessId)

    if ($seenProcessIds.ContainsKey($TargetProcessId)) {
        return
    }
    $seenProcessIds[$TargetProcessId] = $true

    if ($childrenByParent.ContainsKey($TargetProcessId)) {
        foreach ($child in $childrenByParent[$TargetProcessId]) {
            Add-ProcessTree -TargetProcessId ([int]$child.ProcessId)
        }
    }

    [void]$orderedProcessIds.Add($TargetProcessId)
}

foreach ($process in $rootProcesses) {
    Add-ProcessTree -TargetProcessId ([int]$process.ProcessId)
}

$failed = $false
foreach ($processId in $orderedProcessIds) {
    if ($processId -eq $PID) {
        continue
    }
    $process = $processById[$processId]
    $name = if ($process) { $process.Name } else { "unknown" }
    $liveProcess = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $liveProcess) {
        continue
    }
    try {
        Write-Host ("[GEO] stopping PID {0} {1}" -f $processId, $name)
        Stop-Process -InputObject $liveProcess -Force -ErrorAction Stop
    } catch {
        Write-Host ("[ERROR] failed to stop PID {0}: {1}" -f $processId, $_.Exception.Message)
        $failed = $true
    }
}

if ($failed) {
    exit 1
}
exit 0
