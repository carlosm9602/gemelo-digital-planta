"""Controlador PID discreto con anti-windup y transferencia sin salto (bumpless)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PID:
    """PID en forma paralela: u = Kp*e + Ki*integral(e) + Kd*de/dt.

    La derivada se calcula sobre la medición (no sobre el error) para evitar el
    "golpe derivativo" cuando el operador cambia el setpoint.
    """

    kp: float = 40.0
    ki: float = 2.0
    kd: float = 0.0
    salida_min: float = 0.0
    salida_max: float = 100.0
    accion_inversa: bool = False  # True si al subir la salida baja la variable
    _integral: float = field(default=0.0, init=False, repr=False)
    _medicion_previa: float | None = field(default=None, init=False, repr=False)

    def calcular(self, setpoint: float, medicion: float, dt: float) -> float:
        if dt <= 0:
            raise ValueError("dt debe ser positivo")
        error = setpoint - medicion
        if self.accion_inversa:
            error = -error

        derivada = 0.0
        if self._medicion_previa is not None and self.kd:
            derivada = -(medicion - self._medicion_previa) / dt
            if self.accion_inversa:
                derivada = -derivada
        self._medicion_previa = medicion

        integral_tentativa = self._integral + self.ki * error * dt
        salida = self.kp * error + integral_tentativa + self.kd * derivada

        # Anti-windup por integración condicional: solo se acumula si no satura
        # o si el error ayuda a salir de la saturación.
        if salida > self.salida_max:
            salida = self.salida_max
            if error < 0:
                self._integral = integral_tentativa
        elif salida < self.salida_min:
            salida = self.salida_min
            if error > 0:
                self._integral = integral_tentativa
        else:
            self._integral = integral_tentativa
        return salida

    def inicializar(self, salida_actual: float, setpoint: float, medicion: float) -> None:
        """Paso de manual a automático sin salto en la salida."""
        error = setpoint - medicion
        if self.accion_inversa:
            error = -error
        self._integral = salida_actual - self.kp * error
        self._medicion_previa = medicion

    def reiniciar(self) -> None:
        self._integral = 0.0
        self._medicion_previa = None
