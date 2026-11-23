"""Pruebas de punta a punta del frontend con un navegador real (Playwright + Microsoft Edge o Chrome).

Levanta dos servidores en puertos libres con carpetas de datos temporales (una con datos de
demostración y otra vacía), recorre todas las pantallas en escritorio, tableta y móvil, en tema
claro y oscuro, y comprueba en cada una:

  - que no haya errores de JavaScript ni peticiones fallidas;
  - que la página no se desborde a lo ancho y ningún elemento quede fuera de la pantalla;
  - que no haya textos cortados sin puntos suspensivos ni iconos que apunten a un símbolo inexistente;
  - el comportamiento: inicio de sesión, filtros, orden, paginación, detalle, tema, menú, configuración.

Guarda una captura por pantalla en tests/frontend/capturas/ y el resultado en
tests/frontend/resultado_pruebas.json.

Uso:
    .venv/Scripts/python -m pip install -r requirements-dev.txt
    .venv/Scripts/python tests/frontend/probar_frontend.py
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent
CAPTURAS = AQUI / "capturas"
PY = sys.executable

VIEWPORTS = {"escritorio": (1440, 900), "laptop": (1280, 800), "tableta": (820, 1180), "movil": (390, 844)}

resultados: list[dict] = []
errores_consola: list[str] = []


# ── utilidades ───────────────────────────────────────────
def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def servidor(datos: Path, vacio: bool) -> tuple[subprocess.Popen, str]:
    subprocess.run([PY, str(AQUI / "datos_demo.py"), str(datos)] + (["--vacio"] if vacio else []),
                   check=True, capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    puerto = puerto_libre()
    env = {**os.environ, "FACTURAS_IA_DATA": str(datos), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(puerto)],
                            cwd=RAIZ, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/auth/estado", timeout=1)
            return proc, url
        except OSError:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("El servidor no arrancó")


def caso(nombre: str):
    def deco(fn):
        def envoltura(*a, **k):
            inicio = time.time()
            antes = len(errores_consola)
            try:
                fn(*a, **k)
                nuevos = errores_consola[antes:]
                if nuevos:
                    raise AssertionError("Errores en la consola: " + " | ".join(nuevos[:3]))
                resultados.append({"caso": nombre, "ok": True, "segundos": round(time.time() - inicio, 1)})
                print(f"  ✓ {nombre}")
            except Exception as e:  # noqa: BLE001
                resultados.append({"caso": nombre, "ok": False, "error": f"{type(e).__name__}: {e}",
                                   "segundos": round(time.time() - inicio, 1)})
                print(f"  ✗ {nombre}: {e}")
                traceback.print_exc(limit=1)
        return envoltura
    return deco


REVISAR_JS = """() => {
  const fallas = [];
  const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > vw + 1) fallas.push(`la página se desborda a lo ancho (${document.documentElement.scrollWidth}px > ${vw}px)`);
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !el.closest('[hidden]'); };
  const enScroll = (el) => { for (let p = el.parentElement; p; p = p.parentElement) { const s = getComputedStyle(p);
    if (['auto','scroll','hidden'].includes(s.overflowX) && p !== document.body && p !== document.documentElement) return true; } return false; };
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || el.closest('svg') || el.closest('.tooltip')) continue;
    const r = el.getBoundingClientRect();
    if ((r.right > vw + 1 || r.left < -1) && !enScroll(el) && getComputedStyle(el).position !== 'fixed')
      fallas.push(`fuera de pantalla: <${el.tagName.toLowerCase()} class="${el.className}"> (${Math.round(r.left)}–${Math.round(r.right)}px)`);
    const s = getComputedStyle(el);
    if (el.children.length === 0 && el.textContent.trim() && el.scrollWidth > el.clientWidth + 2 &&
        s.overflowX === 'visible' && s.textOverflow !== 'ellipsis' && s.display !== 'inline' && !enScroll(el))
      fallas.push(`texto desbordado: "${el.textContent.trim().slice(0, 40)}" en <${el.tagName.toLowerCase()} class="${el.className}">`);
  }
  for (const u of document.querySelectorAll('use')) {
    const id = (u.getAttribute('href') || '').slice(1);
    if (id && !document.getElementById(id)) fallas.push(`icono inexistente #${id}`);
  }
  return [...new Set(fallas)].slice(0, 12);
}"""


def revisar(page: Page, nombre: str, completa: bool = True) -> None:
    page.wait_for_timeout(350)
    fallas = page.evaluate(REVISAR_JS)
    page.screenshot(path=str(CAPTURAS / f"{nombre}.png"), full_page=completa)
    if fallas:
        raise AssertionError(f"[{nombre}] " + "; ".join(fallas))


def nueva_pagina(nav, url: str, viewport: str, tema: str):
    w, h = VIEWPORTS[viewport]
    ctx = nav.new_context(viewport={"width": w, "height": h}, color_scheme=tema, locale="es-GT",
                          device_scale_factor=1, accept_downloads=True)
    page = ctx.new_page()
    # Las respuestas 4xx que el propio caso provoca (contraseña incorrecta, validación) se registran en la
    # consola como «Failed to load resource»; los fallos reales se detectan por pageerror, requestfailed y 5xx.
    page.on("console", lambda m: m.type == "error" and "fonts.g" not in m.text and "Failed to load resource" not in m.text
            and errores_consola.append(m.text))
    page.on("response", lambda r: r.status >= 500 and errores_consola.append(f"{r.status} en {r.url}"))
    page.on("pageerror", lambda e: errores_consola.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: "fonts.g" not in r.url and errores_consola.append(f"falló {r.url}"))
    return ctx, page


def entrar(page: Page, url: str, usuario: str, clave: str) -> None:
    page.goto(url + "/")
    page.wait_for_selector("#acceso:not([hidden])")
    page.fill("#aUsuario", usuario)
    page.fill("#aClave", clave)
    page.click("#aEntrar")
    page.wait_for_selector("#app:not([hidden])")
    page.wait_for_selector("#kpis .kpi")
    page.wait_for_timeout(500)


# ── pruebas ──────────────────────────────────────────────
def main() -> int:
    CAPTURAS.mkdir(exist_ok=True)
    for f in CAPTURAS.glob("*.png"):
        f.unlink()
    tmp = Path(tempfile.mkdtemp(prefix="facturas_ui_"))
    usuario, clave = "admin.prueba", secrets.token_urlsafe(14)  # credenciales de un solo uso, solo para esta carpeta temporal
    p_demo, url = servidor(tmp / "demo", vacio=False)
    p_vacio, url_vacio = servidor(tmp / "vacio", vacio=True)
    print(f"Servidores: {url} (demo) y {url_vacio} (vacío)")
    try:
        with sync_playwright() as pw:
            try:
                nav = pw.chromium.launch(channel="msedge")
            except Exception:  # noqa: BLE001
                nav = pw.chromium.launch(channel="chrome")
            correr(nav, url, url_vacio, usuario, clave, tmp)
            nav.close()
    finally:
        for p in (p_demo, p_vacio):
            p.terminate()
    ok = sum(r["ok"] for r in resultados)
    (AQUI / "resultado_pruebas.json").write_text(json.dumps(
        {"fecha": datetime.now().isoformat(timespec="seconds"), "total": len(resultados), "correctas": ok,
         "casos": resultados}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{ok} de {len(resultados)} casos correctos. Capturas en {CAPTURAS}")
    return 0 if ok == len(resultados) else 1


def correr(nav, url: str, url_vacio: str, usuario: str, clave: str, tmp: Path) -> None:
    @caso("Seguridad: la API y el diagrama exigen sesión")
    def seguridad():
        for ruta in ("/api/estado", "/api/config", "/api/archivos", "/api/estadisticas"):
            try:
                urllib.request.urlopen(url + ruta)
                raise AssertionError(f"{ruta} respondió sin sesión")
            except urllib.error.HTTPError as e:
                assert e.code == 401, f"{ruta} devolvió {e.code}"
        r = urllib.request.urlopen(url + "/diseno/flujo-facturas-ia.html")
        assert r.url.rstrip("/").endswith(str(url.split(":")[-1])) or r.url.endswith("/"), "el diagrama no redirige al inicio"
    seguridad()

    ctx, page = nueva_pagina(nav, url, "escritorio", "light")

    @caso("Acceso: primera cuenta (configuración inicial) en escritorio claro")
    def primera_cuenta():
        page.goto(url + "/")
        page.wait_for_selector("#acceso:not([hidden])")
        assert page.inner_text("#aTitulo") == "Crea tu cuenta"
        assert page.is_visible("#wConfirmar")
        revisar(page, "01_acceso_crear_cuenta_claro", completa=False)
        page.fill("#aUsuario", usuario)
        page.fill("#aClave", "corta")
        page.fill("#aConfirmar", "corta")
        page.click("#aEntrar")
        page.wait_for_selector("#aAviso:not([hidden])")
        assert "10 caracteres" in page.inner_text("#aAviso"), page.inner_text("#aAviso")
        page.fill("#aClave", clave)
        page.fill("#aConfirmar", clave + "x")
        page.click("#aEntrar")
        assert "no coinciden" in page.inner_text("#aAviso")
        page.fill("#aConfirmar", clave)
        page.click("#aEntrar")
        page.wait_for_selector("#app:not([hidden])")
        page.wait_for_selector("#kpis .kpi")
    primera_cuenta()

    @caso("Panel: indicadores, recorrido, gráficos, corridas y bitácora (escritorio claro)")
    def panel():
        page.wait_for_timeout(800)
        assert page.locator("#kpis .kpi").count() == 5
        assert page.locator("#etapas .etapa").count() == 7
        assert page.locator("#gDiario svg path").count() > 10, "el gráfico diario no tiene columnas"
        assert page.locator("#gMotivos .barra-h").count() >= 3
        assert page.locator("#gModelos .modelo-f").count() == 3
        assert page.locator("#lCorridas .corrida").count() > 10
        assert page.locator("#bitacora li").count() > 2
        assert page.locator("#mRevision").is_visible()
        revisar(page, "02_panel_claro")
    panel()

    @caso("Panel: tooltip del gráfico al pasar el ratón")
    def tooltip():
        caja = page.locator("#gDiario svg").bounding_box()
        page.mouse.move(caja["x"] + caja["width"] - 20, caja["y"] + caja["height"] / 2)
        page.wait_for_selector("#tooltip:not([hidden])")
        assert "Procesadas" in page.inner_text("#tooltip")
        page.locator("#gDiario").screenshot(path=str(CAPTURAS / "03_grafico_tooltip.png"))
        page.mouse.move(5, 5)
    tooltip()

    @caso("Panel: filtros de periodo (7, 90 días y todo)")
    def periodo():
        valores = {}
        for d in ("7", "90", "0", "30"):
            with page.expect_response(lambda r: "/api/estadisticas" in r.url):
                page.click(f"#periodo button[data-dias='{d}']")
            page.wait_for_timeout(250)
            valores[d] = page.inner_text("#kpis .kpi.ok .kpi-v")
            assert page.get_attribute(f"#periodo button[data-dias='{d}']", "aria-checked") == "true"
        assert int(valores["7"].replace(".", "").replace(",", "")) < int(valores["90"].replace(".", "").replace(",", "")), valores
    periodo()

    @caso("Panel: filtro de corridas, selección y filtros de bitácora")
    def corridas():
        page.click("#fCorridas button[data-f='detenida']")
        n = page.locator("#lCorridas .corrida").count()
        assert n >= 1 and page.locator("#lCorridas .corrida.detenida").count() == n
        with page.expect_response(lambda r: "/api/eventos" in r.url):
            page.locator("#lCorridas .corrida").first.click()
        page.wait_for_timeout(200)
        page.click("#fNivel button[data-n='error']")
        assert page.locator("#bitacora li.error").count() >= 1 and page.locator("#bitacora li:not(.error)").count() == 0
        page.click("#fNivel button[data-n='']")
        page.fill("#fBit", "Ningún modelo")
        page.wait_for_timeout(150)
        assert page.locator("#bitacora mark").count() >= 1
        page.locator("#bitacora").scroll_into_view_if_needed()
        revisar(page, "04_panel_corrida_detenida_filtrada")
        page.fill("#fBit", "")
        page.click("#fCorridas button[data-f='']")
    corridas()

    @caso("Menú lateral contraído y persistente al recargar")
    def menu():
        page.click("#bColapsar")
        page.wait_for_timeout(300)
        assert "colapsada" in page.get_attribute("#app", "class")
        assert page.evaluate("document.querySelector('.lateral').getBoundingClientRect().width") < 90
        revisar(page, "05_panel_menu_contraido", completa=False)
        page.reload()
        page.wait_for_selector("#kpis .kpi")
        assert "colapsada" in page.get_attribute("#app", "class")
        page.click("#bColapsar")
        page.wait_for_timeout(300)
    menu()

    @caso("Tema oscuro con el botón de la esquina superior derecha, persistente")
    def tema():
        boton = page.locator(".barra .tema").bounding_box()
        assert boton["x"] + boton["width"] > VIEWPORTS["escritorio"][0] - 60 and boton["y"] < 60, f"el botón de tema no está arriba a la derecha: {boton}"
        page.click(".barra .tema")
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        page.wait_for_timeout(300)
        fondo = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert fondo != "rgb(243, 244, 248)", "el fondo no cambió"
        revisar(page, "06_panel_oscuro")
        page.reload()
        page.wait_for_selector("#kpis .kpi")
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    tema()

    @caso("Facturas: filtros por estado, búsqueda, orden y paginación (oscuro)")
    def facturas():
        page.click(".menu a[data-ruta='facturas']")
        page.wait_for_selector("#tFacturas tbody tr.click")
        assert page.locator("#tFacturas tbody tr.click").count() == 15
        revisar(page, "07_facturas_oscuro")
        page.click("#fEstado button[data-f='revision']")
        filas = page.locator("#tFacturas tbody tr.click")
        assert all("Revisión" in filas.nth(i).inner_text() for i in range(filas.count()))
        page.click("#fEstado button[data-f='']")
        page.fill("#fBuscar", "Martillo")
        page.wait_for_timeout(150)
        assert all("Martillo" in t for t in page.locator("#tFacturas tbody .emisor").all_inner_texts())
        page.fill("#fBuscar", "")
        page.click("#tFacturas th[data-orden='total']")
        totales = [float(t.replace(".", "").replace(",", ".")) for t in page.locator("#tFacturas tbody td.n:nth-child(5)").all_inner_texts() if t != "—"]
        assert totales == sorted(totales, reverse=True), "el orden por total no es descendente"
        page.click("#paginador [data-pag='1']")
        assert "16–30" in page.inner_text("#paginador")
    facturas()

    @caso("Facturas: exportar CSV")
    def csv():
        with page.expect_download() as d:
            page.click("#bCsv")
        assert d.value.suggested_filename.startswith("facturas_") and d.value.suggested_filename.endswith(".csv")
    csv()

    @caso("Facturas: detalle en el cajón lateral (procesada y en revisión)")
    def detalle():
        page.click("#fEstado button[data-f='procesada']")
        page.locator("#tFacturas tbody tr.click").first.click()
        page.wait_for_selector("#cajon:not([hidden])")
        assert page.locator("#dCuerpo .resumen-f").count() == 1
        assert page.locator("#dCuerpo .tabla tbody tr").count() >= 2
        revisar(page, "08_detalle_procesada_oscuro", completa=False)
        page.keyboard.press("Escape")
        assert page.is_hidden("#cajon")
        page.click("#fEstado button[data-f='revision']")
        page.locator("#tFacturas tbody tr.click").first.click()
        page.wait_for_selector("#cajon:not([hidden])")
        assert page.locator("#dCuerpo .motivo-f").count() == 1
        page.click("#dCerrar")
    detalle()

    @caso("Configuración: las ocho secciones se abren y se ven bien (claro)")
    def configuracion():
        page.click(".barra .tema")  # vuelve a claro
        page.click(".menu a[data-ruta='config']")
        for i, sec in enumerate(["conexion", "carpetas", "frecuencia", "modelos", "esquema", "validacion", "catalogo", "probar"]):
            page.click(f"#cnav button[data-c='{sec}']")
            page.wait_for_selector("#cpanel h2")
            page.wait_for_timeout(250)
            assert page.locator("#cpanel .cargando").count() == 0
            revisar(page, f"09_config_{i + 1}_{sec}")
    configuracion()

    @caso("Configuración: guardar con error de validación y guardar bien")
    def guardar():
        page.click("#cnav button[data-c='frecuencia']")
        page.fill("#f_min", "0")
        page.click("#bG")
        page.wait_for_selector("#cErrores:not([hidden])")
        page.fill("#f_min", "30")
        page.click("#bG")
        page.wait_for_selector(".toast.ok")
        assert page.is_hidden("#cErrores")
        page.click("#cnav button[data-c='catalogo']")
        page.fill("#cProbar", "Varilla corrugada 3/8")
        page.click("#bProbar")
        page.wait_for_selector("#cRes .hit")
    guardar()

    @caso("Panel con proceso en curso (recorrido animado)")
    def en_curso():
        def falso(route):
            r = route.fetch()
            datos = r.json()
            datos["servicio"].update(corriendo=True, paso="05 · Extracción IA", archivo="ferretería_0231.jpg")
            route.fulfill(response=r, json=datos)
        page.route("**/api/estado", falso)
        page.click(".menu a[data-ruta='panel']")
        page.wait_for_selector(".etapa.actual")
        assert page.locator(".etapa.hecha").count() == 2
        assert page.is_visible("#bDetener")
        page.locator("#recorrido").screenshot(path=str(CAPTURAS / "10_recorrido_en_curso.png"))
        revisar(page, "10b_panel_en_curso", completa=False)
        page.unroute("**/api/estado")
    en_curso()

    @caso("Alerta de proceso detenido y descartarla")
    def alerta():
        con = sqlite3.connect(tmp / "demo" / "estado.db")
        con.execute("INSERT INTO alertas(ts,nivel,clave,mensaje,activa) VALUES(?,?,?,?,1)",
                    (datetime.now().isoformat(timespec="seconds"), "error", "modelos",
                     "Proceso detenido: Ollama no responde y OpenAI devolvió 503. La factura «distribuidora_0240.jpg» y el resto de la cola siguen pendientes."))
        con.commit(); con.close()
        page.wait_for_selector(".alerta", timeout=8000)
        assert "detenido" in page.get_attribute("#estadoRun", "class")
        revisar(page, "11_panel_alerta", completa=False)
        page.click(".alerta [data-cerrar]")
        page.wait_for_selector(".alerta", state="detached")
    alerta()

    @caso("Cerrar sesión, contraseña incorrecta y volver a entrar")
    def sesion():
        page.click("#bSalir")
        page.wait_for_selector("#acceso:not([hidden])")
        assert page.inner_text("#aTitulo") == "Inicia sesión"
        page.fill("#aUsuario", usuario)
        page.fill("#aClave", "incorrecta-123")
        page.click("#aEntrar")
        page.wait_for_selector("#aAviso:not([hidden])")
        assert "incorrectos" in page.inner_text("#aAviso")
        revisar(page, "12_acceso_error_claro", completa=False)
        page.fill("#aClave", clave)
        page.click("#aEntrar")
        page.wait_for_selector("#app:not([hidden])")
    sesion()
    ctx.close()

    # Pantalla de acceso en oscuro y en otros tamaños.
    for vp in ("escritorio", "movil"):
        c, p = nueva_pagina(nav, url, vp, "dark")

        @caso(f"Acceso en tema oscuro ({vp})")
        def acceso_oscuro():
            p.goto(url + "/")
            p.wait_for_selector("#acceso:not([hidden])")
            p.wait_for_timeout(1800)  # deja avanzar la animación del escáner
            revisar(p, f"13_acceso_oscuro_{vp}", completa=False)
        acceso_oscuro()
        c.close()

    for vp in ("laptop", "tableta", "movil"):
        c, p = nueva_pagina(nav, url, vp, "light")

        @caso(f"Panel, facturas, detalle y configuración en {vp}")
        def responsivo():
            entrar(p, url, usuario, clave)
            revisar(p, f"14_{vp}_panel")
            if vp in ("movil", "tableta"):  # bajo 980 px el menú es un panel que se abre con el botón
                assert p.is_hidden(".lateral-estado") or p.evaluate("document.querySelector('.lateral').getBoundingClientRect().right") <= 0
                p.click("#bMenu")
                p.wait_for_timeout(350)
                assert p.evaluate("document.querySelector('.lateral').getBoundingClientRect().left") >= 0
                revisar(p, f"14_{vp}_menu_abierto", completa=False)
                p.click(".menu a[data-ruta='facturas']")
                p.wait_for_timeout(350)
                assert p.evaluate("document.querySelector('.lateral').getBoundingClientRect().right") <= 0, "el menú no se cerró"
            else:
                p.click(".menu a[data-ruta='facturas']")
            p.wait_for_selector("#tFacturas tbody tr.click")
            revisar(p, f"14_{vp}_facturas")
            p.locator("#tFacturas tbody tr.click").first.click()
            p.wait_for_selector("#cajon:not([hidden])")
            revisar(p, f"14_{vp}_detalle", completa=False)
            p.keyboard.press("Escape")
            p.goto(url + "/#config/modelos")
            p.wait_for_selector("#cpanel .modelo")
            revisar(p, f"14_{vp}_config_modelos")
        responsivo()
        c.close()

    # Sistema recién instalado: sin facturas ni corridas.
    c, p = nueva_pagina(nav, url_vacio, "escritorio", "light")

    @caso("Estados vacíos: panel y facturas sin datos")
    def vacio():
        p.goto(url_vacio + "/")
        p.wait_for_selector("#acceso:not([hidden])")
        p.fill("#aUsuario", usuario)
        p.fill("#aClave", clave)
        p.fill("#aConfirmar", clave)
        p.click("#aEntrar")
        p.wait_for_selector("#kpis .kpi")
        p.wait_for_timeout(600)
        assert "Todavía no hay facturas" in p.inner_text("#gDiario")
        assert p.locator("#gMotivos .vacio-g").count() == 1
        revisar(p, "15_panel_vacio")
        p.click(".menu a[data-ruta='facturas']")
        p.wait_for_selector("#tFacturas .vacio")
        revisar(p, "15_facturas_vacio")
    vacio()
    c.close()
    capturas_readme(nav, url, usuario, clave)


def capturas_readme(nav, url: str, usuario: str, clave: str) -> None:
    """Las tres capturas del README, en docs/capturas/, a doble densidad."""
    destino = RAIZ / "docs" / "capturas"
    destino.mkdir(parents=True, exist_ok=True)
    ctx = nav.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light", locale="es-GT", device_scale_factor=2)
    p = ctx.new_page()

    @caso("Capturas del README")
    def capturar():
        p.goto(url + "/")
        p.wait_for_selector("#acceso:not([hidden])")
        p.wait_for_timeout(4600)  # momento de la animación con los datos extraídos visibles
        p.screenshot(path=str(destino / "acceso.png"))
        entrar(p, url, usuario, clave)
        p.mouse.move(5, 5)
        p.wait_for_timeout(600)
        p.screenshot(path=str(destino / "panel.png"))
        p.click(".barra .tema")
        p.click(".menu a[data-ruta='facturas']")
        p.wait_for_selector("#tFacturas tbody tr.click")
        p.click("#fEstado button[data-f='procesada']")
        p.locator("#tFacturas tbody tr.click").nth(1).click()
        p.wait_for_selector("#cajon:not([hidden])")
        p.wait_for_timeout(500)
        p.screenshot(path=str(destino / "facturas_detalle.png"))
    capturar()
    ctx.close()


if __name__ == "__main__":
    sys.exit(main())
