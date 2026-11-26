"""Alarmas por umbral con el ciclo de vida de ISA-18.2.

Estados (ISA-18.2, sección 11):
    NORMAL -> ACTIVA_NO_RECONOCIDA -> ACTIVA_RECONOCIDA -> NORMAL
                     \\-> NORMALIZADA_NO_RECONOCIDA -> NORMAL

Cada alarma tiene banda muerta (histéresis) y retardo de activación para no
inundar al operador con alarmas que parpadean por ruido.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Estado(StrEnum):
    NORMAL = "normal"
    ACTIVA_NO_RECONOCIDA = "activa_no_reconocida"
    ACTIVA_RECONOCIDA = "activa_reconocida"
    NORMALIZADA_NO_RECONOCIDA = "normalizada_no_reconocida"


@dataclass
class Alarma:
    tag: str
    descripcion: str
    variable: str
    limite: float
    alta: bool  # True: se activa por encima del límite
    prioridad: str  # "alta" | "media" | "baja"
    banda_muerta: float = 0.05
    retardo: int = 3  # muestras seguidas fuera de límite antes de activar
    estado: Estado = Estado.NORMAL
    _contador: int = field(default=0, repr=False)
    activada_en: float | None = None

    def fuera(self, valor: float) -> bool:
        return valor > self.limite if self.alta else valor < self.limite

    def dentro_con_banda(self, valor: float) -> bool:
        if self.alta:
            return valor < self.limite - self.banda_muerta
        return valor > self.limite + self.banda_muerta

    @property
    def activa(self) -> bool:
        return self.estado in (Estado.ACTIVA_NO_RECONOCIDA, Estado.ACTIVA_RECONOCIDA)


def alarmas_por_defecto() -> list[Alarma]:
    return [
        Alarma("LAHH-101", "Nivel muy alto: riesgo de rebose", "nivel", 3.6, True, "alta"),
        Alarma("LAH-101", "Nivel alto", "nivel", 3.2, True, "media"),
        Alarma("LAL-101", "Nivel bajo", "nivel", 1.0, False, "media"),
        Alarma("LALL-101", "Nivel muy bajo: bomba sin succión", "nivel", 0.6, False, "alta"),
        Alarma("PAL-102", "Baja presión de descarga", "presion", 55.0, False, "baja", banda_muerta=2.0),
    ]


@dataclass
class Evento:
    t: float
    tag: str
    tipo: str  # "activada" | "normalizada" | "reconocida"
    prioridad: str
    descripcion: str
    valor: float | None = None


class GestorAlarmas:
    def __init__(self, alarmas: list[Alarma] | None = None):
        self.alarmas = {a.tag: a for a in (alarmas or alarmas_por_defecto())}

    def evaluar(self, muestra: dict) -> list[Evento]:
        eventos: list[Evento] = []
        t = muestra["t"]
        for a in self.alarmas.values():
            valor = muestra[a.variable]
            if a.fuera(valor):
                a._contador += 1
            else:
                a._contador = 0

            if not a.activa and a._contador >= a.retardo:
                a.estado = Estado.ACTIVA_NO_RECONOCIDA
                a.activada_en = t
                eventos.append(Evento(t, a.tag, "activada", a.prioridad, a.descripcion, valor))
            elif a.activa and a.dentro_con_banda(valor):
                a.estado = (
                    Estado.NORMAL
                    if a.estado == Estado.ACTIVA_RECONOCIDA
                    else Estado.NORMALIZADA_NO_RECONOCIDA
                )
                eventos.append(Evento(t, a.tag, "normalizada", a.prioridad, a.descripcion, valor))
        return eventos

    def reconocer(self, tag: str, t: float) -> Evento | None:
        a = self.alarmas.get(tag)
        if a is None:
            raise KeyError(tag)
        if a.estado == Estado.ACTIVA_NO_RECONOCIDA:
            a.estado = Estado.ACTIVA_RECONOCIDA
        elif a.estado == Estado.NORMALIZADA_NO_RECONOCIDA:
            a.estado = Estado.NORMAL
        else:
            return None
        return Evento(t, tag, "reconocida", a.prioridad, a.descripcion)

    def resumen(self) -> list[dict]:
        orden = {"alta": 0, "media": 1, "baja": 2}
        return sorted(
            (
                {
                    "tag": a.tag,
                    "descripcion": a.descripcion,
                    "prioridad": a.prioridad,
                    "estado": a.estado.value,
                    "limite": a.limite,
                    "activada_en": a.activada_en,
                }
                for a in self.alarmas.values()
                if a.estado != Estado.NORMAL
            ),
            key=lambda x: (orden[x["prioridad"]], x["tag"]),
        )

    def alguna_activa(self) -> bool:
        return any(a.activa for a in self.alarmas.values())

    def bits(self) -> int:
        """Palabra de estado para Modbus: un bit por alarma activa."""
        return sum(1 << i for i, a in enumerate(self.alarmas.values()) if a.activa)
