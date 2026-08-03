"""Entry point: create app via factory, then run Flask."""

# Load .env before any app.* modules read env vars at import time.
# This is the ONLY place load_dotenv() should be called.
from app.factory import get_app

app = get_app()

if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
