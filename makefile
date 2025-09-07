PY ?= python3
VENV ?= .venv
VENV_BIN := $(VENV)/bin

.PHONY: tunnel venv install run stop tunnelnt frontend


run:
	$(VENV_BIN)/python -m uvicorn main:app --host 0.0.0.0 --port 8000

stop:
	-pkill -f "uvicorn .*main:app" 2>/dev/null || true
	-pkill -f "event_handler.py" 2>/dev/null || true
	@echo "Stopped server if it was running."

venv:
	@echo "To activate: source $(VENV_BIN)/activate"


tunnel:
	nohup cloudflared tunnel run >/dev/null 2>&1 &

tunnelnt:
	-pkill -f "cloudflared tunnel run" 2>/dev/null || pkill cloudflared 2>/dev/null || true
	@echo "Stopped cloudflared if it was running."


install:
	@if [ ! -x "$(VENV_BIN)/python" ]; then \
		echo "Creating venv at $(VENV)..."; \
		$(PY) -m venv $(VENV); \
	fi
	@$(VENV_BIN)/python -m pip install --upgrade pip
	@if [ -f requirements.txt ]; then \
		$(VENV_BIN)/python -m pip install -r requirements.txt; \
	else \
		$(VENV_BIN)/python -m pip install websockets; \
	fi





