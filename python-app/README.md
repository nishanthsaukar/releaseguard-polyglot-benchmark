# Python Task Manager

## Run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: `http://127.0.0.1:8000/docs`

Tests:

```bash
pytest -q
```
