.PHONY: test compile run-api run-ui compose-up compose-down

test:
	python -m pytest -q

compile:
	python -m compileall -q app tests

run-api:
	uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

run-ui:
	streamlit run app/ui/streamlit_app.py --server.address 127.0.0.1 --server.port 8501

compose-up:
	docker compose up --build

compose-down:
	docker compose down
