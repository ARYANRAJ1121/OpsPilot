# OpsPilot — common developer commands ($0 locally)

.PHONY: install test lint doctor serve smoke eval docker-build

install:
	pip install -e ".[dev]"

test:
	OPSPILOT_CHECKPOINT_BACKEND=memory pytest tests/ -q --tb=short

lint:
	ruff check opspilot tests

doctor:
	opspilot doctor

smoke:
	opspilot smoke-slack
	opspilot smoke-webhooks

eval:
	opspilot eval

serve:
	uvicorn opspilot.server:app --host 0.0.0.0 --port 8000 --reload

docker-build:
	docker build -t opspilot:1.0.1 .
