"""Config file I/O: TOML round-trip, path, and permission bits.

No real network/backend — pure filesystem behavior against a temp dir.
"""

from __future__ import annotations

import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def config_module(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDCTL_CONFIG_DIR", str(tmp_path / "groundctl"))
    # config.py reads the env var at import time, so force a fresh import.
    for name in list(sys.modules):
        if name.startswith("groundctl_cli"):
            del sys.modules[name]
    from groundctl_cli import config

    return config


def test_load_config_missing_file_returns_empty(config_module):
    cfg = config_module.load_config()
    assert cfg.api_url is None
    assert cfg.refresh_token is None
    assert cfg.is_logged_in is False


def test_save_and_load_round_trip(config_module):
    cfg = config_module.Config(api_url="https://groundctl.example.com", refresh_token="abc123")
    config_module.save_config(cfg)

    loaded = config_module.load_config()
    assert loaded.api_url == "https://groundctl.example.com"
    assert loaded.refresh_token == "abc123"
    assert loaded.is_logged_in is True


def test_config_dir_created_0700(config_module):
    config_module.save_config(config_module.Config(api_url="https://x", refresh_token="y"))
    mode = stat.S_IMODE(os.stat(config_module.CONFIG_DIR).st_mode)
    assert mode == 0o700


def test_config_file_written_0600(config_module):
    config_module.save_config(config_module.Config(api_url="https://x", refresh_token="y"))
    mode = stat.S_IMODE(os.stat(config_module.CONFIG_FILE).st_mode)
    assert mode == 0o600


def test_special_characters_round_trip(config_module):
    # Quotes/backslashes must survive a save/load cycle without corrupting
    # the TOML or leaking into a syntax error.
    tricky = 'has "quotes" and \\backslash\\ and unicode: café'
    cfg = config_module.Config(api_url="https://x", refresh_token=tricky)
    config_module.save_config(cfg)
    loaded = config_module.load_config()
    assert loaded.refresh_token == tricky


def test_clear_config_removes_file(config_module):
    config_module.save_config(config_module.Config(api_url="https://x", refresh_token="y"))
    assert config_module.CONFIG_FILE.exists()
    config_module.clear_config()
    assert not config_module.CONFIG_FILE.exists()


def test_clear_config_missing_file_is_noop(config_module):
    config_module.clear_config()  # must not raise
