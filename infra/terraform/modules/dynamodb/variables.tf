# ═══════════════════════════════════════════════════════════════════
# DynamoDB Module — Shared Variables
# ═══════════════════════════════════════════════════════════════════
#
# Variables declared here are shared across all DynamoDB table files
# in this module. Individual table files (scd.tf, context_hierarchy.tf,
# etc.) reference these without re-declaring.
#
# Note: scd.tf declares name_prefix and environment. Since Terraform
# loads all .tf files in a module directory as a single unit, those
# declarations are available to all files in this module.
# This file exists for documentation purposes.
# ═══════════════════════════════════════════════════════════════════
