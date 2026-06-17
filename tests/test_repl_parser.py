from __future__ import annotations


def test_parse_help_command():
    from src.app.repl_parser import parse_command

    command = parse_command("help")

    assert command.name == "help"
    assert command.args == []


def test_parse_run_stage_command():
    from src.app.repl_parser import parse_command

    command = parse_command("run stage pipeline")

    assert command.name == "run"
    assert command.args == ["stage", "pipeline"]


def test_parse_set_vlm_command():
    from src.app.repl_parser import parse_command

    command = parse_command("set vlm on")

    assert command.name == "set"
    assert command.args == ["vlm", "on"]


def test_parse_set_gpu_command():
    from src.app.repl_parser import parse_command

    command = parse_command("set gpu 1")

    assert command.name == "set"
    assert command.args == ["gpu", "1"]


def test_parse_quit_alias_maps_to_exit():
    from src.app.repl_parser import parse_command

    command = parse_command("quit")

    assert command.name == "exit"


def test_parse_unknown_command_raises():
    from src.app.repl_parser import CommandParseError, parse_command

    try:
        parse_command("fly away")
    except CommandParseError as exc:
        assert "unknown command" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected parse error")
