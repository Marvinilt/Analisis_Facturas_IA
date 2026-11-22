"""Ejecución de corridas en segundo plano: manual («Procesar ahora») y programada."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Any

from . import configuracion, db
from .pipeline import Procesador


class Servicio:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._detener = threading.Event()
        self._apagar = threading.Event()
        self.paso: str = ""
        self.archivo: str | None = None
        self.inicio: str | None = None
        self.ultima: dict[str, Any] | None = None
        self.ultima_programada: float = 0.0
        self._planificador: threading.Thread | None = None

    # ── estado ────────────────────────────────────────────
    @property
    def corriendo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def _informar(self, paso: str, archivo: str | None) -> None:
        self.paso, self.archivo = paso, archivo

    def estado(self) -> dict[str, Any]:
        cfg = configuracion.cargar()["frecuencia"]
        proxima = None
        if cfg.get("activo"):
            base = self.ultima_programada or time.time()
            proxima = datetime.fromtimestamp(max(base + 60 * int(cfg["cada_minutos"]), time.time())).isoformat(timespec="seconds")
        return {"corriendo": self.corriendo, "paso": self.paso, "archivo": self.archivo, "inicio": self.inicio,
                "deteniendo": self._detener.is_set(), "proxima": proxima, "programado": bool(cfg.get("activo"))}

    # ── ejecución ─────────────────────────────────────────
    def iniciar(self, origen: str = "manual") -> bool:
        with self._lock:
            if self.corriendo:
                return False
            self._detener.clear()
            self.inicio = db.ahora()
            self._hilo = threading.Thread(target=self._correr, args=(origen,), daemon=True, name="corrida")
            self._hilo.start()
            return True

    def _correr(self, origen: str) -> None:
        try:
            self.ultima = Procesador(informar=self._informar).correr(origen, self._detener)
        finally:
            self.paso, self.archivo = "", None

    def detener(self) -> None:
        self._detener.set()

    def esperar(self, timeout: float | None = None) -> None:
        if self._hilo:
            self._hilo.join(timeout)

    # ── planificador ──────────────────────────────────────
    def iniciar_planificador(self) -> None:
        if self._planificador and self._planificador.is_alive():
            return
        self._planificador = threading.Thread(target=self._bucle, daemon=True, name="planificador")
        self._planificador.start()

    def apagar(self) -> None:
        self._apagar.set()
        self._detener.set()

    @staticmethod
    def _en_horario(cfg: dict) -> bool:
        ahora = datetime.now().strftime("%H:%M")
        ini, fin = cfg.get("hora_inicio", "00:00"), cfg.get("hora_fin", "23:59")
        return ini <= ahora <= fin if ini <= fin else (ahora >= ini or ahora <= fin)

    def _bucle(self) -> None:
        while not self._apagar.wait(15):
            try:
                cfg = configuracion.cargar()["frecuencia"]
                if not cfg.get("activo") or self.corriendo or not self._en_horario(cfg):
                    continue
                if time.time() - self.ultima_programada >= 60 * int(cfg["cada_minutos"]):
                    self.ultima_programada = time.time()
                    self.iniciar("programada")
            except Exception as e:  # noqa: BLE001
                db.evento(None, None, "01", f"Error del planificador: {e}", "error")


servicio = Servicio()


def siguiente_ejecucion(minutos: int) -> str:
    return (datetime.now() + timedelta(minutes=minutos)).isoformat(timespec="seconds")
