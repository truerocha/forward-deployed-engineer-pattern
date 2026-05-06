# =============================================================================
# Dashboard CDN — CloudFront + S3 Origin for Code Factory Dashboard
# Serves the static dashboard HTML via CloudFront with OAC (Origin Access Control)
# The dashboard calls the API Gateway /status/tasks endpoint for live data.
# =============================================================================

# --- CloudFront Origin Access Control (OAC) ---

resource "aws_cloudfront_origin_access_control" "dashboard" {
  name                              = "${local.name_prefix}-dashboard-oac"
  description                       = "OAC for Code Factory dashboard S3 origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# --- CloudFront Distribution ---

resource "aws_cloudfront_distribution" "dashboard" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "Code Factory Pipeline Dashboard"
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.factory_artifacts.bucket_regional_domain_name
    origin_id                = "dashboard-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard.id
    origin_path              = "/dashboard"
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "dashboard-s3"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 300
    max_ttl     = 3600
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Component   = "dashboard"
    Environment = var.environment
  }
}

# --- S3 Bucket Policy: Allow CloudFront OAC to read dashboard/ prefix ---

resource "aws_s3_bucket_policy" "dashboard_cloudfront" {
  bucket = aws_s3_bucket.factory_artifacts.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontOAC"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.factory_artifacts.arn}/dashboard/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.dashboard.arn
          }
        }
      }
    ]
  })
}

# --- Output: Dashboard URL ---

output "dashboard_url" {
  description = "Code Factory Dashboard URL (CloudFront)"
  value       = "https://${aws_cloudfront_distribution.dashboard.domain_name}"
}
