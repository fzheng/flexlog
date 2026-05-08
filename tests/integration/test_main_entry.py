import pytest

import flexlog.__main__ as main_mod


def test_main_module_exposes_main_function():
    assert hasattr(main_mod, "main"), "__main__ must export main()"
    assert callable(main_mod.main)


def test_main_uses_loopback_host_and_default_port(monkeypatch, tmp_data_dir):
    captured = {}

    def fake_run(self, host, port, threaded, debug):
        captured["host"] = host
        captured["port"] = port
        captured["threaded"] = threaded
        captured["debug"] = debug

    monkeypatch.setattr("flask.Flask.run", fake_run, raising=True)
    main_mod.main()
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 5050
    assert captured["threaded"] is True


def test_main_respects_flexlog_port_env(monkeypatch, tmp_data_dir):
    captured = {}

    def fake_run(self, host, port, threaded, debug):
        captured["port"] = port

    monkeypatch.setattr("flask.Flask.run", fake_run, raising=True)
    monkeypatch.setenv("FLEXLOG_PORT", "6060")
    main_mod.main()
    assert captured["port"] == 6060


def test_main_rejects_invalid_port(monkeypatch, tmp_data_dir, capsys):
    monkeypatch.setenv("FLEXLOG_PORT", "not-a-number")
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert "FLEXLOG_PORT" in captured.err


def test_main_rejects_out_of_range_port(monkeypatch, tmp_data_dir, capsys):
    """A numeric port outside 1..65535 must trip the explicit `raise ValueError`."""
    monkeypatch.setenv("FLEXLOG_PORT", "0")
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code == 2
    assert "FLEXLOG_PORT" in capsys.readouterr().err


def test_main_rejects_port_above_max(monkeypatch, tmp_data_dir, capsys):
    monkeypatch.setenv("FLEXLOG_PORT", "70000")
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code == 2
    assert "FLEXLOG_PORT" in capsys.readouterr().err


def test_main_can_be_called_twice_without_state_pollution(monkeypatch, tmp_data_dir):
    """Calling main() twice must work — _configure_logging is idempotent."""
    captured = {"calls": 0}

    def fake_run(self, host, port, threaded, debug):
        captured["calls"] += 1

    monkeypatch.setattr("flask.Flask.run", fake_run, raising=True)
    main_mod.main()
    main_mod.main()
    assert captured["calls"] == 2
