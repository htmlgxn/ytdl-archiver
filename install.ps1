$ErrorActionPreference = "Stop"

$packageName = "ytdl-archiver"

function Ask-YesNo {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [bool]$DefaultYes = $true
    )

    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $default = if ($DefaultYes) { "y" } else { "n" }

    while ($true) {
        try {
            $inputValue = Read-Host "$Prompt $suffix"
        } catch {
            return $DefaultYes
        }

        if ([string]::IsNullOrWhiteSpace($inputValue)) {
            $inputValue = $default
        }

        switch ($inputValue.Trim().ToLowerInvariant()) {
            "y" { return $true }
            "yes" { return $true }
            "n" { return $false }
            "no" { return $false }
            default { Write-Host "Please answer y or n." }
        }
    }
}

function Install-Firefox {
    if (Get-Command firefox -ErrorAction SilentlyContinue) {
        Write-Host "Firefox already installed."
        return
    }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Mozilla.Firefox --exact --accept-source-agreements --accept-package-agreements
        return
    }

    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install firefox -y
        return
    }

    Write-Host "No supported package manager found. Install Firefox manually from https://www.mozilla.org/firefox/."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Installing uv..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $uvPath = Join-Path $HOME ".local\bin"
    if (Test-Path $uvPath -PathType Container -and -not $env:PATH.Contains($uvPath)) {
        $env:PATH = "$uvPath;$env:PATH"
    }
}

if (-not (Get-Command deno -ErrorAction SilentlyContinue)) {
    if (Ask-YesNo "Install Deno? (recommended for best yt-dlp compatibility)" $true) {
        Write-Host "deno not found. Installing deno..."
        powershell -ExecutionPolicy Bypass -c "irm https://deno.land/install.ps1 | iex"
        $denoPath = Join-Path $HOME ".deno\bin"
        if (Test-Path $denoPath -PathType Container -and -not $env:PATH.Contains($denoPath)) {
            $env:PATH = "$denoPath;$env:PATH"
        }
    } else {
        Write-Host "Skipping Deno install."
    }
}

if (Ask-YesNo "Install Firefox? (recommended for cookie import)" $true) {
    Install-Firefox
} else {
    Write-Host "Skipping Firefox install."
}

Write-Host "Installing $packageName..."
uv tool install --upgrade $packageName

Write-Host ""
Write-Host "Install complete!"
Write-Host "Launching $packageName..."

if (Get-Command $packageName -ErrorAction SilentlyContinue) {
    & $packageName
} else {
    uv tool run $packageName
}

if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "$packageName exited with status $LASTEXITCODE. You can retry with:"
    Write-Host "  $packageName"
}
