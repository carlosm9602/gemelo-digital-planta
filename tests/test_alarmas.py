from planta.alarmas import Alarma, Estado, GestorAlarmas


def gestor():
    return GestorAlarmas(
        [Alarma("LAH", "Nivel alto", "nivel", 3.0, True, "media", banda_muerta=0.1, retardo=3)]
    )


def muestra(t, nivel):
    return {"t": t, "nivel": nivel}


def test_retardo_evita_disparos_por_ruido():
    g = gestor()
    assert g.evaluar(muestra(0, 3.5)) == []
    assert g.evaluar(muestra(1, 2.0)) == []  # vuelve antes del retardo
    assert not g.alguna_activa()


def test_ciclo_de_vida_isa_18_2():
    g = gestor()
    for t in range(3):
        eventos = g.evaluar(muestra(t, 3.5))
    assert eventos[0].tipo == "activada"
    assert g.alarmas["LAH"].estado == Estado.ACTIVA_NO_RECONOCIDA
    g.reconocer("LAH", 4)
    assert g.alarmas["LAH"].estado == Estado.ACTIVA_RECONOCIDA
    # dentro de la banda muerta no se normaliza
    g.evaluar(muestra(5, 2.95))
    assert g.alarmas["LAH"].activa
    g.evaluar(muestra(6, 2.5))
    assert g.alarmas["LAH"].estado == Estado.NORMAL


def test_normalizada_sin_reconocer():
    g = gestor()
    for t in range(3):
        g.evaluar(muestra(t, 3.5))
    g.evaluar(muestra(4, 2.0))
    assert g.alarmas["LAH"].estado == Estado.NORMALIZADA_NO_RECONOCIDA
    g.reconocer("LAH", 5)
    assert g.alarmas["LAH"].estado == Estado.NORMAL


def test_bits_para_modbus():
    g = gestor()
    for t in range(3):
        g.evaluar(muestra(t, 3.5))
    assert g.bits() == 1
