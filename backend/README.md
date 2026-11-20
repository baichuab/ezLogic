# ezLogic Backend

FastAPI backend for the ezLogic proof verification platform.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file from the example:
```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

3. Run the development server:
```bash
python main.py
```

The API will be available at `http://localhost:8000`

## API Endpoints

- `GET /health` - Health check
- `POST /api/prove` - Generate and verify a Lean proof
- `POST /api/verify` - Verify a Lean proof

## Project Structure

- `main.py` - FastAPI application entry point
- `config.py` - Configuration management
- `requirements.txt` - Python dependencies
- `.env.example` - Environment variables template
- `proofs/` - Local file system for Lean proofs (created on startup)

## Documentation

Interactive API documentation available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
