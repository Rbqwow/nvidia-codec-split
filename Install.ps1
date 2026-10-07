param(
    [ValidateSet('Apply','Restore','Check')][string]$Action = 'Check',
    [string]$AppRoot = '',
    [string]$StateDir = '',
    [string]$OriginalFrontend = '',
    [string]$LegacyHelper = '',
    [string]$LegacyRoot = '',
    [string]$Profile = '11.0.9.251',
    [string]$PythonPath = '',
    [int]$UserSession = -1,
    [switch]$ElevatedStep
)
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
if (-not $StateDir) { $StateDir = Join-Path $env:LOCALAPPDATA 'NVIDIA Codec Split' }
$StateDir = [IO.Path]::GetFullPath($StateDir)
if (-not $AppRoot) {
    $manifestPath = Join-Path $StateDir 'manifest.json'
    if (Test-Path -LiteralPath $manifestPath) {
        $AppRoot = (Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).app_root
    } else { $AppRoot = Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVIDIA App' }
}
$AppRoot = [IO.Path]::GetFullPath($AppRoot)
if (-not $LegacyHelper) { $LegacyHelper = Join-Path $env:LOCALAPPDATA 'NVIDIA Corporation\NVIDIA Overlay\CodecSplit' }
$LegacyHelper = [IO.Path]::GetFullPath($LegacyHelper)
if (-not $LegacyRoot -and -not $PSBoundParameters.ContainsKey('LegacyHelper') -and
    -not (Test-Path -LiteralPath (Join-Path $LegacyHelper 'native_manifest.json'))) {
    $legacyCandidate = Join-Path (Split-Path -Parent $repoRoot) 'nvidia_codec_patch'
    if (Test-Path -LiteralPath (Join-Path $legacyCandidate 'native_manifest.json')) { $LegacyRoot = $legacyCandidate }
}
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runName = 'NVIDIA Codec Split'
$codecKey = 'HKCU:\Software\NVIDIA Corporation\Global\ShadowPlay\NVSPCAPS'
$runtimeRoot = Join-Path $StateDir 'runtime'
$launcher = Join-Path $runtimeRoot 'run.py'
$startupBackup = Join-Path $StateDir 'startup.json'
$entrypoint = Join-Path $repoRoot 'run.py'
if ($UserSession -lt 0) { $UserSession = (Get-Process -Id $PID).SessionId }
$pythonCommand = if ($PythonPath) { $PythonPath } else { (Get-Command python.exe).Source }
$pythonInfoText = & $pythonCommand -c "import json,sys; print(json.dumps({'exe':sys.executable,'version':list(sys.version_info[:2]),'bits':64 if sys.maxsize>2**32 else 32}))"
if ($LASTEXITCODE -ne 0) { throw 'A working Python installation is required.' }
$pythonInfo = $pythonInfoText | ConvertFrom-Json
if ($pythonInfo.bits -ne 64 -or $pythonInfo.version[0] -ne 3 -or $pythonInfo.version[1] -lt 11) {
    throw 'Install 64-bit Python 3.11 or newer before applying this patch.'
}
$pythonExe = $pythonInfo.exe
$pythonWindowless = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
if ($Action -eq 'Apply' -and -not (Test-Path -LiteralPath $pythonWindowless)) { throw 'pythonw.exe is required for the login helper.' }

function Invoke-CodecTool([string[]]$ToolArguments) {
    $rootArguments = @()
    if ($ToolArguments -notcontains '--app-root') { $rootArguments = @('--app-root',$AppRoot) }
    & $pythonExe $entrypoint @ToolArguments @rootArguments --state-dir $StateDir
    if ($LASTEXITCODE -ne 0) { throw "Codec command failed: $($ToolArguments[0])" }
}

function Read-RegistryValue([string]$Key, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Key)) { return $null }
    $values = Get-ItemProperty -LiteralPath $Key
    $property = $values.PSObject.Properties[$Name]
    if ($property) { return $property.Value }
    return $null
}

function Get-CodecFileHash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Stop-CodecWatcher([string]$LegacyWatcher = '') {
    Invoke-CodecTool @('stop-watch')
    # Wait for its transaction to finish; do not kill a suspended-process worker.
    $helpers = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -and
        $_.CommandLine.IndexOf(('"' + $launcher + '"'), [StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    foreach ($helper in $helpers) {
        $process = Get-Process -Id $helper.ProcessId -ErrorAction SilentlyContinue
        if ($process -and -not $process.WaitForExit(15000)) { throw 'The helper did not stop; operation cancelled.' }
    }
    if ($LegacyWatcher) {
        # The old watcher has no stop event. Terminate only the watcher, then
        # wait for any child memory writer to resume its recording process.
        $legacyHelpers = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -and
            $_.CommandLine.IndexOf(('"' + $LegacyWatcher + '"'), [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
        foreach ($helper in $legacyHelpers) {
            $process = Get-Process -Id $helper.ProcessId -ErrorAction SilentlyContinue
            if ($process) {
                if ([Math]::Abs(($process.StartTime.ToUniversalTime() - $helper.CreationDate.ToUniversalTime()).TotalMilliseconds) -gt 1) {
                    throw 'The legacy helper process changed; retry restoration.'
                }
                $null = $process.Handle
                $process.Kill()
                if (-not $process.WaitForExit(15000)) { throw 'The legacy helper did not stop.' }
            }
        }
        $workerPath = Join-Path (Split-Path -Parent $LegacyWatcher) 'memory_patch.py'
        $workers = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -and
            $_.CommandLine -match ('(?:^|\s|")' + [regex]::Escape($workerPath) + '(?:"|\s|$)')
        })
        foreach ($worker in $workers) {
            $process = Get-Process -Id $worker.ProcessId -ErrorAction SilentlyContinue
            if ($process -and -not $process.WaitForExit(15000)) {
                throw 'A legacy memory writer is still running; retry restoration after it exits.'
            }
        }
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($ElevatedStep) {
    if (-not $isAdmin) { throw 'The file replacement step requires administrator permission.' }
    Start-Transcript -Path (Join-Path $StateDir 'install.log') -Append | Out-Null
    try {
        if ($Action -eq 'Restore') { Invoke-CodecTool @('check-restore') }
        Get-Process -Name 'NVIDIA Overlay' -ErrorAction SilentlyContinue |
            Where-Object { $_.SessionId -eq $UserSession } | Stop-Process
        if ($Action -eq 'Apply') { Invoke-CodecTool @('apply-ui') }
        elseif ($Action -eq 'Restore') {
            Invoke-CodecTool @('restore-ui')
            Restart-Service -Name 'NvContainerLocalSystem' -Force
        } else { Invoke-CodecTool @('check') }
    } finally { Stop-Transcript | Out-Null }
    exit 0
}
if ($Action -eq 'Check') {
    Invoke-CodecTool @('check')
    exit 0
}

# Backups, HKCU settings and login registration belong to the invoking user.
# Only installation file writes/service restart run under Windows UAC.
if ($Action -eq 'Apply') {
    $startupValue = Read-RegistryValue $runKey $runName
    if ($startupValue -and -not $startupValue.Contains($launcher)) {
        throw 'A previous codec helper is registered. Stop/restore the previous installation first.'
    }
    $prepareArgs = @('prepare','--app-root',$AppRoot,'--profile',$Profile)
    if ($OriginalFrontend) { $prepareArgs += @('--original-frontend',$OriginalFrontend) }
    Invoke-CodecTool $prepareArgs
    Invoke-CodecTool @('check')
    Stop-CodecWatcher
    $originalCodec = Read-RegistryValue $codecKey 'rhvyeiok'
} else {
    $startupValue = Read-RegistryValue $runKey $runName
    $legacyWatcher = Join-Path $LegacyHelper 'watcher.py'
    if (-not (Test-Path -LiteralPath (Join-Path $StateDir 'manifest.json')) -or
        ($startupValue -and $startupValue.IndexOf(('"' + $legacyWatcher + '"'), [StringComparison]::OrdinalIgnoreCase) -ge 0)) {
        $importArgs = @('import-legacy','--app-root',$AppRoot,'--profile',$Profile,'--legacy-helper',$LegacyHelper)
        if ($LegacyRoot) { $importArgs += @('--legacy-root',$LegacyRoot) }
        Invoke-CodecTool $importArgs
    }
    # Validate originals/ownership before stopping anything or displaying UAC.
    Invoke-CodecTool @('check-restore')
    $saved = $null
    $legacyWatcher = ''
    if (Test-Path -LiteralPath $startupBackup) {
        $saved = Get-Content -LiteralPath $startupBackup -Raw | ConvertFrom-Json
        if ($saved.Name -ne $runName) { throw 'Startup backup has an unexpected entry name.' }
        if ($saved.LegacyHelper) { $legacyWatcher = Join-Path $saved.LegacyHelper 'watcher.py' }
        if ($startupValue -and $startupValue -ne $saved.Installed -and $startupValue -ne $saved.Previous) {
            throw 'Another helper owns the login entry; refusing an incomplete restore.'
        }
    } elseif ($startupValue) { throw 'Startup backup is missing; cannot restore the registered helper safely.' }
    Stop-CodecWatcher $legacyWatcher
    if ($saved) {
        $state = Get-Content -LiteralPath (Join-Path $StateDir 'manifest.json') -Raw | ConvertFrom-Json
        $profilePath = Join-Path $repoRoot ('src\nvidia_codec_split\profiles\' + $state.profile + '.json')
        $supported = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
        $nativeFile = Join-Path $state.app_root $supported.native.relative
        $currentCodec = Read-RegistryValue $codecKey 'rhvyeiok'
        if ((Test-Path -LiteralPath $nativeFile) -and (Get-CodecFileHash $nativeFile) -eq $supported.native.sha256) {
            if ($currentCodec -is [byte[]] -and $currentCodec.Length -eq 4 -and [BitConverter]::ToInt32($currentCodec,0) -eq 1) {
                $restoreCodec = [byte[]](2,0,0,0)
                if ($saved.Codec -and $saved.Codec.Count -eq 4 -and [BitConverter]::ToInt32([byte[]]$saved.Codec,0) -in @(2,3)) {
                    $restoreCodec = [byte[]]$saved.Codec
                }
                Set-ItemProperty -LiteralPath $codecKey -Name 'rhvyeiok' -Value $restoreCodec
            }
        }
    }
}

$arguments = @('-NoProfile','-File',('"' + $PSCommandPath + '"'),'-Action',$Action,'-ElevatedStep',
    '-AppRoot',('"' + $AppRoot + '"'),'-StateDir',('"' + $StateDir + '"'),'-Profile',$Profile,
    '-PythonPath',('"' + $pythonExe + '"'),'-UserSession',$UserSession)
if ($isAdmin) {
    $installer = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList $arguments -PassThru
} else {
    $installer = Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments -PassThru
}
$installer.WaitForExit()
if ($installer.ExitCode -ne 0) { throw "Administrator step failed. See $StateDir\install.log" }
if ($Action -eq 'Restore' -and $saved) {
    $startupValue = Read-RegistryValue $runKey $runName
    if ($startupValue -eq $saved.Installed) {
        if ($null -eq $saved.Previous) { Remove-ItemProperty -LiteralPath $runKey -Name $runName }
        else { Set-ItemProperty -LiteralPath $runKey -Name $runName -Value $saved.Previous }
    } elseif ($startupValue -and $startupValue -ne $saved.Previous) {
        throw 'The login entry changed during restoration; original UI restored, but the new entry was preserved.'
    }
}
if ($Action -eq 'Apply') {
    New-Item -ItemType Directory -Path (Join-Path $runtimeRoot 'src') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot 'src\nvidia_codec_split') -Destination (Join-Path $runtimeRoot 'src') -Recurse -Force
    Copy-Item -LiteralPath $entrypoint -Destination $launcher -Force
    $startup = '"' + $pythonWindowless + '" "' + $launcher + '" watch --state-dir "' + $StateDir + '"'
    if (-not (Test-Path -LiteralPath $startupBackup)) {
        [pscustomobject]@{Name=$runName;Previous=$startupValue;Installed=$startup;Codec=$originalCodec} |
            ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $startupBackup -Encoding utf8
    } else {
        $saved = Get-Content -LiteralPath $startupBackup -Raw | ConvertFrom-Json
        $saved.Installed = $startup
        $saved.PSObject.Properties.Remove('LegacyHelper')
        $saved | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $startupBackup -Encoding utf8
    }
    New-Item -Path $runKey -Force | Out-Null
    New-ItemProperty -LiteralPath $runKey -Name $runName -Value $startup -PropertyType String -Force | Out-Null
    Start-Process -FilePath $pythonWindowless -ArgumentList @(('"' + $launcher + '"'),'watch','--state-dir',('"' + $StateDir + '"')) -WindowStyle Hidden
}
Start-Process -FilePath (Join-Path $AppRoot 'CEF\NVIDIA Overlay.exe') -WindowStyle Hidden
Write-Output "Completed $Action. Local backups and logs: $StateDir"
