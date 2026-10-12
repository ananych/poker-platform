FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY . .
RUN pip install --upgrade pip && pip install . \
    && useradd -m app && chown -R app /srv
USER app
EXPOSE 8000
# Single worker by design (SDD §8): per-room serialization is in-process.
# app/serve.py binds one dual-stack socket (IPv4 + IPv6) on $PORT (default 8000).
CMD ["sh", "-c", "alembic upgrade head && exec python -m app.serve"]
