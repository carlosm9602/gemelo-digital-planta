from analitica.evaluar import correr_escenario, falsos_positivos


def test_no_hay_falsas_alarmas_en_operacion_normal(detector):
    episodios, _ = falsos_positivos(detector, horas=1.0, semilla=77)
    assert episodios == 0


def test_detecta_cavitacion_antes_que_cualquier_alarma(detector):
    c = correr_escenario(detector, "cavitacion", semilla=5)
    assert c.t_detector is not None and c.t_detector < 30
    assert c.t_alarma is None or c.t_detector < c.t_alarma
    assert c.diagnostico == "bomba"


def test_detecta_deriva_que_las_alarmas_no_ven(detector):
    c = correr_escenario(detector, "deriva", semilla=6)
    assert c.t_detector is not None
    assert c.diagnostico == "transmisor_nivel"


def test_detecta_valvula_trabada(detector):
    c = correr_escenario(detector, "valvula_trabada", semilla=7)
    assert c.t_detector is not None
    assert c.diagnostico == "valvula"
