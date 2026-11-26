"""Inyección de fallas reales de instrumentación y equipo.

Cada falla modifica la planta o la medición a partir del instante en que se
activa. Las cuatro fallas están elegidas porque son comunes en planta y porque
dos de ellas (sensor pegado y deriva) nunca disparan una alarma por umbral: el
controlador "cree" que todo va bien mientras el nivel real se aleja.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DESCRIPCION = {
    "sensor_pegado": "El transmisor de nivel se congela en el último valor (falla típica de un LT con la celda dañada).",
    "deriva": "El transmisor de nivel se descalibra y su lectura sube poco a poco (0,1 m por minuto).",
    "cavitacion": "La bomba cavita: pierde caudal de forma progresiva y la corriente y la presión se vuelven ruidosas.",
    "valvula_trabada": "La válvula de salida se queda pegada y deja de seguir la orden del operador.",
}
TIPOS = tuple(DESCRIPCION)


@dataclass
class FallaActiva:
    tipo: str
    inicio: float
    valor_congelado: float | None = None  # sensor pegado / válvula trabada


@dataclass
class GestorFallas:
    """Guarda qué fallas están activas y aplica su efecto en cada paso."""

    tasa_deriva: float = 0.1 / 60  # m/s
    tasa_cavitacion: float = 0.004  # pérdida de eficiencia por segundo
    eficiencia_minima: float = 0.45
    activas: dict[str, FallaActiva] = field(default_factory=dict)

    def inyectar(self, tipo: str, t: float, nivel_medido: float, apertura_real: float) -> None:
        if tipo not in DESCRIPCION:
            raise ValueError(f"Falla desconocida '{tipo}'. Opciones: {', '.join(TIPOS)}")
        congelado = {"sensor_pegado": nivel_medido, "valvula_trabada": apertura_real}.get(tipo)
        self.activas[tipo] = FallaActiva(tipo, t, congelado)

    def limpiar(self, tipo: str | None = None) -> None:
        if tipo is None:
            self.activas.clear()
        else:
            self.activas.pop(tipo, None)

    def activa(self, tipo: str) -> bool:
        return tipo in self.activas

    # --- efectos -----------------------------------------------------------
    def nivel_medido(self, nivel_sensor: float, t: float) -> float:
        if f := self.activas.get("sensor_pegado"):
            return f.valor_congelado
        if f := self.activas.get("deriva"):
            return nivel_sensor + self.tasa_deriva * (t - f.inicio)
        return nivel_sensor

    def eficiencia_bomba(self, t: float) -> float:
        if f := self.activas.get("cavitacion"):
            return max(self.eficiencia_minima, 1.0 - self.tasa_cavitacion * (t - f.inicio))
        return 1.0

    def ruido_extra(self) -> float:
        """Multiplicador del ruido en corriente y presión (la cavitación hace ruido)."""
        return 6.0 if "cavitacion" in self.activas else 1.0

    def apertura_real(self, apertura_actuador: float) -> float:
        if f := self.activas.get("valvula_trabada"):
            return f.valor_congelado
        return apertura_actuador

    def lista(self) -> list[str]:
        return sorted(self.activas)
