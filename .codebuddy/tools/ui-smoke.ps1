# ui-smoke.ps1 - machine-level UI smoke harness built on agent-browser.
#
# WHY THIS EXISTS: agent-browser CAN do viewport/device emulation, but only via
# `agent-browser set viewport W H [dpr]` / `agent-browser set device "iPhone 14"`.
# The bare `viewport` command does not exist, `--device` only applies at browser
# launch, and headless Chromium ignores `--args --window-size`. The full command
# reference for the installed version is always:
#     agent-browser skills get core --full
#
# This script does one sweep: open -> (optional login) -> for each width:
# set viewport -> measure layout -> screenshot. It also cleans stale
# agent-browser browser processes, which otherwise hold the daemon socket and
# make every later command hang with no output.
#
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads .ps1 as ANSI when there
# is no BOM, so non-ASCII comments get mangled and can swallow code lines.
#
# Usage examples
#   ui-smoke -Routes '#/tools/sources','#/tools/source-tools'
#   ui-smoke -CleanOnly
#   ui-smoke -Route '#/charts' -Widths 360,414,768,1024,1280 -Prefix charts
param(
  [string[]]$Routes,
  [string]$Base = 'http://localhost:8993',
  # Comma-separated string, parsed below. A real [int[]] parameter is unreliable
  # here: the PATH shim is a .cmd, and cmd/`-File` forwarding eats the comma
  # (observed: "-Widths 360,1280" arrived as a single value 3601280).
  [string]$Widths = '360,768,1280',
  [int]$Height = 900,
  [string]$Prefix = 'smoke',
  [string]$OutDir = "$env:TEMP\ui-smoke",
  [string]$Profile = "$env:USERPROFILE\.agent-browser-profile\novelforge",
  [string]$LoginPassword,
  [string]$LoginAccount = 'admin',
  [int]$SettleMs = 1200,
  [switch]$Clean,
  [switch]$CleanOnly,
  [switch]$KeepOpen
)

$ErrorActionPreference = 'Continue'
$ab = (Get-Command agent-browser -ErrorAction SilentlyContinue)
if (-not $ab) {
  # nodejs on PATH is required for the npm shim; the known-good install lives here.
  $env:PATH = "C:\Users\qingr\nodejs;$env:PATH"
  $ab = (Get-Command agent-browser -ErrorAction SilentlyContinue)
}
if (-not $ab) { throw 'agent-browser not found on PATH' }

# agent-browser spawns node internally; a broken node makes the daemon die silently.
$nodeOk = $false
try { $nodeOk = ((& node -e "console.log('ok')" 2>$null) -eq 'ok') } catch { }
if (-not $nodeOk) {
  $env:PATH = "C:\Users\qingr\nodejs;$env:PATH"
  try { $nodeOk = ((& node -e "console.log('ok')" 2>$null) -eq 'ok') } catch { }
}
if (-not $nodeOk) { Write-Output 'WARN: node on PATH does not execute code; launching may fail' }

# Stale browsers hold the daemon socket => every later command hangs silently.
function Remove-StaleBrowsers {
  $ps = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -like '*agent-browser*' -and
      ($_.Name -like 'chrome*' -or $_.Name -like 'agent-browser*')
    }
  $ids = @($ps | Select-Object -ExpandProperty ProcessId)
  if ($ids.Count -gt 0) {
    Write-Output ("cleaned stale processes: " + ($ids -join ','))
    $ps | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 700
  } else {
    Write-Output 'cleaned stale processes: none'
  }
}

if ($Clean -or $CleanOnly) { Remove-StaleBrowsers }
if ($CleanOnly) { return }

if (-not $Routes -or $Routes.Count -eq 0) {
  throw 'pass -Routes (e.g. -Routes "#/tools/sources") or -CleanOnly'
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path $Profile | Out-Null

$measure = @'
(()=>{const iw=innerWidth,de=document.documentElement;
const n=[...document.querySelectorAll('button,a,input,select,textarea')];
const v=n.filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0});
const off=v.filter(e=>{const r=e.getBoundingClientRect();return r.right>iw+1||r.left<-1});
const tiny=v.filter(e=>e.getBoundingClientRect().height<24);
const sb=[...document.querySelectorAll('*')].filter(e=>{const s=getComputedStyle(e);
  return /auto|scroll/.test(s.overflowX)&&e.scrollWidth>e.clientWidth+1&&e.clientWidth>0});
return JSON.stringify({w:iw,sw:de.scrollWidth,ovf:de.scrollWidth>iw+1,
  act:v.length,off:off.length,offSample:off.slice(0,3).map(e=>(e.innerText||e.tagName).slice(0,14)),
  tiny:tiny.length,scrollBoxes:sb.length,
  tabs:document.querySelectorAll('[role=tab]').length,
  sel:document.querySelectorAll('select').length,
  chk:document.querySelectorAll('input[type=checkbox]').length,
  txt:(document.body.innerText||'').length});})()
'@

function To-Url([string]$route) {
  if ($route -match '^https?://') { return $route }
  if ($route.StartsWith('#')) { return "$Base/$route" }
  return "$Base/#/$route"
}

$first = $true
foreach ($route in $Routes) {
  $url = To-Url $route
  Write-Output ("=== {0} ===" -f $url)
  if ($first) {
    & agent-browser open $url --profile $Profile --restore 2>&1 | Select-Object -Last 1
    $first = $false
  } else {
    & agent-browser open $url 2>&1 | Select-Object -Last 1
  }
  Start-Sleep -Milliseconds 1500

  # Login probe. Pass the JS through a variable: the command text itself must not
  # carry quotes, because the shell/tool layer sometimes eats double quotes and
  # the probe then silently evaluates to nothing.
  $probeLogin = '!!document.querySelector("input[type=password]")'
  $isLoginForm = (& agent-browser eval $probeLogin 2>&1 | Select-Object -Last 1) -match 'true'
  if ($isLoginForm) {
    if (-not $LoginPassword) {
      Write-Output 'LOGIN REQUIRED: pass -LoginPassword (route skipped)'
      continue
    }
    Write-Output 'login required: submitting form'
    if ($LoginAccount) { & agent-browser fill 'input[type=text],input[type=email]' $LoginAccount 2>&1 | Out-Null }
    & agent-browser fill 'input[type=password]' $LoginPassword 2>&1 | Out-Null
    & agent-browser press Enter 2>&1 | Out-Null
    Start-Sleep -Seconds 4
    & agent-browser open $url 2>&1 | Select-Object -Last 1
    Start-Sleep -Milliseconds 1500
    # HARD ASSERT. An earlier version emitted metrics + screenshots even when the
    # login had not taken effect, i.e. it reported numbers measured on the LOGIN
    # PAGE with no warning. Never emit data for a page we could not enter.
    $stillLogin = (& agent-browser eval $probeLogin 2>&1 | Select-Object -Last 1) -match 'true'
    if ($stillLogin) {
      Write-Output 'LOGIN FAILED (still on login form) - route skipped, NO metrics emitted'
      continue
    }
    Write-Output 'login ok'
  } else {
    Write-Output 'login state reused'
  }

  $slug = ($route -replace '[^A-Za-z0-9]+', '-').Trim('-')
  if (-not $slug) { $slug = 'page' }
  $widthList = @($Widths -split '[,\s]+' | Where-Object { $_ } | ForEach-Object { [int]$_ })
  if ($widthList.Count -eq 0) { $widthList = @(360, 768, 1280) }
  foreach ($w in $widthList) {
    & agent-browser set viewport $w $Height 2>&1 | Out-Null
    Start-Sleep -Milliseconds $SettleMs
    # Pick the JSON line explicitly: the CLI also prints informational lines
    # (e.g. "[agent-browser] restore: missing; save: saved") on the first call,
    # and a blind `-Last 1` would swallow the real metrics.
    # Match on a bare word (`ovf`) rather than on `{"w":` -- the CLI echoes the
    # JSON with escaped quotes (`{\"w\":`), so a literal-quote pattern misses.
    $m = (& agent-browser eval $measure 2>&1 | Where-Object { $_ -match 'ovf' } | Select-Object -Last 1)
    if (-not $m) { $m = '(no metrics)' }
    Write-Output ("W{0} {1}" -f $w, $m)
    $shot = Join-Path $OutDir ("{0}-{1}-{2}.jpg" -f $Prefix, $slug, $w)
    & agent-browser screenshot $shot 2>&1 | Select-Object -Last 1 | Out-Null
    if (Test-Path $shot) {
      Write-Output ("  shot {0} ({1} KB)" -f $shot, [int]((Get-Item $shot).Length / 1024))
    } else {
      Write-Output ("  shot FAILED {0}" -f $shot)
    }
  }
}

if (-not $KeepOpen) { & agent-browser close --all 2>&1 | Select-Object -Last 1 | Out-Null }
Write-Output 'DONE'
