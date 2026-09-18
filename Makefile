install:
	python -m pip install -r backend/requirements.txt

test:
	python -m pytest -q

run:
	uvicorn backend.main:app --reload
