<!-- Source: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle.md -->
<!-- Upstream raw: https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/pods/pod-lifecycle.md -->
<!-- License: Apache-2.0 (Kubernetes website / documentation) -->
<!-- Truncated locally for image size; consult upstream for full text. -->

---
title: Pod Lifecycle
content_type: concept
weight: 30
math: true
---

<!-- overview -->

This page describes the lifecycle of a Pod. Pods follow a defined lifecycle, starting
in the `Pending` [phase](#pod-phase), moving through `Running` if at least one
of its primary containers starts OK, and then through either the `Succeeded` or
`Failed` phases depending on whether any container in the Pod terminated in failure.

While a Pod runs, the kubelet manages containers and translates the Pod's spec
for the container runtime. The kubelet also manages executing
[probes](#container-probes) that track the health of your application.

Like individual application containers, Pods are considered to be relatively
ephemeral (rather than durable) entities. Pods are created, assigned a unique
ID ([UID](/docs/concepts/overview/working-with-objects/names/#uids)), and scheduled
to run on nodes where they remain until termination (according to restart policy) or
deletion.
If a {{< glossary_tooltip term_id="node" >}} dies, the Pods running on (or scheduled
to run on) that node are [marked for deletion](#pod-garbage-collection). The control
plane marks the Pods for removal after a timeout period.

<!-- body -->

## Pod lifetime

While a Pod is running, the kubelet is able to restart containers to handle
some kind of faults. Within a Pod, Kubernetes tracks different container
[states](#container-states) and determines what action to take to make the Pod
healthy again. This is done in a [polling
loop](/docs/reference/node/kubelet-sync-loop/) that periodically reconciles the
desired state (a Pod spec) with the actual state of the running containers.

In the Kubernetes API, Pods have both a specification and an actual status. The
status for a Pod object consists of a set of [Pod conditions](#pod-conditions).
You can also inject [custom readiness information](#pod-readiness-gate) into the
condition data for a Pod, if that is useful to your application.

Pods are only [scheduled](/docs/concepts/scheduling-eviction/) once in their lifetime;
assigning a Pod to a specific node is called _binding_, and the process of selecting
which node to use is called _scheduling_.
Once a Pod has been scheduled and is bound to a node, Kubernetes tries
to run that Pod on the node. The Pod runs on that node until it stops, or until the Pod
is [terminated](#pod-termination); if Kubernetes isn't able to start the Pod on the selected
node (for example, if the node crashes before the Pod starts), then that particular Pod
never starts.

You can use [Pod Scheduling Readiness](/docs/concepts/scheduling-eviction/pod-scheduling-readiness/)
to delay scheduling for a Pod until all its _scheduling gates_ are removed. For example,
you might want to define a set of Pods but only trigger scheduling once all the Pods
have been created.

### Pods and fault recovery {#pod-fault-recovery}

If one of the containers in the Pod fails, then Kubernetes may try to restart that
specific container.
Read [How Pods handle problems with containers](#container-restarts) to learn more.

Pods can however fail in a way that the cluster cannot recover from, and in that case
Kubernetes does not attempt to heal the Pod further; instead, Kubernetes deletes the
Pod and relies on other components to provide automatic healing.

If a Pod is scheduled to a {{< glossary_tooltip text="node" term_id="node" >}} and that
node then fails, the Pod is treated as unhealthy and Kubernetes eventually deletes the Pod.
A Pod won't survive an {{< glossary_tooltip text="eviction" term_id="eviction" >}} due to
a lack of resources or Node maintenance.

Kubernetes uses a higher-level abstraction, called a
{{< glossary_tooltip term_id="controller" text="controller" >}}, that handles the work of
managing the relatively disposable Pod instances.

A given Pod (as defined by a UID) is never "rescheduled" to a different node; instead,
that Pod can be replaced by a new, near-identical Pod. If you make a replacement Pod, it can
even have same name (as in `.metadata.name`) that the old Pod had, but the replacement
would have a different `.metadata.uid` from the old Pod.

Kubernetes does not guarantee that a replacement for an existing Pod would be scheduled to
the same node as the old Pod that was being replaced.

### Associated lifetimes

When something is said to have the same lifetime as a Pod, such as a
{{< glossary_tooltip term_id="volume" text="volume" >}},
that means that the thing exists as long as that specific Pod (with that exact UID)
exists. If that Pod is deleted for any reason, and even if an identical replacement
is created, the related thing (a volume, in this example) is also destroyed and
created anew.

{{< figure src="/images/docs/pod.svg" title="Figure 1." class="diagram-medium" caption="A multi-container Pod that contains a file puller [sidecar](/docs/concepts/workloads/pods/sidecar-containers/) and a web server. The Pod uses an [ephemeral `emptyDir` volume](/docs/concepts/storage/volumes/#emptydir) for shared storage between the containers." >}}

## Pod phase

A Pod's `status` field is a
[PodStatus](/docs/reference/generated/kubernetes-api/{{< param "version" >}}/#podstatus-v1-core)
object, which has a `phase` field.

The phase of a Pod is a simple, high-level summary of where the Pod is in its
lifecycle. The phase is not intended to be a comprehensive rollup of observations
of container or Pod state, nor is it intended to be a comprehensive state machine.

The number and meanings of Pod phase values are tightly guarded.
Other than what is documented here, nothing should be assumed about Pods that
have a given `phase` value.

Here are the possible values for `phase`:

Value       | Description
:-----------|:-----------
`Pending`   | The Pod has been accepted by the Kubernetes cluster, but one or more of the containers has not been set up and made ready to run. This includes time a Pod spends waiting to be scheduled as well as the time spent downloading container images over the network.
`Running`   | The Pod has been bound to a node, and all of the containers have been created. At least one container is still running, or is in the process of starting or restarting.
`Succeeded` | All containers in the Pod have terminated in success, and will not be restarted.
`Failed`    | All containers in the Pod have terminated, and at least one container has terminated in failure. That is, the container either exited with non-zero status or was terminated by the system, and is not set for automatic restarting.
`Unknown`   | For some reason the state of the Pod could not be obtained. This phase typically occurs due to an error in communicating with the node where the Pod should be running.

{{< note >}}

When a pod is failing to start repeatedly, `CrashLoopBackOff` may appear in the `Status` field of some kubectl commands.
Similarly, when a pod is being deleted, `Terminating` may appear in the `Status` field of some kubectl commands.

Make sure not to confuse _Status_, a kubectl display field for user intuition, with the pod's `phase`.
Pod phase is an explicit part of the Kubernetes data model and of the
[Pod API](/docs/reference/kubernetes-api/workload-resources/pod-v1/). 

```
  NAMESPACE               NAME               READY   STATUS             RESTARTS   AGE
  alessandras-namespace   alessandras-pod    0/1     CrashLoopBackOff   200        2d9h
```

A Pod is granted a term to terminate gracefully, which defaults to 30 seconds.
You can use the flag `--force` to [terminate a Pod by force](/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination-forced).
{{< /note >}}

Since Kubernetes 1.27, the kubelet transitions deleted Pods to a terminal phase
(`Failed` or `Succeeded` depending on the exit statuses of the pod containers)
before their deletion from the API server, with two exceptions:

* [static Pods](/docs/tasks/configure-pod-container/static-pod/) (which are
managed directly by the kubelet and represented by {{< glossary_tooltip
text="mirror Pods" term_id="mirror-pod" >}}) 
*  [force-deleted
Pods](/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination-forced)
without a finalizer

If a node dies or is disconnected from the rest of the cluster, Kubernetes
applies a policy for setting the `phase` of all Pods on the lost node to Failed.

## Container states

As well as the [phase](#pod-phase) of the Pod overall, Kubernetes tracks the state of
each container inside a Pod. You can use
[container lifecycle hooks](/docs/concepts/containers/container-lifecycle-hooks/) to
trigger events to run at certain points in a container's lifecycle.

Once the {{< glossary_tooltip text="scheduler" term_id="kube-scheduler" >}}
assigns a Pod to a Node, the kubelet starts creating containers for that Pod
using a {{< glossary_tooltip text="container runtime" term_id="container-runtime" >}}.
There are three possible container states: `Waiting`, `Running`, and `Terminated`.

To check the state of a Pod's containers, you can use
`kubectl describe pod <name-of-pod>`. The output shows the state for each container
within that Pod.

Each state has a specific meaning:

### `Waiting` {#container-state-waiting}

If a container is not in either the `Running` or `Terminated` state, it is `Waiting`.
A container in the `Waiting` state is still running the operations it requires in
order to complete start up: for example, pulling the container image from a container
image registry, or applying {{< glossary_tooltip text="Secret" term_id="secret" >}}
data.
When you use `kubectl` to query a Pod with a container that is `Waiting`, you also see
a Reason field to summarize why the container is in that state.

### `Running` {#container-state-running}

The `Running` status indicates that a container is executing without issues. If there
was a `postStart` hook configured, it has already executed and finished. When you use
`kubectl` to query a Pod with a container that is `Running`, you also see information
about when the container entered the `Running` state.

### `Terminated` {#container-state-terminated}

A container in the `Terminated` state began execution and then either ran to
completion or failed for some reason. When you use `kubectl` to query a Pod with
a container that is `Terminated`, you see a reason, an exit code, and the start and
finish time for that container's period of execution.

If a container has a `preStop` hook configured, this hook runs before the container enters
the `Terminated` state.

## How Pods handle problems with containers {#container-restarts}

Kubernetes manages container failures within Pods using a [`restartPolicy`](#restart-policy) defined
in the Pod `spec`. This policy determines how Kubernetes reacts to containers exiting due to errors
or other reasons, which falls in the following sequence:

1. **Initial crash**: Kubernetes attempts an immediate restart based on the Pod `restartPolicy`.
1. **Repeated crashes**: After the initial crash Kubernetes applies an exponential
   backoff delay for subsequent restarts, described in [`restartPolicy`](#restart-policy).
   This prevents rapid, repeated restart attempts from overloading the system.
1. **CrashLoopBackOff state**: This indicates that the backoff delay mechanism is currently
   in effect for a given container that is in a crash loop, failing and restarting repeatedly.
1. **Backoff reset**: If a container runs successfully for a certain duration
   (e.g., 10 minutes), Kubernetes resets the backoff delay, treating any new crash
   as the first one.

In practice, a `CrashLoopBackOff` is a condition or event that might be seen as output
from the `kubectl` command, while describing or listing Pods, when a container in the Pod
fails to start properly and then continually tries and fails in a loop.

In other words, when a container enters the crash loop, Kubernetes applies the
exponential backoff delay mentioned in the [Container restart policy](#restart-policy).
This mechanism prevents a faulty container from overwhelming the system with continuous
failed start attempts.

The `CrashLoopBackOff` can be caused by issues like the following:

* Application errors that cause the container to exit.
* Configuration errors, such as incorrect environment variables or missing
  configuration files.
* Resource constraints, where the container might not have enough memory or CPU
  to start properly.
* Health checks failing if the application doesn't start serving within the
  expected time.
* Container liveness probes or startup probes returning a `Failure` result
  as mentioned in the [probes section](#container-probes).

To investigate the root cause of a `CrashLoopBackOff` issue, a user can:

1. **Check logs**: Use `kubectl logs <name-of-pod>` to check the logs of the container.
   This is often the most direct way to diagnose the issue causing the crashes.
1. **Inspect events**: Use `kubectl describe pod <name-of-pod>` to see events
   for the Pod, which can provide hints about configuration or resource issues.
1. **Review configuration**: Ensure that the Pod configuration, including
   environment variables and mounted volumes, is correct and that all required
   external resources are available.
1. **Check resource limits**: Make sure that the container has enough CPU
   and memory allocated. Sometimes, increasing the resources in the Pod definition
   can resolve the issue.
1. **Debug application**: There might exist bugs or misconfigurations in the
   application code. Running this container image locally or in a development
   environment can help diagnose application specific issues.

### Container restarts {#restart-policy}

When a container in your Pod stops, or experiences failure, Kubernetes can restart it.
A restart isn't always appropriate; for example,
{{< glossary_tooltip text="init containers" term_id="init-container" >}} run only once (if successful),
during Pod startup.
You can configure restarts as a policy that applies to all Pods, or using container-level configuration (for example: when you define a
{{< glossary_tooltip text="sidecar container" term_id="sidecar-container" >}}) or define container-level override.

#### Container restarts and resilience {#container-restart-resilience}

The Kubernetes project recommends following cloud-native principles, including resilient
design that accounts for unannounced or arbitrary restarts. You can achieve this either
by failing the Pod and relying on automatic
[replacement](/docs/concepts/workloads/controllers/), or you can design for container-level resilience.
Either approach helps to ensure that your overall workload remains available despite
partial failure.

#### Pod-level container restart policy

The `spec` of a Pod has a `restartPolicy` field with possible values Always, OnFailure,
and Never. The default value is Always.

The `restartPolicy` for a Pod applies to {{< glossary_tooltip text="app containers" term_id="app-container" >}}
in the Pod and to regular [init containers](/docs/concepts/workloads/pods/init-containers/).
[Sidecar containers](/docs/concepts/workloads/pods/sidecar-containers/)
ignore the Pod-level `restartPolicy` field: in Kubernetes, a sidecar is defined as an
entry inside `initContainers` that has its container-level `restartPolicy` set to `Always`.
For init containers that exit with an error, the kubelet restarts the init container if
the Pod level `restartPolicy` is either `OnFailure` or `Always`:

* `Always`: Automatically restarts the container after any termination.
* `OnFailure`: Only restarts the container if it exits with an error (non-zero exit status).
* `Never`: Does not automatically restart the terminated container.

##### Restart behavior comparison

The following table shows how containers behave under different restart policies and exit codes:

| Exit Code | `restartPolicy: Always` | `restartPolicy: OnFailure` | `restartPolicy: Never` | Sidecar Containers |
|-----------|-------------------------|---------------------------|------------------------|-------------------|
| 0 (Success) | Restarts | Does not restart | Does not restart | Always restarts |
| Non-zero (Failure) | Restarts | Restarts | Does not restart | Always restarts |

{{< note >}}
The restart behavior is particularly important when choosing between Deployments and Jobs:
- **Deployments** typically use `restartPolicy: Always` (the only allowed value) to keep applications running continuously
- **Jobs** commonly use `restartPolicy: OnFailure` or `restartPolicy: Never` to handle batch processing tasks appropriately
- **Sidecar containers** are init containers that always restart regardless of the Pod's `restartPolicy` because they have their own container-level `restartPolicy: Always`
{{< /note >}}

##### Example scenarios

Here are concrete examples demonstrating the different restart behaviors:

**Example 1: Web server with `restartPolicy: Always` (typical for Deployments)**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-server
spec:
  restartPolicy: Always  # Container restarts regardless of exit code
  containers:
  - name: nginx
    image: nginx:1.14.2
    # If this container crashes or exits for any reason, it will be restarted
```

**Example 2: Batch job with `restartPolicy: OnFailure`**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: data-processor
spec:
  template:
    spec:
      restartPolicy: OnFailure  # Only restart on non-zero exit codes
      containers:
      - name: processor
        image: busybox:1.28
        command: ['sh', '-c', 'echo "Processing data..."; exit 0']
        # Exit code 0: Job completes successfully, no restart
        # Exit code 1+: Container restarts to retry the task
```

**Example 3: One-time task with `restartPolicy: Never`**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: migration-task
spec:
  restartPolicy: Never  # Never restart, regardless of exit code
  containers:
  - name: migrate
    image: busybox:1.28
    command: ['sh', '-c', 'echo "Running migration..."; exit 1']
    # Even with exit code 1 (failure), the container will not restart
    # The Pod will remain in Failed state
```

##### Sidecar containers and restart policies

[Sidecar containers](/docs/concepts/workloads/pods/sidecar-containers/) have special restart behavior that differs from regular app containers:

- **Sidecar containers ignore Pod-level `restartPolicy`**: They use their own container-level `restartPolicy` field, which is always set to `Always`
- **Independent lifecycle**: Sidecar containers can restart independently of the main application container
- **Persistent operation**: Sidecar containers remain running throughout the Pod's lifetime to provide supporting services

**Example: Pod with sidecar container**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-sidecar
spec:
  restartPolicy: OnFailure  # Applies to main container only
  initContainers:
  - name: logging-sidecar    # This is a sidecar container
    image: fluent/fluent-bit:1.8
    restartPolicy: Always    # Sidecar always restarts regardless of exit code
    # Provides logging services throughout Pod lifetime
  containers:
  - name: main-app          # This follows Pod-level restartPolicy
    image: nginx:1.14.2
    # Will only restart on failure (non-zero exit) due to Pod's OnFailure policy
```

{{< note >}}
While the main application container follows the Pod's `restartPolicy: OnFailure`, the sidecar container will restart regardless of its exit code because sidecar containers always have `restartPolicy: Always` at the container level.
{{< /note >}}

When the kubelet is handling container restarts according to the configured restart
policy, that only applies to restarts that make replacement containers inside the
same Pod and running on the same node. After containers in a Pod exit, the kubelet
restarts them with an exponential backoff delay (10s, 20s, 40s, …), that is capped at
300 seconds (5 minutes). Once a container has executed for 10 minutes without any
problems, the kubelet resets the

<!-- … truncated … -->
