# Pyharmonics GPT

## Quick Start

Start the app with gunicorn (recommended for production):

```bash
# Install dependencies
pip install -r requirements.txt

# Run with gunicorn using config
PORT=5000 gunicorn --config gunicorn.conf.py "app:get_app()"
```

Start development with Flask:

```bash
PORT=5000 python -m app.main
```

## Ports

- App: 5000 (gunicorn by default)
- TradingView Bridge: 5002

## Testing

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest
```
