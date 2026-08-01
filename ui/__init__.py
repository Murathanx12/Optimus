"""Optimus brain viewer — a read-only, localhost-only visualization surface.

This package is a *view* over the brain. It reads through core.store.Store
(opened read_only=True) and core.audit; it has no write path and makes no
network calls. See ui/README.md for the launch command and guarantees.
"""
