"""Entrena el detector con operación normal simulada.

Uso:
    python -m analitica.entrenar --horas 3
"""

from __future__ import annotations

import argparse

import numpy as np

from analitica.detector import RUTA_MODELO, Detector, Extractor
from planta.simulador import Operador, Planta


def datos_normales(horas: float, semilla: int) -> np.ndarray:
    """Simula operación sin fallas, con un operador que mueve válvula y setpoint."""
    planta = Planta(semilla=semilla)
    operador = Operador(planta, semilla=semilla + 100)
    extractor = Extractor(planta.p, planta.dt)
    filas = []
    for _ in range(int(horas * 3600 / planta.dt)):
        operador.actuar()
        x = extractor(planta.paso().a_dict())
        if x is not None and planta.t > 60:  # descarta el arranque
            filas.append(x)
    return np.array(filas)


def entrenar(horas: float = 3.0, semilla: int = 1) -> Detector:
    # varias corridas cortas con semillas distintas cubren más condiciones que una larga
    X = np.vstack([datos_normales(horas / 3, semilla + i) for i in range(3)])
    return Detector.entrenar(X)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horas", type=float, default=3.0, help="horas de operación normal simulada")
    ap.add_argument("--semilla", type=int, default=1)
    args = ap.parse_args()
    detector = entrenar(args.horas, args.semilla)
    ruta = detector.guardar(RUTA_MODELO)
    print(f"Modelo guardado en {ruta} (umbral {detector.umbral:.4f})")


if __name__ == "__main__":
    main()
