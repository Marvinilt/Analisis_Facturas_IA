# Reporte de pruebas del frontend (rediseño v1.1.0)

- **Fecha:** 22 de noviembre de 2026
- **Herramienta:** Playwright 1.65 con Microsoft Edge (Chromium), sin interfaz gráfica
- **Script:** [`probar_frontend.py`](probar_frontend.py)
- **Resultado:** **23 de 23 casos correctos**, en dos corridas seguidas. Además pasan las 40 pruebas unitarias (`pytest tests`): las 34 anteriores y 6 nuevas de inicio de sesión.
- **Evidencia:** 38 capturas en [`capturas/`](capturas/) y el detalle de cada caso en [`resultado_pruebas.json`](resultado_pruebas.json)

## Cómo se prueba

El script levanta dos servidores en puertos libres con carpetas de datos **temporales**, así que nunca toca la carpeta `data/` real ni Google Drive:

| Servidor | Datos | Para qué |
|----------|-------|----------|
| Demo | 45 días de corridas y 236 facturas de emisores ficticios, generados por [`datos_demo.py`](datos_demo.py) | Gráficos, filtros, tablas y capturas con volumen realista |
| Vacío | Sin corridas ni facturas | Estados vacíos y creación de la primera cuenta |

La cuenta de prueba usa una contraseña aleatoria nueva en cada ejecución, que no se guarda en ningún archivo.

En **cada pantalla** se comprueba automáticamente:

1. que no haya errores de JavaScript, peticiones fallidas ni respuestas 5xx;
2. que la página no se desborde a lo ancho y que ningún elemento quede fuera de la pantalla (salvo dentro de un contenedor con desplazamiento propio);
3. que ningún texto quede cortado sin puntos suspensivos;
4. que todos los iconos apunten a un símbolo existente.

## Casos

| # | Caso | Pantallas | Resultado |
|---|------|-----------|-----------|
| 1 | La API y el diagrama exigen sesión (401 sin cookie, el diagrama redirige al inicio) | — | ✅ |
| 2 | Primera cuenta: contraseña corta, contraseñas distintas y creación correcta | `01` | ✅ |
| 3 | Panel completo: 5 indicadores, 7 etapas, gráfico diario, motivos, modelos, corridas y bitácora | `02` | ✅ |
| 4 | Tooltip del gráfico diario al pasar el ratón | `03` | ✅ |
| 5 | Filtros de periodo 7, 30 y 90 días y todo; los indicadores cambian | — | ✅ |
| 6 | Filtro de corridas «Detenidas», selección de una corrida, filtro de nivel «Errores» y búsqueda resaltada en la bitácora | `04` | ✅ |
| 7 | Menú lateral contraído (76 px) y persistente al recargar | `05` | ✅ |
| 8 | Botón de tema en la esquina superior derecha; el tema oscuro persiste al recargar | `06` | ✅ |
| 9 | Facturas: filtro por estado, búsqueda, orden por total y paginación | `07` | ✅ |
| 10 | Exportar CSV | — | ✅ |
| 11 | Detalle en el cajón lateral (procesada y en revisión); se cierra con Esc | `08` | ✅ |
| 12 | Las 8 secciones de Configuración | `09_1` a `09_8` | ✅ |
| 13 | Guardar con error de validación (aparece el recuadro) y guardar bien (aviso); probar una descripción del catálogo | — | ✅ |
| 14 | Proceso en curso: el recorrido marca la etapa actual y aparece «Detener» | `10`, `10b` | ✅ |
| 15 | Alerta de proceso detenido y descartarla | `11` | ✅ |
| 16 | Cerrar sesión, contraseña incorrecta y volver a entrar | `12` | ✅ |
| 17–18 | Pantalla de acceso en tema oscuro, escritorio y móvil | `13` | ✅ |
| 19–21 | Panel, facturas, detalle y configuración en laptop (1280), tableta (820) y móvil (390), con el menú desplegable | `14` | ✅ |
| 22 | Estados vacíos del panel y de facturas | `15` | ✅ |
| 23 | Capturas del README a doble densidad | `docs/capturas` | ✅ |

## Defectos encontrados y corregidos

Las primeras corridas dieron 17 de 22. Estos son los problemas que aparecieron, en las pruebas o al revisar las capturas una por una, y cómo se resolvió cada uno:

| # | Defecto | Dónde | Causa | Corrección |
|---|---------|-------|-------|------------|
| 1 | La tarjeta «Tasa de éxito» desaparecía y en móvil desbordaba la página (530 px en una pantalla de 390) | Panel, tableta y móvil | La tarjeta usaba la clase `sello`, que también nombra el sello animado de la pantalla de acceso, así que heredaba su rotación y su escala | La animación se limitó a `.papel .sello` y la tarjeta pasó a la clase `acento` |
| 2 | El recorrido de 7 etapas quedaba cortado a la derecha en móvil | Panel, móvil | Siete columnas no caben en 390 px | Bajo 720 px el recorrido se muestra como línea de tiempo vertical |
| 3 | La tarjeta de datos extraídos de la pantalla de acceso se veía vacía la mitad del tiempo y su texto se salía | Acceso | Toda la fila aparecía y desaparecía con la animación, y el valor no podía encogerse | Las etiquetas quedan fijas, solo se animan los valores, y el valor recorta con puntos suspensivos |
| 4 | El número de factura se partía en dos líneas («AB-» / «60636») | Facturas | La columna se encogía por la del motivo | Columna sin salto de línea y motivo limitado a 240 px con puntos suspensivos |
| 5 | Formato de miles inconsistente: «8130,08» junto a «19.171,38» | Facturas, detalle | En español, los números de 4 cifras no se agrupan por defecto | Agrupación de miles siempre activa |
| 6 | El texto «1 archivo(s) de otro tipo se ignoran» se cortaba | Indicador «Pendientes» | Texto demasiado largo para la tarjeta | Texto más corto: «1 de otro tipo, ignorado(s)» |
| 7 | En las capturas de página completa el menú lateral no llegaba al final | Todas | El menú es fijo (`sticky`) con la altura de la ventana | El fondo de la columna del menú se pinta en la cuadrícula de la app |
| 8 | Campos de configuración desalineados cuando unos tienen texto de ayuda y otros no | Modelos, Validación | Cada etiqueta tenía alto distinto | Los campos de cada fila se alinean por la base |
| 9 | Hueco vacío en la fila de indicadores en tableta | Panel, tableta | 5 tarjetas en 3 columnas | La última tarjeta ocupa 2 columnas entre 420 y 1280 px |
| 10 | La alerta repetía el título dentro del mensaje («Proceso detenido · Proceso detenido: …») | Panel | El mensaje guardado ya empieza con el título | Se quita el prefijo repetido al mostrarlo |
| 11 | **Intermitente:** al cerrar sesión, el formulario de acceso a veces se reiniciaba mientras se escribía | Acceso | Una consulta de estado que ya estaba en camino volvía con 401 y abría de nuevo la pantalla de acceso | Se detiene el sondeo antes de cerrar la sesión, y un 401 solo abre el acceso si la app estaba visible. Se verificó con dos corridas completas seguidas sin fallos |

Ajustes del propio script de pruebas, que no eran defectos de la app:

- Las respuestas 4xx que el caso provoca a propósito (contraseña incorrecta, validación) aparecen en la consola como «Failed to load resource». Se excluyen de la lista de errores; los errores reales se siguen detectando por excepciones de página, peticiones fallidas y respuestas 5xx.
- En tableta (820 px) el menú también es desplegable, así que el caso abre el menú antes de navegar, igual que en móvil.

## Repetir las pruebas

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python tests\frontend\probar_frontend.py
```

Necesita Microsoft Edge o Google Chrome instalados; Playwright usa el navegador del equipo, sin descargar otro.
