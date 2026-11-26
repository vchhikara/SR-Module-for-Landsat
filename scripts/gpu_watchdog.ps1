# SPDX-License-Identifier: GPL-3.0-or-later
<#
.SYNOPSIS
Watch an NVIDIA GPU during model runs. Stop the plugin's model process before the GPU gets too hot.

.DESCRIPTION
The script reads nvidia-smi every few seconds and writes each reading to a CSV file. It stops the
matching python.exe processes when one of these happens:
  - the temperature is at or above StopC for Samples readings in a row,
  - the temperature is at or above HardC once,
  - the driver reports a hardware slowdown,
  - the sensor cannot be read for Samples readings in a row.
It stops only python.exe processes whose command line matches ProcessPattern. When the model process
stops, the plugin reports an error and publishes no output. The script does not change any GPU
setting, clock, fan or power limit.

Exit code: 0 after Seconds or when StopFile appears, 2 after it stopped a model process or found a
danger condition.

.EXAMPLE
pwsh -File scripts\gpu_watchdog.ps1 -LogPath gpu.csv
#>
[CmdletBinding()]
param(
    [int]$StopC = 82,
    [int]$HardC = 86,
    [int]$Samples = 3,
    [double]$IntervalSeconds = 2,
    [int]$Seconds = 0,                          # 0 means: run until stopped
    [string]$StopFile = '',
    [string]$LogPath = 'gpu_watchdog.csv',
    [string]$ProcessPattern = 'stream_worker\.py'
)

$ErrorActionPreference = 'Stop'
$query = 'temperature.gpu,utilization.gpu,memory.used,power.draw,clocks.sm,clocks_throttle_reasons.hw_slowdown'
if (-not (Test-Path -LiteralPath $LogPath)) {
    Set-Content -LiteralPath $LogPath -Value 'time,temperature_c,utilization_pct,memory_mib,power_w,clock_mhz,hw_slowdown,event'
}

function Write-Reading([string]$values, [string]$event) {
    Add-Content -LiteralPath $LogPath -Value ('{0},{1},{2}' -f (Get-Date -Format 's'), $values, $event)
}

function Stop-ModelProcess {
    $found = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match $ProcessPattern })
    foreach ($item in $found) {
        Stop-Process -Id $item.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue
    }
    return $found.Count
}

$began = Get-Date
$hot = 0
$unreadable = 0
$peak = 0
while ($true) {
    if ($StopFile -and (Test-Path -LiteralPath $StopFile)) { break }
    if ($Seconds -gt 0 -and ((Get-Date) - $began).TotalSeconds -ge $Seconds) { break }
    $reason = ''
    $values = ''
    try {
        $line = (& nvidia-smi "--query-gpu=$query" '--format=csv,noheader,nounits' | Select-Object -First 1)
        $part = $line -split ',\s*'
        $temperature = [int]$part[0]
        $values = $part -join ','
        $unreadable = 0
        $peak = [math]::Max($peak, $temperature)
        if ($temperature -ge $StopC) { $hot++ } else { $hot = 0 }
        if ($temperature -ge $HardC) { $reason = "temperature $temperature C is at or above $HardC C" }
        elseif ($hot -ge $Samples) { $reason = "temperature stayed at or above $StopC C" }
        elseif ($part[5] -eq 'Active') { $reason = 'the driver reports a hardware slowdown' }
    }
    catch {
        $unreadable++
        $values = ',,,,,'
        if ($unreadable -ge $Samples) { $reason = 'the GPU sensor cannot be read' }
    }
    if ($reason) {
        $count = Stop-ModelProcess
        Write-Reading $values "TRIPPED: $reason. Stopped $count model process(es)."
        Write-Output "GPU watchdog TRIPPED: $reason. Stopped $count model process(es). Peak $peak C."
        exit 2
    }
    Write-Reading $values ''
    Start-Sleep -Milliseconds ([int]($IntervalSeconds * 1000))
}
Write-Output "GPU watchdog finished without a trip. Peak temperature $peak C."
exit 0
