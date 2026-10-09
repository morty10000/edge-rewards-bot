# Register autostart for edge-rewards-bot:
#   EdgeRewards-AM / PM : daily runs (09:40 / 19:40) + catch-up retries every 90 min
#   EdgeRewardsWatch    : logon autostart via Startup-folder shortcut
#   EdgeRewardsDashboard: dashboard server autostart (http://127.0.0.1:17173/)
# Usage: powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads .ps1 as ANSI).
$root  = $PSScriptRoot
$py    = Join-Path $root ".venv\Scripts\python.exe"
$pyw   = Join-Path $root ".venv\Scripts\pythonw.exe"
$main  = Join-Path $root "main.py"
$watch = Join-Path $root "watch_edge.py"

$action   = New-ScheduledTaskAction -Execute $pyw -Argument "`"$main`"" -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

function New-RewardsTrigger([string]$at) {
    $t   = New-ScheduledTaskTrigger -Daily -At $at
    $rep = New-ScheduledTaskTrigger -Once -At $at `
        -RepetitionInterval (New-TimeSpan -Minutes 90) `
        -RepetitionDuration (New-TimeSpan -Hours 7 -Minutes 30)
    $t.Repetition = $rep.Repetition
    return $t
}

Register-ScheduledTask -TaskName "EdgeRewards-AM" -Force `
    -Action $action -Trigger (New-RewardsTrigger "09:40") -Settings $settings
Register-ScheduledTask -TaskName "EdgeRewards-PM" -Force `
    -Action $action -Trigger (New-RewardsTrigger "19:40") -Settings $settings

# watcher autostart (no admin required): shortcut in the Startup folder
$startup = [Environment]::GetFolderPath("Startup")
$lnkPath = Join-Path $startup "EdgeRewardsWatch.lnk"
$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath       = $pyw
$lnk.Arguments        = "`"$watch`""
$lnk.WorkingDirectory = $root
$lnk.Description      = "edge-rewards-bot watcher (auto-run on Edge start)"
$lnk.Save()

$dash = Join-Path $root "dashboard.py"
$lnk2 = $ws.CreateShortcut((Join-Path $startup "EdgeRewardsDashboard.lnk"))
$lnk2.TargetPath       = $pyw
$lnk2.Arguments        = "`"$dash`""
$lnk2.WorkingDirectory = $root
$lnk2.Description      = "edge-rewards-bot dashboard http://127.0.0.1:17173/"
$lnk2.Save()

# desktop shortcut to the dashboard URL
$desk = [Environment]::GetFolderPath("Desktop")
$urlPath = Join-Path $desk "EdgeRewards Dashboard.url"
@"
[InternetShortcut]
URL=http://127.0.0.1:17173/
"@ | Set-Content -Path $urlPath -Encoding ASCII

Write-Host "Registered:"
Get-ScheduledTask -TaskName "EdgeRewards-AM" | Select-Object TaskName, State
Get-ScheduledTask -TaskName "EdgeRewards-PM" | Select-Object TaskName, State
Write-Host "AM settings:"
(Get-ScheduledTask -TaskName "EdgeRewards-AM").Settings | Select-Object StartWhenAvailable, DisallowStartIfOnBatteries
Write-Host "Watcher shortcut -> $lnkPath"
Test-Path $lnkPath
Write-Host "Dashboard -> http://127.0.0.1:17173/  (Startup: EdgeRewardsDashboard.lnk)"
