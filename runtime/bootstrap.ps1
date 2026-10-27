$ErrorActionPreference = "Stop"

# Keep the Hook protocol channel UTF-8 even under Windows PowerShell 5.1.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

# Set to $true to include extra environment and argument details in bootstrap.out.
$BootstrapDebug = $true
$launcherArgs = @($args)

$bootstrapLog = Join-Path $HOME ".wttch/bootstrap.out"
$bootstrapLogEncoding = [System.Text.UTF8Encoding]::new($false)
try {
    New-Item -ItemType Directory -Path (Split-Path -Parent $bootstrapLog) -Force | Out-Null
}
catch {
    $bootstrapLog = $null
}

function Add-BootstrapLog {
    param([AllowEmptyString()][string]$Text)

    if (-not $bootstrapLog) {
        return
    }
    $bytes = $bootstrapLogEncoding.GetBytes(
        $Text + [Environment]::NewLine
    )
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        $stream = $null
        try {
            $stream = [System.IO.FileStream]::new(
                $bootstrapLog,
                [System.IO.FileMode]::Append,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::ReadWrite
            )
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush()
            return
        }
        catch {
            if ($attempt -eq 2) {
                # Logging must not change the Hook response when the file is unavailable.
                return
            }
            Start-Sleep -Milliseconds 10
        }
        finally {
            if ($stream) {
                $stream.Dispose()
            }
        }
    }
}

function ConvertTo-NativeArgument {
    param([AllowEmptyString()][string]$Value)

    if ($Value.Length -eq 0) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(
                [string]::new([char]'\', ($backslashes * 2) + 1)
            )
            [void]$builder.Append('"')
        }
        else {
            if ($backslashes -gt 0) {
                [void]$builder.Append(
                    [string]::new([char]'\', $backslashes * 2)
                )
            }
            [void]$builder.Append($character)
        }
        $backslashes = 0
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(
            [string]::new([char]'\', $backslashes * 2)
        )
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

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

$runStarted = Get-Date
$runStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$runId = $PID
Add-BootstrapLog ""
Add-BootstrapLog (
    "=== Wttch bootstrap start {0} pid={1} ===" -f
    $runStarted.ToString("o"),
    $runId
)
Add-BootstrapLog (
    "event=configuration debug={0} cwd={1} home={2} script={3} arguments={4}" -f
    ([int]$BootstrapDebug),
    (Get-Location).Path,
    $HOME,
    $PSCommandPath,
    $launcherArgs.Count
)
Add-BootstrapLog (
    "event=python selected={0}" -f
    $(if ($pythonCommand) { $pythonCommand.Source } else { "not_found" })
)
if ($BootstrapDebug) {
    Add-BootstrapLog (
        "debug=1 os={0} powershell={1} clr={2}" -f
        [Environment]::OSVersion.VersionString,
        $PSVersionTable.PSVersion,
        [Environment]::Version
    )
    for ($argumentIndex = 0; $argumentIndex -lt $launcherArgs.Count; $argumentIndex++) {
        Add-BootstrapLog (
            "debug=1 argument_{0}={1}" -f
            ($argumentIndex + 1),
            $launcherArgs[$argumentIndex]
        )
    }
}

if (-not $pythonCommand) {
    $hookEvent = $null
    for ($index = 0; $index -lt ($launcherArgs.Count - 1); $index++) {
        if ($launcherArgs[$index] -eq "--hook-event") {
            $hookEvent = $launcherArgs[$index + 1]
            break
        }
    }

    $message = "Wttch 插件无法运行: Python 没有安装或未在 PATH 中找到。请用户安装 Python 并重试。"
    if ($hookEvent) {
        $payload = @{
            hookSpecificOutput = @{
                hookEventName = $hookEvent
                additionalContext = $message
            }
        }
        $text = $payload | ConvertTo-Json -Compress -Depth 4
        Add-BootstrapLog $text
        [Console]::Out.WriteLine($text)
    }
    else {
        $text = "WARNING: $message"
        Add-BootstrapLog $text
        [Console]::Error.WriteLine($text)
    }
    $runStopwatch.Stop()
    Add-BootstrapLog (
        "event=process_exit status=0 finished={0} elapsed_ms={1}" -f
        (Get-Date).ToString("o"),
        $runStopwatch.ElapsedMilliseconds
    )
    exit 0
}

$runner = Join-Path $PSScriptRoot "runner.py"
$nativeArguments = @($pythonPrefix) + @($runner) + @($launcherArgs)
$quotedArguments = foreach ($argument in $nativeArguments) {
    ConvertTo-NativeArgument ([string]$argument)
}
$argumentLine = $quotedArguments -join ' '
$stdoutPath = [System.IO.Path]::GetTempFileName()
$stderrPath = [System.IO.Path]::GetTempFileName()
try {
    Add-BootstrapLog (
        "event=process_start pid={0} python={1} target={2}" -f
        $runId,
        $pythonCommand.Source,
        $runner
    )
    $process = Start-Process `
        -FilePath $pythonCommand.Source `
        -ArgumentList $argumentLine `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath
    $stdoutText = [System.IO.File]::ReadAllText(
        $stdoutPath,
        $bootstrapLogEncoding
    )
    $stderrText = [System.IO.File]::ReadAllText(
        $stderrPath,
        $bootstrapLogEncoding
    )
    if ($stdoutText.Length -gt 0) {
        Add-BootstrapLog $stdoutText
        [Console]::Out.Write($stdoutText)
    }
    if ($stderrText.Length -gt 0) {
        Add-BootstrapLog $stderrText
        [Console]::Error.Write($stderrText)
    }
    $exitCode = $process.ExitCode
    $runStopwatch.Stop()
    $exitMessage = (
        "event=process_exit status={0} finished={1} elapsed_ms={2} " +
        "stdout_bytes={3} stderr_bytes={4}"
    )
    Add-BootstrapLog (
        $exitMessage -f
        $exitCode,
        (Get-Date).ToString("o"),
        $runStopwatch.ElapsedMilliseconds,
        $bootstrapLogEncoding.GetByteCount($stdoutText),
        $bootstrapLogEncoding.GetByteCount($stderrText)
    )
    if ($BootstrapDebug) {
        Add-BootstrapLog "debug=1 exit_code=$exitCode"
    }
}
catch {
    $text = ($_ | Out-String).TrimEnd()
    $runStopwatch.Stop()
    Add-BootstrapLog (
        "event=exception type={0} elapsed_ms={1} message={2}" -f
        $_.Exception.GetType().FullName,
        $runStopwatch.ElapsedMilliseconds,
        $_.Exception.Message
    )
    Add-BootstrapLog $text
    [Console]::Error.WriteLine($text)
    exit 1
}
finally {
    [System.IO.File]::Delete($stdoutPath)
    [System.IO.File]::Delete($stderrPath)
}
exit $exitCode
