"""
Onboarding Pipeline — Orchestrates all stages sequentially.

Design ref: §2.3 Information Flow, §4 Execution Modes
"""

import logging
import os
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .trigger_handler import TriggerContext, handle_trigger, parse_eventbridge_event
from .repo_cloner import clone_repository, get_current_sha
from .file_scanner import scan_files, FileRecord
from .ast_extractor import extract_ast, ExtractionResult
from .convention_detector import detect_conventions
from .pattern_inferrer import infer_patterns, build_dependency_summary
from .catalog_writer import write_catalog
from .steering_generator import generate_steering
from .s3_persister import persist_to_s3, persist_failure_report
from .ephemeral_persister import persist_ephemeral
from .observability import ObservabilityEmitter, OnboardingFailureReport

logger = logging.getLogger("fde-onboarding.pipeline")

ALL_STAGES = [
    "trigger_handler",
    "repo_cloner",
    "file_scanner",
    "ast_extractor",
    "convention_detector",
    "pattern_inferrer",
    "catalog_writer",
    "steering_generator",
    "s3_persister",
]


def run_pipeline(
    repo_url: Optional[str] = None,
    clone_depth: int = 1,
    force_full_scan: bool = False,
    correlation_id: Optional[str] = None,
    environment: str = "dev",
    artifacts_bucket: Optional[str] = None,
    aws_region: str = "us-east-1",
    catalog_mode: Optional[str] = None,
    ephemeral_volume_path: Optional[str] = None,
    ephemeral_ttl_hours: int = 24,
    ephemeral_encryption_key_arn: Optional[str] = None,
    ephemeral_audit_endpoint: Optional[str] = None,
) -> dict:
    """
    Execute the full onboarding pipeline.

    Args:
        repo_url: Repository URL (None for local mode).
        clone_depth: Git clone depth.
        force_full_scan: Skip incremental check.
        correlation_id: Optional correlation ID override.
        environment: Deployment environment.
        artifacts_bucket: S3 bucket for artifacts (cloud mode).
        aws_region: AWS region.

    Returns:
        Dict with pipeline results and metadata.
    """
    # --- Stage: Trigger Handler ---
    ctx = handle_trigger(
        repo_url=repo_url,
        clone_depth=clone_depth,
        force_full_scan=force_full_scan,
        correlation_id=correlation_id,
    )

    emitter = ObservabilityEmitter(
        correlation_id=ctx.correlation_id,
        mode=ctx.mode,
        repo_owner=ctx.repo_owner,
        repo_name=ctx.repo_name,
        environment=environment,
    )

    metrics = emitter.emit_stage_start("trigger_handler")
    metrics.complete()
    emitter.emit_stage_complete(metrics)

    # Early exit: incremental skip
    if ctx.skip_scan:
        logger.info("Incremental skip: catalog is up-to-date (correlation=%s)", ctx.correlation_id)
        emitter.emit_pipeline_complete()
        return {
            "status": "skipped",
            "reason": "catalog_up_to_date",
            "correlation_id": ctx.correlation_id,
            "mode": ctx.mode,
        }

    # Track partial results for failure reporting
    partial_results: dict = {}

    try:
        # --- Stage: Repo Cloner (cloud mode only) ---
        commit_sha = "unknown"
        if ctx.mode == "cloud" and ctx.repo_url:
            metrics = emitter.emit_stage_start("repo_cloner")
            try:
                clone_result = clone_repository(
                    repo_url=ctx.repo_url,
                    workspace_path=ctx.workspace_path,
                    clone_depth=ctx.clone_depth,
                    environment=environment,
                    aws_region=aws_region,
                )
                commit_sha = clone_result.commit_sha
                metrics.extra["repo_size_bytes"] = clone_result.repo_size_bytes
            finally:
                emitter.emit_stage_complete(metrics)
        else:
            commit_sha = get_current_sha(ctx.workspace_path)

        # --- Stage: File Scanner ---
        metrics = emitter.emit_stage_start("file_scanner")
        try:
            scan_result = scan_files(ctx.workspace_path)
            metrics.files_processed = scan_result.total_files_scanned
            metrics.errors_count = len(scan_result.errors)
            partial_results["files_scanned"] = scan_result.total_files_scanned
        finally:
            emitter.emit_stage_complete(metrics)

        # --- Stage: AST Extractor ---
        metrics = emitter.emit_stage_start("ast_extractor")
        try:
            source_files = [
                f.path for f in scan_result.files
                if not f.is_generated and f.language != "unknown"
            ]
            extraction_result = extract_ast(ctx.workspace_path, source_files)
            metrics.modules_found = extraction_result.total_modules
            metrics.edges_found = extraction_result.total_edges
            metrics.errors_count = extraction_result.parse_errors
            partial_results["modules_extracted"] = extraction_result.total_modules
            partial_results["edges_found"] = extraction_result.total_edges
        finally:
            emitter.emit_stage_complete(metrics)

        # --- Stage: Convention Detector ---
        metrics = emitter.emit_stage_start("convention_detector")
        try:
            file_paths = [f.path for f in scan_result.files]
            convention_result = detect_conventions(ctx.workspace_path, file_paths)
            metrics.conventions_found = convention_result.total_found
            partial_results["conventions_detected"] = convention_result.total_found
        finally:
            emitter.emit_stage_complete(metrics)

        # --- Stage: Pattern Inferrer ---
        metrics = emitter.emit_stage_start("pattern_inferrer")
        try:
            dep_summary = build_dependency_summary(
                extraction_result.modules,
                extraction_result.edges,
            )

            file_type_dist: dict[str, int] = Counter(
                f.language for f in scan_result.files if f.language != "unknown"
            )

            conv_names = [c.name for c in convention_result.conventions]
            entry_points = _detect_entry_points(scan_result.files)
            dir_structure = _get_directory_structure(ctx.workspace_path, depth=2)

            inference_result = infer_patterns(
                dependency_summary=dep_summary,
                file_type_distribution=dict(file_type_dist),
                conventions=conv_names,
                entry_points=entry_points,
                directory_structure=dir_structure,
                aws_region=aws_region,
            )
            metrics.input_tokens = inference_result.input_tokens
            metrics.output_tokens = inference_result.output_tokens
            metrics.cost_usd = inference_result.cost_usd
            partial_results["pipeline_chain_inferred"] = len(inference_result.pipeline_chain) > 0
        finally:
            emitter.emit_stage_complete(metrics)

        # --- Stage: Catalog Writer ---
        metrics = emitter.emit_stage_start("catalog_writer")
        try:
            if ctx.mode == "local":
                local_catalog_path = ctx.catalog_path
            else:
                local_catalog_path = os.path.join(ctx.workspace_path, "catalog.db")

            total_scan_ms = int((time.time() - emitter._pipeline_start) * 1000)

            catalog_result = write_catalog(
                catalog_path=local_catalog_path,
                repo_url=ctx.repo_url or f"local://{ctx.workspace_path}",
                commit_sha=commit_sha,
                scan_duration_ms=total_scan_ms,
                files=scan_result.files,
                modules=extraction_result.modules,
                edges=extraction_result.edges,
                conventions=convention_result.conventions,
                pipeline_chain=inference_result.pipeline_chain,
                module_boundaries=inference_result.module_boundaries,
                tech_stack=inference_result.tech_stack,
                level_patterns=inference_result.level_patterns,
                error_count=extraction_result.parse_errors + len(scan_result.errors),
            )
            metrics.extra["rows_inserted"] = catalog_result.rows_inserted
        finally:
            emitter.emit_stage_complete(metrics)

        # --- Stage: Steering Generator ---
        metrics = emitter.emit_stage_start("steering_generator")
        try:
            if ctx.mode == "local":
                output_path = os.path.join(ctx.workspace_path, ".kiro", "steering", "fde-draft.md")
                existing_path = os.path.join(ctx.workspace_path, ".kiro", "steering", "fde.md")
            else:
                output_path = os.path.join(ctx.workspace_path, "steering-draft.md")
                existing_path = None

            steering_result = generate_steering(
                catalog_path=local_catalog_path,
                repo_name=ctx.repo_name,
                commit_sha=commit_sha,
                output_path=output_path,
                existing_steering_path=existing_path,
            )
        finally:
            emitter.emit_stage_complete(metrics)

        # --- Stage: S3 Persister (cloud mode only) ---
        persist_result = None
        if ctx.mode == "cloud" and artifacts_bucket:
            # Determine effective catalog mode
            effective_catalog_mode = catalog_mode or os.environ.get("CATALOG_MODE", "cloud")

            if effective_catalog_mode == "ephemeral":
                # Ephemeral mode: persist to encrypted volume, no S3
                metrics = emitter.emit_stage_start("ephemeral_persister")
                try:
                    volume_path = ephemeral_volume_path or os.environ.get("EPHEMERAL_VOLUME_PATH", "/data")
                    ttl = ephemeral_ttl_hours or int(os.environ.get("EPHEMERAL_TTL_HOURS", "24"))
                    key_arn = ephemeral_encryption_key_arn or os.environ.get("EPHEMERAL_ENCRYPTION_KEY_ARN")
                    audit_ep = ephemeral_audit_endpoint or os.environ.get("EPHEMERAL_AUDIT_ENDPOINT")

                    total_scan_ms_final = int((time.time() - emitter._pipeline_start) * 1000)

                    ephemeral_result = persist_ephemeral(
                        catalog_local_path=local_catalog_path,
                        steering_md=steering_result.steering_md,
                        steering_diff=steering_result.steering_diff or None,
                        volume_path=volume_path,
                        correlation_id=ctx.correlation_id,
                        ttl_hours=ttl,
                        encryption_key_arn=key_arn,
                        audit_endpoint=audit_ep,
                        files_count=scan_result.total_files_scanned,
                        modules_count=extraction_result.total_modules,
                        conventions_count=convention_result.total_found,
                        pipeline_steps_count=len(inference_result.pipeline_chain),
                        scan_duration_ms=total_scan_ms_final,
                        llm_cost_usd=inference_result.cost_usd,
                        error_count=extraction_result.parse_errors + len(scan_result.errors),
                    )
                    local_catalog_path = ephemeral_result.catalog_path
                finally:
                    emitter.emit_stage_complete(metrics)
            else:
                # Standard cloud mode: upload to S3
                metrics = emitter.emit_stage_start("s3_persister")
                try:
                    owner = ctx.repo_owner
                    name = ctx.repo_name
                    persist_result = persist_to_s3(
                        bucket=artifacts_bucket,
                        catalog_local_path=local_catalog_path,
                        catalog_s3_key=f"catalogs/{owner}/{name}/catalog.db",
                        steering_md=steering_result.steering_md,
                        steering_s3_key=f"catalogs/{owner}/{name}/steering-draft.md",
                        steering_diff=steering_result.steering_diff or None,
                        diff_s3_key=f"catalogs/{owner}/{name}/steering-diff.md" if steering_result.steering_diff else None,
                        aws_region=aws_region,
                    )
                finally:
                    emitter.emit_stage_complete(metrics)

        emitter.emit_pipeline_complete()

        return {
            "status": "success",
            "correlation_id": ctx.correlation_id,
            "mode": ctx.mode,
            "repo_url": ctx.repo_url,
            "commit_sha": commit_sha,
            "files_scanned": scan_result.total_files_scanned,
            "modules_found": extraction_result.total_modules,
            "conventions_detected": convention_result.total_found,
            "pipeline_steps": len(inference_result.pipeline_chain),
            "module_boundaries": len(inference_result.module_boundaries),
            "tech_stack_tags": len(inference_result.tech_stack),
            "level_patterns": len(inference_result.level_patterns),
            "llm_cost_usd": inference_result.cost_usd,
            "catalog_path": local_catalog_path,
            "steering_path": steering_result.output_path,
            "s3_artifacts": asdict(persist_result) if persist_result else None,
        }

    except Exception as e:
        logger.error("Pipeline failed: %s", e, exc_info=True)
        emitter.emit_stage_error("pipeline", e)

        report = emitter.build_failure_report(
            failed_stage="pipeline",
            error=e,
            partial_results=partial_results,
            all_stages=ALL_STAGES,
            repo_url=ctx.repo_url,
        )

        if ctx.mode == "cloud" and artifacts_bucket:
            try:
                persist_failure_report(
                    bucket=artifacts_bucket,
                    s3_key=f"catalogs/{ctx.repo_owner}/{ctx.repo_name}/failure-report.json",
                    failure_report=asdict(report),
                    aws_region=aws_region,
                )
            except Exception as persist_err:
                logger.error("Failed to persist failure report: %s", persist_err)

        return {
            "status": "failed",
            "correlation_id": ctx.correlation_id,
            "mode": ctx.mode,
            "error": str(e),
            "partial_results": partial_results,
            "stages_completed": emitter.stages_completed,
        }


def _detect_entry_points(files: list[FileRecord]) -> list[str]:
    """Heuristic detection of entry point files."""
    entry_patterns = [
        "main.", "app.", "index.", "server.", "handler.",
        "_handler.", "entrypoint.", "cli.", "lambda_",
    ]
    entry_points = []
    for f in files:
        filename = Path(f.path).name.lower()
        if any(filename.startswith(p) or p in filename for p in entry_patterns):
            entry_points.append(f.path)
    return entry_points[:20]


def _get_directory_structure(workspace_path: str, depth: int = 2) -> list[str]:
    """Get directory structure up to specified depth."""
    structure = []
    workspace = Path(workspace_path)
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "vendor", ".terraform"}

    for dirpath, dirnames, filenames in os.walk(workspace_path):
        rel_dir = Path(dirpath).relative_to(workspace)
        current_depth = len(rel_dir.parts)

        if current_depth > depth:
            dirnames.clear()
            continue

        dirnames[:] = [d for d in dirnames if d not in skip_dirs]

        if current_depth <= depth:
            for d in sorted(dirnames):
                structure.append(f"{rel_dir / d}/")
            for f in sorted(filenames)[:5]:
                structure.append(str(rel_dir / f))

    return structure[:100]


def run_from_event(event: dict, **kwargs) -> dict:
    """Entry point for EventBridge events."""
    params = parse_eventbridge_event(event)
    return run_pipeline(**params, **kwargs)
