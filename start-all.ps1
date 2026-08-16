# start-all.ps1
# One-command startup for the local model stack that the nexoria-website
# chat widget depends on: Ollama -> FastAPI wrapper -> ngrok (static domain).
#
# Run this after a reboot (or whenever the chat on the live site needs to
# come back online). Leaves three background processes running; close
# this window / Ctrl+C the underlying processes to stop them.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File start-all.ps1

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$OllamaExe   = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
$FastApiPort = 8001
$NgrokDomain = "bovine-cylinder-onboard.ngrok-free.dev"

function Test-Url($url) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        return $resp.StatusCode -eq 200
    } catch {
        return $false
    }
}

Write-Host "=== 1. Ollama ===" -ForegroundColor Cyan
if (Test-Url "http://localhost:11434/api/tags") {
    Write-Host "Already running." -ForegroundColor Green
} else {
    Write-Host "Starting Ollama..."
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Url "http://localhost:11434/api/tags") { $ready = $true; break }
    }
    if (-not $ready) { throw "Ollama did not become ready after 30s." }
    Write-Host "Ollama is up." -ForegroundColor Green
}

Write-Host "`n=== 2. FastAPI wrapper (port $FastApiPort) ===" -ForegroundColor Cyan
if (Test-Url "http://localhost:$FastApiPort/health") {
    Write-Host "Already running." -ForegroundColor Green
} else {
    # Load .env into this process's environment before starting uvicorn.
    $envFile = Join-Path $ScriptDir ".env"
    if (-not (Test-Path $envFile)) {
        throw ".env not found at $envFile - copy .env.example to .env and fill in SERVICE_API_KEY first."
    }
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
        }
    }

    $python = "$env:USERPROFILE\anaconda3\python.exe"
    Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "$FastApiPort" `
        -WorkingDirectory $ScriptDir `
        -WindowStyle Hidden

    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Url "http://localhost:$FastApiPort/health") { $ready = $true; break }
    }
    if (-not $ready) { throw "FastAPI service did not become ready after 20s." }
    Write-Host "FastAPI service is up." -ForegroundColor Green
}

Write-Host "`n=== 3. ngrok tunnel ($NgrokDomain) ===" -ForegroundColor Cyan
$ngrokRunning = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
if ($ngrokRunning -and (Test-Url "https://$NgrokDomain/health")) {
    Write-Host "Already running and reachable." -ForegroundColor Green
} else {
    Write-Host "Starting ngrok (pinned to static domain)..."
    Start-Process -FilePath "ngrok" `
        -ArgumentList "http", "$FastApiPort", "--url=https://$NgrokDomain" `
        -WindowStyle Hidden

    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Url "https://$NgrokDomain/health") { $ready = $true; break }
    }
    if (-not $ready) { throw "ngrok tunnel did not become reachable after 20s." }
    Write-Host "ngrok tunnel is up." -ForegroundColor Green
}

Write-Host "`n=== All services up ===" -ForegroundColor Green
Write-Host "Local:  http://localhost:$FastApiPort/health"
Write-Host "Public: https://$NgrokDomain/health"
Write-Host "`nThe nexoria-website chat should now work end-to-end (assuming"
Write-Host "LOCAL_MODEL_URL/LOCAL_MODEL_API_KEY are set on Render to match)."
