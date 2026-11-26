FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[opcua]"

COPY web ./web
# entrena el detector en la construcción para que el contenedor arranque listo
RUN python -m analitica.entrenar --horas 3

EXPOSE 8000 5020 4840
CMD ["uvicorn", "api.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
