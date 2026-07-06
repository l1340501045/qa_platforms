param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"

Set-Location $ProjectDir
docker compose --env-file .env.prod -f docker-compose.prod.yml down
