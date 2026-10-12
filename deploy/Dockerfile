FROM python:3.12-slim-bookworm AS dependencies
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt
COPY worker worker
COPY contracts contracts
COPY tests tests
ENV PYTHONPATH=/deps PYTHONDONTWRITEBYTECODE=1
RUN python -m unittest discover -s tests -v
FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=dependencies /deps /deps
COPY --from=dependencies /build/worker worker
COPY --from=dependencies /build/contracts contracts
ENV PYTHONPATH=/deps PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
CMD ["python","-m","uvicorn","worker.transport:from_environment","--factory","--host","0.0.0.0","--port","8080","--timeout-keep-alive","5","--timeout-graceful-shutdown","20","--no-access-log"]
