# AWS VPC CDK

This task asks an agent to complete a Node.js AWS CDK construct that converts a JSON network intent into a deterministic CloudFormation template. The work is synthesis-only: no AWS account, credentials, or deployment are required.

The starter contains a partial construct that creates a VPC, public/private subnets, and a minimal route layout, but it omits several production network responsibilities and has weak validation. The intended repair adds CIDR validation, secondary CIDR associations, IPv6 handling, per-tier route tables, NAT routing semantics, endpoints, NACLs, flow logs, stable tags, and outputs.

Verification runs the submitted synth command against a held-out configuration, parses the synthesized template, and checks CloudFormation resource semantics plus deterministic output behavior. The tests also mutate the configuration to verify single-NAT, disabled-NAT, CIDR-overlap, endpoint, and AZ-coverage behavior.
