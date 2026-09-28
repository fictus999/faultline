# Only what Faultline needs: one topic, one log group, and least-privilege identities.

resource "aws_sns_topic" "alerts" {
  name              = "faultline-${var.env}-alerts"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_log_group" "alerts" {
  name              = "/faultline/${var.env}/alerts"
  retention_in_days = 14
}

# The notifier may write to this one log group and publish to this one topic. Nothing else.
data "aws_iam_policy_document" "notifier" {
  statement {
    sid       = "WriteAlertLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.alerts.arn}:*"]
  }

  statement {
    sid       = "PublishAlerts"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

# Laptop demo identity. Create its access key by hand (aws iam create-access-key) so the
# secret never lands in Terraform state. CI never uses keys: it assumes the OIDC role below.
resource "aws_iam_user" "notifier" {
  name = "faultline-${var.env}-notifier"
}

resource "aws_iam_user_policy" "notifier" {
  name   = "faultline-notifier"
  user   = aws_iam_user.notifier.name
  policy = data.aws_iam_policy_document.notifier.json
}

# GitHub Actions -> AWS without long-lived keys.
data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_github_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1c58a3a8518e8759bf075b76b750d4f2df264fcd"]
}

locals {
  github_oidc_arn = (
    var.create_github_oidc_provider
    ? aws_iam_openid_connect_provider.github[0].arn
    : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
  )
}

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only this repository's workflows may assume the role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

# Read-only role for `terraform plan` in pull requests.
resource "aws_iam_role" "ci_plan" {
  name               = "faultline-${var.env}-ci-plan"
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
}

resource "aws_iam_role_policy_attachment" "ci_plan_read_only" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# TODO: heartbeat metric alarm (external dead-man's switch) and a budget alarm.
