# ═══════════════════════════════════════════════════════════════════
# EFS Security Group — Network Access Control
# ═══════════════════════════════════════════════════════════════════
#
# Allows NFS (port 2049) inbound ONLY from ECS task security group.
# No public access. No cross-VPC access. Least-privilege networking.
#
# Ingress: TCP 2049 from ECS SG only
# Egress: None required (EFS mount targets respond on the same
#         connection initiated by the client — no outbound initiation).
#         AWS SGs are stateful: response traffic is automatically allowed.
# ═══════════════════════════════════════════════════════════════════

resource "aws_security_group" "efs" {
  name_prefix = "${var.name_prefix}-efs-"
  vpc_id      = var.vpc_id
  description = "Allow NFS access from ECS agent tasks to EFS mount targets"

  tags = {
    Name        = "${var.name_prefix}-efs-sg"
    Component   = "efs"
    Environment = var.environment
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "efs_ingress_nfs" {
  type                     = "ingress"
  from_port                = 2049
  to_port                  = 2049
  protocol                 = "tcp"
  security_group_id        = aws_security_group.efs.id
  source_security_group_id = var.ecs_security_group_id
  description              = "NFS from ECS agent tasks"
}
