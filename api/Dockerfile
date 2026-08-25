# syntax=docker/dockerfile:1
#
# The ODBC driver is the reason this is not python:3.12-slim with a pip install.
# `mssql+aioodbc://` resolves the driver through unixODBC at connection time, so
# it has to exist in the image; the SQLAlchemy URL naming it is not enough.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Microsoft ODBC Driver 18 + unixODBC. ACCEPT_EULA is required by the package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
       | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] \
https://packages.microsoft.com/debian/12/prod bookworm main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
    && apt-get purge -y gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies resolve from pyproject alone, so this layer is cached until the
# dependency list itself changes — not on every source edit.
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./

# A non-root runtime user: the container writes nothing outside /tmp, and object
# storage is reached over the network.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# The container's own health signal. Azure App Service and Container Apps both
# probe an HTTP path; this makes `docker run` agree with them.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"

# One worker by default. Scale out with replicas rather than workers so the
# pipeline poller's Redis lock is the only thing arbitrating duplicate ticks —
# see api/app/services/pipeline_poller.py.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
