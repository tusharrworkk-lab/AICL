FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY acil acil
COPY alembic.ini .
COPY migrations migrations
RUN pip install --no-cache-dir .
CMD ["uvicorn", "acil.main:app", "--host", "0.0.0.0", "--port", "8000"]
