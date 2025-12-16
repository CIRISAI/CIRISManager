# CIRISManager Research Infrastructure - Outputs

output "manager_public_ip" {
  description = "Public IP of the manager VM"
  value       = vultr_instance.manager.main_ip
}

output "manager_vpc_ip" {
  description = "VPC IP of the manager VM"
  value       = vultr_instance.manager.internal_ip
}

output "agents_public_ip" {
  description = "Public IP of the agents VM"
  value       = vultr_instance.agents.main_ip
}

output "agents_vpc_ip" {
  description = "VPC IP of the agents VM"
  value       = vultr_instance.agents.internal_ip
}

output "scout1_public_ip" {
  description = "Public IP of the scout1 VM"
  value       = vultr_instance.scout1.main_ip
}

output "scout1_vpc_ip" {
  description = "VPC IP of the scout1 VM"
  value       = vultr_instance.scout1.internal_ip
}

output "scout2_public_ip" {
  description = "Public IP of the scout2 VM"
  value       = vultr_instance.scout2.main_ip
}

output "scout2_vpc_ip" {
  description = "VPC IP of the scout2 VM"
  value       = vultr_instance.scout2.internal_ip
}

output "vpc_id" {
  description = "VPC ID for the research network"
  value       = vultr_vpc.research.id
}

output "ssh_config" {
  description = "SSH config snippet for easy access"
  value       = <<-EOF

    # Add to ~/.ssh/config:
    Host ciris-manager
        HostName ${vultr_instance.manager.main_ip}
        User root
        IdentityFile ~/.ssh/ciris_deploy

    Host ciris-agents
        HostName ${vultr_instance.agents.main_ip}
        User root
        IdentityFile ~/.ssh/ciris_deploy

    Host ciris-scout1
        HostName ${vultr_instance.scout1.main_ip}
        User root
        IdentityFile ~/.ssh/ciris_deploy

    Host ciris-scout2
        HostName ${vultr_instance.scout2.main_ip}
        User root
        IdentityFile ~/.ssh/ciris_deploy
  EOF
}

output "manager_config_snippet" {
  description = "CIRISManager config.yml server entries"
  value       = <<-EOF

    # Add to /etc/ciris-manager/config.yml servers section:
    servers:
      - server_id: manager
        hostname: manager.ciris.ai
        is_local: true

      - server_id: agents
        hostname: agents.ciris.ai
        is_local: false
        public_ip: ${vultr_instance.agents.main_ip}
        vpc_ip: ${vultr_instance.agents.internal_ip}
        docker_host: https://${vultr_instance.agents.internal_ip}:2376
        tls_ca: /etc/ciris-manager/docker-certs/agents/ca.pem
        tls_cert: /etc/ciris-manager/docker-certs/agents/client-cert.pem
        tls_key: /etc/ciris-manager/docker-certs/agents/client-key.pem

      - server_id: scout1
        hostname: scout1.ciris.ai
        is_local: false
        public_ip: ${vultr_instance.scout1.main_ip}
        vpc_ip: ${vultr_instance.scout1.internal_ip}
        docker_host: https://${vultr_instance.scout1.internal_ip}:2376
        tls_ca: /etc/ciris-manager/docker-certs/scout1/ca.pem
        tls_cert: /etc/ciris-manager/docker-certs/scout1/client-cert.pem
        tls_key: /etc/ciris-manager/docker-certs/scout1/client-key.pem

      - server_id: scout2
        hostname: scout2.ciris.ai
        is_local: false
        public_ip: ${vultr_instance.scout2.main_ip}
        vpc_ip: ${vultr_instance.scout2.internal_ip}
        docker_host: https://${vultr_instance.scout2.internal_ip}:2376
        tls_ca: /etc/ciris-manager/docker-certs/scout2/ca.pem
        tls_cert: /etc/ciris-manager/docker-certs/scout2/client-cert.pem
        tls_key: /etc/ciris-manager/docker-certs/scout2/client-key.pem
  EOF
}
