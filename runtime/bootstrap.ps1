$ErrorActionPreference = "Stop"

# Keep the Hook protocol channel UTF-8 even under Windows PowerShell 5.1.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$pythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$pythonPrefix = @()
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python3 -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $pythonCommand) {
    $pythonCommand = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pythonCommand) {
        $pythonPrefix = @("-3")
    }
}

if (-not $pythonCommand) {
    $hookEvent = $null
    for ($index = 0; $index -lt ($args.Count - 1); $index++) {
        if ($args[$index] -eq "--hook-event") {
            $hookEvent = $args[$index + 1]
            break
        }
    }

    $message = "Wttch plugin did not run: Python is not installed or is not available on PATH. Ask the user to install Python and retry."
    if ($hookEvent) {
        $payload = @{
            hookSpecificOutput = @{
                hookEventName = $hookEvent
                additionalContext = $message
            }
        }
        [Console]::Out.WriteLine(($payload | ConvertTo-Json -Compress -Depth 4))
    }
    else {
        [Console]::Error.WriteLine("WARNING: $message")
    }
    exit 0
}

$runner = Join-Path $PSScriptRoot "runner.py"
& $pythonCommand.Source @pythonPrefix $runner @args
exit $LASTEXITCODE
