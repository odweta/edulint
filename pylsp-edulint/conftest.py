def pytest_configure(config):
    config.addinivalue_line("markers", "worker: starts the warm EduLint worker process (slow)")
