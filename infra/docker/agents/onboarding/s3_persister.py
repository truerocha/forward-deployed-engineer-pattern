"""
S3 Persister — Uploads the catalog and steering draft to S3.
Skipped in local mode.

Design ref: §3.9 S3 Persister
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde-onboarding.s3_persister")


@dataclass
class PersistResult:
    """Result of S3 persistence."""

    catalog_s3_uri: str
    steering_s3_uri: str
    diff_s3_uri: Optional[str]
    failure_report_s3_uri: Optional[str]
    duration_ms: int


def persist_to_s3(
    bucket: str,
    catalog_local_path: str,
    catalog_s3_key: str,
    steering_md: str,
    steering_s3_key: str,
    steering_diff: Optional[str] = None,
    diff_s3_key: Optional[str] = None,
    aws_region: str = "us-east-1",
) -> PersistResult:
    """
    Upload catalog and steering artifacts to S3.

    Args:
        bucket: S3 bucket name.
        catalog_local_path: Local path to the SQLite catalog file.
        catalog_s3_key: S3 key for the catalog.
        steering_md: Generated steering markdown content.
        steering_s3_key: S3 key for the steering draft.
        steering_diff: Optional unified diff (re-scan only).
        diff_s3_key: S3 key for the diff file.
        aws_region: AWS region.

    Returns:
        PersistResult with S3 URIs.
    """
    start = time.time()
    s3 = boto3.client("s3", region_name=aws_region)

    _upload_file(s3, bucket, catalog_local_path, catalog_s3_key)
    catalog_uri = f"s3://{bucket}/{catalog_s3_key}"

    _upload_text(s3, bucket, steering_md, steering_s3_key, "text/markdown")
    steering_uri = f"s3://{bucket}/{steering_s3_key}"

    diff_uri = None
    if steering_diff and diff_s3_key:
        _upload_text(s3, bucket, steering_diff, diff_s3_key, "text/plain")
        diff_uri = f"s3://{bucket}/{diff_s3_key}"

    duration_ms = int((time.time() - start) * 1000)

    logger.info(
        "S3 persist complete: catalog=%s, steering=%s, diff=%s (%dms)",
        catalog_uri, steering_uri, diff_uri or "none", duration_ms,
    )

    return PersistResult(
        catalog_s3_uri=catalog_uri,
        steering_s3_uri=steering_uri,
        diff_s3_uri=diff_uri,
        failure_report_s3_uri=None,
        duration_ms=duration_ms,
    )


def persist_failure_report(
    bucket: str,
    s3_key: str,
    failure_report: dict,
    aws_region: str = "us-east-1",
) -> str:
    """Upload a failure report to S3."""
    s3 = boto3.client("s3", region_name=aws_region)
    content = json.dumps(failure_report, indent=2, default=str)
    _upload_text(s3, bucket, content, s3_key, "application/json")
    uri = f"s3://{bucket}/{s3_key}"
    logger.info("Failure report uploaded: %s", uri)
    return uri


def _upload_file(s3, bucket: str, local_path: str, s3_key: str) -> None:
    """Upload a local file to S3."""
    try:
        s3.upload_file(local_path, bucket, s3_key)
    except ClientError as e:
        raise RuntimeError(f"Failed to upload {local_path} to s3://{bucket}/{s3_key}: {e}") from e


def _upload_text(s3, bucket: str, content: str, s3_key: str, content_type: str) -> None:
    """Upload text content to S3."""
    try:
        s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=content.encode("utf-8"),
            ContentType=content_type,
        )
    except ClientError as e:
        raise RuntimeError(f"Failed to upload to s3://{bucket}/{s3_key}: {e}") from e
