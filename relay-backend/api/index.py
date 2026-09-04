"""Vercel entrypoint. Vercel's Python builder detects the `app` ASGI
callable in files under api/ and wraps it as a serverless function — this
file just re-exports the real FastAPI app, no separate logic lives here.
"""

from app.main import app  # noqa: F401
