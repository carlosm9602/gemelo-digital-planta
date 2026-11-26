import pytest

from planta.simulador import Planta


def planta_estable(**kw) -> Planta:
    p = Planta(semilla=1, **kw)
    for _ in range(200):
        p.paso()
    return p


def test_sensor_pegado_congela_la_lectura():
    p = planta_estable()
    p.inyectar_falla("sensor_pegado")
    lecturas = {p.paso().nivel for _ in range(50)}
    assert len(lecturas) == 1


def test_deriva_aleja_la_lectura_del_nivel_real():
    p = planta_estable()
    p.inyectar_falla("deriva")
    for _ in range(600):  # 5 minutos
        m = p.paso()
    assert m.nivel - m.nivel_real > 0.3  # el PID baja el nivel real mientras la lectura "está bien"


def test_cavitacion_reduce_el_caudal_de_la_bomba():
    p = planta_estable()
    antes = p.paso()
    p.inyectar_falla("cavitacion")
    for _ in range(300):
        m = p.paso()
    caudal_por_velocidad_antes = antes.caudal_entrada / antes.velocidad
    caudal_por_velocidad_despues = m.caudal_entrada / m.velocidad
    assert caudal_por_velocidad_despues < 0.7 * caudal_por_velocidad_antes


def test_valvula_trabada_ignora_la_orden():
    p = planta_estable()
    p.inyectar_falla("valvula_trabada")
    q_antes = p.paso().caudal_salida
    p.fijar_apertura(10)
    for _ in range(60):
        m = p.paso()
    assert abs(m.caudal_salida - q_antes) < 3  # sigue saliendo casi lo mismo


def test_limpiar_fallas():
    p = planta_estable()
    p.inyectar_falla("deriva")
    p.fallas.limpiar()
    assert p.paso().fallas == []


def test_falla_desconocida():
    with pytest.raises(ValueError):
        planta_estable().inyectar_falla("terremoto")
