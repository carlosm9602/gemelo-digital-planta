from planta.simulador import Planta, ma_desde_nivel


def test_estado_estable_en_el_setpoint():
    p = Planta(semilla=2)
    for _ in range(400):
        m = p.paso()
    assert abs(m.nivel_real - 2.0) < 0.05
    assert abs(m.caudal_entrada - m.caudal_salida) < 2.0


def test_sigue_un_cambio_de_setpoint():
    p = Planta(semilla=2)
    p.fijar_setpoint(2.8)
    for _ in range(600):
        m = p.paso()
    assert abs(m.nivel_real - 2.8) < 0.05


def test_modo_manual_mantiene_la_velocidad():
    p = Planta(semilla=2)
    p.fijar_modo("manual", velocidad_manual=30)
    for _ in range(100):
        m = p.paso()
    assert abs(m.velocidad - 30) < 0.5


def test_escala_4_20_ma():
    assert ma_desde_nivel(0) == 4.0
    assert ma_desde_nivel(4.0) == 20.0
    assert ma_desde_nivel(2.0) == 12.0
