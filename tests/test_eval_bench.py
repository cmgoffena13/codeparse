import pytest

from eval.bench import parse_args, selected_arms


def test_parse_args_defaults_to_every_arm() -> None:
    args = parse_args([])
    assert args.tasks is None
    assert args.arm is None
    assert selected_arms(args.arm) == ("baseline", "codeparse")


def test_parse_args_selects_one_task_and_codeparse() -> None:
    args = parse_args(["--tasks", "search-dialect-transpilation", "--arm", "codeparse"])
    assert args.tasks == ["search-dialect-transpilation"]
    assert selected_arms(args.arm) == ("codeparse",)


def test_parse_args_rejects_an_unknown_arm() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--arm", "both"])
