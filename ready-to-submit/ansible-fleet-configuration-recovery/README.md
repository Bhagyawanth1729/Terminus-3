# Ansible Fleet Configuration Recovery

This task models recovery of a production-style Ansible configuration estate spanning three sites, multiple service and policy catalogs, heterogeneous endpoint data, Vault-managed secrets, local controller configuration, role orchestration, templating, state promotion, rollout planning, and operator evidence.

## System shape

The environment is rooted at `/app/fleet-automation`. Inventory and group variables describe the fleet; service and policy catalogs provide shared configuration inputs; roles render host configuration and coordinate cross-host data; the state and rollout engines model safe promotion and operational sequencing. Incident logs, a structured handoff, and configuration-selection evidence provide the starting diagnostic trail.

The scenario is intentionally coupled. A controller/configuration problem can mask role-discovery failures, which can in turn mask orchestration, parser/schema, Vault, template, IPv6, aggregation, or convergence defects. A useful repair therefore has to follow execution evidence and preserve the existing operating model rather than replacing the system with a simplified path.

## Repair approach

A complete repair restores a supported Ansible execution environment and project-local configuration discovery first. Repository-local role discovery, role identity, ordering, handlers, and host responsibility boundaries are then made portable and deterministic. Sensitive variables stay encrypted with Ansible Vault, while the normal project execution path can consume them noninteractively.

The Ansible content itself is repaired with native modules and valid task schemas. Template/data handling remains general across the supplied inventory and catalogs, including mixed endpoint shapes, optional groups, cross-host aggregation, numeric policy ordering, telemetry data, and IPv4/IPv6 representation. Existing service and policy catalogs, the three-site topology, operator evidence, state machinery, rollout logic, configuration destinations, and semantic contracts are preserved.

## Verification

Verification combines structural and behavioral checks. The supplied fleet playbook must execute successfully against the local inventory, generated configuration must satisfy the semantic validator, and sensitive data must remain protected at rest. Independent tests also exercise controller/config discovery, role discovery, orchestration/schema correctness, heterogeneous data rendering, aggregation and IPv6 behavior, preservation of production-scale inputs, and failure boundaries.

Convergence is part of correctness: an unchanged second execution must succeed without unnecessary task changes, handler churn, duplicated generated content, or state drift. Preservation checks ensure that repairing the automation does not achieve success by shrinking or bypassing the production model.

The public Ansible references used to construct the environment are listed in `environment/docs/official-ansible-sources.txt`; the incident evidence is under `environment/runtime/`.
