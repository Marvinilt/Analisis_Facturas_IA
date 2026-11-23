# Reporte de pruebas: publicación en Cloudflare Containers (v1.2.0)

- **Fecha:** 22 de noviembre de 2026
- **Resultado:** 46 pruebas unitarias correctas (`pytest tests`), 23 de 23 casos del frontend (`tests/frontend/probar_frontend.py`) y las comprobaciones de abajo, en local con Docker y en el dominio público.

## 1. Pruebas automáticas nuevas

| Archivo | Qué comprueba |
|---------|---------------|
| `tests/test_nube.py` | Empaquetar y restaurar la base y la configuración; se borran el `-wal` y el `-shm` viejos; se ignoran entradas ajenas o con rutas como `../`; solo se sube un respaldo si cambió la base o algún archivo, y se reintenta tras un fallo de red. |
| `tests/test_auth.py` | Primera cuenta desde internet solo con el código de configuración (sin código o con uno malo: 403; con el bueno: 200; después: 409) y rutas internas: `/_interno/pulso` responde 404 sin el token correcto. |
| `tests/conftest.py` | Fija una carpeta de datos temporal antes de importar la app (ver el defecto 1). |

## 2. Imagen Docker en local, con un servidor de respaldo falso

Se construyó la imagen (`docker build --platform linux/amd64`, 1 min 51 s) y se corrió con `FACTURAS_IA_RESPALDO_URL` apuntando a un servidor de Python que imita a la clase `Almacen` del Worker. Para no tocar Google Drive, el paquete de prueba tenía el procesamiento programado apagado y el proveedor local.

| Paso | Resultado |
|------|-----------|
| Arranque | `Respaldo restaurado (18667 bytes): estado.db, config.json` y Uvicorn en marcha. La cuenta existente aparece (`requiere_configuracion: false`). |
| Cambio en la base | A los 30 s se subió un respaldo nuevo (`PUT 18860 bytes`). |
| Otro cambio y `docker stop` (SIGTERM) | Se subió el último respaldo al apagarse (`PUT 18875 bytes`) y el proceso terminó en menos de 1 s. |
| Contenedor nuevo | Restauró las dos filas de prueba y la cuenta. |
| Zona horaria | `date` dentro del contenedor muestra CST, igual que el equipo. |

## 3. En Cloudflare (https://facturas.marvinlt.cloud)

| Comprobación | Resultado |
|--------------|-----------|
| Arranque en frío (primera petición) | 200 en 9,1 s; las siguientes, 0,3–0,4 s. |
| Migración de datos (`PUT /_admin/respaldo`) | 200, 18 933 bytes. El contenedor se reinició y la cuenta aparece en la nube. |
| `/_interno/salud` desde internet | 404: el Worker bloquea las rutas internas. |
| `/_admin/respaldo` sin token | 401. Con token, descarga el respaldo (19 021 bytes). |
| `/api/estado` sin sesión | 401. |
| Login con datos incorrectos y `Origin` propio | 401 «Usuario o contraseña incorrectos» (la comprobación de origen acepta el dominio). |
| Login con `Origin` ajeno | 403 «Origen no permitido». |
| Crear cuenta desde internet con una cuenta ya creada | 409. |
| Cabeceras | `Strict-Transport-Security` y `X-Frame-Options: SAMEORIGIN`. |
| Corrida programada en la nube | Corrida 43 a las 22:22 (hora local): se conectó a Google Drive por Composio, leyó «Facturas IA» y no había facturas pendientes. |
| Respaldo automático | `PUT http://respaldo.interno/respaldo - Ok` en los registros del Worker: el intercept funciona. |

Capturas del campo «Código de configuración» simulando una visita desde internet a una instalación vacía: [`16_codigo_configuracion_escritorio.png`](frontend/capturas/16_codigo_configuracion_escritorio.png) y [`16_codigo_configuracion_movil.png`](frontend/capturas/16_codigo_configuracion_movil.png).

## Defectos encontrados y corregidos

| # | Defecto | Causa | Corrección |
|---|---------|-------|------------|
| 1 | Al agregar `test_nube.py`, las pruebas de `test_unidad.py` escribieron 10 corridas de prueba, 40 eventos, 1 archivo y los contadores en la base **real** `data/estado.db`, y 5 pruebas fallaron | `test_nube.py` importaba la app durante la recolección, antes de que `test_unidad.py` fijara `FACTURAS_IA_DATA`, así que la app quedó apuntando a `data/` | Se borraron exactamente esas filas (corridas 32–41 de origen «prueba», sus eventos y el archivo `f1.pdf`); los contadores los rehízo la corrida real siguiente. Nuevo `tests/conftest.py`, que fija una carpeta temporal antes de cualquier importación. Se verificó que tras correr todas las pruebas la base real no cambia. |
| 2 | En la imagen, el paso de `tzdata` quedó en una sola línea con espacios de más | El script que lo insertó interpretó la barra invertida del final de línea | Se reescribió con continuaciones de línea normales. |
| 3 | Tras detener el túnel viejo seguía vivo el proceso `cloudflared` | Se detuvo el comando de Wrangler, pero no el proceso hijo | Se cerró el proceso `cloudflared` a mano. |
