"""Test bootstrap: put the project on sys.path and build throwaway apps."""

import json
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

import app as controller  # noqa: E402


def make_config(**overrides):
    config = controller.load_config(BASE / "config.json")
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return config


def make_app(config=None, log_dir=None):
    config = config if config is not None else make_config()
    log_dir = Path(log_dir or tempfile.mkdtemp())
    log_path = log_dir / "controller.log"
    app = controller.create_app(config, log_path)
    app.testing = True
    return app, log_path
