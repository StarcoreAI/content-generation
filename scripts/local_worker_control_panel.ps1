$ErrorActionPreference = "Stop"

try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
} catch {
    Write-Host ("[ERROR] cannot open local control panel: {0}" -f $_.Exception.Message)
    exit 1
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stopScript = Join-Path $projectRoot "scripts\stop_local_crawl_worker.ps1"

$form = New-Object System.Windows.Forms.Form
$form.Text = "GEO Local Crawler Control"
$form.StartPosition = "CenterScreen"
$form.Size = New-Object System.Drawing.Size(380, 170)
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
$form.MaximizeBox = $false
$form.MinimizeBox = $true
$form.TopMost = $true

$label = New-Object System.Windows.Forms.Label
$label.Text = "Local crawler worker is running on this computer."
$label.AutoSize = $true
$label.Location = New-Object System.Drawing.Point(18, 18)
$form.Controls.Add($label)

$status = New-Object System.Windows.Forms.Label
$status.Text = "Use this button if anti-bot or peak-hour rejection blocks crawling."
$status.AutoSize = $false
$status.Size = New-Object System.Drawing.Size(330, 32)
$status.Location = New-Object System.Drawing.Point(18, 48)
$form.Controls.Add($status)

$stopButton = New-Object System.Windows.Forms.Button
$stopButton.Text = "Stop local crawler"
$stopButton.Size = New-Object System.Drawing.Size(150, 34)
$stopButton.Location = New-Object System.Drawing.Point(18, 88)
$form.Controls.Add($stopButton)

$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Text = "Close"
$closeButton.Size = New-Object System.Drawing.Size(90, 34)
$closeButton.Location = New-Object System.Drawing.Point(184, 88)
$closeButton.Add_Click({ $form.Close() })
$form.Controls.Add($closeButton)

$stopButton.Add_Click({
    $stopButton.Enabled = $false
    $status.Text = "Stopping local crawler..."
    try {
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$stopScript`""
        $process = Start-Process -FilePath "powershell" -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -eq 0) {
            $status.Text = "Stop command sent. You can close this window."
        } else {
            $status.Text = "Stop failed. Close worker windows manually if needed."
        }
    } catch {
        $status.Text = "Stop failed. Close worker windows manually if needed."
    } finally {
        $stopButton.Enabled = $true
    }
})

[void]$form.ShowDialog()
