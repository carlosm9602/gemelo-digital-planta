"""API del gemelo digital: corre la planta, publica por WebSocket, Modbus y OPC UA.

Ejecutar:
    uvicorn api.main:app --app-dir src --port 8000

Variables de entorno:
    VELOCIDAD_SIM  factor de tiempo (1 = tiempo real, 5 = cinco veces más rápido). Por defecto 1.
    MODBUS         1 para levantar el servidor Modbus TCP (puerto MODBUS_PUERTO, 5020). Por defecto 1.
    OPCUA          1 para levantar el servidor OPC UA en el puerto 4840. Por defecto 0.
    HISTORIADOR    ruta del archivo SQLite. Por defecto historiador.db.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from analitica.detector import RUTA_MODELO, Detector
from api.historiador import Historiador
from planta.alarmas import GestorAlarmas
from planta.fallas import DESCRIPCION, TIPOS
from planta.simulador import Planta

log = logging.getLogger("gemelo")
WEB = Path(__file__).resolve().parents[2] / "web"


def _env(nombre: str, defecto: str) -> str:
    return os.environ.get(nombre, defecto)


class Gemelo:
    """Une planta, alarmas, detector, historiador y comunicaciones en un solo ciclo."""

    def __init__(self, velocidad_sim: float = 1.0, ruta_db: str = "historiador.db"):
        self.planta = Planta(semilla=None)
        self.alarmas = GestorAlarmas()
        self.historiador = Historiador(ruta_db)
        self.detector = self._cargar_detector()
        self.velocidad_sim = velocidad_sim
        self.clientes: set[WebSocket] = set()
        self.modbus = None
        self.opcua = None
        self.anomalia_previa = False
        self.ultimo: dict | None = None
        self._por_enviar: list[dict] = []

    def evento(
        self, t: float, tipo: str, tag: str, prioridad: str = "", descripcion: str = "", datos=None
    ) -> dict:
        """Guarda un evento en el historiador y lo deja listo para el próximo envío por WebSocket."""
        ev = self.historiador.guardar_evento(t, tipo, tag, prioridad, descripcion, datos)
        self._por_enviar.append(ev)
        return ev

    @staticmethod
    def _cargar_detector() -> Detector:
        if not RUTA_MODELO.exists():
            from analitica.entrenar import entrenar

            log.info("No hay modelo entrenado: entrenando con 3 h de operación simulada...")
            entrenar().guardar(RUTA_MODELO)
        return Detector.cargar(RUTA_MODELO)

    async def iniciar_comunicaciones(self) -> None:
        if _env("MODBUS", "1") == "1":
            from comunicacion.servidor_modbus import ServidorModbus

            self.modbus = ServidorModbus(puerto=int(_env("MODBUS_PUERTO", "5020")))
            await self.modbus.iniciar()
            self._sincronizar_modbus()
        if _env("OPCUA", "0") == "1":
            from comunicacion.servidor_opcua import ServidorOPCUA

            self.opcua = ServidorOPCUA()
            await self.opcua.iniciar()

    def _sincronizar_modbus(self) -> None:
        if self.modbus:
            p = self.planta
            self.modbus.escribir_consignas(p.setpoint, p.apertura_cmd, p.modo, p.velocidad_manual)

    def _consignas_desde_modbus(self) -> None:
        if not self.modbus:
            return
        c = self.modbus.leer_consignas()
        if c:
            self.planta.fijar_setpoint(c["setpoint"])
            self.planta.fijar_apertura(c["apertura"])
            self.planta.fijar_modo(c["modo"], c["velocidad_manual"])
            self.evento(
                self.planta.t,
                "operador",
                "MODBUS",
                descripcion="Consignas cambiadas por un cliente Modbus",
                datos=c,
            )

    async def ciclo(self) -> None:
        """Un paso de la planta y todo lo que cuelga de él."""
        self._consignas_desde_modbus()
        m = self.planta.paso().a_dict()
        r = self.detector.procesar(m)
        puntaje = r.puntaje if r else 0.0
        anomalia = bool(r and r.anomalia)
        m.update(puntaje=round(puntaje, 4), anomalia=anomalia, umbral=round(self.detector.umbral, 4))

        for e in self.alarmas.evaluar(m):
            self.evento(e.t, f"alarma_{e.tipo}", e.tag, e.prioridad, e.descripcion, {"valor": e.valor})
        if anomalia and not self.anomalia_previa:
            self.evento(
                m["t"],
                "deteccion",
                "DETECTOR",
                "alta",
                r.explicacion or "Comportamiento anómalo",
                {"causa": r.causa, "zscores": r.zscores},
            )
        elif self.anomalia_previa and not anomalia:
            self.evento(
                m["t"], "deteccion_fin", "DETECTOR", descripcion="El comportamiento volvió a la normalidad"
            )
        self.anomalia_previa = anomalia
        m["explicacion"] = r.explicacion if r and anomalia else None
        m["zscores"] = r.zscores if r else {}

        self.historiador.guardar_muestra(m)
        if self.modbus:
            fallas_bits = sum(1 << i for i, f in enumerate(TIPOS) if f in m["fallas"])
            self.modbus.publicar(m, puntaje, anomalia, self.alarmas.bits(), fallas_bits)
        if self.opcua:
            await self.opcua.publicar(m, anomalia)

        self.ultimo = m
        eventos, self._por_enviar = self._por_enviar, []
        await self.difundir(
            {"tipo": "muestra", "muestra": m, "eventos": eventos, "alarmas": self.alarmas.resumen()}
        )

    async def difundir(self, mensaje: dict) -> None:
        caidos = []
        for ws in self.clientes:
            try:
                await ws.send_json(mensaje)
            except Exception:  # noqa: BLE001 - cliente cerrado
                caidos.append(ws)
        for ws in caidos:
            self.clientes.discard(ws)

    async def correr(self) -> None:
        while True:
            inicio = asyncio.get_running_loop().time()
            try:
                await self.ciclo()
            except Exception:  # noqa: BLE001 - el lazo de control no se debe caer
                log.exception("Error en el ciclo")
            espera = self.planta.dt / self.velocidad_sim - (asyncio.get_running_loop().time() - inicio)
            await asyncio.sleep(max(espera, 0.0))

    async def cerrar(self) -> None:
        if self.modbus:
            await self.modbus.detener()
        if self.opcua:
            await self.opcua.detener()
        self.historiador.cerrar()


gemelo: Gemelo | None = None


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    global gemelo
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    gemelo = Gemelo(float(_env("VELOCIDAD_SIM", "1")), _env("HISTORIADOR", "historiador.db"))
    await gemelo.iniciar_comunicaciones()
    tarea = asyncio.create_task(gemelo.correr())
    yield
    tarea.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea
    await gemelo.cerrar()


app = FastAPI(
    title="Gemelo digital de planta",
    description="Simulador de proceso de nivel con PID, Modbus TCP, OPC UA, alarmas ISA-18.2 y detección de fallas.",
    version="0.1.0",
    lifespan=ciclo_de_vida,
)


# ---------------------------------------------------------------- modelos de entrada
class Setpoint(BaseModel):
    valor: float = Field(..., ge=0.2, le=3.8, description="Nivel deseado en metros")


class Apertura(BaseModel):
    valor: float = Field(..., ge=0, le=100, description="Apertura de la válvula de salida en %")


class Modo(BaseModel):
    modo: str = Field(..., pattern="^(auto|manual)$")
    velocidad_manual: float | None = Field(None, ge=0, le=100)


def _g() -> Gemelo:
    if gemelo is None:
        raise HTTPException(503, "El gemelo todavía está arrancando")
    return gemelo


# ---------------------------------------------------------------- rutas
@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(WEB / "index.html")


@app.get("/api/estado", summary="Última muestra, alarmas y fallas activas")
def estado():
    g = _g()
    return {"muestra": g.ultimo, "alarmas": g.alarmas.resumen(), "fallas_disponibles": DESCRIPCION}


@app.post("/api/setpoint", summary="Cambia el setpoint de nivel")
def setpoint(body: Setpoint):
    g = _g()
    g.planta.fijar_setpoint(body.valor)
    g._sincronizar_modbus()
    g.evento(g.planta.t, "operador", "LIC-101", descripcion=f"Setpoint a {body.valor} m")
    return {"setpoint": g.planta.setpoint}


@app.post("/api/valvula", summary="Cambia la apertura de la válvula de salida")
def valvula(body: Apertura):
    g = _g()
    g.planta.fijar_apertura(body.valor)
    g._sincronizar_modbus()
    g.evento(g.planta.t, "operador", "FV-102", descripcion=f"Apertura a {body.valor} %")
    return {"apertura": g.planta.apertura_cmd}


@app.post("/api/modo", summary="Automático o manual")
def modo(body: Modo):
    g = _g()
    g.planta.fijar_modo(body.modo, body.velocidad_manual)
    g._sincronizar_modbus()
    return {"modo": g.planta.modo}


@app.post("/api/fallas/{tipo}", summary="Inyecta una falla")
def inyectar(tipo: str):
    g = _g()
    if tipo not in DESCRIPCION:
        raise HTTPException(404, f"Falla desconocida. Opciones: {', '.join(TIPOS)}")
    g.planta.inyectar_falla(tipo)
    g.evento(g.planta.t, "falla_inyectada", tipo, descripcion=DESCRIPCION[tipo])
    return {"fallas": g.planta.fallas.lista()}


@app.delete("/api/fallas", summary="Quita todas las fallas")
def limpiar_fallas():
    g = _g()
    g.planta.fallas.limpiar()
    g.evento(g.planta.t, "falla_retirada", "TODAS", descripcion="Fallas retiradas")
    return {"fallas": []}


@app.post("/api/alarmas/{tag}/reconocer", summary="Reconoce una alarma (ISA-18.2)")
def reconocer(tag: str):
    g = _g()
    try:
        ev = g.alarmas.reconocer(tag, g.planta.t)
    except KeyError as e:
        raise HTTPException(404, f"No existe la alarma {tag}") from e
    if ev:
        g.evento(ev.t, "alarma_reconocida", tag, ev.prioridad, ev.descripcion)
    return {"alarmas": g.alarmas.resumen()}


@app.get("/api/historico", summary="Muestras guardadas en el historiador")
def historico(desde: float = 0.0, limite: int = 5000):
    return _g().historiador.consultar(desde, min(limite, 20000))


@app.get("/api/eventos", summary="Últimos eventos")
def eventos():
    return list(_g().historiador.eventos_recientes)


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    g = _g()
    await websocket.accept()
    g.clientes.add(websocket)
    await websocket.send_json(
        {
            "tipo": "inicio",
            "historia": list(g.historiador.recientes)[-600:],
            "eventos": list(g.historiador.eventos_recientes),
            "fallas_disponibles": DESCRIPCION,
            "alarmas": g.alarmas.resumen(),
        }
    )
    try:
        while True:
            await websocket.receive_text()  # mantiene viva la conexión
    except WebSocketDisconnect:
        g.clientes.discard(websocket)


app.mount("/static", StaticFiles(directory=WEB), name="static")
