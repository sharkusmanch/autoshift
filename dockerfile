FROM python:3.10-slim

WORKDIR /autoshift
COPY . /autoshift/
RUN pip install --upgrade pip && \
    pip install -r requirements.txt && \
    mkdir -p /autoshift/data

# Entrypoint uses env vars, so all CLI args are optional
CMD ["python", "auto.py"]