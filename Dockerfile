FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPSPILOT_CHECKPOINT_BACKEND=sqlite \
    OPSPILOT_TRACE_DIR=/data/trace_store \
    OPSPILOT_CHECKPOINT_PATH=/data/trace_store/checkpoints.sqlite \
    OPSPILOT_APPROVAL_QUEUE_PATH=/data/trace_store/pending_approvals.json

COPY pyproject.toml README.md LICENSE ./
COPY opspilot ./opspilot

RUN pip install --no-cache-dir -e .

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "opspilot.server:app", "--host", "0.0.0.0", "--port", "8000"]
