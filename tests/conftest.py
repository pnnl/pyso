import pytest

def pytest_addoption(parser):
        parser.addoption(
             "--run-local", action="store_true", default=False, help="Run tests requiring local data"
        )

def pytest_collection_modifyitems(config, items):

    if not config.getoption("--run-local"):
        skip_local = pytest.mark.skip(reason="need --run-local option to run")
        for item in items:
            if "local" in item.keywords:
                item.add_marker(skip_local)
