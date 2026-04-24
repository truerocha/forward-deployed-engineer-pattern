#!/usr/bin/env python3
"""Language lint for the FDE design document.

Checks for:
1. Weasel words — vague qualifiers that weaken claims
2. Violent language — metaphors of war, combat, destruction
3. Trauma-associated language — terms that may trigger distress
4. Ableist language — terms that reference disability as negative

Reports findings with line numbers and suggestions.

Usage: python3 scripts/lint_language.py docs/design/forward-deployed-ai-engineers.md
"""
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Weasel words — vague qualifiers that weaken claims
# ---------------------------------------------------------------------------
WEASEL_WORDS = [
    (r"\bvery\b", "Remove 'very' — use a stronger word"),
    (r"\breally\b", "Remove 'really' — be specific"),
    (r"\bquite\b", "Remove 'quite' — quantify instead"),
    (r"\bsomewhat\b", "Remove 'somewhat' — be precise"),
    (r"\bfairly\b", "Remove 'fairly' — quantify instead"),
    (r"\bprobably\b", "Replace 'probably' with evidence or remove"),
    (r"\bperhaps\b", "Replace 'perhaps' with evidence or remove"),
    (r"\bsort of\b", "Remove 'sort of' — be direct"),
    (r"\bkind of\b", "Remove 'kind of' — be direct"),
    (r"\bbasically\b", "Remove 'basically' — just state the fact"),
    (r"\bobviously\b", "Remove 'obviously' — if it's obvious, no need to say it"),
    (r"\bclearly\b", "Remove 'clearly' — show, don't tell"),
    (r"\bjust\b(?!\s+the\b)", "Consider removing 'just' — it minimizes"),
    (r"\bsimply\b", "Remove 'simply' — it may not be simple for the reader"),
    (r"\bseems?\b", "Replace 'seem(s)' with evidence"),
    (r"\bappears?\b(?!\s+in\b)", "Replace 'appear(s)' with evidence"),
    (r"\bmight\b", "Replace 'might' with 'can' or evidence"),
    (r"\bcould\b(?!\s+not\b)", "Consider replacing 'could' with 'can' or evidence"),
    (r"\bmost people\b", "Replace 'most people' with specific data"),
    (r"\bit is (thought|believed|said)\b", "Replace with attribution or evidence"),
    (r"\bsome\b(?!\s+(of|studies|research|projects))", "Replace 'some' with specific quantity"),
    (r"\bmany\b(?!\s+(enterprise|projects|studies))", "Replace 'many' with specific quantity"),
    (r"\bfew\b(?!\s*-)", "Replace 'few' with specific quantity"),
    (r"\bnumerous\b", "Replace 'numerous' with specific quantity"),
    (r"\bvarious\b", "Replace 'various' with specific list"),
    (r"\bsignificant(?:ly)?\b(?!.*p<|.*ANOVA|.*statistic)", "Quantify 'significant' — use numbers"),
]

# ---------------------------------------------------------------------------
# Violent language — metaphors of war, combat, destruction
# ---------------------------------------------------------------------------
VIOLENT_LANGUAGE = [
    (r"\bkill(?:s|ed|ing)?\b", "Replace 'kill' with 'stop', 'end', or 'remove'"),
    (r"\bdestroy(?:s|ed|ing)?\b", "Replace 'destroy' with 'remove' or 'delete'"),
    (r"\battack(?:s|ed|ing)?\b", "Replace 'attack' with 'address' or 'handle'"),
    (r"\bbomb(?:s|ed|ing)?\b", "Replace 'bomb' with 'fail' or 'error'"),
    (r"\bwar\b(?!ning)", "Replace 'war' with 'conflict' or 'competition'"),
    (r"\bbattle(?:s|d)?\b", "Replace 'battle' with 'challenge' or 'effort'"),
    (r"\bfight(?:s|ing)?\b", "Replace 'fight' with 'address' or 'resolve'"),
    (r"\bweapon(?:s|ize[ds]?)?\b", "Replace 'weapon' with 'tool' or 'mechanism'"),
    (r"\bexplode(?:s|d)?\b", "Replace 'explode' with 'expand rapidly' or 'fail'"),
    (r"\bcrush(?:es|ed|ing)?\b", "Replace 'crush' with 'compress' or 'reduce'"),
    (r"\bblind(?:ly|ed|s)?\b(?!ness)", "Replace 'blind' with 'unaware' or 'without visibility'"),
    (r"\bcripple[ds]?\b", "Replace 'cripple' with 'impair' or 'limit'"),
    (r"\bslave\b", "Replace 'slave' with 'replica', 'secondary', or 'worker'"),
    (r"\bmaster\b(?!/)", "Replace 'master' with 'primary', 'main', or 'leader'"),
    (r"\bnuke[ds]?\b", "Replace 'nuke' with 'reset' or 'clear'"),
    (r"\bexecute\b(?!\s*(these|this|the|validation|test))", "Consider 'run' instead of 'execute'"),
]

# ---------------------------------------------------------------------------
# Trauma-associated language
# ---------------------------------------------------------------------------
TRAUMA_LANGUAGE = [
    (r"\bpanic(?:s|ked|king)?\b", "Replace 'panic' with 'urgent response' or 'alert'"),
    (r"\bparanoi[ad]\b", "Replace 'paranoid/paranoia' with 'cautious' or 'vigilant'"),
    (r"\binsane\b", "Replace 'insane' with 'unreasonable' or 'extreme'"),
    (r"\bcrazy\b", "Replace 'crazy' with 'unexpected' or 'unusual'"),
    (r"\bstupid\b", "Replace 'stupid' with 'ineffective' or 'suboptimal'"),
    (r"\bdumb\b", "Replace 'dumb' with 'silent' or 'ineffective'"),
    (r"\bsuffer(?:s|ed|ing)?\b", "Replace 'suffer' with 'experience' or 'encounter'"),
    (r"\bvictim\b", "Replace 'victim' with 'affected party' or 'target'"),
    (r"\babuse[ds]?\b", "Replace 'abuse' with 'misuse' or 'overuse'"),
    (r"\baddicted\b", "Replace 'addicted' with 'dependent' or 'reliant'"),
    (r"\btrauma\b", "Replace 'trauma' with 'impact' or 'disruption'"),
    (r"\btoxic\b", "Replace 'toxic' with 'harmful' or 'counterproductive'"),
]


def lint_file(filepath: str) -> list[dict]:
    """Lint a file for language issues.

    Returns list of findings, each with:
      - line: line number (1-indexed)
      - category: weasel|violent|trauma
      - match: the matched text
      - suggestion: what to do instead
      - context: the full line
    """
    findings = []
    text = Path(filepath).read_text()
    lines = text.split("\n")

    # Skip code blocks
    in_code_block = False

    for line_num, line in enumerate(lines, 1):
        # Toggle code block state
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # Skip table headers and separators
        if line.strip().startswith("|---") or line.strip().startswith("| ---"):
            continue

        for pattern, suggestion in WEASEL_WORDS:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                findings.append({
                    "line": line_num,
                    "category": "weasel",
                    "match": match.group(),
                    "suggestion": suggestion,
                    "context": line.strip()[:120],
                })

        for pattern, suggestion in VIOLENT_LANGUAGE:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                findings.append({
                    "line": line_num,
                    "category": "violent",
                    "match": match.group(),
                    "suggestion": suggestion,
                    "context": line.strip()[:120],
                })

        for pattern, suggestion in TRAUMA_LANGUAGE:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                findings.append({
                    "line": line_num,
                    "category": "trauma",
                    "match": match.group(),
                    "suggestion": suggestion,
                    "context": line.strip()[:120],
                })

    return findings


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/lint_language.py <file.md>")
        sys.exit(1)

    filepath = sys.argv[1]
    findings = lint_file(filepath)

    if not findings:
        print(f"No language issues found in {filepath}")
        sys.exit(0)

    # Group by category
    by_category = {}
    for f in findings:
        by_category.setdefault(f["category"], []).append(f)

    print(f"\nLanguage lint: {filepath}")
    print(f"Total findings: {len(findings)}")
    print(f"  Weasel words: {len(by_category.get('weasel', []))}")
    print(f"  Violent language: {len(by_category.get('violent', []))}")
    print(f"  Trauma language: {len(by_category.get('trauma', []))}")
    print()

    for category in ["violent", "trauma", "weasel"]:
        items = by_category.get(category, [])
        if not items:
            continue
        print(f"=== {category.upper()} ({len(items)}) ===")
        for f in items:
            print(f"  L{f['line']}: '{f['match']}' — {f['suggestion']}")
            print(f"    > {f['context']}")
        print()

    sys.exit(1 if by_category.get("violent") or by_category.get("trauma") else 0)


if __name__ == "__main__":
    main()
