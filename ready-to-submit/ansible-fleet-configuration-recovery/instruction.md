# Recover the Ansible fleet configuration

Recover the inherited multi-site Ansible fleet automation under `/app/fleet-automation`. The repository represents an operator-owned production configuration system, not a greenfield rewrite: use the incident evidence and existing inventory/catalog contracts to diagnose the failures, restore a supported and portable Ansible execution path, and preserve the fleet's production shape.

- Run the project with a supported Ansible release and make project-local configuration/bootstrap discovery work from `/app/fleet-automation`; do not rely on machine-global configuration or a shell-based replacement for Ansible behavior.
- Make every project role resolve portably from the repository and restore the intended role identities, dependency ordering, handler behavior, and host responsibility boundaries.
- Keep sensitive production variables encrypted at rest with Ansible Vault while allowing the documented project execution path to run noninteractively. Do not replace secret references with plaintext credentials.
- Repair YAML/parser, task/action, and module-argument errors using normal Ansible modules and valid task schemas. Do not bypass broken tasks with ad-hoc shell commands.
- Preserve the heterogeneous inventory and data model. Templates and role logic must correctly handle the existing endpoint/site/policy/telemetry shapes, cross-host aggregation, optional groups, numeric policy ordering, and both IPv4 and IPv6 endpoints.
- Preserve the service catalog, policy catalog, three-site inventory, operator incident evidence, rollout/state engines, and the existing configuration destinations and operating contracts unless a change is required to make the inherited behavior correct.
- Use the solver-visible evidence at `/app/fleet-automation/environment/runtime/logs/incident-bootstrap.log`, `/app/fleet-automation/environment/runtime/logs/incident-playbook.log`, `/app/fleet-automation/environment/runtime/reports/incident-handoff.json`, and `/app/fleet-automation/environment/runtime/evidence/config-selection.txt` to guide diagnosis. Official Ansible references used for this environment are listed in `/app/fleet-automation/environment/docs/official-ansible-sources.txt`.
- The full fleet playbook must complete successfully against the supplied local inventory and materialize valid configuration/state for the fleet. The existing semantic validation path must also pass on the resulting runtime state.
- Treat convergence as part of the repair: an unchanged second execution must succeed without unnecessary changes, handler churn, duplicated generated content, or state drift.

Keep the implementation general to the supplied fleet model. Do not special-case particular verifier examples, defect identifiers, or expected test values; the repaired automation should remain correct when the existing inventory and catalogs are varied within their documented shapes.
