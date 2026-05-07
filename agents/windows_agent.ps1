param(
    [Parameter(Mandatory=$true)]
    [string]$TaskUrl,
    [switch]$KeepBundle
)

$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    chcp 65001 | Out-Null
} catch { }
$bundleUrl = $TaskUrl.TrimEnd('/') + "/bundle/windows.ps1"
$bundlePath = Join-Path $env:TEMP ("eventlab-bundle-" + [guid]::NewGuid().ToString() + ".ps1")

Write-Host "[Diploma EventLab] Downloading execution bundle..."
Invoke-WebRequest -Uri $bundleUrl -UseBasicParsing -OutFile $bundlePath

try {
    Write-Host "[Diploma EventLab] Running bundle: $bundlePath"
    powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File $bundlePath
} finally {
    if (-not $KeepBundle) {
        Remove-Item -Path $bundlePath -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "[Diploma EventLab] Bundle kept at: $bundlePath"
    }
}
