param(
    [ValidateSet('Apply','Restore','Check')][string]$Action = 'Check',
    [string]$AppRoot = '',
    [string]$StateDir = '',
    [string]$OriginalFrontend = '',
    [string]$Profile = '11.0.9.251',
    [string]$PythonPath = '',
    [int]$UserSession = -1,
    [switch]$ElevatedStep
)
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
if (-not $AppRoot) { $AppRoot = Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVIDIA App' }
if (-not $StateDir) { $StateDir = Join-Path $env:LOCALAPPDATA 'NVIDIA Codec Split' }
$StateDir = [IO.Path]::GetFullPath($StateDir)
$AppRoot = [IO.Path]::GetFullPath($AppRoot)
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
if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'pythonw.exe is required for the login helper.' }

function Invoke-CodecTool([string[]]$ToolArguments) {
    & $pythonExe $entrypoint @ToolArguments --state-dir $StateDir
    if ($LASTEXITCODE -ne 0) { throw "Codec command failed: $($ToolArguments[0])" }
}

function Read-RegistryValue([string]$Key, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Key)) { return $null }
    $values = Get-ItemProperty -LiteralPath $Key
    $property = $values.PSObject.Properties[$Name]
    if ($property) { return $property.Value }
    return $null
}

function Stop-CodecWatcher {
    Invoke-CodecTool @('stop-watch')
    # Wait for its transaction to finish; do not kill a suspended-process worker.
    $helpers = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'pythonw.exe' -and $_.CommandLine -and $_.CommandLine.Contains($launcher)
    })
    foreach ($helper in $helpers) {
        $process = Get-Process -Id $helper.ProcessId -ErrorAction SilentlyContinue
        if ($process -and -not $process.WaitForExit(15000)) { throw 'The helper did not stop; operation cancelled.' }
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($ElevatedStep) {
    if (-not $isAdmin) { throw 'The file replacement step requires administrator permission.' }
    Start-Transcript -Path (Join-Path $StateDir 'install.log') -Append | Out-Null
    try {
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
    Stop-CodecWatcher
    if (Test-Path -LiteralPath $startupBackup) {
        $saved = Get-Content -LiteralPath $startupBackup -Raw | ConvertFrom-Json
        if ((Read-RegistryValue $runKey $runName) -eq $saved.Installed) {
            if ($null -eq $saved.Previous) { Remove-ItemProperty -LiteralPath $runKey -Name $saved.Name }
            else { Set-ItemProperty -LiteralPath $runKey -Name $saved.Name -Value $saved.Previous }
        }
        $state = Get-Content -LiteralPath (Join-Path $StateDir 'manifest.json') -Raw | ConvertFrom-Json
        $profilePath = Join-Path $repoRoot ('src\nvidia_codec_split\profiles\' + $state.profile + '.json')
        $supported = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
        $nativeFile = Join-Path $state.app_root $supported.native.relative
        $currentCodec = Read-RegistryValue $codecKey 'rhvyeiok'
        if ((Test-Path -LiteralPath $nativeFile) -and (Get-FileHash -LiteralPath $nativeFile).Hash.ToLowerInvariant() -eq $supported.native.sha256) {
            if ($currentCodec -and $currentCodec.Length -eq 4 -and [BitConverter]::ToInt32([byte[]]$currentCodec,0) -eq 1 -and $saved.Codec) {
                Set-ItemProperty -LiteralPath $codecKey -Name 'rhvyeiok' -Value ([byte[]]$saved.Codec)
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
        $saved | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $startupBackup -Encoding utf8
    }
    New-Item -Path $runKey -Force | Out-Null
    New-ItemProperty -LiteralPath $runKey -Name $runName -Value $startup -PropertyType String -Force | Out-Null
    Start-Process -FilePath $pythonWindowless -ArgumentList @(('"' + $launcher + '"'),'watch','--state-dir',('"' + $StateDir + '"')) -WindowStyle Hidden
}
Start-Process -FilePath (Join-Path $AppRoot 'CEF\NVIDIA Overlay.exe') -WindowStyle Hidden
Write-Output "Completed $Action. Local backups and logs: $StateDir"
