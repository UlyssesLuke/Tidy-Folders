# After building: start the .exe the way Windows does at sign-in (--tray) and check the tray behaviour.
#   powershell -ExecutionPolicy Bypass -File tests\gui\check_exe_tray.ps1
# Uses its own temporary settings and sample folder. Close any copy of Tidy Folders you have open
# first (from the tray: right-click > Quit), since only one copy can run at a time.
param([string]$Exe = (Join-Path $PSScriptRoot "..\..\dist\Tidy Folders.exe"))
$ErrorActionPreference = 'Stop'
$Exe = (Resolve-Path $Exe).Path
$work = Join-Path ([IO.Path]::GetTempPath()) ("tidy-check-exe-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$appHome = Join-Path $work 'appdata'
$sample = Join-Path $work 'Sample Folder'
New-Item -ItemType Directory -Force $appHome, $sample | Out-Null
$old = (Get-Date).AddDays(-10)
foreach ($n in 'holiday.jpg', 'invoice.pdf', 'song.mp3') {
    $p = Join-Path $sample $n; Set-Content -Path $p -Value 'sample'; (Get-Item $p).LastWriteTime = $old
}
@{ folders = @($sample); auto_sort = $true; interval_seconds = 5; tray_hint_shown = $true } |
    ConvertTo-Json | Set-Content -Path (Join-Path $appHome 'settings.json') -Encoding utf8

Add-Type @"
using System; using System.Runtime.InteropServices;
public class TrayCheckWin {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string c, string t);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
}
"@
function Copies { @(Get-Process -Name 'Tidy Folders' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Exe }) }
function Visible { $h = [TrayCheckWin]::FindWindow('TkTopLevel', 'Tidy Folders'); ($h -ne [IntPtr]::Zero) -and [TrayCheckWin]::IsWindowVisible($h) }
function Check($label, $ok) { if ($ok) { "PASS  $label" } else { "FAIL  $label"; $script:failed = $true } }
$failed = $false
if ((Copies).Count) { "Tidy Folders is already running. Quit it from the tray first."; exit 1 }
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$hadStartup = $null -ne (Get-ItemProperty $runKey -Name 'Tidy Folders' -ErrorAction SilentlyContinue)

$env:TIDY_FOLDERS_HOME = $appHome
try {
    Start-Process -FilePath $Exe -ArgumentList '--tray' | Out-Null
    for ($i = 0; $i -lt 40 -and -not (Test-Path (Join-Path $sample 'Images\holiday.jpg')); $i++) { Start-Sleep -Milliseconds 500 }
    Check 'started with --tray: running in the background' ((Copies).Count -ge 1)
    Check 'auto-sorted while hidden' (Test-Path (Join-Path $sample 'Images\holiday.jpg'))
    Check 'no window shown at sign-in (tray only)' (-not (Visible))
    $procs = (Copies).Count

    Start-Process -FilePath $Exe | Out-Null  # opening it again, e.g. from the Start menu
    for ($i = 0; $i -lt 20 -and -not (Visible); $i++) { Start-Sleep -Milliseconds 500 }
    Check 'opening it again shows the hidden window' (Visible)
    Start-Sleep -Seconds 3
    Check 'no second copy started' ((Copies).Count -eq $procs)

    $h = [TrayCheckWin]::FindWindow('TkTopLevel', 'Tidy Folders')
    [TrayCheckWin]::PostMessage($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # click the X
    Start-Sleep -Seconds 2
    Check 'closing the window hides it to the tray' ((-not (Visible)) -and ((Copies).Count -eq $procs))

    $hasStartup = $null -ne (Get-ItemProperty $runKey -Name 'Tidy Folders' -ErrorAction SilentlyContinue)
    Check 'your start-up list was not changed' ($hasStartup -eq $hadStartup)
} finally {
    Copies | Stop-Process -Force
    Start-Sleep -Milliseconds 500
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
if ($failed) { 'SOME CHECKS FAILED'; exit 1 } else { 'EXE TRAY CHECK PASSED' }
