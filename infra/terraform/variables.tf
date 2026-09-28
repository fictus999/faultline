variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "env" {
  type    = string
  default = "demo"
}

variable "alert_email" {
  type        = string
  description = "Receives HIGH and CRITICAL alerts. AWS emails a confirmation link first."
}

variable "github_repo" {
  type        = string
  default     = "fictus999/faultline"
  description = "owner/repo whose GitHub Actions may assume the CI role through OIDC."
}

variable "create_github_oidc_provider" {
  type        = bool
  default     = true
  description = "Set to false if the account already has the GitHub OIDC provider."
}
