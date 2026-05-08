"""Database engine + session factory for flexlog.

Models live in flexlog.db.models. The engine is created from
flexlog.paths.db_path() at app-factory time; session lifecycle is
request-scoped via Flask's `g` object and the teardown handler.
"""
