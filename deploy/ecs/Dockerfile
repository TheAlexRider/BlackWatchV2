FROM python:3.12-alpine

WORKDIR /app

# Probe agent uses only stdlib HTTP + sockets — no pip installs needed.
COPY ecs_probe.py /app/ecs_probe.py

# Run as non-root since the agent does no privileged operations.
RUN adduser -D -u 10001 probe
USER probe

ENTRYPOINT ["python3", "/app/ecs_probe.py"]
