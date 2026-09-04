# RevRecover — Razorpay MCP + env setup for Cursor
# Run from project root: .\scripts\setup-mcp.ps1

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

Write-Host ""
Write-Host "=== RevRecover: Razorpay MCP Setup ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Get test keys from: https://dashboard.razorpay.com/app/keys"
Write-Host "Make sure Test Mode is ON (toggle in dashboard sidebar)."
Write-Host ""

$keyId = Read-Host "Enter Razorpay Key ID (rzp_test_...)"
$keySecret = Read-Host "Enter Razorpay Key Secret" -AsSecureString
$keySecretPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($keySecret)
)

if (-not $keyId.StartsWith("rzp_test_")) {
    Write-Host "Warning: Key ID does not start with rzp_test_ — are you using LIVE keys?" -ForegroundColor Yellow
    $confirm = Read-Host "Continue anyway? (y/N)"
    if ($confirm -ne "y") { exit 1 }
}

# Base64 token (used by remote MCP if you switch to npx later)
$tokenBytes = [Text.Encoding]::UTF8.GetBytes("${keyId}:${keySecretPlain}")
$base64Token = [Convert]::ToBase64String($tokenBytes)
$authHeader = "Basic $base64Token"

# Write .env (gitignored)
@"
RAZORPAY_KEY_ID=$keyId
RAZORPAY_KEY_SECRET=$keySecretPlain
AUTH_HEADER=$authHeader
"@ | Set-Content -Path ".env" -Encoding UTF8

New-Item -ItemType Directory -Force -Path ".cursor" | Out-Null

# Prefer Docker on Windows — avoids mcp-remote Node version issues
$dockerAvailable = $null -ne (Get-Command docker -ErrorAction SilentlyContinue)

if ($dockerAvailable) {
    Write-Host "Docker detected — using razorpay/mcp Docker image (recommended on Windows)." -ForegroundColor Green

    $dockerPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (-not (Test-Path $dockerPath)) {
        $dockerPath = "docker"
    }

    $mcpConfig = @{
        mcpServers = @{
            razorpay = @{
                command = $dockerPath
                args    = @(
                    "run", "--rm", "-i",
                    "-e", "RAZORPAY_KEY_ID",
                    "-e", "RAZORPAY_KEY_SECRET",
                    "razorpay/mcp"
                )
                env = @{
                    RAZORPAY_KEY_ID     = $keyId
                    RAZORPAY_KEY_SECRET = $keySecretPlain
                }
            }
        }
    } | ConvertTo-Json -Depth 10

    Write-Host "Pulling razorpay/mcp image (first time only)..." -ForegroundColor Yellow
    docker pull razorpay/mcp
}
else {
    Write-Host "Docker not found — falling back to npx mcp-remote (requires Node.js 20+)." -ForegroundColor Yellow

    $nodePath = "C:\Program Files\nodejs\node.exe"
    if (-not (Test-Path $nodePath)) {
        Write-Host "Error: Node.js 20+ required. Install from https://nodejs.org/" -ForegroundColor Red
        exit 1
    }

    $mcpConfig = @{
        mcpServers = @{
            razorpay = @{
                command = $nodePath
                args    = @(
                    (Join-Path $env:APPDATA "npm\node_modules\mcp-remote\dist\proxy.js"),
                    "https://mcp.razorpay.com/mcp",
                    "--header",
                    "Authorization:$authHeader"
                )
                env = @{
                    AUTH_HEADER = $authHeader
                }
            }
        }
    } | ConvertTo-Json -Depth 10
}

$mcpConfig | Set-Content -Path ".cursor\mcp.json" -Encoding UTF8

# Also register in global Cursor MCP config (required for Cursor to load the server)
$globalMcpPath = Join-Path $env:USERPROFILE ".cursor\mcp.json"
if (Test-Path $globalMcpPath) {
    $globalMcp = Get-Content $globalMcpPath -Raw | ConvertFrom-Json
    if (-not $globalMcp.mcpServers) {
        $globalMcp | Add-Member -NotePropertyName mcpServers -NotePropertyValue (@{})
    }
    $globalMcp.mcpServers.razorpay = $mcpConfig.mcpServers.razorpay
    $globalMcp | ConvertTo-Json -Depth 10 | Set-Content -Path $globalMcpPath -Encoding UTF8
    Write-Host "  Updated: $globalMcpPath (global Cursor MCP)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
Write-Host "  Created: .env (gitignored)"
Write-Host "  Created: .cursor/mcp.json (gitignored)"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Make sure Docker Desktop is running (if using Docker mode)"
Write-Host "  2. Restart Cursor (or reload window)"
Write-Host "  3. Settings -> MCP -> confirm 'razorpay' server is connected"
Write-Host "  4. In chat, try: 'List available Razorpay tools'"
Write-Host ""
Write-Host "Security: Never commit .env or .cursor/mcp.json to git." -ForegroundColor Yellow
Write-Host ""
