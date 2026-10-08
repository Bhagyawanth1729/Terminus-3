# legacy-single-container-workload-to-Kubernetes-cutover

Terminus Edition 3 task: migrate a monolithic claims-upload host unit
into Kubernetes manifests. Agents edit `/app/k8s`; the separate
verifier statically checks those manifests against the frozen
process inventory and incident-driven constraints.

Reference docs under `environment/reference/kubernetes` are
truncated Apache-2.0 excerpts from kubernetes/website.
