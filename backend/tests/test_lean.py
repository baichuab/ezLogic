"""Tests for the pure (no real Lean process needed) parts of agent/lean.py."""

from agent.lean import _without_imports


def test_leaves_plain_code_untouched():
    code = "example : 2 + 2 = 4 := by norm_num"
    assert _without_imports(code) == code


def test_blanks_a_leading_import():
    code = "import Mathlib\nexample : 2 + 2 = 4 := by norm_num"
    assert _without_imports(code) == "\nexample : 2 + 2 = 4 := by norm_num"


def test_blanks_an_import_after_a_line_comment():
    # The bug this guards against: Lean rejects `import` anywhere once a command
    # runs inside an existing environment, even right after a leading comment --
    # not just outside a leading block of import/blank lines.
    code = "-- a comment first\nimport Mathlib\nexample : 2 + 2 = 4 := by norm_num"
    out = _without_imports(code)
    assert "import" not in out
    assert out == "-- a comment first\n\nexample : 2 + 2 = 4 := by norm_num"


def test_blanks_an_import_after_a_block_comment():
    code = "/- comment -/\nimport Mathlib\nexample : 2 + 2 = 4 := by norm_num"
    out = _without_imports(code)
    assert "import" not in out
    assert out.count("\n") == code.count("\n")  # line numbers are preserved


def test_blanks_multiple_imports_anywhere_in_the_snippet():
    code = "import Mathlib.Data.Nat.Basic\nexample : True := trivial\nimport Mathlib.Data.Int.Basic\n"
    out = _without_imports(code)
    assert "import" not in out
    assert "example : True := trivial" in out


def test_preserves_line_numbers_so_error_positions_still_match():
    code = "-- note\nimport Mathlib\n\nexample : False := by\n  sorry"
    out = _without_imports(code)
    assert out.splitlines()[3] == code.splitlines()[3]  # the `example` line is unmoved


def test_does_not_touch_import_appearing_mid_identifier_or_string():
    # Only a line that *starts* (ignoring leading whitespace) with `import ` is
    # treated as an import statement.
    code = 'example : "this imports nothing" = "this imports nothing" := rfl'
    assert _without_imports(code) == code
