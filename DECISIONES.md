# Decisiones del proyecto Facturas IA

Registro de las decisiones tomadas durante el desarrollo. Cada una indica qué se decidió, por qué y dónde se puede cambiar.
Fecha de inicio: 22 de noviembre de 2026.

## Flujo y manejo de errores

| # | Decisión | Motivo | Dónde se cambia |
|---|----------|--------|-----------------|
| 1 | **La descarga no revisa si el archivo está dañado.** Un PDF protegido, una imagen corrupta o ilegible siguen adelante y fallan en el paso 05 (extracción); como sus datos no son confiables, terminan en *Revisión manual* con el motivo exacto. | Pedido explícito: el daño se detecta al extraer y validar, no al descargar. | `app/pipeline.py` · `extraer_y_validar` |
| 2 | **Si ningún modelo está disponible, la corrida se detiene.** Una caída del servicio, falta de saldo, API key inválida u Ollama apagado se tratan como *error técnico*: el modelo se marca como no disponible y se prueba el siguiente; si no queda ninguno, la factura vuelve a *pendiente* (no se mueve) y no se procesa el resto de la cola. Aparece un aviso en el panel con el error de cada modelo. | Pedido explícito. Un modelo caído no dice nada de la factura, así que no debe ir a revisión. | `app/pipeline.py` · `ProcesoDetenido` |
| 3 | Se distinguen dos clases de error: `ErrorProveedor` (el modelo no responde → puede detener el proceso) y `ErrorDocumento` (el documento no da datos → cuenta como intento fallido y puede terminar en revisión). | Es lo que permite aplicar las reglas 1 y 2 sin ambigüedad. | `app/extraction/base.py` |
| 4 | **3 intentos de extracción por factura.** El 1.º usa el modelo primario; los siguientes usan el siguiente modelo de la cadena y se quedan en el último (el más robusto). Cada reintento recibe una *pista* con lo que falló (por ejemplo, «las líneas suman 1.000,00 pero el total leído es 1.180,00»). | Escalar del modelo barato al robusto controla el costo; la pista sube la tasa de acierto del reintento. | Configuración → Modelos |
| 5 | Si el documento no se puede abrir (PDF con contraseña, imagen corrupta), **no se reintenta con otros modelos**: va directo a revisión sin gastar llamadas. | Ningún modelo podría leerlo. | `app/extraction/preparar.py` |
| 6 | Una factura válida necesita: esquema completo, montos que cuadran y confianza del modelo ≥ 0,6. | La confianza que reporta el modelo es poco fiable por sí sola; el cuadre de montos es la prueba fuerte, y la confianza solo frena los casos que el propio modelo marca como dudosos. | Configuración → Reglas de validación |
| 7 | Cuadre: por línea `cantidad × precio − descuento = importe` (tolerancia 0,02 + 0,005 por unidad, porque el precio unitario impreso viene redondeado); `Σ importes = subtotal` (0,05 + 0,005 por línea); `subtotal − descuento + impuestos + otros = total` (0,05). Las líneas sin cantidad o sin precio solo cuentan para la suma. | Tolerancias de redondeo realistas sin aceptar errores de lectura. | Configuración → Reglas de validación |
| 8 | **Duplicados**: un archivo con la misma huella (md5) que uno ya procesado va a revisión; una factura con el mismo emisor + número que ya existe en la hoja también. Siempre se marca como duplicado el que llega después. | Evita contabilizar dos veces la misma factura. | `app/pipeline.py` |
| 9 | Los archivos que no son PDF, JPG, PNG o WEBP **se ignoran y se quedan en la carpeta**. No cuentan como pendientes y no van a revisión. | El flujo solo procesa imágenes y PDF; mover otros archivos sería tocar cosas que el usuario no pidió. | `app/storage/base.py` · `TIPOS_ADMITIDOS` |
| 10 | El archivo se mueve **solo después** de que las filas quedaron escritas en la hoja. Si la escritura falla, la factura queda pendiente; si falla el movimiento, se marca «registrada, sin mover» y la siguiente corrida solo la mueve. Las filas llevan el ID del archivo para no duplicarlas al reintentar. | Ningún corte deja datos perdidos ni filas repetidas. | `app/pipeline.py` |
| 11 | Al arrancar el servidor, las facturas que quedaron «en proceso» por un corte vuelven a pendiente. | Recuperación ante cortes. | `app/main.py` |

| 11b | **Los descuentos siempre restan**, vengan impresos como «25,00» o «-25,00». | Lo descubrió la prueba en Drive: la factura escaneada imprime «Descuento -25,00», el modelo lo copió negativo y el cuadre lo sumaba (5.907 en lugar de 5.857), así que la mandó a revisión por error. Además, las instrucciones piden a los modelos devolver el descuento en positivo. | `app/validacion.py` · `cuadre` |

## Modelos

| # | Decisión | Motivo |
|---|----------|--------|
| 12 | **Primario: GLM-OCR en local (Ollama) + `gpt-5.4-nano` para ordenar el JSON.** GLM-OCR no tiene consumo gratis en la API de Z.ai (cobra por token), pero el modelo es abierto (licencia MIT) y corre gratis en local con Ollama. | Pedido: probar GLM-OCR con consumo gratuito. |
| 13 | GLM-OCR se usa para **leer texto** (`Text Recognition:`), no para generar el JSON. En las pruebas, el texto salió casi perfecto, pero su modo de JSON directo confundió campos (puso «FACTURA» como número de factura y copió el subtotal en el descuento). El texto se ordena en el esquema con un modelo de texto barato de OpenAI usando salida estructurada estricta. La opción «GLM-OCR directo (100 % local)» queda disponible en Configuración. | Precisión. |
| 14 | Si el PDF trae capa de texto, **se usa ese texto y se salta el OCR**. | Es exacto e instantáneo; GLM-OCR en CPU tarda unos 45 s por página. |
| 15 | GLM-OCR recibe las imágenes reducidas a 1000 px de lado. | En CPU: 1160 px tardó 123 s y 900 px tardó 46 s con la misma precisión en las cifras. |
| 16 | **Respaldo: OpenAI `gpt-5.4-mini` con visión**, que lee la imagen directamente (y la capa de texto del PDF si existe). | Es un motor de lectura distinto al primario, así que sus errores no se repiten. Respondió en unos 4 s por factura en las pruebas. |
| 17 | Las respuestas de OpenAI usan **salida estructurada estricta** generada desde el esquema configurable: todos los campos son obligatorios y los opcionales aceptan `null`. Se agregan `es_factura`, `confianza` y `observaciones`. | El modelo no puede devolver un JSON fuera del esquema. |
| 18 | Para los modelos `gpt-5*` se usa `reasoning_effort: low`. | Una transcripción no necesita razonamiento largo; baja el tiempo y el costo. |

## Google Drive y resultados

| # | Decisión | Motivo |
|---|----------|--------|
| 19 | La conexión con Drive y Sheets se hace con **Composio Connect** (servidor MCP en `connect.composio.dev`, cabecera `x-consumer-api-key`). La clave entregada (`ck_…`) no sirve para el SDK de proyectos de Composio, pero sí para Connect, donde Google Drive y Google Sheets ya estaban conectados. | Pedido: usar Composio si no se podía configurar Google directamente. |
| 20 | Se llama a la API REST de Google a través de `COMPOSIO_PROXY_EXECUTE` (listar, crear carpetas, mover, leer y escribir celdas) y a `GOOGLEDRIVE_DOWNLOAD_FILE` para descargar el contenido. | El proxy da control fino sobre los parámetros, por ejemplo para limitar todo a una carpeta. |
| 21 | **Todo se limita a la carpeta «Facturas IA» y sus subcarpetas.** Antes de descargar o mover un archivo se comprueba que sigue dentro de la carpeta de entrada. Si hay dos carpetas con el mismo nombre, el sistema se detiene y lo avisa. | Pedido explícito: usar solo esa carpeta. |
| 22 | **El archivo de resultados es una hoja de Google Sheets** llamada «Facturas Procesadas IA», creada dentro de «Facturas IA». | Sheets permite agregar filas por API sin descargar ni volver a subir el archivo, y sin choques si alguien lo tiene abierto. Desde Drive se descarga como Excel (.xlsx) cuando se necesite. |
| 23 | La hoja tiene tres pestañas: **Facturas** (una fila por factura: datos del esquema, total catálogo, % catálogo, modelo, intentos), **Detalle** (una fila por línea, con el producto del catálogo que coincidió) y **Errores** (lo que fue a revisión, con paso y motivo). Si el esquema agrega campos, se agregan columnas al final sin romper las existentes. | Datos tabulares y auditables. |
| 23b | **Cada pestaña de la hoja se lee una sola vez por corrida** y se mantiene una copia local; las filas nuevas se agregan con `values:append`, que no necesita leer antes. Ante un error 429 de Google se espera 15, 30 y 60 s y se reintenta. | Lo descubrió la prueba en Drive: la API de Sheets que usa Composio tiene un límite de lecturas por minuto y el primer diseño leía la hoja unas 4 veces por factura. |
| 24 | La subcarpeta de revisión se llama **«Revisión manual»**, como la que ya existía en el Drive. | Respeta lo que el usuario creó. |
| 25 | Subir archivos de prueba a Drive se hace con el *workbench* remoto de Composio (el archivo viaja en base64 y `GOOGLEDRIVE_UPLOAD_FILE` lo deja en la carpeta). Esto es solo para las pruebas; el sistema no sube archivos. | Composio Connect no acepta archivos locales directamente. |
| 26 | Existe un modo **«Carpeta local»** que imita Drive (subcarpetas y un .xlsx real) para probar sin conexión. | Pruebas rápidas y repetibles. |

## Catálogo

| # | Decisión | Motivo |
|---|----------|--------|
| 27 | Coincidencia en orden: **código exacto → palabra clave o sinónimo (palabra completa, sin tildes ni mayúsculas) → parecido de texto ≥ 85** (rapidfuzz por ventanas de palabras). Gana el mayor puntaje. | Tolera errores de tipeo («Pintrua») sin falsos positivos («Pegamento» no coincide con «Pintura»). |
| 28 | El total catálogo se suma **sin impuestos** por defecto; con la opción activada se prorratea el impuesto de la factura. | Es el valor más común para contabilizar; se cambia en Configuración. |
| 29 | El catálogo inicial (Cemento, Varilla, Pintura, Arroz, Aceite vegetal) es **de ejemplo** y coincide con las facturas de prueba. Se edita o se importa desde CSV (`código,producto,palabra1|palabra2`). | Necesario para probar. |

## Normalización

| # | Decisión | Motivo |
|---|----------|--------|
| 30 | Las fechas `dd/mm/aaaa` se leen con el **día primero**. | Formato de las facturas en español. |
| 31 | Los números `1.234,56` y `1,234.56` se detectan automáticamente: el último separador es el decimal. `1,130` (grupos de 3) se toma como miles. | Facturas de distintos formatos. |

## Aplicación

| # | Decisión | Motivo |
|---|----------|--------|
| 32 | Backend en **Python 3.13 + FastAPI**, estado en **SQLite** (`data/estado.db`), configuración en `data/config.json`, planificador interno (hilo). El frontend es HTML + JavaScript sin dependencias, servido por el mismo servidor. | Una sola instalación, sin servicios externos aparte de los modelos y Google. |
| 33 | Las API keys escritas en la app se guardan **cifradas** (Fernet) en `data/secretos.enc`, con la clave en `data/.clave`. Si no hay, se usa el `.env`, que admite los nombres con guion actuales (`OPENAI-APIKEY`, `COMPOSIO-APIKEY`). El navegador nunca recibe una clave completa. | Seguridad básica sin infraestructura extra. |
| 34 | La revisión automática viene **apagada** y se activa en Configuración → Frecuencia (cada 5 minutos por defecto, máximo 20 facturas por corrida). | Evita que el sistema empiece a mover archivos al instalarlo. |
| 35 | Los avisos se muestran en el panel; **no se envían correos**. | No hay una cuenta de correo conectada en Composio. Se puede agregar Gmail desde Composio y extender `db.alerta`. |
| 36 | ~~La app no tiene inicio de sesión y escucha solo en `localhost`.~~ **Reemplazada por la 37** en la v1.1.0. | Uso personal en este equipo. Al publicarla en Cloudflare se agregó autenticación. |

## Rediseño, acceso y publicación (v1.1.0)

| # | Decisión | Motivo | Dónde se cambia |
|---|----------|--------|-----------------|
| 37 | **La app exige inicio de sesión** para todo, salvo la página de inicio, sus archivos estáticos y `/api/auth/*`. La sesión es una cookie `HttpOnly`, `SameSite=Lax` y `Secure` cuando llega por HTTPS; dura 12 horas. En la base solo se guarda el hash SHA-256 del token. | Pedido: agregar un login. Además, al publicar en Cloudflare la app queda accesible desde internet, así que la decisión 36 («sin inicio de sesión») deja de valer. | `app/auth.py`, `app/main.py` · `proteger` |
| 38 | Contraseñas con **scrypt** (biblioteca estándar, sin dependencias nuevas), mínimo 10 caracteres. Tras **5 intentos fallidos en 5 minutos** desde la misma IP, el acceso se bloquea 5 minutos. La IP se toma de `CF-Connecting-IP` cuando la petición pasa por Cloudflare. | Proteger una app expuesta sin agregar infraestructura. | `app/auth.py` |
| 39 | **La primera cuenta solo se crea desde el mismo equipo** (petición a `localhost` que no pasó por un proxy). Desde el túnel se ve un aviso con las dos formas de crearla: abrir `http://localhost:8000` en el equipo o usar `python -m app.auth crear-usuario <usuario>`. | Si la pantalla de «crear cuenta» estuviera abierta en internet, el primero en llegar se quedaría con el sistema. | `app/auth.py` · `es_local` |
| 40 | Las peticiones que modifican algo (`POST`, `PUT`, `DELETE`) con una cabecera `Origin` de otro sitio se rechazan con 403, y se agregan las cabeceras `X-Content-Type-Options`, `X-Frame-Options` y `Referrer-Policy`. | Defensa contra CSRF y clickjacking. | `app/main.py` · `proteger` |
| 41 | **Gráficos propios en SVG, sin bibliotecas.** Los colores salen de variables CSS, así que cambian solos con el tema. Columnas apiladas con la base recta y la esquina superior redondeada, una separación de 2 px entre segmentos, leyenda y tooltip en cada columna. | El frontend seguía sin dependencias (decisión 32) y funciona sin internet, salvo las fuentes, que tienen respaldo del sistema. | `web/graficos.js` |
| 42 | Los indicadores del panel se calculan en el servidor (`/api/estadisticas?dias=N`): serie diaria, motivos de revisión clasificados, rendimiento por modelo a partir del historial de intentos y duración de las corridas. | Un solo pedido por periodo en vez de descargar todas las facturas al navegador. | `app/estadisticas.py` |
| 43 | Identidad visual: acento **violeta de sello** (#4B3FD1), el color de los sellos de las facturas en papel; Bricolage Grotesque para títulos y cifras y Figtree para la interfaz. El rojo, el naranja y el verde quedan reservados para los estados (error, revisión, procesada) y siempre van con icono y texto. | Una identidad propia del tema de la app, no una plantilla genérica. | `web/styles.css` |
| 44 | Tema claro u oscuro: por defecto sigue al sistema; el botón de la esquina superior derecha lo fija y se recuerda en el navegador. El menú contraído y el periodo elegido también se recuerdan. | Pedido. | `web/app.js` |
| 45 | **Publicación en `facturas.marvinlt.cloud` con un Worker de Cloudflare + Workers VPC + Cloudflare Tunnel**, gestionado con Wrangler. El Worker tiene el dominio propio y reenvía a `127.0.0.1:8000` por un servicio VPC atado al túnel `facturas-ia`; fija las cabeceras de origen para que la app distinga el tráfico de internet. | El sistema depende de Ollama local, de SQLite y de un planificador en segundo plano: no puede correr en Pages ni en Workers. El token de Wrangler no tiene permiso para editar DNS, y el dominio propio de un Worker crea su registro solo, así que no hace falta ese permiso. | `deploy/cloudflare/`, `scripts/publicar_cloudflare.ps1` |
| 46 | Las pruebas del frontend usan **Playwright con el Edge o el Chrome del equipo** y datos de demostración generados en carpetas temporales. Las credenciales de prueba se generan al azar en cada corrida y no se guardan. | Pruebas repetibles con un navegador real, sin tocar `data/` ni Drive. | `tests/frontend/` |
| 47 | Detrás del Worker el `Host` es `127.0.0.1:8000`, así que la comprobación de origen acepta también `X-Forwarded-Host`, que fija el Worker. | Sin esto, todo `POST` desde el dominio público se rechazaría. | `app/main.py` · `proteger` |
