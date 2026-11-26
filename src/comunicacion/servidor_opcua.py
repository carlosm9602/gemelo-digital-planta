"""Servidor OPC UA opcional (se activa con la variable de entorno OPCUA=1).

Publica las variables del proceso en un espacio de nombres propio, con nombres
tipo ISA-5.1 (LT-101, FT-101, ...), para conectarse desde UaExpert, Node-RED,
Ignition u otro cliente OPC UA.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

VARIABLES = {
    "LT-101.PV": ("nivel", "Nivel del tanque [m]"),
    "FT-101.PV": ("caudal_entrada", "Caudal de entrada [L/s]"),
    "FT-102.PV": ("caudal_salida", "Caudal de salida [L/s]"),
    "SC-101.PV": ("velocidad", "Velocidad de la bomba [%]"),
    "IT-101.PV": ("corriente", "Corriente del motor [A]"),
    "PT-102.PV": ("presion", "Presión de descarga [kPa]"),
    "LIC-101.SP": ("setpoint", "Setpoint de nivel [m]"),
}


class ServidorOPCUA:
    def __init__(self, url: str = "opc.tcp://0.0.0.0:4840/gemelo/"):
        self.url = url
        self.servidor = None
        self.nodos: dict[str, object] = {}

    async def iniciar(self) -> None:
        from asyncua import Server  # import diferido: la dependencia es opcional

        self.servidor = Server()
        await self.servidor.init()
        self.servidor.set_endpoint(self.url)
        self.servidor.set_server_name("Gemelo digital de planta")
        idx = await self.servidor.register_namespace("urn:gemelo-digital-planta")
        planta = await self.servidor.nodes.objects.add_object(idx, "Planta")
        for nombre, (_, descripcion) in VARIABLES.items():
            nodo = await planta.add_variable(idx, nombre, 0.0)
            self.nodos[nombre] = nodo
            log.debug("OPC UA: %s (%s)", nombre, descripcion)
        anomalia = await planta.add_variable(idx, "Detector.Anomalia", False)
        self.nodos["Detector.Anomalia"] = anomalia
        await self.servidor.start()
        log.info("OPC UA escuchando en %s", self.url)

    async def publicar(self, m: dict, anomalia: bool) -> None:
        if not self.servidor:
            return
        for nombre, (campo, _) in VARIABLES.items():
            await self.nodos[nombre].write_value(float(m[campo]))
        await self.nodos["Detector.Anomalia"].write_value(bool(anomalia))

    async def detener(self) -> None:
        if self.servidor:
            await self.servidor.stop()
