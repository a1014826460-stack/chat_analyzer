FROM python:3.12-slim

WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server_api ./server_api
COPY alembic.ini .
COPY alembic ./alembic
CMD ["uvicorn", "server_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
