"""Inicio de sesión y protección de la API (sin red, con una carpeta de datos temporal)."""
from __future__ import annotations

import importlib
import os
import secrets
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
DATOS_SESION = os.environ["FACTURAS_IA_DATA"]


@pytest.fixture()
def cliente(monkeypatch):
    datos = Path(tempfile.mkdtemp(prefix="facturas_auth_"))
    monkeypatch.setenv("FACTURAS_IA_DATA", str(datos))
    sys.path.insert(0, str(RAIZ))
    for m in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    main = importlib.import_module("app.main")
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c
    importlib.import_module("app.db").reiniciar_conexion()
    for m in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    os.environ["FACTURAS_IA_DATA"] = DATOS_SESION


def test_api_exige_sesion(cliente):
    for ruta in ("/api/estado", "/api/config", "/api/archivos", "/api/estadisticas", "/api/secretos"):
        assert cliente.get(ruta).status_code == 401, ruta
    assert cliente.get("/").status_code == 200
    assert cliente.get("/web/app.js").status_code == 200


def test_primera_cuenta_y_login(cliente):
    estado = cliente.get("/api/auth/estado").json()
    assert estado == {"autenticado": False, "usuario": None, "requiere_configuracion": True,
                      "configuracion_permitida": True, "requiere_codigo": False}
    assert cliente.post("/api/auth/configurar", json={"usuario": "ad", "clave": "corta"}).status_code == 422
    clave = secrets.token_urlsafe(12)
    assert cliente.post("/api/auth/configurar", json={"usuario": "Admin", "clave": clave}).status_code == 200
    assert cliente.get("/api/estado").status_code == 200
    # Ya hay una cuenta: no se puede crear otra por esta vía.
    assert cliente.post("/api/auth/configurar", json={"usuario": "otro", "clave": clave}).status_code == 409
    cliente.post("/api/auth/logout")
    assert cliente.get("/api/estado").status_code == 401
    assert cliente.post("/api/auth/login", json={"usuario": "admin", "clave": "mala-clave-1"}).status_code == 401
    assert cliente.post("/api/auth/login", json={"usuario": "ADMIN", "clave": clave}).status_code == 200
    assert cliente.get("/api/auth/estado").json()["usuario"] == "admin"


def test_primera_cuenta_no_se_crea_por_el_tunel(cliente):
    r = cliente.post("/api/auth/configurar", json={"usuario": "admin", "clave": secrets.token_urlsafe(12)},
                     headers={"cf-connecting-ip": "203.0.113.9"})
    assert r.status_code == 403
    assert cliente.get("/api/auth/estado", headers={"cf-connecting-ip": "203.0.113.9"}).json()["configuracion_permitida"] is False


def test_primera_cuenta_en_la_nube_con_codigo(cliente, monkeypatch):
    """En el contenedor de Cloudflare la primera cuenta se crea desde internet solo con el código de configuración."""
    codigo = secrets.token_urlsafe(16)
    monkeypatch.setenv("FACTURAS_IA_CODIGO_CONFIGURACION", codigo)
    cab = {"cf-connecting-ip": "203.0.113.20"}
    estado = cliente.get("/api/auth/estado", headers=cab).json()
    assert estado["configuracion_permitida"] is True and estado["requiere_codigo"] is True
    clave = secrets.token_urlsafe(12)
    assert cliente.post("/api/auth/configurar", json={"usuario": "admin", "clave": clave}, headers=cab).status_code == 403
    assert cliente.post("/api/auth/configurar", json={"usuario": "admin", "clave": clave, "codigo": "otro-codigo"},
                        headers=cab).status_code == 403
    r = cliente.post("/api/auth/configurar", json={"usuario": "admin", "clave": clave, "codigo": codigo}, headers=cab)
    assert r.status_code == 200
    # Con la cuenta creada, el código ya no sirve para nada.
    assert cliente.post("/api/auth/configurar", json={"usuario": "otro", "clave": clave, "codigo": codigo},
                        headers=cab).status_code == 409
    assert cliente.get("/api/auth/estado", headers=cab).json()["requiere_codigo"] is False


def test_rutas_internas_exigen_token(cliente, monkeypatch):
    assert cliente.get("/_interno/salud").status_code == 200
    assert cliente.get("/_interno/pulso").status_code == 404
    monkeypatch.setenv("FACTURAS_IA_TOKEN_INTERNO", "token-de-prueba-123")
    assert cliente.get("/_interno/pulso", headers={"x-token-interno": "malo"}).status_code == 404
    r = cliente.get("/_interno/pulso", headers={"x-token-interno": "token-de-prueba-123"})
    assert r.status_code == 200 and set(r.json()) >= {"programado", "corriendo"}


def test_bloqueo_tras_intentos_fallidos(cliente):
    cliente.post("/api/auth/configurar", json={"usuario": "admin", "clave": secrets.token_urlsafe(12)})
    cliente.post("/api/auth/logout")
    cab = {"cf-connecting-ip": "198.51.100.7"}
    codigos = [cliente.post("/api/auth/login", json={"usuario": "admin", "clave": f"mala-{i}-xxxxx"}, headers=cab).status_code
               for i in range(6)]
    assert codigos[:5] == [401] * 5 and codigos[5] == 429


def test_origen_ajeno_rechazado(cliente):
    r = cliente.post("/api/auth/login", json={"usuario": "x", "clave": "y"}, headers={"origin": "https://otro-sitio.example"})
    assert r.status_code == 403


def test_contrasena_guardada_con_hash():
    sys.path.insert(0, str(RAIZ))
    from app import auth
    h = auth.cifrar_clave("una clave larga 123")
    assert h.startswith("scrypt$") and "una clave" not in h
    assert auth.verificar_clave("una clave larga 123", h)
    assert not auth.verificar_clave("otra clave larga 123", h)
