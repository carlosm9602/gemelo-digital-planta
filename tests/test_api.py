"""Prueba de humo de la API: arranca el gemelo sin Modbus y ejercita las rutas."""

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def cliente(monkeypatch, tmp_path):
    monkeypatch.setenv("MODBUS", "0")
    monkeypatch.setenv("OPCUA", "0")
    monkeypatch.setenv("VELOCIDAD_SIM", "20")
    monkeypatch.setenv("HISTORIADOR", str(tmp_path / "h.db"))
    from api.main import app

    with TestClient(app) as c:
        time.sleep(1.0)
        yield c


def test_estado_y_ordenes(cliente):
    assert cliente.get("/api/estado").json()["muestra"] is not None
    assert cliente.post("/api/setpoint", json={"valor": 2.5}).json()["setpoint"] == 2.5
    assert cliente.post("/api/valvula", json={"valor": 40}).json()["apertura"] == 40
    assert cliente.post("/api/setpoint", json={"valor": 9}).status_code == 422


def test_fallas(cliente):
    assert cliente.post("/api/fallas/deriva").json()["fallas"] == ["deriva"]
    assert cliente.post("/api/fallas/inexistente").status_code == 404
    assert cliente.delete("/api/fallas").json()["fallas"] == []


def test_websocket_entrega_historia_y_muestras(cliente):
    with cliente.websocket_connect("/ws") as ws:
        inicio = ws.receive_json()
        assert inicio["tipo"] == "inicio" and "fallas_disponibles" in inicio
        assert ws.receive_json()["tipo"] == "muestra"


def test_historico(cliente):
    time.sleep(1.5)
    assert len(cliente.get("/api/historico").json()) > 0
