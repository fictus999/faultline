output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.alerts.name
}

output "notifier_user" {
  value = aws_iam_user.notifier.name
}

output "ci_plan_role_arn" {
  value = aws_iam_role.ci_plan.arn
}
