"""Shared pytest fixtures. No real DB or network calls in unit/security tests --
external dependencies are faked at the port boundary per constraint matrix.
"""
import os

# Test-only defaults so Settings() can construct without a real .env file.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production-use-only")
