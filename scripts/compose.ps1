param()

# Keep native flags such as -d intact instead of binding PowerShell common parameters.
$ComposeArguments = @($args)

$ErrorActionPreference = 'Stop'
$deploymentRoot = Split-Path -Parent $PSScriptRoot
$composePath = Join-Path $deploymentRoot 'compose.yaml'

if (-not $ComposeArguments -or $ComposeArguments.Count -eq 0) {
    $ComposeArguments = @('ps')
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    & docker compose --project-directory $deploymentRoot -f $composePath @ComposeArguments
} else {
    if ($deploymentRoot -notmatch '^([A-Za-z]):\\(.+)$') {
        throw 'The WSL wrapper requires a local Windows drive path.'
    }
    $driveLetter = $Matches[1].ToLowerInvariant()
    $relativePath = $Matches[2].Replace('\', '/')
    $linuxRoot = "/mnt/$driveLetter/$relativePath"
    & wsl -d Ubuntu -- docker compose --project-directory $linuxRoot -f "$linuxRoot/compose.yaml" @ComposeArguments
}

if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose exited with code $LASTEXITCODE"
}
