"""Shared pytest fixtures."""
import pytest
from app import create_app


@pytest.fixture
def app():
    """Create application with testing configuration."""
    application = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
    return application


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
