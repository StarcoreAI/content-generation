$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if (-not $env:GEO_HOST) {
    $env:GEO_HOST = "0.0.0.0"
}
if (-not $env:GEO_PORT) {
    $env:GEO_PORT = "5000"
}
$hostValue = $env:GEO_HOST
$port = [int]$env:GEO_PORT
Set-Location $root

function Get-ListenerPid {
    param([int]$Port)

    try {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($listener -and $listener.OwningProcess) {
            return [int]$listener.OwningProcess
        }
    }
    catch {
        # Fall back to netstat below.
    }

    $line = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING\s+\d+$" | Select-Object -First 1
    if ($line) {
        $parts = $line.ToString().Trim() -split "\s+"
        return [int]$parts[-1]
    }

    return $null
}

function Save-Pid {
    param([int]$ProcessId)
    Set-Content -Path (Join-Path $root "server.pid") -Value $ProcessId -Encoding ASCII
}

function Test-ExcludedLanIp {
    param([string]$IpAddress)

    if (-not $IpAddress) { return $true }
    if ($IpAddress -like "127.*") { return $true }
    if ($IpAddress -like "169.254.*") { return $true }
    if ($IpAddress -match "^198\.(18|19)\.") { return $true }
    return $false
}

function Test-PrivateLanIp {
    param([string]$IpAddress)

    if ($IpAddress -match "^10\.") { return $true }
    if ($IpAddress -match "^192\.168\.") { return $true }
    if ($IpAddress -match "^172\.(1[6-9]|2[0-9]|3[0-1])\.") { return $true }
    return $false
}

function Test-ExcludedInterface {
    param([string]$InterfaceAlias)

    return [bool]($InterfaceAlias -match "vEthernet|Virtual|VMware|VirtualBox|Loopback|Bluetooth|Tailscale|ZeroTier|Clash|Sakura|VPN|Wintun|TAP|Hyper-V|Docker|WSL")
}

function Get-LanIps {
    $ips = @()
    try {
        $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                -not (Test-ExcludedLanIp $_.IPAddress) -and
                -not (Test-ExcludedInterface $_.InterfaceAlias)
            } |
            Sort-Object @{Expression={ if (Test-PrivateLanIp $_.IPAddress) { 0 } else { 1 } }}, IPAddress |
            Select-Object -ExpandProperty IPAddress
    }
    catch {
        $ips = ipconfig |
            Select-String -Pattern "IPv4" |
            ForEach-Object {
                $parts = $_.ToString() -split ":"
                if ($parts.Count -ge 2) { $parts[-1].Trim() }
            } |
            Where-Object { -not (Test-ExcludedLanIp $_) -and (Test-PrivateLanIp $_) }
    }

    $uniqueIps = @($ips | Select-Object -Unique)
    $preferredIps = @($uniqueIps | Where-Object { $_ -match "^192\.168\." -or $_ -match "^10\." })
    if ($preferredIps.Count -gt 0) {
        return $preferredIps
    }
    return $uniqueIps
}

function Write-AccessUrls {
    Write-Host "Open local: http://localhost:$port"
    if ($hostValue -in @("0.0.0.0", "::")) {
        $lanIps = Get-LanIps
        if ($lanIps.Count -gt 0) {
            foreach ($lanIp in $lanIps) {
                Write-Host "Open LAN:   http://${lanIp}:$port"
            }
        }
        else {
            Write-Host "Open LAN:   no usable LAN IPv4 found"
        }
    }
}

$existingPid = Get-ListenerPid -Port $port
if ($existingPid) {
    Save-Pid -ProcessId $existingPid
    Write-Host "Already running PID $existingPid"
    Write-AccessUrls
    exit 0
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$app = Join-Path $root "app.py"
if (-not (Test-Path $app)) {
    throw "app.py not found: $app"
}

$logs = Join-Path $root "logs"
if (-not (Test-Path $logs)) {
    New-Item -ItemType Directory -Path $logs | Out-Null
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $python
$psi.Arguments = "-u `"$app`""
$psi.WorkingDirectory = $root
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.EnvironmentVariables["GEO_HOST"] = $hostValue
$psi.EnvironmentVariables["GEO_PORT"] = [string]$port

$process = [System.Diagnostics.Process]::Start($psi)
$createdPid = [int]$process.Id

Save-Pid -ProcessId $createdPid

$deadline = (Get-Date).AddSeconds(15)
$listenerPid = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    $listenerPid = Get-ListenerPid -Port $port
    if ($listenerPid) {
        break
    }
}

if ($listenerPid) {
    Save-Pid -ProcessId $listenerPid
    Write-Host "Started PID $listenerPid"
    Write-AccessUrls
    exit 0
}

Write-Host "Started process PID $createdPid, but port $port was not detected."
exit 1
