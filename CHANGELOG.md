# Changelog

Todos los cambios importantes de este proyecto se registran aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [0.1.0] - 2026-11-30

### Añadido
- Simulador de proceso de nivel con balance de masa, bomba con variador, válvula con actuador y ruido de instrumentos.
- PID con anti-windup y transferencia sin salto entre manual y automático.
- Inyección de cuatro fallas: sensor de nivel pegado, deriva del transmisor, cavitación de la bomba y válvula trabada.
- Alarmas por umbral con ciclo de vida ISA-18.2, banda muerta y retardo.
- Detector de anomalías con residuos físicos, Isolation Forest y límite por residuo, con diagnóstico por reglas.
- Evaluación reproducible del detector contra las alarmas (`python -m analitica.evaluar`) y cuaderno con el caso de deriva.
- Servidor Modbus TCP (lectura y escritura de consignas) y servidor OPC UA opcional.
- API FastAPI con WebSocket, historiador SQLite y tablero web estilo ISA-101.
- Docker Compose, 26 pruebas con pytest y CI en GitHub Actions.
