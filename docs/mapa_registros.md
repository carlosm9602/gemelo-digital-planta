# Mapa de registros Modbus TCP

Servidor en el puerto **5020** (no el 502, para no pedir permisos de administrador), unidad/esclavo **1**. Direcciones base 0: el registro 0 es el 30001 o 40001 en notación clásica.

Todos los valores son enteros sin signo de 16 bits, escalados como indica la tabla.

## Input registers (función 04, solo lectura)

| Dirección | Clásica | Tag | Variable | Escala | Ejemplo |
|---|---|---|---|---|---|
| 0 | 30001 | LT-101 | Nivel medido | mm | 2000 = 2,000 m |
| 1 | 30002 | LT-101 | Señal del transmisor | µA (4000-20000) | 12000 = 12 mA |
| 2 | 30003 | FT-101 | Caudal de entrada | L/s × 100 | 4012 = 40,12 L/s |
| 3 | 30004 | FT-102 | Caudal de salida | L/s × 100 | |
| 4 | 30005 | SC-101 | Velocidad de la bomba | % × 10 | 503 = 50,3 % |
| 5 | 30006 | IT-101 | Corriente del motor | A × 100 | 458 = 4,58 A |
| 6 | 30007 | PT-102 | Presión de descarga | kPa × 10 | 1151 = 115,1 kPa |
| 7 | 30008 | — | Puntaje del detector | × 1000 | 374 = 0,374 |
| 8 | 30009 | — | Anomalía detectada | 0 / 1 | |
| 9 | 30010 | — | Alarmas activas | bit i = alarma i | ver abajo |
| 10 | 30011 | — | Fallas inyectadas (solo simulación) | bit i = falla i | ver abajo |

Bits de alarmas (registro 9): 0 LAHH-101, 1 LAH-101, 2 LAL-101, 3 LALL-101, 4 PAL-102.

Bits de fallas (registro 10): 0 sensor_pegado, 1 deriva, 2 cavitacion, 3 valvula_trabada.

## Holding registers (funciones 03 / 06 / 16, lectura y escritura)

| Dirección | Clásica | Variable | Escala | Rango |
|---|---|---|---|---|
| 0 | 40001 | Setpoint de nivel LIC-101 | mm | 200-3800 |
| 1 | 40002 | Apertura de la válvula FV-102 | % × 10 | 0-1000 |
| 2 | 40003 | Modo del lazo | 0 = automático, 1 = manual | |
| 3 | 40004 | Velocidad en manual | % × 10 | 0-1000 |

El gemelo lee los holding registers en cada ciclo (cada 0,5 s). Si un cliente externo los cambia, la planta obedece y queda un evento "Consignas cambiadas por un cliente Modbus" en el historiador. Si el cambio se hace desde el tablero web, el servidor actualiza los registros para que el HMI externo vea lo mismo.

## Probarlo

Con cualquier cliente Modbus (Modbus Poll, QModMaster, Node-RED, un PLC o un HMI) apuntando a `IP_del_equipo:5020`, o desde Python:

```python
from pymodbus.client import ModbusTcpClient

c = ModbusTcpClient("localhost", port=5020)
c.connect()
print(c.read_input_registers(0, count=11).registers)
c.write_register(0, 2500)  # setpoint a 2,5 m
c.close()
```

## OPC UA

Con `OPCUA=1` (activo en Docker) también se publica un servidor en `opc.tcp://localhost:4840/gemelo/`, espacio de nombres `urn:gemelo-digital-planta`, objeto `Planta`, con las variables `LT-101.PV`, `FT-101.PV`, `FT-102.PV`, `SC-101.PV`, `IT-101.PV`, `PT-102.PV`, `LIC-101.SP` y `Detector.Anomalia`. Se puede explorar con UaExpert.
