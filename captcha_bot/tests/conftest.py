import pytest


# Make all async tests use asyncio automatically
def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")
