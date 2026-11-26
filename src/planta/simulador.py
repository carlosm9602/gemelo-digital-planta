"""Simulador de un proceso de nivel: tanque, bomba de entrada y válvula de salida.

Balance de masa del tanque (sección constante A):

    A · dh/dt = Q_entrada - Q_salida
    Q_entrada = Q_max · (velocidad / 100) · eficiencia
    Q_salida  = Cv · (apertura / 100) · sqrt(h)

Un PID mueve la velocidad de la bomba (variador) para mantener el nivel en el
setpoint. El operador cambia la apertura de la válvula de salida, que es la
perturbación. Las señales medidas llevan ruido y pasan por los transmisores
4-20 mA, donde actúan las fallas.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from planta.fallas import GestorFallas
from planta.pid import PID


@dataclass(frozen=True)
class Parametros:
    area: float = 2.0  # m²
    altura: float = 4.0  # m, rango del transmisor 0-4 m
    q_max: float = 0.08  # m³/s con la bomba al 100 %
    cv: float = 0.0566  # m^2.5/s, coeficiente de la válvula de salida
    tau_valvula: float = 3.0  # s, constante de tiempo del actuador
    tau_bomba: float = 2.0  # s, rampa del variador
    ruido_nivel: float = 0.004  # m
    ruido_caudal: float = 0.01  # fracción
    ruido_corriente: float = 0.05  # A
    ruido_presion: float = 0.8  # kPa


@dataclass
class Muestra:
    """Lo que vería un SCADA en un instante. Caudales en L/s."""

    t: float
    setpoint: float
    nivel: float  # medido por el transmisor (puede estar fallando)
    caudal_entrada: float
    caudal_salida: float
    velocidad: float  # % del variador
    apertura_cmd: float  # % ordenado por el operador
    corriente: float  # A
    presion: float  # kPa en la descarga de la bomba
    modo: str
    fallas: list[str] = field(default_factory=list)
    nivel_real: float = 0.0  # solo para evaluación; un SCADA real no lo conoce

    def a_dict(self) -> dict:
        return asdict(self)


def ma_desde_nivel(nivel: float, altura: float = 4.0) -> float:
    """Escala de ingeniería a 4-20 mA."""
    return 4.0 + 16.0 * min(max(nivel / altura, 0.0), 1.0)


class Planta:
    def __init__(self, parametros: Parametros | None = None, dt: float = 0.5, semilla: int | None = 7):
        self.p = parametros or Parametros()
        self.dt = dt
        self.rng = np.random.default_rng(semilla)
        self.pid = PID(kp=150.0, ki=2.5, salida_min=0.0, salida_max=100.0)
        self.fallas = GestorFallas()
        self.t = 0.0
        self.setpoint = 2.0
        self.apertura_cmd = 50.0
        self.modo = "auto"
        self.velocidad_manual = 50.0
        # estado físico
        self.nivel = 2.0
        self.velocidad = 50.0
        self.apertura_actuador = 50.0
        self._ultima: Muestra | None = None
        self.pid.inicializar(self.velocidad, self.setpoint, self.nivel)  # arranque sin salto

    # --- órdenes del operador ---------------------------------------------
    def fijar_setpoint(self, valor: float) -> None:
        self.setpoint = min(max(valor, 0.2), self.p.altura - 0.2)

    def fijar_apertura(self, valor: float) -> None:
        self.apertura_cmd = min(max(valor, 0.0), 100.0)

    def fijar_modo(self, modo: str, velocidad_manual: float | None = None) -> None:
        if modo not in ("auto", "manual"):
            raise ValueError("modo debe ser 'auto' o 'manual'")
        if velocidad_manual is not None:
            self.velocidad_manual = min(max(velocidad_manual, 0.0), 100.0)
        if modo == "auto" and self.modo == "manual" and self._ultima:
            self.pid.inicializar(self.velocidad, self.setpoint, self._ultima.nivel)
        self.modo = modo

    def inyectar_falla(self, tipo: str) -> None:
        nivel_medido = self._ultima.nivel if self._ultima else self.nivel
        self.fallas.inyectar(tipo, self.t, nivel_medido, self.apertura_actuador)

    # --- un paso de simulación --------------------------------------------
    def paso(self) -> Muestra:
        p, dt, rng = self.p, self.dt, self.rng

        # 1) medición de nivel (con ruido y posibles fallas)
        nivel_sensor = self.nivel + rng.normal(0, p.ruido_nivel)
        nivel_medido = self.fallas.nivel_medido(nivel_sensor, self.t)
        nivel_medido = min(max(nivel_medido, 0.0), p.altura)

        # 2) control
        if self.modo == "auto":
            orden = self.pid.calcular(self.setpoint, nivel_medido, dt)
        else:
            orden = self.velocidad_manual
        self.velocidad += (orden - self.velocidad) * min(dt / p.tau_bomba, 1.0)

        # 3) actuadores
        self.apertura_actuador += (self.apertura_cmd - self.apertura_actuador) * min(dt / p.tau_valvula, 1.0)
        apertura_real = self.fallas.apertura_real(self.apertura_actuador)
        if self.fallas.activa("valvula_trabada"):
            self.apertura_actuador = apertura_real  # el vástago no se mueve

        # 4) proceso
        eficiencia = self.fallas.eficiencia_bomba(self.t)
        q_in = p.q_max * (self.velocidad / 100.0) * eficiencia
        q_out = p.cv * (apertura_real / 100.0) * math.sqrt(max(self.nivel, 0.0))
        self.nivel = min(max(self.nivel + (q_in - q_out) / p.area * dt, 0.0), p.altura)
        self.t += dt

        # 5) instrumentos de campo
        ruido = self.fallas.ruido_extra()
        frac = self.velocidad / 100.0
        corriente = 2.0 + 10.0 * frac**2 * (0.6 + 0.4 * eficiencia) + rng.normal(0, p.ruido_corriente * ruido)
        presion = (
            40.0
            + 9.81 * self.nivel
            + 220.0 * frac**2 * eficiencia**2
            + rng.normal(0, p.ruido_presion * ruido)
        )

        muestra = Muestra(
            t=round(self.t, 3),
            setpoint=self.setpoint,
            nivel=round(nivel_medido, 4),
            caudal_entrada=round(q_in * 1000 * (1 + rng.normal(0, p.ruido_caudal)), 3),
            caudal_salida=round(q_out * 1000 * (1 + rng.normal(0, p.ruido_caudal)), 3),
            velocidad=round(self.velocidad, 3),
            apertura_cmd=round(self.apertura_cmd, 2),
            corriente=round(max(corriente, 0.0), 3),
            presion=round(presion, 2),
            modo=self.modo,
            fallas=self.fallas.lista(),
            nivel_real=round(self.nivel, 4),
        )
        self._ultima = muestra
        return muestra

    @property
    def ultima(self) -> Muestra | None:
        return self._ultima


class Operador:
    """Operador simulado: mueve la válvula y el setpoint de vez en cuando.

    Sirve para generar datos de entrenamiento con operación normal variada.
    """

    def __init__(self, planta: Planta, semilla: int | None = 11, cada: float = 60.0):
        self.planta = planta
        self.rng = np.random.default_rng(semilla)
        self.cada = cada
        self._proximo = cada

    def actuar(self) -> None:
        if self.planta.t >= self._proximo:
            self._proximo += self.cada * self.rng.uniform(0.5, 1.5)
            if self.rng.random() < 0.7:
                self.planta.fijar_apertura(self.rng.uniform(25, 75))
            else:
                self.planta.fijar_setpoint(round(self.rng.uniform(1.5, 2.8), 1))
