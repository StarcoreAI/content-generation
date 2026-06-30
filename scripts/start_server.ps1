$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$port = 5000
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

function Get-LanIp {
    try {
        $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
            Select-Object -First 1 -ExpandProperty IPAddress
        return $ip
    }
    catch {
        return $null
    }
}

function Write-AccessUrls {
    Write-Host "Open local: http://localhost:5000"
    $lanIp = Get-LanIp
    if ($lanIp) {
        Write-Host "Open LAN:   http://${lanIp}:5000"
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

$createdPid = $null
$commandLine = "`"$python`" -u `"$app`""

try {
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $commandLine
        CurrentDirectory = $root
    } -ErrorAction Stop

    if ($result.ReturnValue -ne 0) {
        throw "Win32_Process.Create returned $($result.ReturnValue)"
    }
    $createdPid = [int]$result.ProcessId
}
catch {
    Write-Host "WMI start failed, falling back to clean ProcessStartInfo: $($_.Exception.Message)"

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $python
    $psi.Arguments = "-u `"$app`""
    $psi.WorkingDirectory = $root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $psi.EnvironmentVariables.Clear()
    $pathValue = [System.Environment]::GetEnvironmentVariable("Path", "Process")
    if (-not $pathValue) {
        $pathValue = [System.Environment]::GetEnvironmentVariable("PATH", "Process")
    }

    $envMap = @{
        "Path" = $pathValue
        "SystemRoot" = $env:SystemRoot
        "WINDIR" = $env:WINDIR
        "TEMP" = $env:TEMP
        "TMP" = $env:TMP
        "USERPROFILE" = $env:USERPROFILE
        "APPDATA" = $env:APPDATA
        "LOCALAPPDATA" = $env:LOCALAPPDATA
        "COMSPEC" = $env:COMSPEC
        "PYTHONUTF8" = "1"
        "PYTHONIOENCODING" = "utf-8"
    }

    foreach ($key in $envMap.Keys) {
        if ($envMap[$key]) {
            $psi.EnvironmentVariables[$key] = [string]$envMap[$key]
        }
    }

    $process = [System.Diagnostics.Process]::Start($psi)
    $createdPid = [int]$process.Id
}

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
