# syntax=docker/dockerfile:1.6
FROM python:3.14-slim AS base

# System deps for sqlite-vec, pypdf, sops, age
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libffi-dev \
      libssl-dev \
      ca-certificates \
      curl \
      gnupg \
      sqlite3 \
      age \
      tini \
    && rm -rf /var/lib/apt/lists/*

# Install sops
RUN curl -fsSL -o /tmp/sops.deb \
      https://github.com/getsops/sops/releases/download/v3.9.1/sops_3.9.1_amd64.deb \
    && dpkg -i /tmp/sops.deb \
    && rm /tmp/sops.deb

FROM base AS app

# Non-root user
RUN useradd -m -u 10001 -s /bin/bash bot
WORKDIR /app

# Python deps first, for layer caching
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Alembic config + migration scripts — needed so `alembic upgrade head`
# works inside the container at first deploy and after schema changes.
COPY alembic.ini ./
COPY migrations/ ./migrations/

# Entrypoint decrypts sops secrets if present, then exec's the command
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Wrap the pip-installed botctl so `docker compose exec bot botctl ...`
# routes through the entrypoint (sops decrypt + export) instead of
# bypassing it. Without this, botctl inherits whatever env_file the
# compose file sets — which has empty/commented secret fields that
# pydantic's int validator rejects.
RUN mv /usr/local/bin/botctl /usr/local/bin/_botctl.real \
 && printf '#!/bin/sh\nexec /entrypoint.sh /usr/local/bin/_botctl.real "$@"\n' > /usr/local/bin/botctl \
 && chmod +x /usr/local/bin/botctl

USER bot
VOLUME ["/data"]
ENV DONNA_ENV=prod \
    DONNA_DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
CMD ["python", "-m", "donna.main"]
