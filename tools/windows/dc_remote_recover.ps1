# Desktop Commander Remote: read-only diagnostic or explicitly authorized, bounded recovery.
# Public code contains no machine-specific IDs or authentication material.
# Requires Windows PowerShell 5.1 under the same user as the existing scheduled task.
[CmdletBinding()]
param(
    [ValidateSet('Diagnose', 'RecoverOnce')][string]$Mode = 'Diagnose',
    [switch]$Apply,
    [string]$TaskName = 'DesktopCommanderRemote',
    [ValidateRange(1, 3)][int]$MaxAttemptsPerHour = 2,
    [ValidateRange(60, 3600)][int]$MinBackoffSeconds = 300
)
$ErrorActionPreference = 'Stop'
$base = Join-Path $env:LOCALAPPDATA 'DesktopCommanderRemote'
$entry = Join-Path $base 'pinned-runtime-0.3.0\node_modules\@wonderwhy-er\desktop-commander\dist\index.js'
$session = Join-Path $env:USERPROFILE '.desktop-commander-device\device.json'
$stateFile = Join-Path $base 'recovery-attempts.json'
$watchdogTaskName = 'DesktopCommanderRemoteWatchdog'

function Get-RemoteNodeProcesses {
    $all = @(Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction Stop)
    return @($all | Where-Object {
        $cmd = [string]$_.CommandLine
        $cmd -match 'desktop-commander[\\/]dist[\\/]index\.js' -and
        $cmd -match '(?:^|\s)remote(?:\s|$)'
    })
}
function Get-StalledNpxProcesses {
    $all = @(Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction Stop)
    return @($all | Where-Object {
        $cmd = [string]$_.CommandLine
        $cmd -match 'npx-cli\.js' -and $cmd -match 'desktop-commander' -and
        $cmd -match '(?:^|\s)remote(?:\s|$)'
    })
}
function Get-LogIndicators {
    $counts = [ordered]@{
        StartupFailure = 0
        InvalidRefresh = 0
        AuthorizationPrompt = 0
        ReachedReady = 0
        MarkedOffline = 0
        ChildMcpLoss = 0
    }
    $specs = @(
        @{ Filename = 'remote-pinned.log'; Encoding = 'Unicode' },
        @{ Filename = 'remote.log'; Encoding = 'Unicode' },
        @{ Filename = 'launcher.log'; Encoding = 'Default' }
    )
    foreach ($spec in $specs) {
        $path = Join-Path $base $spec.Filename
        if (-not (Test-Path -LiteralPath $path)) { continue }
        try {
            $lines = @(Get-Content -LiteralPath $path -Tail 250 -Encoding $spec.Encoding -ErrorAction Stop)
        } catch { continue }
        foreach ($line in $lines) {
            $str = [string]$line
            if ($str -match 'Device startup failed') { $counts.StartupFailure++ }
            if ($str -match 'Invalid Refresh Token|Refresh Token: Already Used') { $counts.InvalidRefresh++ }
            if ($str -match 'Requesting device code|Starting device authorization flow|Authorization required') { $counts.AuthorizationPrompt++ }
            if ($str -match 'Device ready|Remote is connected') { $counts.ReachedReady++ }
            if ($str -match 'Device marked as offline') { $counts.MarkedOffline++ }
            if ($str -match 'local Desktop Commander MCP|Could not restart local Desktop') { $counts.ChildMcpLoss++ }
        }
    }
    return $counts
}
function Get-Summary {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    $processes = @(Get-RemoteNodeProcesses)
    $npx = @(Get-StalledNpxProcesses)
    $watchdog = Get-ScheduledTask -TaskName $watchdogTaskName -ErrorAction SilentlyContinue
    $watchdogInfo = if ($watchdog) { Get-ScheduledTaskInfo -TaskName $watchdogTaskName -ErrorAction SilentlyContinue } else { $null }
    $connected = 0
    foreach ($proc in $processes) {
        try {
            $connected += @(Get-NetTCPConnection -OwningProcess $proc.ProcessId -State Established -ErrorAction Stop).Count
        } catch { }
    }
    [ordered]@{
        Status = 'DIAGNOSTIC_ONLY'
        TaskEnabled = ($task.State -ne 'Disabled')
        TaskState = [string]$task.State
        LastTaskResult = [int]$taskInfo.LastTaskResult
        LastTaskRunLocal = $taskInfo.LastRunTime.ToString('s')
        PinnedEntryExists = (Test-Path -LiteralPath $entry)
        SessionFileExists = (Test-Path -LiteralPath $session)
        RemoteProcessCount = $processes.Count
        RemoteEstablishedTcp = $connected
        LegacyNpxProcessCount = $npx.Count
        ExistingWatchdogRegistered = [bool]$watchdog
        ExistingWatchdogEnabled = [bool]($watchdog -and $watchdog.State -ne 'Disabled')
        ExistingWatchdogState = if ($watchdog) { [string]$watchdog.State } else { 'ABSENT' }
        ExistingWatchdogLastResult = if ($watchdogInfo) { [int]$watchdogInfo.LastTaskResult } else { $null }
        ExistingWatchdogLastRunLocal = if ($watchdogInfo) { $watchdogInfo.LastRunTime.ToString('s') } else { $null }
        LogIndicators = (Get-LogIndicators)
        CredentialContentsRead = $false
        CloudCommandsExecuted = $false
    }
}
function Save-ThrottleState([datetime[]]$timestamps) {
    if (-not (Test-Path -LiteralPath $base)) { throw 'REMOTE_LOCALAPPDATA_FOLDER_MISSING' }
    $pending = $stateFile + '.writing'
    if (Test-Path -LiteralPath $pending) { throw 'PRIOR_RECOVERY_WRITE_INCOMPLETE' }
    try {
        $payload = @{ AttemptUtc = @($timestamps | ForEach-Object { $_.ToUniversalTime().ToString('o') }) } | ConvertTo-Json -Depth 3
        [System.IO.File]::WriteAllText($pending, $payload, [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $pending -Destination $stateFile -Force -ErrorAction Stop
    } finally {
        if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending -Force }
    }
}
function Get-RecentAttempts {
    if (-not (Test-Path -LiteralPath $stateFile)) { return @() }
    try {
        $raw = Get-Content -LiteralPath $stateFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        $values = @($raw.AttemptUtc)
        return @($values | ForEach-Object { [datetime]::Parse([string]$_).ToUniversalTime() } |
            Where-Object { $_ -ge [datetime]::UtcNow.AddHours(-1) })
    } catch { throw 'RECOVERY_STATE_INVALID_REFUSE_RETRY' }
}
try {
    $summary = Get-Summary
    if ($Mode -eq 'Diagnose') {
        $summary | ConvertTo-Json -Depth 6
        exit 0
    }
    $status = 'RECOVERY_NOT_ATTEMPTED'
    if (-not $Apply) { $status = 'DRY_RUN_NEEDS_EXPLICIT_APPLY' }
    elseif ($summary.RemoteProcessCount -gt 0) { $status = 'SKIP_REMOTE_PROCESS_EXISTS' }
    elseif ($summary.LegacyNpxProcessCount -gt 0) { $status = 'SKIP_LEGACY_NPX_PROCESS_PRESENT' }
    elseif ($summary.ExistingWatchdogEnabled) { $status = 'SKIP_EXISTING_WATCHDOG_MANAGES_RECOVERY' }
    elseif (-not $summary.PinnedEntryExists) { $status = 'SKIP_PINNED_RUNTIME_MISSING' }
    elseif (-not $summary.SessionFileExists) { $status = 'SKIP_LOCAL_SESSION_MISSING_USER_AUTH_REQUIRED' }
    elseif (-not $summary.TaskEnabled) { $status = 'SKIP_TASK_DISABLED' }
    elseif ($summary.TaskState -ne 'Ready') { $status = 'SKIP_TASK_NOT_READY' }
    elseif ($summary.LogIndicators.InvalidRefresh -gt 0 -or $summary.LogIndicators.AuthorizationPrompt -gt 0) {
        $status = 'SKIP_AUTH_INDICATION_REQUIRES_HUMAN_REVIEW'
    } else {
        $attempts = @(Get-RecentAttempts)
        if ($attempts.Count -ge $MaxAttemptsPerHour) { $status = 'SKIP_HOURLY_RETRY_BUDGET' }
        elseif ($attempts.Count -gt 0 -and
            ([datetime]::UtcNow - ($attempts | Sort-Object -Descending | Select-Object -First 1)).TotalSeconds -lt $MinBackoffSeconds) {
            $status = 'SKIP_BACKOFF_INTERVAL'
        } else {
            # Record BEFORE firing so an interrupted caller cannot evade the retry budget.
            Save-ThrottleState (@($attempts) + @([datetime]::UtcNow))
            Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
            $status = 'START_REQUESTED_NOT_YET_VERIFIED'
        }
    }
    [ordered]@{ Status = $status; Task = $summary; CloudReachability = 'UNVERIFIED' } |
        ConvertTo-Json -Depth 7
    exit 0
} catch {
    [ordered]@{ Status = 'RECOVERY_DIAGNOSTIC_ERROR'; ErrorType = $_.Exception.GetType().Name;
        ErrorCode = 'INSPECT_PRIVATE_LOCAL_LOG_FOR_DETAILS'; Applied = $false } | ConvertTo-Json -Compress
    exit 2
}
