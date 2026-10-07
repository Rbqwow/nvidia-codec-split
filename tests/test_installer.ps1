$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $repoRoot 'Install.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw ($parseErrors | Out-String) }
$stopFunction = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Stop-CodecWatcher'}, $false)
if (-not $stopFunction) { throw 'Installer stop function is missing.' }
# Load only the helper function. All process/tool operations below are fakes;
# this test never runs the installer or touches NVIDIA/registry state.
Invoke-Expression $stopFunction.Extent.Text
$hashFunction = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-CodecFileHash'}, $false)
if (-not $hashFunction) { throw 'Installer hash function is missing.' }
Invoke-Expression $hashFunction.Extent.Text
# Check against the standard SHA-256 test vector without Get-FileHash (which
# can be unavailable in a Windows PowerShell session inherited from pwsh).
$hashInput = [IO.Path]::GetTempFileName()
try {
    [IO.File]::WriteAllBytes($hashInput, [Text.Encoding]::ASCII.GetBytes('abc'))
    if ((Get-CodecFileHash $hashInput) -ne 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad') {
        throw 'Installer native hash check failed.'
    }
} finally { Remove-Item -LiteralPath $hashInput }

class FakeCodecProcess {
    [int]$Id
    [datetime]$StartTime
    [int]$Handle = 1
    [bool]$Exits = $true
    FakeCodecProcess([int]$id, [datetime]$started) { $this.Id = $id; $this.StartTime = $started }
    [void] Kill() { $script:trace.Add("kill:$($this.Id)") }
    [bool] WaitForExit([int]$milliseconds) {
        $script:trace.Add("wait:$($this.Id)")
        return $this.Exits
    }
}
function Invoke-CodecTool([string[]]$ToolArguments) { $script:trace.Add($ToolArguments[0]) }
function Get-CimInstance([string]$ClassName) { return $script:processRows }
function Get-Process([int]$Id, [string]$ErrorAction) { return $script:processObjects[$Id] }
function Assert-Trace([string[]]$Expected) {
    if (($script:trace -join '|') -ne ($Expected -join '|')) {
        throw "Unexpected process operations: $($script:trace -join '|')"
    }
}
function Reset-Fakes {
    $script:trace = [Collections.Generic.List[string]]::new()
    $script:processObjects = @{}
    $script:processRows = @()
}
function Add-FakeProcess([int]$Id, [string]$Name, [string]$CommandLine) {
    $started = [datetime]::UtcNow
    $script:processRows += [pscustomobject]@{ProcessId=$Id;Name=$Name;CommandLine=$CommandLine;CreationDate=$started}
    $script:processObjects[$Id] = [FakeCodecProcess]::new($Id, $started)
}

$launcher = 'C:\Private State\runtime\run.py'
$legacyWatcher = 'C:\OldHelper\watcher.py'
$worker = 'C:\OldHelper\memory_patch.py'
Reset-Fakes
Add-FakeProcess 101 'python.exe' ('python.exe "' + $launcher + '" watch')
Add-FakeProcess 102 'pythonw.exe' ('pythonw.exe "' + $legacyWatcher + '"')
Add-FakeProcess 103 'python.exe' ('python.exe ' + $worker + ' 1234')
Add-FakeProcess 104 'pythonw.exe' 'pythonw.exe "C:\Unrelated\watcher.py"'
Add-FakeProcess 105 'python.exe' ('python.exe "' + $worker + '.unrelated"')
Stop-CodecWatcher $legacyWatcher
Assert-Trace @('stop-watch','wait:101','kill:102','wait:102','wait:103')

Reset-Fakes
Add-FakeProcess 102 'pythonw.exe' ('pythonw.exe "' + $legacyWatcher + '"')
Add-FakeProcess 103 'python.exe' ('python.exe "' + $worker + '" 1234')
$script:processObjects[103].Exits = $false
$caught = $false
try { Stop-CodecWatcher $legacyWatcher } catch {
    if ($_.Exception.Message -notlike '*memory writer is still running*') { throw }
    $caught = $true
}
if (-not $caught) { throw 'Restoration must stop when the memory writer times out.' }
Assert-Trace @('stop-watch','kill:102','wait:102','wait:103')

Reset-Fakes
Add-FakeProcess 102 'pythonw.exe' ('pythonw.exe "' + $legacyWatcher + '"')
$script:processObjects[102].StartTime = [datetime]::UtcNow.AddMinutes(1)
$caught = $false
try { Stop-CodecWatcher $legacyWatcher } catch {
    if ($_.Exception.Message -notlike '*process changed*') { throw }
    $caught = $true
}
if (-not $caught) { throw 'A reused legacy PID must be refused before termination.' }
Assert-Trace @('stop-watch')
Write-Output 'Installer tests passed: helper ownership, worker completion and PID reuse.'
