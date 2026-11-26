from planta.pid import PID


def test_lleva_la_variable_al_setpoint():
    # proceso integrador simple: dy/dt = 0.01 * (u - 50)
    pid, y = PID(kp=5, ki=0.5), 0.0
    for _ in range(4000):
        u = pid.calcular(10.0, y, 0.1)
        y += 0.01 * (u - 50) * 0.1
    assert abs(y - 10.0) < 0.05


def test_respeta_los_limites_de_salida():
    pid = PID(kp=100, ki=10, salida_min=0, salida_max=100)
    assert pid.calcular(10, 0, 0.5) == 100
    assert pid.calcular(0, 10, 0.5) == 0


def test_anti_windup_no_acumula_integral_saturado():
    pid = PID(kp=1, ki=1, salida_max=100)
    for _ in range(1000):
        pid.calcular(1000, 0, 1.0)  # saturado arriba mucho tiempo
    # al invertirse el error la salida debe bajar de inmediato, sin arrastrar integral
    assert pid.calcular(0, 10, 1.0) < 100


def test_transferencia_sin_salto():
    pid = PID(kp=40, ki=2)
    pid.inicializar(salida_actual=63.0, setpoint=2.0, medicion=2.0)
    assert abs(pid.calcular(2.0, 2.0, 0.5) - 63.0) < 1e-9
