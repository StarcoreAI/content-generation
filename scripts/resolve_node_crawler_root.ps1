$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$candidatePaths = New-Object System.Collections.Generic.List[string]
$seen = @{}

function Add-Candidate {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return
    }
    try {
        $resolved = (Resolve-Path -LiteralPath $PathValue -ErrorAction Stop).Path
    } catch {
        return
    }
    $key = $resolved.ToLowerInvariant()
    if (-not $seen.ContainsKey($key)) {
        $seen[$key] = $true
        [void]$candidatePaths.Add($resolved)
    }
}

function Test-CrawlerRoot {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $false
    }
    return Test-Path -LiteralPath (Join-Path $PathValue "src\adapters\index.js")
}

$searchBases = New-Object System.Collections.Generic.List[string]
[void]$searchBases.Add($projectRoot)
[void]$searchBases.Add((Split-Path -Parent $projectRoot))
$grandParent = Split-Path -Parent (Split-Path -Parent $projectRoot)
if ($grandParent) {
    [void]$searchBases.Add($grandParent)
}

foreach ($base in $searchBases) {
    if ([string]::IsNullOrWhiteSpace($base) -or -not (Test-Path -LiteralPath $base)) {
        continue
    }
    Get-ChildItem -LiteralPath $base -Directory -Filter "ai-search-crawler*" -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Candidate $_.FullName }
}

Add-Candidate $env:GEO_NODE_CRAWLER_ROOT

$userSearchBases = @(
    if ($env:USERPROFILE) {
        Join-Path $env:USERPROFILE "OneDrive\programing"
        Join-Path $env:USERPROFILE "OneDrive\programming"
    }
)

foreach ($base in $userSearchBases) {
    if ([string]::IsNullOrWhiteSpace($base) -or -not (Test-Path -LiteralPath $base)) {
        continue
    }
    Get-ChildItem -LiteralPath $base -Directory -Filter "ai-search-crawler*" -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Candidate $_.FullName }
}

foreach ($candidate in $candidatePaths) {
    if (Test-CrawlerRoot $candidate) {
        Write-Output $candidate
        exit 0
    }
}

exit 1
