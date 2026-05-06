# COE: CloudFront OAC + SSE-KMS Access Denied

> Date: 2026-05-06
> Severity: Medium (blocked dashboard deployment for ~30 minutes)
> Root Cause: S3 objects encrypted with SSE-KMS are unreadable by CloudFront OAC without explicit kms:Decrypt permission

## Symptom

CloudFront distribution returned HTTP 403 (Access Denied) when serving `dashboard/index.html` from S3, despite:
- Bucket policy correctly granting `s3:GetObject` to `cloudfront.amazonaws.com` with `aws:SourceArn` condition
- OAC correctly attached to the distribution
- Distribution status: Deployed

## Investigation Timeline

1. Assumed `BlockPublicPolicy=true` was blocking the bucket policy → **Wrong** (wafr-alpha has same setting and works)
2. Assumed CloudFront cache was stale → Invalidated, still 403 → **Wrong**
3. Assumed OAC propagation delay → Waited, still 403 → **Wrong**
4. Checked object encryption: `ServerSideEncryption: aws:kms` → **Root cause found**

## Root Cause

The S3 bucket has default encryption set to `aws:kms` (via Terraform `aws_s3_bucket_server_side_encryption_configuration`). When objects are uploaded without specifying encryption, they inherit KMS encryption.

CloudFront OAC uses SigV4 to sign requests to S3, but it does NOT have `kms:Decrypt` permission on the bucket's KMS key. S3 returns 403 because it cannot decrypt the object to serve it.

The wafr-alpha distribution works because its dedicated bucket (`wafr-alpha-publish-content`) uses SSE-S3 (AES256), not SSE-KMS.

## Fix

Upload dashboard objects with explicit `--sse AES256` to override the bucket default:

```bash
aws s3 cp index.html s3://$BUCKET/dashboard/index.html --sse AES256 --content-type "text/html"
```

This is now automated in `scripts/deploy-dashboard.sh`.

## Prevention

1. The `deploy-dashboard.sh` script always uses `--sse AES256` for dashboard uploads
2. Added to `docs/guides/staff-engineer-post-deploy.md` troubleshooting table
3. Alternative long-term fix: add `kms:Decrypt` to the CloudFront OAC's assumed role (but SSE-S3 is simpler for public-facing static content)

## Lessons

- **Don't assume the same bucket policy pattern works across different encryption configurations.** The wafr-alpha reference worked because it uses a different encryption type.
- **Check object-level encryption, not just bucket-level policy.** The 403 from S3 doesn't distinguish "policy denied" from "KMS denied."
- **Apply 5 Whys before trying fixes.** The first 3 attempts (public access block, cache invalidation, propagation delay) were symptom-chasing. The 4th attempt (check encryption) found the root cause.
