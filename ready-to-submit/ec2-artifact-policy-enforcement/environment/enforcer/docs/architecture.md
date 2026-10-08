# ArtifactGuard architecture

ArtifactGuard keeps the existing `evaluate` and `verify-permit` CLI contract while routing evaluation through a policy platform composed of normalization, policy, scanner, cache, exception, permit, audit, replay, and state subsystems. Acquisition requests carry package, container, or dependency surface context. Policy controls are selected by surface, manager, and environment. Durable state is rooted at the caller-provided state directory.

The starter intentionally contains the approved defect topology across trust normalization, evidence freshness, exception ordering and scope, permit authentication and binding, audit durability, and recovery/concurrency boundaries. The solver must repair those coupled behaviors without breaking the CLI contract.
