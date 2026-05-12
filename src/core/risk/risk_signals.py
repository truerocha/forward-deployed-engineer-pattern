"""
Risk Signal Extractor — Extracts normalized risk signals from task context.

Each signal is a value in [0, 1] representing the intensity of a risk factor.
Signals are extracted from:
  1. Historical failure data (DynamoDB DORA metrics + failure_modes)
  2. Code complexity (onboarding catalog / data contract)
  3. DORA trend analysis (rolling window metrics)
  4. Organism complexity classification

Source: PEC Blueprint Chapter 1 (Contextual Encoder)
  "Converts a PR into a multi-dimensional vector. It maps code changes
   against the Knowledge Graph of the system (dependencies, historical
   bug hotspots, and developer expertise)."

Integration:
  - Reads from DORACollector (dora_metrics.py) for historical data
  - Reads from data_contract for task-specific signals
  - Reads from onboarding catalog (S3) for repo-level signals
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("fde.risk.signals")


@dataclass
class RiskSignals:
    """Normalized risk signal vector.

    All values are in [0, 1] where:
      0.0 = no risk contribution from this signal
      1.0 = maximum risk contribution from this signal

    The inference engine multiplies each signal by its weight
    and passes through sigmoid to produce the final risk score.
    """

    # Historical failure signals
    historical_cfr: float = 0.0            # Change Failure Rate (0=0%, 1=100%)
    failure_recurrence: float = 0.0        # Same failure mode recurring (0=never, 1=3+ times)
    repo_hotspot: float = 0.0             # Target files are in failure hotspots (0=cold, 1=hot)

    # Complexity signals
    file_count: float = 0.0               # Normalized file count (0=1 file, 1=15+ files)
    cyclomatic_complexity: float = 0.0    # Avg complexity of targets (0=simple, 1=very complex)
    dependency_depth: float = 0.0         # Dependency chain depth (0=leaf, 1=deep core)
    cross_module: float = 0.0             # Cross-module changes (0=single module, 1=3+ modules)

    # DORA trend signals
    lead_time_trend: float = 0.0          # Lead time increasing (0=stable/decreasing, 1=rapidly increasing)
    deployment_frequency: float = 0.0     # Deploy frequency (0=low/stagnant, 1=high/healthy)

    # Organism complexity
    organism_level: float = 0.0           # Task complexity (0=O1 trivial, 1=O5 novel)

    # Protective signals (higher = LESS risk)
    test_coverage: float = 0.0            # Test coverage of target area (0=none, 1=full)
    prior_success: float = 0.0            # Same task type succeeded before (0=never, 1=always)
    catalog_confidence: float = 0.0       # Onboarding catalog confidence (0=low, 1=high)

    def to_vector(self) -> list[float]:
        """Convert to ordered vector for matrix operations."""
        return [
            self.historical_cfr,
            self.failure_recurrence,
            self.repo_hotspot,
            self.file_count,
            self.cyclomatic_complexity,
            self.dependency_depth,
            self.cross_module,
            self.lead_time_trend,
            self.deployment_frequency,
            self.organism_level,
            self.test_coverage,
            self.prior_success,
            self.catalog_confidence,
        ]

    def to_dict(self) -> dict[str, float]:
        """Serialize for observability and persistence."""
        return {
            "historical_cfr": self.historical_cfr,
            "failure_recurrence": self.failure_recurrence,
            "repo_hotspot": self.repo_hotspot,
            "file_count": self.file_count,
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "dependency_depth": self.dependency_depth,
            "cross_module": self.cross_module,
            "lead_time_trend": self.lead_time_trend,
            "deployment_frequency": self.deployment_frequency,
            "organism_level": self.organism_level,
            "test_coverage": self.test_coverage,
            "prior_success": self.prior_success,
            "catalog_confidence": self.catalog_confidence,
        }


class RiskSignalExtractor:
    """Extracts normalized risk signals from task context and historical data.

    This is the "Contextual Encoder" from the PEC Blueprint — it transforms
    raw task metadata into a normalized signal vector that the inference
    engine can score.

    Usage:
        extractor = RiskSignalExtractor()
        signals = extractor.extract(
            data_contract={"repo": "my-service", "type": "feature", ...},
            dora_metrics={"change_failure_rate": {"failure_rate_pct": 8.5}},
            failure_history=[{"code": "FM-06", ...}],
            catalog_metadata={"confidence": 0.85, "complexity_avg": 12},
        )
    """

    def __init__(self, history_window_days: int = 30):
        self._history_window_days = history_window_days

    def extract(
        self,
        data_contract: dict[str, Any],
        dora_metrics: dict[str, Any] | None = None,
        failure_history: list[dict[str, Any]] | None = None,
        catalog_metadata: dict[str, Any] | None = None,
    ) -> RiskSignals:
        """Extract all risk signals from available context.

        Args:
            data_contract: The canonical task data contract (from Router).
            dora_metrics: Recent DORA metrics summary (from DORACollector).
            failure_history: Recent failure mode classifications for this repo.
            catalog_metadata: Onboarding catalog data for the target repo.

        Returns:
            RiskSignals with all values normalized to [0, 1].
        """
        dora = dora_metrics or {}
        failures = failure_history or []
        catalog = catalog_metadata or {}

        signals = RiskSignals(
            # Historical
            historical_cfr=self._extract_cfr(dora),
            failure_recurrence=self._extract_failure_recurrence(failures, data_contract),
            repo_hotspot=self._extract_hotspot(failures, data_contract),

            # Complexity
            file_count=self._extract_file_count(data_contract),
            cyclomatic_complexity=self._extract_complexity(catalog, data_contract),
            dependency_depth=self._extract_dependency_depth(catalog),
            cross_module=self._extract_cross_module(data_contract),

            # DORA trends
            lead_time_trend=self._extract_lead_time_trend(dora),
            deployment_frequency=self._extract_deploy_frequency(dora),

            # Organism
            organism_level=self._extract_organism_level(data_contract),

            # Protective
            test_coverage=self._extract_test_coverage(catalog),
            prior_success=self._extract_prior_success(failures, data_contract),
            catalog_confidence=self._extract_catalog_confidence(catalog),
        )

        logger.debug("Risk signals extracted: %s", signals.to_dict())
        return signals

    # ─── Historical Signal Extractors ───────────────────────────

    def _extract_cfr(self, dora: dict[str, Any]) -> float:
        """Extract Change Failure Rate signal.

        Maps CFR percentage to [0, 1]:
          0% -> 0.0, 5% -> 0.25, 15% -> 0.75, 20%+ -> 1.0
        """
        cfr_data = dora.get("change_failure_rate", {})
        cfr_pct = cfr_data.get("failure_rate_pct", 0.0)
        return min(1.0, cfr_pct / 20.0)

    def _extract_failure_recurrence(
        self, failures: list[dict], data_contract: dict,
    ) -> float:
        """Extract failure recurrence signal.

        Checks if the same failure mode has occurred recently for similar tasks.
        0 occurrences -> 0.0, 1 -> 0.33, 2 -> 0.67, 3+ -> 1.0
        """
        task_type = data_contract.get("type", "")
        repo = data_contract.get("repo", "")

        matching = sum(
            1 for f in failures
            if f.get("task_type") == task_type or f.get("repo") == repo
        )
        return min(1.0, matching / 3.0)

    def _extract_hotspot(
        self, failures: list[dict], data_contract: dict,
    ) -> float:
        """Extract repo hotspot signal.

        Checks if target files/modules have been involved in recent failures.
        """
        target_files = set(data_contract.get("target_files", []))
        if not target_files:
            return 0.0

        hotspot_hits = 0
        for failure in failures:
            failed_files = set(failure.get("files_involved", []))
            if target_files & failed_files:
                hotspot_hits += 1

        return min(1.0, hotspot_hits / 3.0)

    # ─── Complexity Signal Extractors ───────────────────────────

    def _extract_file_count(self, data_contract: dict) -> float:
        """Extract file count signal.

        1 file -> 0.0, 5 files -> 0.33, 10 files -> 0.67, 15+ -> 1.0
        """
        file_count = data_contract.get("estimated_files", 1)
        if isinstance(file_count, str):
            file_count = {"few": 3, "several": 7, "many": 12}.get(file_count, 5)
        return min(1.0, max(0.0, (file_count - 1) / 14.0))

    def _extract_complexity(
        self, catalog: dict, data_contract: dict,
    ) -> float:
        """Extract cyclomatic complexity signal.

        Uses catalog's average complexity for target modules.
        Complexity 1-5 -> 0.0-0.25, 5-15 -> 0.25-0.75, 15+ -> 0.75-1.0
        """
        avg_complexity = catalog.get("complexity_avg", 0)
        if not avg_complexity:
            type_complexity = {
                "bugfix": 8, "feature": 12, "refactor": 15,
                "security": 10, "infrastructure": 7,
            }
            avg_complexity = type_complexity.get(data_contract.get("type", ""), 10)

        return min(1.0, max(0.0, avg_complexity / 20.0))

    def _extract_dependency_depth(self, catalog: dict) -> float:
        """Extract dependency depth signal.

        Depth 0-1 -> 0.0, 2-3 -> 0.33-0.5, 4-5 -> 0.67-0.83, 6+ -> 1.0
        """
        depth = catalog.get("max_dependency_depth", 0)
        return min(1.0, max(0.0, depth / 6.0))

    def _extract_cross_module(self, data_contract: dict) -> float:
        """Extract cross-module change signal.

        1 module -> 0.0, 2 modules -> 0.5, 3+ modules -> 1.0
        """
        modules = data_contract.get("affected_modules", [])
        if isinstance(modules, list):
            count = len(modules)
        else:
            count = 1
        return min(1.0, max(0.0, (count - 1) / 2.0))

    # ─── DORA Trend Extractors ──────────────────────────────────

    def _extract_lead_time_trend(self, dora: dict) -> float:
        """Extract lead time trend signal.

        Compares recent lead time to historical average.
        Stable/decreasing -> 0.0, 50% increase -> 0.5, 100%+ increase -> 1.0
        """
        lead_time_data = dora.get("dora_metrics", {}).get("lead_time_avg_ms", 0)
        historical_avg = dora.get("historical_lead_time_avg_ms", lead_time_data)

        if not historical_avg or historical_avg == 0:
            return 0.0

        ratio = lead_time_data / historical_avg
        if ratio <= 1.0:
            return 0.0
        return min(1.0, (ratio - 1.0))

    def _extract_deploy_frequency(self, dora: dict) -> float:
        """Extract deployment frequency signal (PROTECTIVE).

        High frequency = healthy team = lower risk.
        >1/day -> 1.0 (protective), <0.1/day -> 0.0 (not protective)
        """
        deploy_data = dora.get("dora_metrics", {}).get("deployment_frequency", {})
        deploys_per_day = deploy_data.get("deploys_per_day", 0.0)
        return min(1.0, max(0.0, deploys_per_day))

    # ─── Organism Level Extractor ───────────────────────────────

    def _extract_organism_level(self, data_contract: dict) -> float:
        """Extract organism complexity level signal.

        O1 -> 0.0, O2 -> 0.25, O3 -> 0.5, O4 -> 0.75, O5 -> 1.0
        """
        organism = data_contract.get("organism_level", "O3")
        if isinstance(organism, str):
            level_map = {"O1": 0.0, "O2": 0.25, "O3": 0.5, "O4": 0.75, "O5": 1.0}
            return level_map.get(organism, 0.5)
        if isinstance(organism, (int, float)):
            return min(1.0, max(0.0, (organism - 1) / 4.0))
        return 0.5

    # ─── Protective Signal Extractors ───────────────────────────

    def _extract_test_coverage(self, catalog: dict) -> float:
        """Extract test coverage signal (PROTECTIVE).

        0% coverage -> 0.0, 50% -> 0.5, 80%+ -> 0.8-1.0
        """
        coverage = catalog.get("test_coverage_pct", 0)
        return min(1.0, max(0.0, coverage / 100.0))

    def _extract_prior_success(
        self, failures: list[dict], data_contract: dict,
    ) -> float:
        """Extract prior success signal (PROTECTIVE).

        Checks if similar tasks have succeeded recently.
        All failures -> 0.0, mixed -> 0.5, all successes -> 1.0
        """
        task_type = data_contract.get("type", "")
        repo = data_contract.get("repo", "")

        matching_failures = sum(
            1 for f in failures
            if f.get("task_type") == task_type or f.get("repo") == repo
        )

        return max(0.0, 1.0 - (matching_failures / 3.0))

    def _extract_catalog_confidence(self, catalog: dict) -> float:
        """Extract catalog confidence signal (PROTECTIVE).

        How well the onboarding agent understood this repo.
        0.0 = no catalog, 1.0 = high confidence catalog available
        """
        confidence = catalog.get("confidence", 0.0)
        return min(1.0, max(0.0, float(confidence)))
