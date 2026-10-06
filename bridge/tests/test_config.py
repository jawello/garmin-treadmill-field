import pytest

from treadmill_bridge.config import Config, State, load_config


def test_load_defaults_and_values(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('api_token = "abc"\nhold_speed_during_start = true\n')
    config = load_config(str(path))
    assert config == Config(api_token="abc", hold_speed_during_start=True)
    assert config.api_port == 8080 and config.treadmill_address is None


def test_rejects_unknown_keys_and_missing_token(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('api_token = "x"\ntypo = 1\n')
    with pytest.raises(ValueError, match="typo"):
        load_config(str(bad))
    empty = tmp_path / "empty.toml"
    empty.write_text("")
    with pytest.raises(ValueError, match="api_token"):
        load_config(str(empty))


def test_state_persists_address(tmp_path):
    state = State(str(tmp_path / "state.json"))
    assert state.treadmill_address is None
    state.save_address("57:4C:4D:2F:0C:93/P")
    assert State(str(tmp_path / "state.json")).treadmill_address == "57:4C:4D:2F:0C:93/P"


def test_treadmill_stays_on_radio_a_unless_asked(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('api_token = "abc"\n')
    assert load_config(str(path)).treadmill_on_usb_radio is False
    path.write_text('api_token = "abc"\ntreadmill_on_usb_radio = true\n')
    assert load_config(str(path)).treadmill_on_usb_radio is True
