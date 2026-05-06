"""
Entrypoint for the Repo Onboarding Agent when run as a module:
    python -m agents.onboarding

Reads configuration from environment variables and executes the pipeline.
"""

import json
import logging
import os
import sys

from .pipeline import run_pipeline, run_from_event

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fde-onboarding")


def main():
    logger.info("Repo Onboarding Agent starting...")

    environment = os.environ.get("ENVIRONMENT", "dev")
    artifacts_bucket = os.environ.get("ARTIFACTS_BUCKET", "")
    aws_region = os.environ.get("AWS_REGION", "us-east-1")

    # Check for EventBridge event
    eventbridge_event = os.environ.get("EVENTBRIDGE_EVENT", "")
    if eventbridge_event:
        logger.info("Mode: EventBridge event")
        event = json.loads(eventbridge_event)
        result = run_from_event(
            event,
            environment=environment,
            artifacts_bucket=artifacts_bucket,
            aws_region=aws_region,
        )
    else:
        # Direct invocation via environment variables
        repo_url = os.environ.get("REPO_URL", "")
        clone_depth = int(os.environ.get("CLONE_DEPTH", "1"))
        force_full_scan = os.environ.get("FORCE_FULL_SCAN", "").lower() in ("true", "1", "yes")
        correlation_id = os.environ.get("CORRELATION_ID", "")

        logger.info(
            "Mode: Direct invocation (repo_url=%s, depth=%d, force=%s)",
            repo_url or "local",
            clone_depth,
            force_full_scan,
        )

        result = run_pipeline(
            repo_url=repo_url or None,
            clone_depth=clone_depth,
            force_full_scan=force_full_scan,
            correlation_id=correlation_id or None,
            environment=environment,
            artifacts_bucket=artifacts_bucket or None,
            aws_region=aws_region,
            catalog_mode=os.environ.get("CATALOG_MODE"),
            ephemeral_volume_path=os.environ.get("EPHEMERAL_VOLUME_PATH"),
            ephemeral_ttl_hours=int(os.environ.get("EPHEMERAL_TTL_HOURS", "24")),
            ephemeral_encryption_key_arn=os.environ.get("EPHEMERAL_ENCRYPTION_KEY_ARN"),
            ephemeral_audit_endpoint=os.environ.get("EPHEMERAL_AUDIT_ENDPOINT"),
        )

    logger.info("Result: %s", json.dumps(result, indent=2, default=str))

    if result.get("status") == "failed":
        sys.exit(1)

    logger.info("Onboarding agent execution complete.")


if __name__ == "__main__":
    main()
