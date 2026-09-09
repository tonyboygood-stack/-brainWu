param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9]+$')][string]$StockCode,
    [ValidateRange(1,120)][int]$Days = 20,
    [ValidateRange(1,180)][int]$Months = 72,
    [switch]$Refresh
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$runtimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $runtimePython) {
    $stockPython = $runtimePython
} elseif ($pythonCommand) {
    $stockPython = $pythonCommand.Source
} else {
    throw '找不到Python執行環境，請先設定Python。'
}
$stockScript = Join-Path $projectRoot '000_Agent\scripts\stock-fetch.py'
$stockArgs = @('-X', 'utf8', '-B', $stockScript, $StockCode, '--days', $Days, '--months', $Months)
if ($Refresh) { $stockArgs += '--no-cache' }
& $stockPython @stockArgs
exit $LASTEXITCODE
