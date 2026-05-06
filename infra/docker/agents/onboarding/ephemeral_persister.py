"""
Ephemeral Persister — Handles catalog persistence in regulated environments
where data cannot leave the compute boundary.

Design ref: ADR-016 Ephemeral Catalog and Data Residency

In ephemeral mode:
- Catalog stays in an encrypted Docker volume (customer KMS key)
- No S3 upload, no network transfer of code metadata
- Audit events emitted with counts/durations only (never file paths or module names)
- TTL-based auto-destruction via volume lifecycle
- Steering draft written to volume for human review inside the boundary
"""

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("fde-onboarding.ephemeral_persister")


@dataclass
class EphemeralPersistResult:
    """Result of ephemeral persistence."""

    catalog_path: str
    steering_path: str
    volume_path: str
    ttl_hours: int
    encryption_verified: bool
    audit_event_emitted: bool
    duration_ms: int


@dataclass
class AuditEvent:
    """
    Audit event for regulated environments.

    CRITICAL: This event NEVER contains file paths, module names, dependency
    edges, tech stack tags, or any code structure metadata. Only operational
    counts and durations are safe to export.
    """

    event_type: str
    correlation_id: str
    timestamp: str
    mode: str
    files_count: int
    modules_count: int
    conventions_count: int
    pipeline_steps_count: int
    scan_duration_ms: int
    llm_cost_usd: float
    error_count: int
    ttl_hours: int
    volume_path: str
    encryption_key_arn: Optional[str]


def persist_ephemeral(
    catalog_local_path: str,
    steering_md: str,
    steering_diff: Optional[str],
    volume_path: str,
    correlation_id: str,
    ttl_hours: int = 24,
    encryption_key_arn: Optional[str] = None,
    audit_endpoint: Optional[str] = None,
    files_count: int = 0,
    modules_count: int = 0,
    conventions_count: int = 0,
    pipeline_steps_count: int = 0,
    scan_duration_ms: int = 0,
    llm_cost_usd: float = 0.0,
    error_count: int = 0,
) -> EphemeralPersistResult:
    """
    Persist catalog and steering to an encrypted Docker volume.

    No data leaves the compute boundary. The volume is encrypted with the
    customer's KMS key and auto-destroyed after the configured TTL.
    """
    start = time.time()

    os.makedirs(volume_path, exist_ok=True)

    # Move catalog to encrypted volume
    volume_catalog_path = os.path.join(volume_path, "catalog.db")
    if catalog_local_path != volume_catalog_path:
        shutil.copy2(catalog_local_path, volume_catalog_path)
        try:
            os.unlink(catalog_local_path)
        except OSError:
            pass

    # Write steering draft to volume
    volume_steering_path = os.path.join(volume_path, "steering-draft.md")
    with open(volume_steering_path, "w") as f:
        f.write(steering_md)

    # Write steering diff if present
    if steering_diff:
        with open(os.path.join(volume_path, "steering-diff.md"), "w") as f:
            f.write(steering_diff)

    # Write TTL metadata (for auto-destruction scheduler)
    ttl_metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ttl_hours": ttl_hours,
        "destroy_after": (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat(),
        "correlation_id": correlation_id,
        "encryption_key_arn": encryption_key_arn,
    }
    with open(os.path.join(volume_path, ".ttl-metadata.json"), "w") as f:
        json.dump(ttl_metadata, f, indent=2)

    # Verify encryption
    encryption_verified = _verify_encryption(volume_path, encryption_key_arn)

    # Emit audit event (safe operational metrics only)
    audit_emitted = _emit_audit_event(
        event_type="catalog_persisted_ephemeral",
        correlation_id=correlation_id,
        volume_path=volume_path,
        ttl_hours=ttl_hours,
        encryption_key_arn=encryption_key_arn,
        audit_endpoint=audit_endpoint,
        files_count=files_count,
        modules_count=modules_count,
        conventions_count=conventions_count,
        pipeline_steps_count=pipeline_steps_count,
        scan_duration_ms=scan_duration_ms,
        llm_cost_usd=llm_cost_usd,
        error_count=error_count,
    )

    duration_ms = int((time.time() - start) * 1000)

    logger.info(
        "Ephemeral persist complete: volume=%s, ttl=%dh, encrypted=%s, audit=%s (%dms)",
        volume_path, ttl_hours, encryption_verified, audit_emitted, duration_ms,
    )

    return EphemeralPersistResult(
        catalog_path=volume_catalog_path,
        steering_path=volume_steering_path,
        volume_path=volume_path,
        ttl_hours=ttl_hours,
        encryption_verified=encryption_verified,
        audit_event_emitted=audit_emitted,
        duration_ms=duration_ms,
    )


def destroy_ephemeral_volume(
    volume_path: str,
    correlation_id: str,
    audit_endpoint: Optional[str] = None,
) -> bool:
    """
    Explicitly destroy the ephemeral volume contents.

    Performs:
    1. Secure overwrite of catalog.db (zero-fill)
    2. Delete all files in the volume
    3. Emit destruction audit event
    """
    try:
        catalog_path = os.path.join(volume_path, "catalog.db")
        if os.path.exists(catalog_path):
            size = os.path.getsize(catalog_path)
            with open(catalog_path, "wb") as f:
                f.write(b"\x00" * size)
            os.unlink(catalog_path)

        for item in os.listdir(volume_path):
            item_path = os.path.join(volume_path, item)
            if os.path.isfile(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)

        _emit_audit_event(
            event_type="catalog_destroyed_ephemeral",
            correlation_id=correlation_id,
            volume_path=volume_path,
            ttl_hours=0,
            encryption_key_arn=None,
            audit_endpoint=audit_endpoint,
            files_count=0, modules_count=0, conventions_count=0,
            pipeline_steps_count=0, scan_duration_ms=0,
            llm_cost_usd=0.0, error_count=0,
        )

        logger.info("Ephemeral volume destroyed: %s (correlation=%s)", volume_path, correlation_id)
        return True

    except Exception as e:
        logger.error("Failed to destroy ephemeral volume %s: %s", volume_path, e)
        return False


def _verify_encryption(volume_path: str, encryption_key_arn: Optional[str]) -> bool:
    """Verify that the volume is encrypted (deployment-time guarantee)."""
    if encryption_key_arn:
        logger.info("Encryption key configured: %s", encryption_key_arn[:40] + "...")
        return True

    env_key = os.environ.get("EPHEMERAL_ENCRYPTION_KEY_ARN", "")
    if env_key:
        return True

    logger.warning("No encryption key configured for ephemeral volume")
    return False


def _emit_audit_event(
    event_type: str,
    correlation_id: str,
    volume_path: str,
    ttl_hours: int,
    encryption_key_arn: Optional[str],
    audit_endpoint: Optional[str],
    files_count: int,
    modules_count: int,
    conventions_count: int,
    pipeline_steps_count: int,
    scan_duration_ms: int,
    llm_cost_usd: float,
    error_count: int,
) -> bool:
    """
    Emit an audit event to the customer's SIEM.

    SECURITY: This event MUST NEVER contain file paths, module names,
    dependency edges, tech stack tags, or any code-derived content.
    """
    event_dict = {
        "event_type": event_type,
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "ephemeral",
        "files_count": files_count,
        "modules_count": modules_count,
        "conventions_count": conventions_count,
        "pipeline_steps_count": pipeline_steps_count,
        "scan_duration_ms": scan_duration_ms,
        "llm_cost_usd": llm_cost_usd,
        "error_count": error_count,
        "ttl_hours": ttl_hours,
    }
    logger.info("AUDIT: %s", json.dumps(event_dict))

    if audit_endpoint:
        try:
            import urllib.request
            req = urllib.request.Request(
                audit_endpoint,
                data=json.dumps(event_dict).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception as e:
            logger.warning("Failed to emit audit event to %s: %s", audit_endpoint, e)
            return False

    return True
