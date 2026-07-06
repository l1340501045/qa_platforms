param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"

function Test-DockerReady {
    docker info *> $null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-DockerReady)) {
    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktop) {
        Start-Process $dockerDesktop | Out-Null
    }

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        if (Test-DockerReady) {
            break
        }
    }
}

if (-not (Test-DockerReady)) {
    throw "Docker Desktop 未就绪，请先启动 Docker Desktop。"
}

Set-Location $ProjectDir

if (-not (Test-Path ".env.prod")) {
    throw "缺少 .env.prod，请先从 .env.prod.example 复制并填写真实 LLM 配置。"
}

docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
