"""Vercel Python Function entry point: serves every /api/* route with the existing stdlib handler."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server import Handler  # noqa: E402


class handler(Handler):
    """Vercel invokes this BaseHTTPRequestHandler subclass; credentials come from Vercel env vars."""
