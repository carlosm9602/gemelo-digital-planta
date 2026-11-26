"""Compara el detector contra las alarmas clásicas por umbral.

Para cada tipo de falla corre varios escenarios (semillas y aperturas distintas),
inyecta la falla con la planta estable y mide:
  * cuántos segundos tarda el detector en marcar anomalía,
  * cuántos segundos tarda la primera alarma por umbral (o si nunca llega),
  * cuántas falsas detecciones hace en operación normal.

Uso:
    python -m analitica.evaluar --escenarios 10
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np

from analitica.detector import CARACTERISTICAS, RUTA_MODELO, Detector, Extractor, diagnosticar
from planta.alarmas import GestorAlarmas
from planta.fallas import TIPOS
from planta.simulador import Operador, Planta

ESPERADO = {
    "sensor_pegado": "transmisor_nivel",
    "deriva": "transmisor_nivel",
    "cavitacion": "bomba",
    "valvula_trabada": "valvula",
}
CALENTAMIENTO = 300.0  # s antes de inyectar la falla
HORIZONTE = 900.0  # s observados después de la falla


@dataclass
class Corrida:
    falla: str
    t_detector: float | None
    t_alarma: float | None
    alarma: str | None
    diagnostico: str | None = None


def correr_escenario(detector: Detector, falla: str, semilla: int) -> Corrida:
    rng = np.random.default_rng(semilla)
    planta = Planta(semilla=semilla)
    alarmas = GestorAlarmas()
    extractor = Extractor(planta.p, planta.dt)
    planta.fijar_apertura(rng.uniform(55, 75))
    planta.fijar_setpoint(round(rng.uniform(1.8, 2.4), 1))

    t_ala = alarma = t_falla = None
    cambio_valvula = rng.uniform(10, 40)  # el operador mueve la válvula poco después
    tiempos, filas = [], []
    while planta.t < CALENTAMIENTO + HORIZONTE:
        if t_falla is None and planta.t >= CALENTAMIENTO:
            planta.inyectar_falla(falla)
            t_falla = planta.t
        if t_falla is not None and falla == "valvula_trabada" and planta.t - t_falla >= cambio_valvula:
            planta.fijar_apertura(
                planta.apertura_cmd - 25 if planta.apertura_cmd > 50 else planta.apertura_cmd + 25
            )
            cambio_valvula = float("inf")
        m = planta.paso().a_dict()
        x = extractor(m)
        eventos = alarmas.evaluar(m)
        if x is not None:
            tiempos.append(planta.t)
            filas.append(x)
        if t_falla is not None and t_ala is None and any(e.tipo == "activada" for e in eventos):
            t_ala = planta.t - t_falla
            alarma = next(e.tag for e in eventos if e.tipo == "activada")

    X = np.array(filas)
    anom = detector.anomalias_lote(X)
    tiempos = np.array(tiempos)
    despues = np.where(anom & (tiempos >= t_falla))[0]
    t_det = float(tiempos[despues[0]] - t_falla) if len(despues) else None
    diag = None
    if len(despues):
        i = min(despues[0] + 20, len(X) - 1)  # 10 s después de detectar, como lo vería el operador
        z = detector.escalador.transform(X[i : i + 1])[0]
        diag = diagnosticar(dict(zip(CARACTERISTICAS, z, strict=True)))[0]
    return Corrida(falla, t_det, t_ala, alarma, diag)


def falsos_positivos(detector: Detector, horas: float, semilla: int = 999) -> tuple[int, float]:
    """Cuenta episodios de anomalía en operación normal (con operador moviendo cosas)."""
    planta = Planta(semilla=semilla)
    operador = Operador(planta, semilla=semilla)
    extractor = Extractor(planta.p, planta.dt)
    filas = []
    while planta.t < horas * 3600:
        operador.actuar()
        x = extractor(planta.paso().a_dict())
        if x is not None and planta.t > 60:
            filas.append(x)
    anom = detector.anomalias_lote(np.array(filas))
    episodios = int(np.sum(anom[1:] & ~anom[:-1]) + anom[0])
    return episodios, episodios / horas


def evaluar(detector: Detector, escenarios: int = 10, horas_normales: float = 4.0) -> dict:
    corridas = [correr_escenario(detector, f, 1000 + i) for f in TIPOS for i in range(escenarios)]
    fp, fp_hora = falsos_positivos(detector, horas_normales)
    filas = []
    for f in TIPOS:
        cs = [c for c in corridas if c.falla == f]
        det = [c.t_detector for c in cs if c.t_detector is not None]
        ala = [c.t_alarma for c in cs if c.t_alarma is not None]
        adelanto = [
            c.t_alarma - c.t_detector for c in cs if c.t_detector is not None and c.t_alarma is not None
        ]
        esperado = ESPERADO[f]
        bien = sum(1 for c in cs if c.diagnostico == esperado)
        filas.append(
            {
                "falla": f,
                "diagnostico_ok": f"{bien}/{len(det)}" if det else "—",
                "detectadas": f"{len(det)}/{len(cs)}",
                "t_detector_s": round(float(np.median(det)), 1) if det else None,
                "alarmas": f"{len(ala)}/{len(cs)}",
                "t_alarma_s": round(float(np.median(ala)), 1) if ala else None,
                "adelanto_s": round(float(np.median(adelanto)), 1) if adelanto else None,
            }
        )
    return {
        "filas": filas,
        "falsos_positivos": fp,
        "falsos_por_hora": round(fp_hora, 2),
        "horas_normales": horas_normales,
        "escenarios": escenarios,
    }


def a_markdown(res: dict) -> str:
    nombres = {
        "sensor_pegado": "Sensor de nivel pegado",
        "deriva": "Deriva del transmisor",
        "cavitacion": "Cavitación de la bomba",
        "valvula_trabada": "Válvula trabada",
    }
    lineas = [
        "| Falla | Detectadas por el modelo | Tiempo mediano del modelo | Diagnóstico correcto | Alarmas por umbral que sonaron | Tiempo mediano de la alarma |",
        "|---|---|---|---|---|---|",
    ]
    for f in res["filas"]:
        t_det = f"{f['t_detector_s']} s" if f["t_detector_s"] is not None else "—"
        t_ala = f"{f['t_alarma_s']} s" if f["t_alarma_s"] is not None else "nunca"
        lineas.append(
            f"| {nombres[f['falla']]} | {f['detectadas']} | {t_det} | {f['diagnostico_ok']} | {f['alarmas']} | {t_ala} |"
        )
    lineas.append("")
    lineas.append(
        f"Falsas detecciones en {res['horas_normales']:g} h de operación normal con cambios de "
        f"setpoint y válvula: {res['falsos_positivos']} ({res['falsos_por_hora']} por hora)."
    )
    return "\n".join(lineas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--escenarios", type=int, default=10)
    ap.add_argument("--horas-normales", type=float, default=4.0)
    args = ap.parse_args()
    detector = Detector.cargar(RUTA_MODELO)
    print(a_markdown(evaluar(detector, args.escenarios, args.horas_normales)))


if __name__ == "__main__":
    main()
