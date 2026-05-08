# -------------------------------------------------------------------
# Bedrock Knowledge Base Module (Activity 3.16)
#
# Creates:
#   - OpenSearch Serverless collection (vector engine)
#   - Bedrock Knowledge Base with embedding model
#   - S3 data source for knowledge ingestion
#
# Prerequisites:
#   - Bedrock model access must be pre-approved in the account
#   - S3 artifacts bucket must exist
#
# Ref: docs/design/fde-core-brain-development.md Section 3
# -------------------------------------------------------------------

variable "name_prefix" {
  type        = string
  description = "Prefix for all resource names (e.g., fde-dev)"
}

variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "artifacts_bucket_arn" {
  type        = string
  description = "ARN of the S3 bucket containing knowledge artifacts"
}

variable "embedding_model_id" {
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
  description = "Bedrock embedding model ID for vectorization"
}

# -------------------------------------------------------------------
# Data sources
# -------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  collection_name = "${var.name_prefix}-knowledge-vectors"
  kb_name         = "${var.name_prefix}-knowledge-base"
  account_id      = data.aws_caller_identity.current.account_id
  region          = data.aws_region.current.name
}

# -------------------------------------------------------------------
# OpenSearch Serverless — Security Policies
# -------------------------------------------------------------------

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "${var.name_prefix}-kb-enc"
  type = "encryption"
  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource     = ["collection/${local.collection_name}"]
      }
    ]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "network" {
  name = "${var.name_prefix}-kb-net"
  type = "network"
  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.collection_name}"]
        },
        {
          ResourceType = "dashboard"
          Resource     = ["collection/${local.collection_name}"]
        }
      ]
      AllowFromPublic = true
    }
  ])
}

resource "aws_opensearchserverless_access_policy" "data" {
  name = "${var.name_prefix}-kb-data"
  type = "data"
  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "index"
          Resource     = ["index/${local.collection_name}/*"]
          Permission   = [
            "aoss:CreateIndex",
            "aoss:DeleteIndex",
            "aoss:UpdateIndex",
            "aoss:DescribeIndex",
            "aoss:ReadDocument",
            "aoss:WriteDocument",
          ]
        },
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.collection_name}"]
          Permission   = [
            "aoss:CreateCollectionItems",
            "aoss:DeleteCollectionItems",
            "aoss:UpdateCollectionItems",
            "aoss:DescribeCollectionItems",
          ]
        }
      ]
      Principal = [
        aws_iam_role.bedrock_kb_role.arn,
        "arn:aws:iam::${local.account_id}:root",
      ]
    }
  ])
}

# -------------------------------------------------------------------
# OpenSearch Serverless — Collection (Vector Engine)
# -------------------------------------------------------------------

resource "aws_opensearchserverless_collection" "knowledge" {
  name = local.collection_name
  type = "VECTORSEARCH"

  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
    aws_opensearchserverless_access_policy.data,
  ]

  tags = {
    Name        = local.collection_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "fde-knowledge-base-vectors"
  }
}

# -------------------------------------------------------------------
# IAM Role for Bedrock Knowledge Base
# -------------------------------------------------------------------

resource "aws_iam_role" "bedrock_kb_role" {
  name = "${var.name_prefix}-bedrock-kb-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "bedrock.amazonaws.com"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = local.account_id
          }
        }
      }
    ]
  })

  tags = {
    Name        = "${var.name_prefix}-bedrock-kb-role"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "bedrock_kb_s3" {
  name = "${var.name_prefix}-bedrock-kb-s3"
  role = aws_iam_role.bedrock_kb_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = [
          var.artifacts_bucket_arn,
          "${var.artifacts_bucket_arn}/*",
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "bedrock_kb_aoss" {
  name = "${var.name_prefix}-bedrock-kb-aoss"
  role = aws_iam_role.bedrock_kb_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "aoss:APIAccessAll",
        ]
        Resource = [
          aws_opensearchserverless_collection.knowledge.arn,
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "bedrock_kb_model" {
  name = "${var.name_prefix}-bedrock-kb-model"
  role = aws_iam_role.bedrock_kb_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
        ]
        Resource = [
          "arn:aws:bedrock:${local.region}::foundation-model/${var.embedding_model_id}",
        ]
      }
    ]
  })
}

# -------------------------------------------------------------------
# Bedrock Knowledge Base
# -------------------------------------------------------------------

resource "aws_bedrockagent_knowledge_base" "main" {
  name     = local.kb_name
  role_arn = aws_iam_role.bedrock_kb_role.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${local.region}::foundation-model/${var.embedding_model_id}"
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.knowledge.arn
      vector_index_name = "bedrock-knowledge-base-default-index"
      field_mapping {
        vector_field   = "bedrock-knowledge-base-default-vector"
        text_field     = "AMAZON_BEDROCK_TEXT_CHUNK"
        metadata_field = "AMAZON_BEDROCK_METADATA"
      }
    }
  }

  tags = {
    Name        = local.kb_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Activity    = "3.16"
  }
}

# -------------------------------------------------------------------
# Bedrock Knowledge Base — S3 Data Source
# -------------------------------------------------------------------

resource "aws_bedrockagent_data_source" "s3" {
  name              = "${var.name_prefix}-s3-source"
  knowledge_base_id = aws_bedrockagent_knowledge_base.main.id

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = var.artifacts_bucket_arn
    }
  }
}

# -------------------------------------------------------------------
# Outputs
# -------------------------------------------------------------------

output "knowledge_base_id" {
  value       = aws_bedrockagent_knowledge_base.main.id
  description = "Bedrock Knowledge Base ID for use in retrieval APIs"
}

output "collection_endpoint" {
  value       = aws_opensearchserverless_collection.knowledge.collection_endpoint
  description = "OpenSearch Serverless collection endpoint URL"
}

output "data_source_id" {
  value       = aws_bedrockagent_data_source.s3.data_source_id
  description = "Bedrock data source ID for triggering ingestion jobs"
}

output "knowledge_base_role_arn" {
  value       = aws_iam_role.bedrock_kb_role.arn
  description = "IAM role ARN used by the Knowledge Base"
}
