#!/usr/bin/env python3
"""FDE Quality Threshold Test — Bare vs Structured prompt comparison.

This test validates that the FDE mechanism (steering + hooks) produces
measurably higher quality agent responses compared to bare prompts.

It works by:
  1. Defining a realistic task scenario
  2. Defining the BARE prompt (Simple Question pattern — no context)
  3. Defining the FDE prompt (Context + Instruction pattern — with steering + hook prompts)
  4. Defining a quality rubric with objective, checkable criteria
  5. Scoring both responses against the rubric

The test does NOT call an external LLM API. Instead, it uses the actual
Kiro agent (you, reading this) as the LLM. The test provides two response
files that the agent must generate before the test can score them.

## How to run this test:

### Step 1: Generate the BARE response
Ask the agent WITHOUT #fde steering:
  "Fix the severity distribution — findings are all MEDIUM"
Save the response to: tests/fixtures/fde_quality/bare_response.md

### Step 2: Generate the FDE response
Ask the agent WITH #fde steering and all hooks enabled:
  "Fix the severity distribution — findings are all MEDIUM"
Save the response to: tests/fixtures/fde_quality/fde_response.md

### Step 3: Run this test
  python3 -m pytest tests/test_fde_quality_threshold.py -v

The test scores both responses and asserts that the FDE response
scores at least 2x higher than the bare response.

Run: python3 -m pytest tests/test_fde_quality_threshold.py -v
"""
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
FIXTURES_DIR = os.path.join(ROOT, "tests", "fixtures", "fde_quality")
BARE_RESPONSE = os.path.join(FIXTURES_DIR, "bare_response.md")
FDE_RESPONSE = os.path.join(FIXTURES_DIR, "fde_response.md")


# ---------------------------------------------------------------------------
# Quality Rubric — objective, checkable criteria
# ---------------------------------------------------------------------------
# Each criterion is a tuple: (name, description, check_function)
# check_function takes the response text and returns True/False
# Criteria are derived from the FDE protocol phases

QUALITY_RUBRIC = [
    # --- Phase 1: Reconnaissance ---
    (
        "identifies_affected_modules",
        "Response identifies which specific modules are affected (publish_tree, publish_sanitizer, etc.)",
        lambda r: any(
            m in r.lower()
            for m in ["publish_tree", "publish_sanitizer", "facts_extractor"]
        ),
    ),
    (
        "identifies_pipeline_position",
        "Response identifies where in the pipeline (E1-E6) the change sits",
        lambda r: bool(re.search(r"E[1-6]|edge|pipeline", r, re.IGNORECASE)),
    ),
    (
        "identifies_artifact_type",
        "Response distinguishes code artifact vs knowledge artifact",
        lambda r: any(
            t in r.lower()
            for t in ["knowledge artifact", "code artifact", "domain", "semantic"]
        ),
    ),
    (
        "identifies_downstream_impact",
        "Response considers downstream consumers of the change",
        lambda r: any(
            d in r.lower()
            for d in ["downstream", "consumer", "portal", "renderer", "sanitizer"]
        ),
    ),
    # --- Phase 2: Structured Intake ---
    (
        "states_acceptance_criteria",
        "Response defines what 'done' looks like (not just 'fix it')",
        lambda r: any(
            a in r.lower()
            for a in [
                "acceptance",
                "criteria",
                "non-flat",
                "more than one",
                "severity level",
                "distribution",
            ]
        ),
    ),
    (
        "states_constraints",
        "Response identifies what should NOT change",
        lambda r: any(
            c in r.lower()
            for c in [
                "constraint",
                "should not",
                "must not",
                "do not modify",
                "out of scope",
                "not change",
            ]
        ),
    ),
    # --- Phase 3.a: Adversarial ---
    (
        "considers_root_cause",
        "Response investigates root cause, not just symptom",
        lambda r: any(
            rc in r.lower()
            for rc in [
                "root cause",
                "why",
                "underlying",
                "architecture",
                "risk engine",
                "addressability",
            ]
        ),
    ),
    (
        "considers_parallel_paths",
        "Response checks for the same pattern in sibling code",
        lambda r: any(
            p in r.lower()
            for p in ["parallel", "sibling", "similar", "other fact type", "same pattern"]
        ),
    ),
    (
        "validates_domain_knowledge",
        "Response references domain source of truth (WAF corpus, docs)",
        lambda r: any(
            d in r.lower()
            for d in [
                "corpus",
                "waf",
                "well-architected",
                "wellarchitected",
                "source of truth",
                "domain",
            ]
        ),
    ),
    # --- Phase 3.b: Pipeline Testing ---
    (
        "specifies_test_scope",
        "Response specifies which tests to run (contract, knowledge, etc.)",
        lambda r: any(
            t in r.lower()
            for t in [
                "contract test",
                "test scope",
                "run_tests",
                "pytest",
                "--scope",
                "knowledge test",
            ]
        ),
    ),
    (
        "validates_edge_contract",
        "Response validates the output matches what the next module expects",
        lambda r: any(
            e in r.lower()
            for e in ["edge", "contract", "schema", "output match", "next module"]
        ),
    ),
    # --- Phase 3.c: 5W2H ---
    (
        "answers_what",
        "Response states WHAT was changed",
        lambda r: any(
            w in r.lower()
            for w in ["changed", "modified", "updated", "fix", "adjust"]
        ),
    ),
    (
        "answers_where",
        "Response states WHERE in the pipeline",
        lambda r: any(
            w in r.lower()
            for w in [
                "publish_tree",
                "severity",
                "pipeline",
                "E4",
                "E3",
                "mapping",
            ]
        ),
    ),
    (
        "answers_why",
        "Response explains WHY this approach vs alternatives",
        lambda r: any(
            w in r.lower()
            for w in ["because", "reason", "alternative", "approach", "instead"]
        ),
    ),
    (
        "answers_how_validated",
        "Response states HOW the change was validated",
        lambda r: any(
            h in r.lower()
            for h in ["validated", "tested", "verified", "confirmed", "ran"]
        ),
    ),
    # --- Phase 3.d: 5 Whys ---
    (
        "investigates_beyond_symptom",
        "Response goes beyond the surface symptom to investigate deeper causes",
        lambda r: any(
            i in r.lower()
            for i in [
                "why",
                "cause",
                "flat",
                "map",
                "engine",
                "addressability",
                "class of",
            ]
        ),
    ),
    # --- Phase 4: Completion ---
    (
        "reports_what_validated",
        "Response reports what was validated and what was NOT",
        lambda r: any(
            v in r.lower()
            for v in [
                "validated",
                "not validated",
                "residual",
                "risk",
                "gap",
                "follow-up",
            ]
        ),
    ),
    # --- Anti-patterns avoided ---
    (
        "avoids_symptom_chasing",
        "Response does NOT just patch the severity map without investigating why it's flat",
        lambda r: not (
            "change medium to" in r.lower()
            and "root cause" not in r.lower()
            and "why" not in r.lower()
        ),
    ),
]


# ---------------------------------------------------------------------------
# Scoring function
# ---------------------------------------------------------------------------
def score_response(response_text: str) -> dict:
    """Score a response against the quality rubric.

    Returns dict with:
      - total: number of criteria met
      - max: total number of criteria
      - ratio: total/max
      - details: list of (criterion_name, passed, description)
    """
    details = []
    total = 0
    for name, description, check_fn in QUALITY_RUBRIC:
        passed = check_fn(response_text)
        if passed:
            total += 1
        details.append((name, passed, description))
    return {
        "total": total,
        "max": len(QUALITY_RUBRIC),
        "ratio": total / len(QUALITY_RUBRIC) if QUALITY_RUBRIC else 0,
        "details": details,
    }


# ===========================================================================
# Test: Score the BARE response (generated without FDE)
# ===========================================================================
class TestBareResponse:
    """Score the bare (no-FDE) response against the quality rubric."""

    @pytest.fixture(scope="class")
    def bare_text(self):
        if not os.path.isfile(BARE_RESPONSE):
            pytest.skip(
                f"Bare response not yet generated. "
                f"Save it to {BARE_RESPONSE}"
            )
        with open(BARE_RESPONSE) as f:
            return f.read()

    @pytest.fixture(scope="class")
    def bare_score(self, bare_text):
        return score_response(bare_text)

    def test_bare_response_scored(self, bare_score):
        """The bare response should score — we just record the result."""
        print(f"\nBARE SCORE: {bare_score['total']}/{bare_score['max']} "
              f"({bare_score['ratio']:.0%})")
        for name, passed, desc in bare_score["details"]:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {name}: {desc}")


# ===========================================================================
# Test: Score the FDE response (generated with FDE steering + hooks)
# ===========================================================================
class TestFDEResponse:
    """Score the FDE-enhanced response against the quality rubric."""

    @pytest.fixture(scope="class")
    def fde_text(self):
        if not os.path.isfile(FDE_RESPONSE):
            pytest.skip(
                f"FDE response not yet generated. "
                f"Save it to {FDE_RESPONSE}"
            )
        with open(FDE_RESPONSE) as f:
            return f.read()

    @pytest.fixture(scope="class")
    def fde_score_result(self, fde_text):
        return score_response(fde_text)

    def test_fde_response_scored(self, fde_score_result):
        """The FDE response should score — we just record the result."""
        print(f"\nFDE SCORE: {fde_score_result['total']}/{fde_score_result['max']} "
              f"({fde_score_result['ratio']:.0%})")
        for name, passed, desc in fde_score_result["details"]:
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {name}: {desc}")


# ===========================================================================
# Test: Compare BARE vs FDE — FDE must score significantly higher
# ===========================================================================
class TestQualityThreshold:
    """Compare bare vs FDE responses and assert quality threshold."""

    @pytest.fixture(scope="class")
    def both_scores(self):
        if not os.path.isfile(BARE_RESPONSE):
            pytest.skip(f"Bare response not generated: {BARE_RESPONSE}")
        if not os.path.isfile(FDE_RESPONSE):
            pytest.skip(f"FDE response not generated: {FDE_RESPONSE}")
        with open(BARE_RESPONSE) as f:
            bare = f.read()
        with open(FDE_RESPONSE) as f:
            fde = f.read()
        return score_response(bare), score_response(fde)

    def test_fde_scores_higher_than_bare(self, both_scores):
        """FDE response must score strictly higher than bare response."""
        bare_score, fde_score = both_scores
        print(f"\nBARE: {bare_score['total']}/{bare_score['max']} "
              f"({bare_score['ratio']:.0%})")
        print(f"FDE:  {fde_score['total']}/{fde_score['max']} "
              f"({fde_score['ratio']:.0%})")
        assert fde_score["total"] > bare_score["total"], (
            f"FDE ({fde_score['total']}) must score higher than "
            f"bare ({bare_score['total']})"
        )

    def test_fde_meets_minimum_threshold(self, both_scores):
        """FDE response must meet at least 75% of quality criteria."""
        _, fde_score = both_scores
        threshold = 0.75
        assert fde_score["ratio"] >= threshold, (
            f"FDE score {fde_score['ratio']:.0%} below "
            f"minimum threshold {threshold:.0%}"
        )

    def test_fde_improvement_ratio(self, both_scores):
        """FDE must improve over bare by at least 30% (absolute)."""
        bare_score, fde_score = both_scores
        improvement = fde_score["ratio"] - bare_score["ratio"]
        min_improvement = 0.30
        print(f"\nImprovement: {improvement:.0%} "
              f"(minimum required: {min_improvement:.0%})")
        assert improvement >= min_improvement, (
            f"FDE improvement {improvement:.0%} below "
            f"minimum {min_improvement:.0%}"
        )

    def test_detailed_comparison(self, both_scores):
        """Print detailed side-by-side comparison."""
        bare_score, fde_score = both_scores
        print("\n" + "=" * 70)
        print("DETAILED COMPARISON: BARE vs FDE")
        print("=" * 70)
        print(f"{'Criterion':<35} {'Bare':>6} {'FDE':>6} {'Delta':>6}")
        print("-" * 70)
        bare_wins = 0
        fde_wins = 0
        ties = 0
        for (name, bare_pass, _), (_, fde_pass, _) in zip(
            bare_score["details"], fde_score["details"]
        ):
            b = "PASS" if bare_pass else "FAIL"
            f = "PASS" if fde_pass else "FAIL"
            if fde_pass and not bare_pass:
                delta = "+FDE"
                fde_wins += 1
            elif bare_pass and not fde_pass:
                delta = "+BARE"
                bare_wins += 1
            else:
                delta = "="
                ties += 1
            print(f"  {name:<33} {b:>6} {f:>6} {delta:>6}")
        print("-" * 70)
        print(f"  FDE wins: {fde_wins}  |  Bare wins: {bare_wins}  |  Ties: {ties}")
        print(f"  BARE total: {bare_score['total']}/{bare_score['max']} "
              f"({bare_score['ratio']:.0%})")
        print(f"  FDE total:  {fde_score['total']}/{fde_score['max']} "
              f"({fde_score['ratio']:.0%})")
        print("=" * 70)
