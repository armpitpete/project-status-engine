[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $HOME ".project-status-engine-private-deploy"),
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$KeyComment = "project-status-engine-private-dashboard"
$KeyName = "project-status-engine-private-deploy-ed25519"

function Stop-WithError {
    param([string]$Message)
    throw $Message
}

$sshKeygen = Get-Command ssh-keygen -ErrorAction SilentlyContinue
if (-not $sshKeygen) {
    Stop-WithError "ssh-keygen was not found. Install the Windows OpenSSH Client optional feature first."
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
$keyPath = Join-Path $resolvedOutput $KeyName
$publicKeyPath = "$keyPath.pub"
$manifestPath = Join-Path $resolvedOutput "provisioning-manifest.txt"

$existing = @(@($keyPath, $publicKeyPath, $manifestPath) | Where-Object { Test-Path -LiteralPath $_ })
if ($existing.Count -gt 0 -and -not $Force) {
    Stop-WithError (
        "Provisioning files already exist. Refusing to overwrite: " +
        ($existing -join ", ") +
        ". Re-run with -Force only after confirming the previous key is no longer in use."
    )
}

New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
if ($Force) {
    foreach ($path in @($keyPath, $publicKeyPath, $manifestPath)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
}

# Windows PowerShell 5.1 drops an unquoted empty native-command argument.
# Start-Process receives an explicit pair of quote characters so ssh-keygen
# parses -N as an empty passphrase rather than consuming the following flag.
$sshKeygenArguments = @(
    "-t", "ed25519",
    "-N", '""',
    "-C", "`"$KeyComment`"",
    "-f", "`"$keyPath`""
)
$keygenProcess = Start-Process `
    -FilePath $sshKeygen.Source `
    -ArgumentList $sshKeygenArguments `
    -NoNewWindow `
    -Wait `
    -PassThru
if ($keygenProcess.ExitCode -ne 0) {
    Stop-WithError "ssh-keygen failed with exit code $($keygenProcess.ExitCode)."
}

if (-not (Test-Path -LiteralPath $keyPath) -or -not (Test-Path -LiteralPath $publicKeyPath)) {
    Stop-WithError "ssh-keygen did not create the expected private and public key files."
}

$fingerprint = (& $sshKeygen.Source -lf $publicKeyPath 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($fingerprint)) {
    Stop-WithError "The generated public-key fingerprint could not be read."
}

$manifest = @(
    "Project Status Engine private deployment credential",
    "Generated: $([DateTimeOffset]::Now.ToString('o'))",
    "Private key: $keyPath",
    "Public key: $publicKeyPath",
    "Public-key fingerprint: $fingerprint",
    "",
    "Required handling:",
    "1. Keep the private key local and secret.",
    "2. Install only the public key on server.vaelinya.uk for the vaelinya account.",
    "3. Store the complete private-key file as GitHub Actions secret PRIVATE_STATUS_DEPLOY_KEY.",
    "4. Verify the server SSH host fingerprint independently before setting PRIVATE_STATUS_KNOWN_HOSTS.",
    "5. Do not enable PRIVATE_STATUS_DEPLOY_ENABLED until the server and both secrets are ready."
)
$manifest | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Dedicated Ed25519 deployment key created."
Write-Host "Private key: $keyPath"
Write-Host "Public key:  $publicKeyPath"
Write-Host "Manifest:    $manifestPath"
Write-Host "Fingerprint: $fingerprint"
Write-Host ""
Write-Host "The private-key contents were not printed. Follow the manifest and repository deployment documentation."
