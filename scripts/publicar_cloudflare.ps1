<#
.SYNOPSIS
  Publica Facturas IA en un subdominio propio con Cloudflare Tunnel.

.DESCRIPTION
  Con -Configurar (una sola vez): inicia sesión en Cloudflare si hace falta, crea el túnel,
  escribe ~/.cloudflared/<túnel>.yml y crea el registro DNS del subdominio.
  Sin parámetros: comprueba que la app responda y publica el túnel hasta que pulses Ctrl+C.

.EXAMPLE
  .\scripts\publicar_cloudflare.ps1 -Configurar
  .\scripts\publicar_cloudflare.ps1
  .\scripts\publicar_cloudflare.ps1 -Configurar -Subdominio facturas-demo -Dominio ejemplo.com
#>
param(
  [switch]$Configurar,
  [string]$Subdominio = "facturas",
  [string]$Dominio = "marvinlt.cloud",
  [string]$Tunel = "facturas-ia",
  [int]$Puerto = 8000
)
$ErrorActionPreference = "Stop"

function Find-Cloudflared {
  $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($p in @("$env:ProgramFiles\cloudflared\cloudflared.exe", "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
                   "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe")) {
    if (Test-Path $p) { return $p }
  }
  throw "No se encontró cloudflared. Instálalo con: winget install --id Cloudflare.cloudflared"
}

function Get-Tunel([string]$cf, [string]$nombre) {
  $json = & $cf tunnel list --output json 2>$null
  if (-not $json) { return $null }
  return ($json | ConvertFrom-Json) | Where-Object { $_.name -eq $nombre } | Select-Object -First 1
}

$cf = Find-Cloudflared
$dir = Join-Path $HOME ".cloudflared"
$hostname = "$Subdominio.$Dominio"
$config = Join-Path $dir "$Tunel.yml"

if ($Configurar) {
  if (-not (Test-Path (Join-Path $dir "cert.pem"))) {
    Write-Host "Se abrirá el navegador para autorizar el dominio $Dominio en tu cuenta de Cloudflare."
    & $cf tunnel login
  }
  $t = Get-Tunel $cf $Tunel
  if (-not $t) {
    & $cf tunnel create $Tunel | Out-Host
    $t = Get-Tunel $cf $Tunel
  }
  if (-not $t) { throw "No se pudo crear el túnel $Tunel." }
  $cred = Join-Path $dir "$($t.id).json"
  $yaml = @"
tunnel: $($t.id)
credentials-file: $cred
ingress:
  - hostname: $hostname
    service: http://127.0.0.1:$Puerto
  - service: http_status:404
"@
  # Sin BOM: el lector YAML de cloudflared no lo acepta.
  [IO.File]::WriteAllText($config, $yaml, (New-Object Text.UTF8Encoding $false))
  # Sin --overwrite-dns: si ya existe un registro con ese nombre, no se pisa.
  & $cf tunnel route dns $Tunel $hostname | Out-Host
  Write-Host "Listo: https://$hostname -> http://127.0.0.1:$Puerto (túnel $Tunel, configuración en $config)."
  Write-Host "Para publicar: .\scripts\publicar_cloudflare.ps1"
  return
}

if (-not (Test-Path $config)) {
  throw "Falta la configuración del túnel. Ejecuta primero: .\scripts\publicar_cloudflare.ps1 -Configurar"
}
try {
  Invoke-WebRequest "http://127.0.0.1:$Puerto/api/auth/estado" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
  Write-Warning "La app no responde en el puerto $Puerto. Iníciala en otra terminal con:"
  Write-Warning "  .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port $Puerto"
}
Write-Host "Publicando https://$hostname (Ctrl+C para detener)."
& $cf tunnel --config $config run $Tunel
