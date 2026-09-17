import os
import tempfile
import threading
import time
import urllib.request
import urllib.error


def _is_server_ready(url="http://127.0.0.1:8000/health"):
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def pytest_configure(config):
    if "DATABASE_URL" not in os.environ:
        directory = tempfile.TemporaryDirectory(prefix="ble-attendance-tests-")
        config._attendance_test_directory = directory
        os.environ["DATABASE_URL"] = "sqlite:///" + directory.name.replace("\\", "/") + "/attendance.db"

    if not _is_server_ready():
        try:
            import uvicorn
            from Backend.main import app
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="error"))
            t = threading.Thread(target=server.run, daemon=True)
            t.start()
            config._attendance_test_server = server
            for _ in range(50):
                if _is_server_ready():
                    break
                time.sleep(0.1)
        except Exception:
            pass


def pytest_unconfigure(config):
    server = getattr(config, "_attendance_test_server", None)
    if server is not None:
        server.should_exit = True
    directory = getattr(config, "_attendance_test_directory", None)
    if directory is not None:
        from Backend.database import engine
        engine.dispose()
        os.environ.pop("DATABASE_URL", None)
        directory.cleanup()
