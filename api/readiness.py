"""Vercel entrypoint for the same live checks used by the local app."""
from app import Handler, IntegrityCheck


_integrity = IntegrityCheck()


class handler(Handler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, integrity=_integrity, **kwargs)
