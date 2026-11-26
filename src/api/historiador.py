"""Historiador de proceso en SQLite: muestras y eventos (alarmas, fallas, detecciones)."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path

COLUMNAS = [
    "t",
    "setpoint",
    "nivel",
    "caudal_entrada",
    "caudal_salida",
    "velocidad",
    "apertura_cmd",
    "corriente",
    "presion",
    "puntaje",
    "anomalia",
]


class Historiador:
    def __init__(self, ruta: str | Path = "historiador.db", memoria: int = 1200, lote: int = 20):
        self.con = sqlite3.connect(str(ruta), check_same_thread=False)
        self.con.execute(f"CREATE TABLE IF NOT EXISTS muestras ({', '.join(c + ' REAL' for c in COLUMNAS)})")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS eventos (t REAL, tipo TEXT, tag TEXT, prioridad TEXT, "
            "descripcion TEXT, datos TEXT)"
        )
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_muestras_t ON muestras(t)")
        self.recientes: deque[dict] = deque(maxlen=memoria)
        self.eventos_recientes: deque[dict] = deque(maxlen=200)
        self._pendientes: list[tuple] = []
        self.lote = lote

    def guardar_muestra(self, m: dict) -> None:
        self.recientes.append(m)
        self._pendientes.append(tuple(float(m.get(c) or 0) for c in COLUMNAS))
        if len(self._pendientes) >= self.lote:
            self.vaciar()

    def guardar_evento(
        self,
        t: float,
        tipo: str,
        tag: str,
        prioridad: str = "",
        descripcion: str = "",
        datos: dict | None = None,
    ) -> dict:
        ev = {
            "t": t,
            "tipo": tipo,
            "tag": tag,
            "prioridad": prioridad,
            "descripcion": descripcion,
            "datos": datos or {},
        }
        self.eventos_recientes.append(ev)
        self.con.execute(
            "INSERT INTO eventos VALUES (?,?,?,?,?,?)",
            (t, tipo, tag, prioridad, descripcion, json.dumps(datos or {}, ensure_ascii=False)),
        )
        self.con.commit()
        return ev

    def vaciar(self) -> None:
        if self._pendientes:
            self.con.executemany(
                f"INSERT INTO muestras VALUES ({','.join('?' * len(COLUMNAS))})", self._pendientes
            )
            self.con.commit()
            self._pendientes.clear()

    def consultar(self, desde: float = 0.0, limite: int = 5000) -> list[dict]:
        self.vaciar()
        filas = self.con.execute(
            "SELECT * FROM muestras WHERE t >= ? ORDER BY t LIMIT ?", (desde, limite)
        ).fetchall()
        return [dict(zip(COLUMNAS, f, strict=True)) for f in filas]

    def cerrar(self) -> None:
        self.vaciar()
        self.con.close()
