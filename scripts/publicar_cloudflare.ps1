<#
.SYNOPSIS
  Publica Facturas IA en Cloudflare Containers (Worker + Durable Object + contenedor) y administra sus datos.

.DESCRIPTION
  Arquitectura:  navegador -> Worker «facturas-ia» (facturas.marvinlt.cloud, HTTPS)
                 -> Durable Object «FacturasApp» -> contenedor con la app de Python (puerto 8000)

  El sistema corre entero en Cloudflare: no depende de que este equipo esté encendido.
  Los datos (base SQLite, config.json, claves cifradas) se respaldan en el almacenamiento del Durable Object.

  Sin parámetros: construye la imagen y despliega (necesita Docker Desktop abierto y «wrangler login»).
  -Secretos:          copia las API keys del .env a los secretos del Worker (y crea el token de administración).
  -SubirDatos:        reemplaza los datos de la nube por los de la carpeta data/ local y reinicia el contenedor.
  -BajarRespaldo:     descarga el último respaldo de la nube a un .tar.gz.
  -CodigoConfiguracion: para una instalación sin cuenta, crea un código de un solo uso para crear la
                      primera cuenta desde internet. Lo guarda en deploy/cloudflare/.codigo_configuracion.

.EXAMPLE
  .\scripts\publicar_cloudflare.ps1 -Secretos
  .\scripts\publicar_cloudflare.ps1
  .\scripts\publicar_cloudflare.ps1 -BajarRespaldo -Destino .\respaldo.tar.gz
#>
param(
  [switch]$Secretos,
  [switch]$SubirDatos,
  [switch]$BajarRespaldo,
  [switch]$CodigoConfiguracion,
  [string]$Destino = "",
  [string]$Dominio = "facturas.marvinlt.cloud"
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$worker = Join-Path $raiz "deploy\cloudflare"
$archivoToken = Join-Path $worker ".token_admin"
$python = Join-Path $raiz ".venv\Scripts\python.exe"

if (-not (Get-Command wrangler -ErrorAction SilentlyContinue)) {
  throw "No se encontró Wrangler. Instálalo con: npm install -g wrangler, y luego: wrangler login"
}

function New-Aleatorio([int]$bytes = 32) {
  $b = New-Object byte[] $bytes
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  return [Convert]::ToBase64String($b).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Get-TokenAdmin {
  if (-not (Test-Path $archivoToken)) { throw "Falta el token de administración. Ejecuta primero: .\scripts\publicar_cloudflare.ps1 -Secretos" }
  return (Get-Content $archivoToken -Raw).Trim()
}

function Send-Secretos([hashtable]$valores) {
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("facturas-secretos-" + [guid]::NewGuid() + ".json")
  try {
    [IO.File]::WriteAllText($tmp, ($valores | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
    Push-Location $worker
    try { wrangler secret bulk $tmp } finally { Pop-Location }
  } finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

if ($Secretos) {
  $valores = @{}
  $archivoEnv = Join-Path $raiz ".env"
  if (Test-Path $archivoEnv) {
    foreach ($linea in Get-Content $archivoEnv -Encoding UTF8) {
      $l = $linea.Trim()
      if (-not $l -or $l.StartsWith("#") -or -not $l.Contains("=")) { continue }
      $k, $v = $l.Split("=", 2)
      $k = $k.Trim().ToUpper().Replace("-", "_"); $v = $v.Trim().Trim('"').Trim("'")
      if ($k -in @("OPENAI_APIKEY", "OPENAI_API_KEY") -and $v) { $valores["OPENAI_APIKEY"] = $v }
      if ($k -in @("COMPOSIO_APIKEY", "COMPOSIO_API_KEY") -and $v) { $valores["COMPOSIO_APIKEY"] = $v }
    }
  }
  if (-not (Test-Path $archivoToken)) { [IO.File]::WriteAllText($archivoToken, (New-Aleatorio)) }
  $valores["TOKEN_ADMIN"] = Get-TokenAdmin
  Send-Secretos $valores
  Write-Host "Secretos cargados: $($valores.Keys -join ', '). Se aplican la próxima vez que arranque el contenedor."
  return
}

if ($CodigoConfiguracion) {
  $codigo = New-Aleatorio 18
  Send-Secretos @{ CODIGO_CONFIGURACION = $codigo }
  $archivo = Join-Path $worker ".codigo_configuracion"
  [IO.File]::WriteAllText($archivo, $codigo)
  Write-Host "Código guardado en $archivo. Vale solo mientras no exista ninguna cuenta."
  Write-Host "Se aplica cuando el contenedor vuelva a arrancar (por ejemplo, tras: .\scripts\publicar_cloudflare.ps1)."
  return
}

if ($BajarRespaldo) {
  if (-not $Destino) { $Destino = Join-Path $raiz ("respaldo-nube-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".tar.gz") }
  Invoke-WebRequest "https://$Dominio/_admin/respaldo" -Headers @{ Authorization = "Bearer $(Get-TokenAdmin)" } -OutFile $Destino -UseBasicParsing
  Write-Host "Respaldo descargado en $Destino"
  return
}

if ($SubirDatos) {
  Write-Warning "Esto reemplaza TODOS los datos de la nube (facturas, bitácora, cuenta y configuración) por los de data/ local."
  $ok = Read-Host "Escribe SI para continuar"
  if ($ok -ne "SI") { Write-Host "Cancelado."; return }
  $paquete = Join-Path ([IO.Path]::GetTempPath()) "facturas-ia-subida.tar.gz"
  & $python -m app.nube empaquetar $paquete
  if ($LASTEXITCODE -ne 0) { throw "No se pudo empaquetar data/." }
  try {
    $r = Invoke-WebRequest "https://$Dominio/_admin/respaldo" -Method Put -InFile $paquete -ContentType "application/gzip" `
      -Headers @{ Authorization = "Bearer $(Get-TokenAdmin)" } -UseBasicParsing
    Write-Host "Datos subidos: $($r.Content). El contenedor se reinicia con ellos en la próxima visita."
  } finally { Remove-Item $paquete -Force -ErrorAction SilentlyContinue }
  return
}

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker no está corriendo. Abre Docker Desktop y vuelve a intentarlo." }
Push-Location $worker
try { wrangler deploy } finally { Pop-Location }
Write-Host "Publicado en https://$Dominio"
