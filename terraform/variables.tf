# CIRISManager Research Infrastructure - Variables
# This is RESEARCH infrastructure, separate from CIRISBridge production infra

variable "vultr_api_key" {
  description = "Vultr API key"
  type        = string
  sensitive   = true
}

variable "ssh_key_ids" {
  description = "List of Vultr SSH key IDs to add to instances"
  type        = list(string)
}

variable "region" {
  description = "Vultr region for deployment"
  type        = string
  default     = "ord"  # Chicago - same region as current main server
}

# Manager VM Configuration
variable "manager_plan" {
  description = "Vultr plan for manager VM (vc2-1c-2gb recommended)"
  type        = string
  default     = "vc2-1c-2gb"  # 1 vCPU, 2GB RAM, 55GB SSD - $12/mo
}

variable "manager_hostname" {
  description = "Hostname for manager VM"
  type        = string
  default     = "ciris-manager"
}

variable "manager_label" {
  description = "Label for manager VM in Vultr console"
  type        = string
  default     = "ciris-manager-research"
}

# Agents VM Configuration
variable "agents_plan" {
  description = "Vultr plan for agents VM (vc2-2c-4gb recommended)"
  type        = string
  default     = "vc2-2c-4gb"  # 2 vCPU, 4GB RAM, 80GB SSD - $24/mo
}

variable "agents_hostname" {
  description = "Hostname for agents VM"
  type        = string
  default     = "ciris-agents"
}

variable "agents_label" {
  description = "Label for agents VM in Vultr console"
  type        = string
  default     = "ciris-agents-research"
}

# OS Configuration
variable "os_id" {
  description = "Vultr OS ID (2284 = Ubuntu 24.04 LTS)"
  type        = number
  default     = 2284
}

# VPC Configuration
variable "vpc_description" {
  description = "Description for the VPC"
  type        = string
  default     = "CIRIS Research Infrastructure VPC"
}

variable "vpc_subnet" {
  description = "VPC subnet CIDR"
  type        = string
  default     = "10.10.0.0"
}

variable "vpc_subnet_size" {
  description = "VPC subnet mask size"
  type        = number
  default     = 24
}

# Scout1 VM Configuration
variable "scout1_plan" {
  description = "Vultr plan for scout1 VM"
  type        = string
  default     = "vc2-1c-2gb"  # 1 vCPU, 2GB RAM - $12/mo
}

variable "scout1_hostname" {
  description = "Hostname for scout1 VM"
  type        = string
  default     = "ciris-scout1"
}

variable "scout1_label" {
  description = "Label for scout1 VM in Vultr console"
  type        = string
  default     = "ciris-scout1-research"
}

# Scout2 VM Configuration
variable "scout2_plan" {
  description = "Vultr plan for scout2 VM"
  type        = string
  default     = "vc2-1c-2gb"  # 1 vCPU, 2GB RAM - $12/mo
}

variable "scout2_hostname" {
  description = "Hostname for scout2 VM"
  type        = string
  default     = "ciris-scout2"
}

variable "scout2_label" {
  description = "Label for scout2 VM in Vultr console"
  type        = string
  default     = "ciris-scout2-research"
}

# Tags
variable "environment" {
  description = "Environment tag"
  type        = string
  default     = "research"
}

variable "project" {
  description = "Project tag"
  type        = string
  default     = "ciris"
}
