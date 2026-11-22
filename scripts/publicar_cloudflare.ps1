<#
.SYNOPSIS
  Publica Facturas IA en un subdominio propio con Cloudflare (Wrangler + túnel + Workers VPC).

.DESCRIPTION
  Arquitectura:  navegador -> Worker «facturas-ia» (dominio propio, HTTPS)
                 -> Workers VPC «facturas-ia-app» -> túnel «facturas-ia» -> http://127.0.0.1:8000

  No necesita permisos de DNS: el dominio propio del Worker crea su registro solo.

  Con -Configurar (una sola vez): crea el túnel y el servicio VPC si no existen, escribe el ID del
  servicio en deploy/cloudflare/wrangler.jsonc y despliega el Worker.
  Sin parámetros: comprueba que la app responda y conecta el túnel hasta que pulses Ctrl+C.

  Requiere Wrangler con la sesión iniciada (wrangler login).

.EXAMPLE
  .\scripts\publicar_cloudflare.ps1 -Configurar
  .\scripts\publicar_cloudflare.ps1
#>
param(
  [switch]$Configurar,
  [string]$Tunel = "facturas-ia",
  [string]$ServicioVpc = "facturas-ia-app",
  [int]$Puerto = 8000
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$worker = Join-Path $raiz "deploy\cloudflare"

if (-not (Get-Command wrangler -ErrorAction SilentlyContinue)) {
  throw "No se encontró Wrangler. Instálalo con: npm install -g wrangler, y luego: wrangler login"
}

function Get-IdTunel {
  $salida = wrangler tunnel list 2>&1 | Out-String
  # Tabla de wrangler: | id | name | status | ...
  $m = [regex]::Match($salida, "([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\W+$([regex]::Escape($Tunel))\s*[^\w-]")
  if ($m.Success) { return $m.Groups[1].Value }
  return $null
}

if ($Configurar) {
  $id = Get-IdTunel
  if (-not $id) {
    $salida = wrangler tunnel create $Tunel 2>&1 | Out-String
    $id = [regex]::Match($salida, "ID:\s*([0-9a-f-]{36})").Groups[1].Value
  }
  if (-not $id) { throw "No se pudo crear ni encontrar el túnel $Tunel." }
  Write-Host "Túnel $Tunel`: $id"

  $lista = wrangler vpc service list 2>&1 | Out-String
  $svc = [regex]::Match($lista, "([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\W+$([regex]::Escape($ServicioVpc))\s*[^\w-]").Groups[1].Value
  if (-not $svc) {
    $salida = wrangler vpc service create $ServicioVpc --type http --tunnel-id $id --ipv4 127.0.0.1 --http-port $Puerto 2>&1 | Out-String
    $svc = [regex]::Match($salida, "VPC service:\s*([0-9a-f-]{36})").Groups[1].Value
  }
  if (-not $svc) { throw "No se pudo crear ni encontrar el servicio VPC $ServicioVpc." }
  Write-Host "Servicio VPC $ServicioVpc`: $svc"

  $cfg = Join-Path $worker "wrangler.jsonc"
  $texto = [IO.File]::ReadAllText($cfg)
  $texto = [regex]::Replace($texto, '"service_id":\s*"[^"]*"', "`"service_id`": `"$svc`"")
  [IO.File]::WriteAllText($cfg, $texto, (New-Object Text.UTF8Encoding $false))

  Push-Location $worker
  try { wrangler deploy } finally { Pop-Location }
  Write-Host "Listo. Para publicar: .\scripts\publicar_cloudflare.ps1"
  return
}

try {
  Invoke-WebRequest "http://127.0.0.1:$Puerto/api/auth/estado" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
  Write-Warning "La app no responde en el puerto $Puerto. Iníciala en otra terminal con:"
  Write-Warning "  .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port $Puerto"
}
$id = Get-IdTunel
if (-not $id) { throw "No existe el túnel $Tunel. Ejecuta primero: .\scripts\publicar_cloudflare.ps1 -Configurar" }
Write-Host "Conectando el túnel $Tunel ($id). Ctrl+C para detener."
wrangler tunnel run $id
