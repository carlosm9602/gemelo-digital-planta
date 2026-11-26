# Cómo contribuir a Gemelo Digital de Planta con Detección de Fallas

Gracias por el interés. Para que el trabajo sea fácil de revisar:

1. Abre primero un *issue* contando el error o la mejora.
2. Haz un *fork* y crea una rama desde `main`: `git checkout -b feat/nombre-corto`.
3. Usa mensajes de commit con el formato [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/):
   `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
4. Asegúrate de que las pruebas pasen en local:

   ```bash
   pip install -e .[dev]
   ruff check .
   pytest -v
   ```

5. Abre el *pull request* describiendo qué cambia y cómo probarlo.

## Estilo de código

- Python: formato y lint con `ruff`, tipado donde aporte claridad, docstrings en español.
- Nombres de variables y funciones descriptivos; nada de credenciales en el código (usa `.env`).
