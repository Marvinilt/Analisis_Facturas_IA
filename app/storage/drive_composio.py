"""Google Drive + Google Sheets a través de Composio Connect.

Todo se limita a la carpeta de entrada (por defecto «Facturas IA») y sus subcarpetas:
  - nunca se lista, mueve ni crea nada fuera de ella;
  - el archivo de resultados (Google Sheets) vive dentro de la carpeta de entrada.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any

from .base import Almacen, AlmacenError, ArchivoDrive, alinear
from .composio_mcp import ComposioError, ComposioMCP

FOLDER = "application/vnd.google-apps.folder"
SHEET = "application/vnd.google-apps.spreadsheet"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
CAMPOS_ARCHIVO = "id,name,mimeType,size,md5Checksum,createdTime,webViewLink,parents"


def _esc(nombre: str) -> str:
    return nombre.replace("\\", "\\\\").replace("'", "\\'")


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class DriveComposio(Almacen):
    def __init__(self, cfg_drive: dict[str, Any], api_key: str):
        self.cfg = cfg_drive
        self.c = ComposioMCP(api_key)
        self.ids: dict[str, str] = {}
        self.sheet_id: str | None = None
        self.sheet_url: str | None = None
        self._hojas: set[str] | None = None  # pestañas existentes (se leen una vez)
        self._cache: dict[str, list[list[Any]]] = {}  # contenido de cada pestaña, leído una vez por corrida
        self._lock = threading.RLock()

    # ── utilidades ────────────────────────────────────────
    ESPERAS_429 = (15, 30, 60)  # Google limita lecturas/escrituras por minuto: se espera y se reintenta

    def _llamar(self, toolkit: str, endpoint: str, metodo: str, query: dict | None, body: Any) -> Any:
        for i, espera in enumerate((*self.ESPERAS_429, None)):
            try:
                return self.c.proxy(toolkit, endpoint, metodo, query, body)
            except ComposioError as e:
                if e.estado_http == 429 and espera is not None:
                    time.sleep(espera)
                    continue
                raise AlmacenError(str(e), temporal=e.temporal) from e
        raise AlmacenError("Límite de Google alcanzado", temporal=True)

    def _drive(self, endpoint: str, metodo: str = "GET", query: dict | None = None, body: Any = None) -> Any:
        return self._llamar("googledrive", endpoint, metodo, query, body)

    def _sheets(self, endpoint: str, metodo: str = "GET", query: dict | None = None, body: Any = None) -> Any:
        return self._llamar("googlesheets", f"{SHEETS_API}{endpoint}", metodo, query, body)

    def _listar(self, q: str, campos: str = CAMPOS_ARCHIVO) -> list[dict]:
        salida, token = [], None
        while True:
            query = {"q": q, "fields": f"nextPageToken,files({campos})", "pageSize": 200,
                     "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            if token:
                query["pageToken"] = token
            datos = self._drive("/files", query=query) or {}
            salida += datos.get("files", [])
            token = datos.get("nextPageToken")
            if not token:
                return salida

    # ── preparación ───────────────────────────────────────
    def preparar(self) -> dict[str, Any]:
        with self._lock:
            nombre = self.cfg["carpeta_entrada"]
            carpetas = self._listar(f"name='{_esc(nombre)}' and mimeType='{FOLDER}' and trashed=false", "id,name,parents")
            if not carpetas:
                raise AlmacenError(f"No se encontró la carpeta «{nombre}» en Google Drive.")
            if len(carpetas) > 1:
                raise AlmacenError(f"Hay {len(carpetas)} carpetas llamadas «{nombre}». Deja solo una o cambia el nombre en Configuración.")
            raiz = carpetas[0]["id"]
            self.ids = {"entrada": raiz}
            creadas = []
            for clave, cfg_nombre in (("procesadas", "carpeta_procesadas"), ("revision", "carpeta_revision")):
                sub = self.cfg[cfg_nombre]
                hallado = self._listar(f"'{raiz}' in parents and name='{_esc(sub)}' and mimeType='{FOLDER}' and trashed=false", "id,name")
                if hallado:
                    self.ids[clave] = hallado[0]["id"]
                else:
                    nuevo = self._drive("/files", "POST", {"fields": "id"}, {"name": sub, "mimeType": FOLDER, "parents": [raiz]})
                    self.ids[clave] = nuevo["id"]
                    creadas.append(sub)
            # archivo de resultados dentro de la carpeta de entrada
            nombre_hoja = self.cfg["archivo_resultados"]
            hojas = self._listar(f"'{raiz}' in parents and name='{_esc(nombre_hoja)}' and mimeType='{SHEET}' and trashed=false", "id,name,webViewLink")
            if hojas:
                self.sheet_id, self.sheet_url = hojas[0]["id"], hojas[0].get("webViewLink")
            else:
                nuevo = self._drive("/files", "POST", {"fields": "id,webViewLink"},
                                    {"name": nombre_hoja, "mimeType": SHEET, "parents": [raiz]})
                self.sheet_id, self.sheet_url = nuevo["id"], nuevo.get("webViewLink")
                creadas.append(nombre_hoja)
            self._hojas, self._cache = None, {}
            return {"carpeta_id": raiz, "subcarpetas": dict(self.ids), "resultados": self.sheet_url, "creadas": creadas}

    def _requiere(self) -> None:
        if not self.ids:
            self.preparar()

    # ── archivos ──────────────────────────────────────────
    def listar_entrada(self) -> list[ArchivoDrive]:
        self._requiere()
        raiz = self.ids["entrada"]
        archivos = self._listar(f"'{raiz}' in parents and trashed=false and mimeType!='{FOLDER}'")
        salida = []
        for f in archivos:
            if f["mimeType"] == SHEET and f["id"] == self.sheet_id:
                continue
            salida.append(ArchivoDrive(id=f["id"], nombre=f["name"], mime=f["mimeType"],
                                       tamano=int(f["size"]) if f.get("size") else None, md5=f.get("md5Checksum"),
                                       creado=f.get("createdTime"), enlace=f.get("webViewLink")))
        salida.sort(key=lambda a: a.creado or "")
        return salida

    def contar(self, destino: str) -> int:
        self._requiere()
        return len(self._listar(f"'{self.ids[destino]}' in parents and trashed=false and mimeType!='{FOLDER}'", "id"))

    def _verificar_en_entrada(self, archivo: ArchivoDrive) -> None:
        meta = self._drive(f"/files/{archivo.id}", query={"fields": "id,parents", "supportsAllDrives": "true"})
        if self.ids["entrada"] not in (meta.get("parents") or []):
            raise AlmacenError(f"«{archivo.nombre}» ya no está en la carpeta de entrada; se omite.")

    def descargar(self, archivo: ArchivoDrive) -> bytes:
        self._requiere()
        self._verificar_en_entrada(archivo)
        try:
            datos = self.c.ejecutar("GOOGLEDRIVE_DOWNLOAD_FILE", {"fileId": archivo.id})
            contenido = datos.get("downloaded_file_content") or {}
            url = contenido.get("s3url")
            if not url:
                raise AlmacenError(f"Composio no devolvió el contenido de «{archivo.nombre}».", temporal=True)
            return self.c.descargar_url(url)
        except ComposioError as e:
            raise AlmacenError(f"No se pudo descargar «{archivo.nombre}»: {e}", temporal=e.temporal) from e
        except Exception as e:  # httpx
            if isinstance(e, AlmacenError):
                raise
            raise AlmacenError(f"No se pudo descargar «{archivo.nombre}»: {e}", temporal=True) from e

    def mover(self, archivo: ArchivoDrive, destino: str, nuevo_nombre: str | None = None) -> None:
        self._requiere()
        query = {"addParents": self.ids[destino], "removeParents": self.ids["entrada"], "fields": "id,parents",
                 "supportsAllDrives": "true"}
        self._drive(f"/files/{archivo.id}", "PATCH", query, {"name": nuevo_nombre} if nuevo_nombre else {})

    # ── hoja de resultados ────────────────────────────────
    def _asegurar_hoja(self, hoja: str) -> None:
        if self._hojas is not None and hoja in self._hojas:
            return
        info = self._sheets(f"/{self.sheet_id}", query={"fields": "sheets.properties"})
        titulos = [s["properties"]["title"] for s in info.get("sheets", [])]
        if hoja not in titulos:
            # La hoja por defecto de un archivo nuevo («Hoja 1»/«Sheet1») se renombra en vez de crear otra.
            vacia = None
            if len(titulos) == 1 and titulos[0] not in ("Facturas", "Detalle", "Errores"):
                valores = self._sheets(f"/{self.sheet_id}/values/'{titulos[0]}'!A1:B2")
                if not valores.get("values"):
                    vacia = info["sheets"][0]["properties"]["sheetId"]
            if vacia is not None:
                req = {"updateSheetProperties": {"properties": {"sheetId": vacia, "title": hoja}, "fields": "title"}}
            else:
                req = {"addSheet": {"properties": {"title": hoja}}}
            self._sheets(f"/{self.sheet_id}:batchUpdate", "POST", body={"requests": [req]})
            titulos.append(hoja)
        self._hojas = set(titulos)

    def leer_hoja(self, hoja: str) -> list[list[Any]]:
        """Lee la pestaña una sola vez por corrida; después se usa la copia local que se mantiene al escribir."""
        with self._lock:
            if hoja not in self._cache:
                self._requiere()
                self._asegurar_hoja(hoja)
                datos = self._sheets(f"/{self.sheet_id}/values/'{hoja}'", query={"valueRenderOption": "UNFORMATTED_VALUE"})
                self._cache[hoja] = datos.get("values", []) if isinstance(datos, dict) else []
            return copy.deepcopy(self._cache[hoja])

    def agregar_filas(self, hoja: str, filas: list[dict[str, Any]]) -> None:
        if not filas:
            return
        with self._lock:
            actuales = self.leer_hoja(hoja)
            encabezado = [str(x) for x in actuales[0]] if actuales else []
            nuevo, valores = alinear(encabezado, filas)
            if nuevo != encabezado:
                self._sheets(f"/{self.sheet_id}/values/'{hoja}'!A1:{_col(len(nuevo))}1", "PUT",
                             {"valueInputOption": "RAW"}, {"values": [nuevo]})
            # «append» agrega al final de la tabla sin necesidad de leerla antes (no pisa filas
            # que alguien haya agregado a mano durante la corrida).
            self._sheets(f"/{self.sheet_id}/values/'{hoja}'!A1:append", "POST",
                         {"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                         {"values": [[_celda(v) for v in fila] for fila in valores]})
            cache = self._cache.setdefault(hoja, [])
            if cache:
                cache[0] = nuevo
            else:
                cache.append(nuevo)
            cache.extend(valores)

    def enlace_resultados(self) -> str | None:
        return self.sheet_url

    def describir(self) -> dict[str, Any]:
        return {"proveedor": "Google Drive (Composio)", "carpeta": self.cfg["carpeta_entrada"],
                "resultados": self.sheet_url}


def _celda(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    # Evita que Sheets interprete textos como fórmulas.
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not _es_numero(s) else s


def _es_numero(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
