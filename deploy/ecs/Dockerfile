FROM python:3.12-alpine

WORKDIR /app

# boto3 is the only dep — SQS send + SSM read. We pin a known-stable version
# so the agent image is reproducible; bump in CI when AWS APIs we use evolve.
RUN pip install --no-cache-dir 'boto3==1.35.*'

COPY ecs_probe.py /app/ecs_probe.py

# Run as non-root since the agent does no privileged operations.
RUN adduser -D -u 10001 probe
USER probe

ENTRYPOINT ["python3", "/app/ecs_probe.py"]
