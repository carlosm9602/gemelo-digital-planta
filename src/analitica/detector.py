"""Detector de anomalías con residuos físicos + Isolation Forest.

En vez de dar al modelo las señales en crudo, se le dan *residuos*: la
diferencia entre lo que mide cada instrumento y lo que la física del proceso
dice que debería medir. En operación normal los residuos son ruido alrededor de
cero sin importar el setpoint o la apertura; cuando algo se daña, uno o varios
se separan. Así el modelo aprende "qué es normal" con pocas horas de datos y
además se puede explicar qué residuo disparó la detección.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from planta.simulador import Parametros

CARACTERISTICAS = [
    "r_balance",  # A·dh/dt - (Qe - Qs)          -> el nivel no cuadra con los caudales
    "r_bomba",  # Qe - Qe esperado por velocidad -> la bomba no entrega lo que debería
    "r_valvula",  # Qs - Qs esperado por apertura  -> la válvula o el nivel no cuadran
    "r_corriente",  # I - I esperada por velocidad
    "r_presion",  # P - P esperada por velocidad y nivel
    "ruido_corriente",  # desviación estándar móvil del residuo de corriente
]

EXPLICACION = {
    "r_balance": "El nivel medido no cuadra con el balance de caudales: revisar el transmisor de nivel",
    "r_bomba": "La bomba entrega menos caudal del esperado para su velocidad: posible cavitación o desgaste",
    "r_valvula": "El caudal de salida no corresponde a la apertura ordenada: válvula trabada o nivel mal medido",
    "r_corriente": "La corriente del motor no corresponde a su velocidad",
    "r_presion": "La presión de descarga no corresponde a la velocidad de la bomba",
    "ruido_corriente": "La corriente del motor está ruidosa: vibración o cavitación",
}

DIAGNOSTICO = {
    "bomba": "La bomba entrega menos caudal del esperado y la corriente está ruidosa: posible cavitación",
    "transmisor_nivel": "El nivel medido no cuadra con la presión ni con los caudales: revisar el transmisor LT-101 (pegado o descalibrado)",
    "valvula": "El caudal de salida no sigue la apertura ordenada: la válvula FV-102 puede estar trabada",
}


def diagnosticar(z: dict[str, float]) -> tuple[str, str]:
    """Reglas de diagnóstico sobre los residuos normalizados (en desviaciones estándar).

    El orden importa: cada regla usa la firma física de una falla. La presión de
    descarga incluye la columna de agua (9,81·h), así que es un segundo medidor
    de nivel independiente del LT-101.
    """
    if z["ruido_corriente"] > 6 or z["r_bomba"] < -6:
        return "bomba", DIAGNOSTICO["bomba"]
    rv, rp = z["r_valvula"], z["r_presion"]
    # Si el LT-101 miente, el caudal esperado por la válvula y la presión esperada se
    # equivocan en el mismo sentido y en proporción. Si la válvula se traba, la presión cuadra.
    nivel_inconsistente = rv * rp > 0 and abs(rp) > 0.8 and abs(rp) >= 0.12 * abs(rv) and abs(rv) > 2.5
    if nivel_inconsistente or abs(z["r_balance"]) > 3:
        return "transmisor_nivel", DIAGNOSTICO["transmisor_nivel"]
    if abs(rv) > 4:
        return "valvula", DIAGNOSTICO["valvula"]
    causa = max(z, key=lambda k: abs(z[k]))
    return causa, EXPLICACION[causa]


RUTA_MODELO = Path(__file__).resolve().parents[2] / "modelos" / "detector.joblib"


class Extractor:
    """Convierte cada muestra del SCADA en el vector de residuos (con memoria corta).

    Es la parte "gemelo" del detector: lleva su propio modelo de la planta
    (incluida la dinámica del actuador de la válvula) y compara contra lo medido.
    """

    def __init__(self, p: Parametros | None = None, dt: float = 0.5, ventana: int = 20):
        self.p = p or Parametros()
        self.dt = dt
        self.ventana = ventana
        self._niveles: deque[float] = deque(maxlen=ventana + 1)
        self._netos: deque[float] = deque(maxlen=ventana + 1)  # Qe - Qs, m³/s
        self._buffer: deque[list[float]] = deque(maxlen=ventana)
        self._apertura_est: float | None = None

    def listo(self) -> bool:
        return len(self._buffer) == self.ventana and len(self._niveles) == self.ventana + 1

    def __call__(self, m: dict) -> np.ndarray | None:
        p = self.p
        frac = m["velocidad"] / 100.0
        h = max(m["nivel"], 0.0)
        qe, qs = m["caudal_entrada"] / 1000.0, m["caudal_salida"] / 1000.0

        # posición estimada del vástago: la misma dinámica de primer orden del actuador
        if self._apertura_est is None:
            self._apertura_est = m["apertura_cmd"]
        self._apertura_est += (m["apertura_cmd"] - self._apertura_est) * min(self.dt / p.tau_valvula, 1.0)

        # el nivel de la muestra k es el de antes del paso; los caudales de k lo llevan a k+1
        self._niveles.append(h)
        self._netos.append(qe - qs)

        r_corriente = m["corriente"] - (2.0 + 10.0 * frac**2)
        crudo = [
            (qe - p.q_max * frac) * 1000.0,
            (qs - p.cv * (self._apertura_est / 100.0) * math.sqrt(h)) * 1000.0,
            r_corriente,
            m["presion"] - (40.0 + 9.81 * h + 220.0 * frac**2),
        ]
        self._buffer.append(crudo)
        if not self.listo():
            return None

        neto_medio = float(np.mean(list(self._netos)[:-1]))
        dhdt = (self._niveles[-1] - self._niveles[0]) / (self.ventana * self.dt)
        r_balance = (p.area * dhdt - neto_medio) * 1000.0
        b = np.array(self._buffer)
        media = b.mean(axis=0)
        ruido = float(np.std(b[:, 2]))
        return np.array([r_balance, *media, ruido])


@dataclass
class Resultado:
    puntaje: float  # mayor = más raro
    anomalia: bool
    causa: str | None
    explicacion: str | None
    zscores: dict[str, float]


class Detector:
    def __init__(
        self,
        modelo: IsolationForest,
        escalador: StandardScaler,
        umbral: float,
        persistencia: int = 6,
        limite_z: float = 8.0,
        liberacion: int = 20,
    ):
        self.modelo = modelo
        self.escalador = escalador
        self.umbral = umbral
        self.persistencia = persistencia
        # Isolation Forest se satura cuando un solo residuo se dispara mucho (la mayoría
        # de árboles no corta por esa variable). El límite por residuo cubre ese caso.
        self.limite_z = limite_z
        # histéresis: para volver a "normal" hacen falta `liberacion` muestras seguidas sin anomalía
        self.liberacion = liberacion
        self.extractor = Extractor()
        self._fuera = self._dentro = 0
        self._activa = False

    def _avanzar(self, fuera: bool) -> bool:
        """Máquina de estados con retardo de activación y de liberación (como una alarma)."""
        if fuera:
            self._fuera, self._dentro = self._fuera + 1, 0
        else:
            self._fuera, self._dentro = 0, self._dentro + 1
        if not self._activa and self._fuera >= self.persistencia:
            self._activa = True
        elif self._activa and self._dentro >= self.liberacion:
            self._activa = False
        return self._activa

    @classmethod
    def entrenar(
        cls, X: np.ndarray, percentil: float = 99.9, persistencia: int = 6, semilla: int = 0
    ) -> Detector:
        escalador = StandardScaler().fit(X)
        Z = escalador.transform(X)
        modelo = IsolationForest(n_estimators=100, contamination="auto", random_state=semilla).fit(Z)
        puntajes = -modelo.score_samples(Z)
        umbral = float(np.percentile(puntajes, percentil))
        limite_z = float(np.max(np.abs(Z))) * 1.2  # ningún dato normal lo supera
        return cls(modelo, escalador, umbral, persistencia, limite_z)

    def reiniciar(self) -> None:
        self.extractor = Extractor()
        self._fuera = self._dentro = 0
        self._activa = False

    def procesar(self, muestra: dict) -> Resultado | None:
        x = self.extractor(muestra)
        if x is None:
            return None
        z = self.escalador.transform(x.reshape(1, -1))
        puntaje = float(-self.modelo.score_samples(z)[0])
        fuera = puntaje > self.umbral or float(np.max(np.abs(z))) > self.limite_z
        anomalia = self._avanzar(fuera)
        zs = {n: round(float(v), 2) for n, v in zip(CARACTERISTICAS, z[0], strict=True)}
        causa, explicacion = diagnosticar(zs) if anomalia else (None, None)
        return Resultado(puntaje, anomalia, causa, explicacion, zs)

    def anomalias_lote(self, X: np.ndarray) -> np.ndarray:
        """Versión por lotes para evaluar corridas largas (mismo resultado que `procesar`)."""
        Z = self.escalador.transform(X)
        puntajes = -self.modelo.score_samples(Z)
        sobre = (puntajes > self.umbral) | (np.max(np.abs(Z), axis=1) > self.limite_z)
        self._fuera = self._dentro = 0
        self._activa = False
        return np.array([self._avanzar(bool(s)) for s in sobre])

    def guardar(self, ruta: Path = RUTA_MODELO) -> Path:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "modelo": self.modelo,
                "escalador": self.escalador,
                "umbral": self.umbral,
                "persistencia": self.persistencia,
                "limite_z": self.limite_z,
                "caracteristicas": CARACTERISTICAS,
            },
            ruta,
        )
        return ruta

    @classmethod
    def cargar(cls, ruta: Path = RUTA_MODELO) -> Detector:
        d = joblib.load(ruta)
        return cls(d["modelo"], d["escalador"], d["umbral"], d["persistencia"], d.get("limite_z", 8.0))
