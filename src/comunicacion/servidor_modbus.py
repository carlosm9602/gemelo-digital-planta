"""Servidor Modbus TCP que expone la planta como lo haría un PLC.

El mapa de registros está en docs/mapa_registros.md. Los valores se envían como
enteros de 16 bits escalados (por ejemplo, nivel en mm, caudal en L/s x 100).
Un HMI o SCADA externo puede escribir el setpoint, la apertura de la válvula y
el modo en los holding registers; el gemelo los lee en cada ciclo.
"""

from __future__ import annotations

import asyncio
import logging

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext

try:  # pymodbus >= 3.10
    from pymodbus.datastore import ModbusDeviceContext as _Contexto
except ImportError:  # pragma: no cover - versiones anteriores
    from pymodbus.datastore import ModbusSlaveContext as _Contexto

from pymodbus.server import StartAsyncTcpServer

from planta.simulador import ma_desde_nivel

log = logging.getLogger(__name__)

FC_HOLDING = 3
FC_INPUT = 4

# Input registers (solo lectura, 3xxxx)
IR = {
    "nivel_mm": 0,
    "nivel_ua": 1,  # señal del transmisor en microamperios (4000-20000)
    "caudal_entrada_cls": 2,  # L/s x 100
    "caudal_salida_cls": 3,
    "velocidad_x10": 4,  # % x 10
    "corriente_x100": 5,  # A x 100
    "presion_x10": 6,  # kPa x 10
    "puntaje_x1000": 7,  # puntaje del detector x 1000
    "anomalia": 8,  # 0/1
    "alarmas_bits": 9,  # bit i = alarma i activa
    "fallas_bits": 10,  # bit i = falla inyectada i (solo simulación)
}
# Holding registers (lectura/escritura, 4xxxx)
HR = {
    "setpoint_mm": 0,
    "apertura_x10": 1,
    "modo": 2,  # 0 = automático, 1 = manual
    "velocidad_manual_x10": 3,
}


def _u16(valor: float) -> int:
    return int(min(max(round(valor), 0), 65535))


class ServidorModbus:
    def __init__(self, host: str = "0.0.0.0", puerto: int = 5020):
        self.host, self.puerto = host, puerto
        dispositivo = _Contexto(
            # bloque desde 1: el contexto suma 1 a la dirección Modbus (registro 0 = celda 1)
            ir=ModbusSequentialDataBlock(1, [0] * 32),
            hr=ModbusSequentialDataBlock(1, [0] * 32),
        )
        try:
            self.contexto = ModbusServerContext(devices=dispositivo, single=True)
        except TypeError:  # pragma: no cover - pymodbus < 3.10
            self.contexto = ModbusServerContext(slaves=dispositivo, single=True)
        self._tarea: asyncio.Task | None = None
        self._escrito: list[int] | None = None

    @property
    def _disp(self):
        return self.contexto[0]

    async def iniciar(self) -> None:
        self._tarea = asyncio.create_task(
            StartAsyncTcpServer(context=self.contexto, address=(self.host, self.puerto))
        )
        log.info("Modbus TCP escuchando en %s:%s", self.host, self.puerto)

    async def detener(self) -> None:
        if self._tarea:
            self._tarea.cancel()

    def publicar(self, m: dict, puntaje: float, anomalia: bool, alarmas_bits: int, fallas_bits: int) -> None:
        valores = [0] * len(IR)
        valores[IR["nivel_mm"]] = _u16(m["nivel"] * 1000)
        valores[IR["nivel_ua"]] = _u16(ma_desde_nivel(m["nivel"]) * 1000)
        valores[IR["caudal_entrada_cls"]] = _u16(m["caudal_entrada"] * 100)
        valores[IR["caudal_salida_cls"]] = _u16(m["caudal_salida"] * 100)
        valores[IR["velocidad_x10"]] = _u16(m["velocidad"] * 10)
        valores[IR["corriente_x100"]] = _u16(m["corriente"] * 100)
        valores[IR["presion_x10"]] = _u16(m["presion"] * 10)
        valores[IR["puntaje_x1000"]] = _u16(puntaje * 1000)
        valores[IR["anomalia"]] = int(anomalia)
        valores[IR["alarmas_bits"]] = alarmas_bits
        valores[IR["fallas_bits"]] = fallas_bits
        self._disp.setValues(FC_INPUT, 0, valores)

    def escribir_consignas(
        self, setpoint: float, apertura: float, modo: str, velocidad_manual: float
    ) -> None:
        """Refleja en los holding registers lo que se cambió desde el tablero web."""
        valores = [
            _u16(setpoint * 1000),
            _u16(apertura * 10),
            0 if modo == "auto" else 1,
            _u16(velocidad_manual * 10),
        ]
        self._disp.setValues(FC_HOLDING, 0, valores)
        self._escrito = valores

    def leer_consignas(self) -> dict | None:
        """Devuelve las consignas si un cliente Modbus externo las cambió."""
        actuales = list(self._disp.getValues(FC_HOLDING, 0, len(HR)))
        if self._escrito is None or actuales == self._escrito:
            return None
        self._escrito = actuales
        return {
            "setpoint": actuales[HR["setpoint_mm"]] / 1000,
            "apertura": actuales[HR["apertura_x10"]] / 10,
            "modo": "auto" if actuales[HR["modo"]] == 0 else "manual",
            "velocidad_manual": actuales[HR["velocidad_manual_x10"]] / 10,
        }
