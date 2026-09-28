terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }

  # Remote state with S3-native locking (DynamoDB locking is deprecated).
  # Create the bucket once, then uncomment and run `terraform init -migrate-state`.
  # backend "s3" {
  #   bucket       = "faultline-tfstate-<account-id>"
  #   key          = "faultline/demo.tfstate"
  #   region       = "ap-south-1"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = "faultline"
      Env     = var.env
    }
  }
}
