FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY checkpoint/ ./checkpoint/
COPY examples/ ./examples/

RUN pip install --no-cache-dir .

CMD ["python", "examples/demo_agent.py"]
