"""Read Lean's pretty-printed goal states.

A goal state looks like

    case succ
    a b : Nat
    h : a ≤
      b
    ⊢ a + 1 ≤ b + 1

with several goals separated by blank lines. Continuation lines are indented.
"""


def split_goals(goals: str) -> list[str]:
    return [g for g in goals.split("\n\n") if g.strip()]


def case_tag(goals: str) -> str:
    """The case tag of the first goal (`succ` for `case succ`), or "" if it has none."""
    parts = split_goals(goals)
    if parts and parts[0].startswith("case "):
        return parts[0].split("\n", 1)[0][len("case ") :].strip()
    return ""


def continues(earlier_tag: str, later_tag: str) -> bool:
    """Whether a goal tagged `later_tag` can descend from one tagged `earlier_tag`. Goals in
    different branches (`zero` vs `succ`, `left` vs `right`) cannot."""
    return earlier_tag == "" or later_tag == earlier_tag or later_tag.startswith(earlier_tag + ".")


def hypothesis_names(goals: str) -> set[str]:
    """Names of the hypotheses in the first (main) goal. Inaccessible names (`h✝`) are skipped."""
    parts = split_goals(goals)
    if not parts:
        return set()
    names: set[str] = set()
    for line in parts[0].split("\n"):
        if line.startswith("⊢"):
            break
        if not line or line[0].isspace() or line.startswith("case "):
            continue
        head, sep, _ = line.partition(" : ")
        if not sep:
            continue
        names.update(n for n in head.split() if "✝" not in n)
    return names
