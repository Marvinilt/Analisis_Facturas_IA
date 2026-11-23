# Changelog

Todos los cambios relevantes de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/) y el proyecto usa [Versionado Semántico 2.0.0](https://semver.org/lang/es/).

Las referencias del tipo **D-12** apuntan a la decisión correspondiente en [DECISIONES.md](DECISIONES.md).

## [Sin publicar]

_Sin cambios todavía._

---

## [1.2.0] - 2026-11-22

El sistema pasa a correr entero en **Cloudflare Containers**: ya no depende de que el equipo local esté encendido.

### Agregado

#### Contenedor (`Dockerfile`, `.dockerignore`)

- Imagen `python:3.13-slim` con `tzdata`, las dependencias de `requirements.txt` y solo `app/`, `web/` y `diseno/`. Corre con un usuario sin privilegios (uid 10001) y guarda los datos en `/datos` (D-48).
- Al arrancar ejecuta `python -m app.nube restaurar` y luego Uvicorn con `exec`, para que reciba SIGTERM y se apague de forma ordenada (60 s de gracia).
- `.dockerignore` deja fuera `.env`, `data/`, pruebas, documentación y herramientas: ningún secreto ni dato entra en la imagen.

#### Worker y Durable Object (`deploy/cloudflare/`)

- Durable Object `FacturasApp` con la API nativa `ctx.container`: arranca el contenedor (1/4 vCPU, 1 GiB, 4 GB), espera a que responda `/_interno/salud`, le pasa los secretos como variables de entorno y le reenvía todas las peticiones (D-48).
- Clase `Almacen` que intercepta `http://respaldo.interno` desde el contenedor y guarda el respaldo en el almacenamiento SQLite del Durable Object, en trozos de 512 KB y con generaciones para que un corte a medias no deje un respaldo roto (D-49).
- Cron `*/5 * * * *` (pulso) que mantiene despierto el contenedor mientras el procesamiento programado esté activo o haya una corrida, y lo apaga de forma ordenada tras 15 minutos sin visitas (D-50).
- Ruta `/_admin/respaldo` (GET para descargar, PUT para reemplazar) protegida con el secreto `TOKEN_ADMIN`; el Worker bloquea `/_interno/*` desde internet.

#### Aplicación

- `app/nube.py`: empaqueta la base (API de respaldo de SQLite) con `config.json`, `secretos.enc` y `.clave`; restaura solo nombres conocidos; vigila cambios con `PRAGMA data_version` y sube un respaldo cada 30 s si hubo cambios y al apagarse (D-49).
- Rutas internas `/_interno/salud` y `/_interno/pulso` (esta exige un token que el Durable Object genera en cada arranque).
- Código de configuración de un solo uso para crear la primera cuenta desde internet en una nube vacía (`FACTURAS_IA_CODIGO_CONFIGURACION`), con el mismo límite de intentos que el inicio de sesión; campo nuevo en la pantalla de acceso (D-50).
- Tabla `ajustes` en la base: guarda la hora de la última corrida programada para que un reinicio del contenedor no adelante la siguiente.

#### Script (`scripts/publicar_cloudflare.ps1`)

- Sin parámetros: construye la imagen y despliega (comprueba que Docker esté corriendo).
- `-Secretos`, `-SubirDatos`, `-BajarRespaldo` y `-CodigoConfiguracion`.

#### Pruebas

- `tests/test_nube.py`: empaquetar y restaurar, nombres ajenos ignorados, subida solo con cambios y reintento tras un fallo.
- `tests/test_auth.py`: creación de la primera cuenta con código y protección de las rutas internas.
- `tests/conftest.py`: todas las pruebas usan una carpeta de datos temporal.

### Cambiado

- Publicación: el Worker ya no reenvía por Workers VPC y túnel a `127.0.0.1:8000`, sino al Durable Object del contenedor. La decisión D-45 queda reemplazada por la D-48.
- Los datos y la cuenta del equipo local se migraron a la nube. La app local queda como entorno de desarrollo.

### Corregido

- Las pruebas podían escribir en la carpeta `data/` real si un módulo de prueba importaba la app antes de fijar `FACTURAS_IA_DATA`. Ahora `tests/conftest.py` la fija antes de cualquier importación.

---

## [1.1.0] - 2026-11-22

Rediseño completo del frontend, inicio de sesión, panel de indicadores con gráficos y publicación en internet con Cloudflare Tunnel.

### Agregado

#### Inicio de sesión y seguridad (`app/auth.py`, `app/main.py`)

- Pantalla de acceso con usuario y contraseña, opción «Mantener la sesión en este equipo», mostrar u ocultar la contraseña y medidor de fortaleza al crear la cuenta (D-37).
- Contraseñas con scrypt de la biblioteca estándar y mínimo de 10 caracteres; sesiones por cookie `HttpOnly`, `SameSite=Lax` y `Secure` por HTTPS, de 12 horas, guardando en la base solo el hash del token (D-37, D-38).
- Bloqueo de 5 minutos tras 5 intentos fallidos desde la misma IP, que se toma de `CF-Connecting-IP` cuando la petición pasa por Cloudflare (D-38).
- Creación de la primera cuenta solo desde el mismo equipo y comando `python -m app.auth crear-usuario <usuario>` para crear la cuenta o cambiar la contraseña (D-39).
- Middleware que exige sesión en toda la API y en el diagrama, rechaza las peticiones de otro origen que modifican datos y agrega cabeceras de seguridad (D-40).
- Endpoints `/api/auth/estado`, `/api/auth/login`, `/api/auth/configurar` y `/api/auth/logout`.

#### Panel de indicadores (`app/estadisticas.py`, `web/graficos.js`)

- Endpoint `/api/estadisticas?dias=N` con la serie diaria de resultados, los motivos de revisión clasificados, el rendimiento por modelo, el monto registrado y el total catálogo, y la duración de las corridas (D-42).
- **Recorrido de cada factura**: las 7 etapas del flujo, con el dato clave de cada una, cuántas facturas se desvían a revisión en cada etapa y la etapa en curso animada cuando hay una corrida. En móvil se muestra como línea de tiempo vertical.
- Cinco indicadores: pendientes en Drive, procesadas y a revisión (con su tendencia diaria), tasa de éxito con barra de proporción y monto registrado con el total catálogo.
- Filtro de periodo: 7, 30 y 90 días, o todo. Se recuerda en el navegador.
- Gráfico de columnas apiladas **Resultado por día**, con leyenda y tooltip por día.
- Gráfico de barras **Por qué van a revisión**, con cantidad y porcentaje.
- Tabla **Rendimiento por modelo**: intentos, porcentaje de datos válidos y segundos promedio.
- Lista de **corridas** con filtro (programadas, manuales, detenidas), duración y resultado; al elegir una se ve su bitácora.
- **Bitácora** con filtro por nivel (info, avisos, errores) y búsqueda con resaltado.
- Gráficos propios en SVG, sin bibliotecas, que siguen el tema (D-41).

#### Interfaz

- Rediseño completo con identidad propia: acento violeta de sello, tipografías Bricolage Grotesque y Figtree, y colores de estado reservados con icono y texto (D-43).
- Menú lateral con iconos, contraíble a 76 px y persistente; en tableta y móvil se abre como panel lateral.
- Botón de **tema claro u oscuro** en la esquina superior derecha de todas las pantallas, incluida la de acceso. Por defecto sigue al sistema (D-44).
- Barra superior fija con el estado del proceso, **Procesar ahora** y **Detener**.
- Estado del servicio y contador de facturas en revisión en el menú lateral.
- **Facturas**: filtros por estado con contadores, búsqueda por archivo, emisor, número o motivo, orden por cualquier columna, paginación de 15, exportación a CSV, tipo de archivo identificado y navegación con teclado.
- **Detalle de la factura** en un panel lateral: totales, motivo de revisión, datos extraídos, líneas con su producto del catálogo, reglas de validación con iconos, intentos por modelo, texto OCR y bitácora. Se cierra con Esc o al hacer clic fuera.
- **Configuración** con navegación por iconos, interruptores en lugar de casillas, campos alineados, enlaces directos a cada sección (`#config/modelos`) y estados de carga.
- Avisos apilables, tooltips, estados vacíos con indicaciones y animaciones que respetan «reducir movimiento».

#### Publicación

- Sistema publicado en **https://facturas.marvinlt.cloud** con un Worker de Cloudflare con dominio propio (`deploy/cloudflare/`), un servicio de Workers VPC y el túnel `facturas-ia`. Sin abrir puertos y sin permiso para editar DNS (D-45).
- El Worker fija las cabeceras de origen (`CF-Connecting-IP`, `X-Forwarded-*`), agrega HSTS y muestra una página de «no disponible» cuando el equipo está apagado.
- Script `scripts/publicar_cloudflare.ps1`: con `-Configurar` crea el túnel y el servicio VPC y despliega el Worker; sin parámetros conecta el túnel.
- La comprobación de origen acepta `X-Forwarded-Host` para funcionar detrás del Worker (D-47).

#### Pruebas y documentación

- 6 pruebas unitarias nuevas de inicio de sesión y protección de la API (`tests/test_auth.py`); en total, 40.
- Pruebas de punta a punta de la interfaz con Playwright y el navegador del equipo: 23 casos en escritorio, laptop, tableta y móvil, en tema claro y oscuro, con detección automática de errores de JavaScript, desbordes, textos cortados e iconos rotos (`tests/frontend/probar_frontend.py`, D-46).
- Generador de datos de demostración: 45 días, 236 facturas de emisores ficticios (`tests/frontend/datos_demo.py`).
- Reporte de pruebas con los 11 defectos encontrados y su corrección, y 38 capturas (`tests/frontend/REPORTE_PRUEBAS.md`).
- `requirements-dev.txt` con Playwright.
- README reescrito: badges de las tecnologías, capturas, arquitectura con Cloudflare, ejecución, configuración, publicación, interfaz, API y seguridad.
- Decisiones 37 a 46 en `DECISIONES.md`.

### Cambiado

- La aplicación ya no es de acceso libre: todas las rutas, salvo la pantalla de acceso, requieren sesión. La decisión 36 queda reemplazada por la 37.
- El frontend pasa de pestañas en la cabecera a una estructura con menú lateral y rutas por `#hash`.
- Los números se muestran siempre con separador de miles.

### Corregido

Defectos encontrados por las pruebas de la interfaz antes de publicar la versión (detalle en el reporte):

- La tarjeta «Tasa de éxito» heredaba la animación del sello de la pantalla de acceso y desbordaba la página en móvil.
- Al cerrar sesión, una consulta de estado tardía podía reiniciar el formulario de acceso mientras se escribía.
- El número de factura se partía en dos líneas y el formato de miles era inconsistente.
- Campos de configuración desalineados, hueco en los indicadores en tableta y título repetido en las alertas.

## [1.0.0] - 2026-11-22

Primera versión completa del sistema: procesamiento de punta a punta de facturas desde Google Drive hasta Google Sheets, con aplicación web de operación y configuración.

### Agregado

#### Pipeline de procesamiento (`app/pipeline.py`)

- Flujo completo en 14 pasos más el desvío a revisión: vigilar carpeta (01), detectar nuevos (02), cola (03), descargar y preparar (04), extracción IA (05), modelo de respaldo (06), validar esquema (07), cuadre de montos (08), decisión de confiabilidad (09), cruce con catálogo (10), total catálogo (11), registro en la hoja (12), mover a *Procesadas* (13), mover a *Revisión manual* (R) y conteo final (14).
- Creación automática de las subcarpetas *Procesadas* y *Revisión manual* dentro de «Facturas IA» cuando no existen.
- Procesamiento secuencial con máximo de facturas por corrida configurable.
- Detención de la corrida (`ProcesoDetenido`) cuando ningún modelo de la cadena está disponible: la factura vuelve a *pendiente*, no se mueve y el resto de la cola no se procesa (D-2).
- Distinción entre `ErrorProveedor` (el modelo no responde) y `ErrorDocumento` (el documento no da datos) para separar caídas de servicio de facturas no confiables (D-3).
- Hasta 3 intentos de extracción por factura, escalando del modelo primario al más robusto, con una *pista* en cada reintento que describe lo que falló (D-4).
- Envío directo a revisión, sin gastar llamadas, de documentos que no se pueden abrir (PDF con contraseña, imagen corrupta) (D-5).
- Detección de duplicados por huella md5 del archivo y por emisor + número de factura ya registrados; siempre se marca el que llega después (D-8).
- Archivos de tipos no admitidos (distintos de PDF, JPG, PNG y WEBP) ignorados y dejados en la carpeta, sin contarlos como pendientes (D-9).
- Orden seguro de operaciones: el archivo se mueve solo después de escribir las filas; estado «registrada, sin mover» para completar el movimiento en la siguiente corrida; filas con el ID del archivo para no duplicarlas al reintentar (D-10).
- Recuperación al arrancar: las facturas que quedaron «en proceso» por un corte vuelven a *pendiente* (D-11).
- Bitácora de eventos por archivo y por paso, con niveles de información, aviso y error.

#### Extracción con IA (`app/extraction/`)

- Interfaz común de extractores (`base.py`) y cadena de modelos configurable.
- Extractor **GLM-OCR local vía Ollama** (`glm_ocr.py`) en modo reconocimiento de texto, con estructuración posterior mediante `gpt-5.4-nano` (D-12, D-13).
- Opción alternativa «GLM-OCR directo (100 % local)» disponible en Configuración (D-13).
- Extractor **OpenAI con visión** `gpt-5.4-mini` como respaldo (`openai_ext.py`), que también aprovecha la capa de texto del PDF si existe (D-16).
- Salida estructurada estricta generada desde el esquema configurable, con los campos opcionales aceptando `null` y los campos adicionales `es_factura`, `confianza` y `observaciones` (D-17).
- `reasoning_effort: low` para los modelos `gpt-5*` (D-18).
- Preparación de documentos (`preparar.py`): uso de la capa de texto del PDF cuando existe para saltar el OCR (D-14), rasterizado de PDF a 150 dpi, máximo 5 páginas, reducción de imágenes a 1800 px y a 1000 px para GLM-OCR (D-15).
- Instrucciones de extracción centralizadas (`instrucciones.py`), incluida la regla de devolver los descuentos en positivo.
- Reintentos técnicos y timeout por modelo configurables.

#### Validación (`app/validacion.py`)

- Validación contra JSON Schema (Draft 2020-12) editable desde la app.
- Cuadre de montos por línea (`cantidad × precio − descuento = importe`), suma de líneas contra subtotal y fórmula del total (`subtotal − descuento + impuestos + otros cargos = total`), con tolerancias de redondeo realistas que crecen con la cantidad y el número de líneas (D-7).
- Regla de decisión: esquema completo + montos que cuadran + confianza ≥ 0,6 + el documento es una factura (D-6).
- Mapeo configurable de nombres de campos para el cuadre, de modo que el esquema pueda cambiar sin tocar el código.
- Normalización de números con detección automática del separador decimal (`1.234,56` y `1,234.56`; `1,130` como miles) (D-31).
- Normalización de fechas con el día primero (`dd/mm/aaaa`) (D-30).

#### Catálogo (`app/catalogo.py`)

- Coincidencia de líneas en orden: código exacto → palabra clave o sinónimo (palabra completa, sin tildes ni mayúsculas) → parecido de texto ≥ 85 con rapidfuzz por ventanas de palabras (D-27).
- Cálculo del *total catálogo* y del porcentaje sobre el subtotal, sin impuestos por defecto o con impuesto prorrateado como opción (D-28).
- Catálogo de ejemplo con Cemento, Varilla, Pintura, Arroz y Aceite vegetal (D-29).
- Importación del catálogo desde CSV (`código,producto,palabra1|palabra2`).

#### Almacenamiento (`app/storage/`)

- Interfaz común de almacenamiento (`base.py`) con los tipos admitidos y los nombres de las pestañas de resultados.
- Integración con **Google Drive y Google Sheets mediante Composio Connect** (MCP en `connect.composio.dev`, cabecera `x-consumer-api-key`) (D-19).
- Cliente MCP (`composio_mcp.py`) y uso de `COMPOSIO_PROXY_EXECUTE` sobre la API REST de Google para listar, crear carpetas, mover y leer/escribir celdas, y de `GOOGLEDRIVE_DOWNLOAD_FILE` para descargar (D-20).
- Restricción de todas las operaciones a la carpeta «Facturas IA» y sus subcarpetas, con verificación antes de descargar o mover y detención si hay carpetas con el mismo nombre (D-21).
- Hoja de resultados **«Facturas Procesadas IA»** creada dentro de «Facturas IA» con las pestañas *Facturas*, *Detalle* y *Errores*; columnas nuevas agregadas al final cuando el esquema crece (D-22, D-23).
- Modo **Carpeta local** que imita Drive con subcarpetas y un `.xlsx` real, para probar sin conexión (D-26).

#### Aplicación web

- API REST con FastAPI (`app/main.py`): estado, procesar, detener, corridas, eventos, archivos y su detalle, alertas, configuración por secciones con restablecer, secretos, prueba de conexión con Drive, modelos de Ollama, prueba de extracción y prueba de catálogo.
- Servicio de corridas en segundo plano y planificador interno con frecuencia, franja horaria y máximo por corrida; la revisión automática viene apagada al instalar (`app/servicio.py`, D-34).
- Estado persistente en SQLite: archivos, corridas, bitácora y alertas (`app/db.py`, D-32).
- Configuración editable con valores por defecto y validación por sección (`app/configuracion.py`).
- API keys escritas en la app guardadas cifradas con Fernet; lectura de respaldo desde `.env` con nombres con guion o guion bajo; el navegador nunca recibe una clave completa (`app/secretos.py`, `app/settings.py`, D-33).
- Frontend sin dependencias (`web/`) con pestañas:
  - **Panel**: contadores, botón *Procesar ahora*, paso en curso, últimas corridas, alertas y bitácora.
  - **Facturas**: estado de cada archivo y detalle con datos extraídos, líneas y coincidencias del catálogo, reglas de validación, intentos por modelo y texto OCR.
  - **Configuración**: conexión, carpetas, frecuencia, cadena de modelos y API keys, esquema (tabla o JSON), reglas de validación, catálogo con importación CSV y prueba de descripciones, y *Probar extracción* con un archivo local.
  - **Diagrama**: flujo interactivo del proceso.
- Alertas en el panel cuando la corrida se detiene por falta de modelos o hay un problema con Google Drive; se cierran solas al recuperarse (D-35).

#### Pruebas y herramientas

- 34 pruebas unitarias sin red (`tests/test_unidad.py`): números, fechas, cuadre de líneas y totales, descuento impreso en negativo, campos faltantes, documentos que no son factura, confianza baja, catálogo y falsos positivos, esquema estricto, lectura de JSON y reglas de la cadena de modelos (caída total, uso del respaldo, reintentos y envío a revisión).
- Generador de 11 documentos de prueba (`tests/generar_documentos.py`): PDF con texto, PDF escaneado, JPG, PNG, totales erróneos, descuentos, foto borrosa, PDF protegido, documento que no es factura, duplicado y archivo de texto, con los resultados esperados en `tests/docs/esperado.json`.
- Prueba de punta a punta con modelos reales en carpeta local y en Google Drive (`tests/e2e.py`).
- Escenario real de «modelos caídos» (`tests/e2e_caida.py`): verifica que la corrida se detiene, ninguna factura se mueve y queda una alerta.
- Script para subir los documentos de prueba a Drive mediante el workbench remoto de Composio (`scripts/subir_pruebas_drive.py`, D-25).
- Script de solo lectura para inspeccionar la hoja y las carpetas en Drive (`scripts/ver_hoja.py`).

#### Documentación

- `README.md` con descripción, arquitectura, flujo, instalación, configuración, uso, API, pruebas, seguridad y solución de problemas.
- `DECISIONES.md` con las 36 decisiones de diseño, su motivo y dónde se cambian.
- Diagrama interactivo del flujo (`diseno/flujo-facturas-ia.html`).
- `CHANGELOG.md` (este archivo).
- Plantilla de claves `.env.example` y `.gitignore` que excluye `.env`, `data/` y cachés.

### Corregido durante la validación de la versión

Problemas encontrados en las pruebas de punta a punta en Google Drive y resueltos antes de publicar la versión:

- **Descuentos impresos en negativo sumaban en lugar de restar.** La factura escaneada imprime «Descuento -25,00»; el modelo lo copiaba negativo y el cuadre daba 5.907 en lugar de 5.857, enviando a revisión una factura correcta. Ahora los descuentos siempre restan, vengan con o sin signo, y las instrucciones piden a los modelos devolverlos en positivo (D-11b).
- **Límite de lecturas por minuto de Google Sheets (error 429).** El primer diseño leía la hoja unas 4 veces por factura. Ahora cada pestaña se lee una sola vez por corrida con copia local, las filas nuevas se agregan con `values:append` y ante un 429 se reintenta tras 15, 30 y 60 s (D-23b).
- **GLM-OCR en modo JSON confundía campos** (ponía «FACTURA» como número y copiaba el subtotal en el descuento). Se cambió a modo de reconocimiento de texto con estructuración posterior por `gpt-5.4-nano` (D-13).
- **Tiempo de OCR en CPU.** Con imágenes de 1160 px GLM-OCR tardaba 123 s por página; reduciéndolas a 1000 px baja a unos 45–60 s sin perder precisión en las cifras (D-15).

### Seguridad

- La aplicación escucha solo en `localhost` y no tiene autenticación; está pensada para uso personal (D-36).
- Claves cifradas en reposo y nunca expuestas completas al navegador (D-33).
- Operaciones en Drive limitadas a la carpeta «Facturas IA» y sus subcarpetas (D-21).
