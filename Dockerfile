# One image for all three Python services. docker-compose.yml picks the command:
#   api        uvicorn app.api.main:app ...
#   worker     python -m app.worker.main
#   dashboard  streamlit run dashboard/review_app.py ...
# One image = one build, one set of library versions, no drift between services.

FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE: no .pyc files in the container
# PYTHONUNBUFFERED: print/log lines appear immediately in `docker compose logs`
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1 = OpenMP runtime. XGBoost needs it on Linux; the slim image doesn't include it.
# Without it the worker crashes with "libgomp.so.1: cannot open shared object file".
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements FIRST and install: Docker caches this layer, so changing your code
# later does not reinstall every library (builds go from minutes to seconds).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Then the code (changes often -> last).
COPY alembic.ini pyproject.toml ./
COPY alembic/ alembic/
COPY app/ app/
COPY scripts/ scripts/
COPY dashboard/ dashboard/
COPY artifacts_meta/ artifacts_meta/

# Never run as root inside a container: if the app is compromised, the attacker is not root.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000 8001 8501

# Default command = the API. The worker and dashboard override it in docker-compose.yml.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]