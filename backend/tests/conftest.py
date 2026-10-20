import os
from pathlib import Path
from tempfile import TemporaryDirectory


_test_runtime = TemporaryDirectory(
    prefix="personal-options-trader-tests-",
    dir=Path(__file__).resolve().parent,
)
_test_root = Path(_test_runtime.name)
os.environ["DATABASE_URL"] = f"sqlite:///{(_test_root / 'test.db').as_posix()}"
os.environ["DATA_DIR"] = str(_test_root / "OptionsTraderData")


def pytest_sessionfinish(session, exitstatus):
    # Close SQLite handles before TemporaryDirectory removes its database on Windows.
    from app.database import engine

    engine.dispose()
    _test_runtime.cleanup()
