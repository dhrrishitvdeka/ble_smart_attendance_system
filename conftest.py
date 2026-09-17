import os
import tempfile


def pytest_configure(config):
    if "DATABASE_URL" not in os.environ:
        directory = tempfile.TemporaryDirectory(prefix="ble-attendance-tests-")
        config._attendance_test_directory = directory
        os.environ["DATABASE_URL"] = "sqlite:///" + directory.name.replace("\\", "/") + "/attendance.db"


def pytest_unconfigure(config):
    directory = getattr(config, "_attendance_test_directory", None)
    if directory is not None:
        from Backend.database import engine
        engine.dispose()
        os.environ.pop("DATABASE_URL", None)
        directory.cleanup()
