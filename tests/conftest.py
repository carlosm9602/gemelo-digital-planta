"""Fixtures compartidas: un detector entrenado una sola vez por sesión de pruebas."""

import pytest

from analitica.entrenar import entrenar


@pytest.fixture(scope="session")
def detector():
    return entrenar(horas=1.5, semilla=3)
