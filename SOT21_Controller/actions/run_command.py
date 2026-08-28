"""Whitelisted command execution (AUTOMATION group).

The browser sends a *key*; the key is looked up in config.json. An arbitrary
command string from the tablet is never executed — there is no code path that
takes one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from . import ActionError, Result, action


def resolve(ctx, key: str) -> dict[str, Any]:
    """Look a command key up in config.json and normalise it to a dict."""
    commands = ctx.config.get("commands", {})
    entry = commands.get(key)
    if entry is None:
        raise ActionError(f"config.json に登録されていない処理です: {key}")
    if isinstance(entry, str):            # short form: "key": "C:\\path\\x.bat"
        entry = {"program": entry}
    if not isinstance(entry, dict) or not entry.get("program"):
        raise ActionError(f"commands.{key} の書式が不正です")
    return entry


def _absolute(ctx, value: str) -> str:
    """Relative paths in config.json resolve against the project directory."""
    path = Path(value)
    if path.is_absolute() or not (ctx.base_dir / path).exists():
        return str(path)
    return str((ctx.base_dir / path).resolve())


def build_argv(ctx, entry: dict[str, Any]) -> list[str]:
    program = _absolute(ctx, str(entry["program"]))
    argv = [program] + [_absolute(ctx, str(a)) for a in entry.get("args", [])]
    if program.lower().endswith(".bat") or program.lower().endswith(".cmd"):
        # cmd.exe is required to run a batch file, and /c keeps it non-interactive.
        argv = ["cmd", "/c"] + argv
    return argv


def execute(ctx, key: str) -> Result:
    entry = resolve(ctx, key)
    argv = build_argv(ctx, entry)
    label = entry.get("label", key)
    cwd = entry.get("cwd")
    if cwd:
        cwd = _absolute(ctx, str(cwd))
    program = argv[2] if argv[0] == "cmd" else argv[0]
    if not Path(program).exists() and "/" not in program and "\\" not in program:
        pass  # a bare name like "python" is resolved from PATH
    elif not Path(program).exists():
        raise ActionError(f"実行ファイルが見つかりません: {program}")

    if not entry.get("wait"):
        try:
            subprocess.Popen(argv, cwd=cwd)
        except OSError as exc:
            raise ActionError(f"起動に失敗しました: {exc}") from exc
        return Result(True, f"{label} を起動しました", " ".join(argv))

    timeout = int(entry.get("timeout", 60))
    try:
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                   timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ActionError(f"{label} がタイムアウトしました ({timeout}s)") from None
    except OSError as exc:
        raise ActionError(f"起動に失敗しました: {exc}") from exc

    output = (completed.stdout or "") + (completed.stderr or "")
    output = output.strip()[:2000]
    if completed.returncode != 0:
        raise ActionError(f"{label} が異常終了しました (code {completed.returncode})\n"
                          + output)
    return Result(True, f"{label} 完了", output or "(出力なし)",
                  {"returncode": completed.returncode})


@action("run_python", "Python処理実行", "AUTOMATION", params={"command": "test_python"})
def run_python(ctx, params: dict[str, Any]) -> Result:
    return execute(ctx, params.get("command", "test_python"))


@action("run_bat", "BAT実行", "AUTOMATION", params={"command": "test_bat"})
def run_bat(ctx, params: dict[str, Any]) -> Result:
    return execute(ctx, params.get("command", "test_bat"))


@action("run_shortfactory", "ShortFACTORY実行", "AUTOMATION",
        params={"command": "shortfactory"}, confirm=True)
def run_shortfactory(ctx, params: dict[str, Any]) -> Result:
    return execute(ctx, params.get("command", "shortfactory"))
