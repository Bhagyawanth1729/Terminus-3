<!-- Source: https://kubernetes.io/docs/concepts/workloads/controllers/deployment.md -->
<!-- Upstream raw: https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/controllers/deployment.md -->
<!-- License: Apache-2.0 (Kubernetes website / documentation) -->
<!-- Truncated locally for image size; consult upstream for full text. -->

---
reviewers:
- janetkuo
title: Deployments
api_metadata:
- apiVersion: "apps/v1"
  kind: "Deployment"
feature:
  title: Automated rollouts and rollbacks
  description: >
    Kubernetes progressively rolls out changes to your application or its configuration, while monitoring application health to ensure it doesn't kill all your instances at the same time. If something goes wrong, Kubernetes will rollback the change for you. Take advantage of a growing ecosystem of deployment solutions.
description: >-
  A Deployment manages a set of Pods to run an application workload, usually one that doesn't maintain state.
content_type: concept
weight: 10
hide_summary: true # Listed separately in section index
---

<!-- overview -->

A _Deployment_ provides declarative updates for {{< glossary_tooltip text="Pods" term_id="pod" >}} and
{{< glossary_tooltip term_id="replica-set" text="ReplicaSets" >}}.

You describe a _desired state_ in a Deployment, and the Deployment {{< glossary_tooltip term_id="controller" >}} changes the actual state to the desired state at a controlled rate. You can define Deployments to create new ReplicaSets, or to remove existing Deployments and adopt all their resources with new Deployments.

{{< note >}}
Do not manage ReplicaSets owned by a Deployment. Consider opening an issue in the main Kubernetes repository if your use case is not covered below.
{{< /note >}}

<!-- body -->

## Use Case

The following are typical use cases for Deployments:

* [Create a Deployment to rollout a ReplicaSet](#creating-a-deployment). The ReplicaSet creates Pods in the background. Check the status of the rollout to see if it succeeds or not.
* [Declare the new state of the Pods](#updating-a-deployment) by updating the PodTemplateSpec of the Deployment. A new ReplicaSet is created, and the Deployment gradually scales it up while scaling down the old ReplicaSet, ensuring Pods are replaced at a controlled rate. Each new ReplicaSet updates the revision of the Deployment.
* [Rollback to an earlier Deployment revision](#rolling-back-a-deployment) if the current state of the Deployment is not stable. Each rollback updates the revision of the Deployment.
* [Scale up the Deployment to facilitate more load](#scaling-a-deployment).
* [Pause the rollout of a Deployment](#pausing-and-resuming-a-deployment) to apply multiple fixes to its PodTemplateSpec and then resume it to start a new rollout.
* [Use the status of the Deployment](#deployment-status) as an indicator that a rollout has stuck.
* [Clean up older ReplicaSets](#clean-up-policy) that you don't need anymore.

## Creating a Deployment

The following is an example of a Deployment. It creates a ReplicaSet to bring up three `nginx` Pods:

{{% code_sample file="controllers/nginx-deployment.yaml" %}}

In this example:

* A Deployment named `nginx-deployment` is created, indicated by the
  `.metadata.name` field. This name will become the basis for the ReplicaSets
  and Pods which are created later. See [Writing a Deployment Spec](#writing-a-deployment-spec)
  for more details.
* The Deployment creates a ReplicaSet that creates three replicated Pods, indicated by the `.spec.replicas` field.
* The `.spec.selector` field defines how the created ReplicaSet finds which Pods to manage.
  In this case, you select a label that is defined in the Pod template (`app: nginx`).
  However, more sophisticated selection rules are possible,
  as long as the Pod template itself satisfies the rule.

  {{< note >}}
  The `.spec.selector.matchLabels` field is a map of {key,value} pairs.
  A single {key,value} in the `matchLabels` map is equivalent to an element of `matchExpressions`,
  whose `key` field is "key", the `operator` is "In", and the `values` array contains only "value".
  All of the requirements, from both `matchLabels` and `matchExpressions`, must be satisfied in order to match.
  {{< /note >}}

* The `.spec.template` field contains the following sub-fields:
  * The Pods are labeled `app: nginx`using the `.metadata.labels` field.
  * The Pod template's specification, or `.spec` field, indicates that
    the Pods run one container, `nginx`, which runs the `nginx`
    [Docker Hub](https://hub.docker.com/) image at version 1.14.2.
  * Create one container and name it `nginx` using the `.spec.containers[0].name` field.

Before you begin, make sure your Kubernetes cluster is up and running.
Follow the steps given below to create the above Deployment:

1. Create the Deployment by running the following command:

   ```shell
   kubectl apply -f https://k8s.io/examples/controllers/nginx-deployment.yaml
   ```

2. Run `kubectl get deployments` to check if the Deployment was created.

   If the Deployment is still being created, the output is similar to the following:
   ```
   NAME               READY   UP-TO-DATE   AVAILABLE   AGE
   nginx-deployment   0/3     0            0           1s
   ```
   When you inspect the Deployments in your cluster, the following fields are displayed:
   * `NAME` lists the names of the Deployments in the namespace.
   * `READY` displays how many replicas of the application are available to your users. It follows the pattern ready/desired.
   * `UP-TO-DATE` displays the number of replicas that have been updated to achieve the desired state.
   * `AVAILABLE` displays how many replicas of the application are available to your users.
   * `AGE` displays the amount of time that the application has been running.

   Notice how the number of desired replicas is 3 according to `.spec.replicas` field.

3. To see the Deployment rollout status, run `kubectl rollout status deployment/nginx-deployment`.

   The output is similar to:
   ```
   Waiting for rollout to finish: 2 out of 3 new replicas have been updated...
   deployment "nginx-deployment" successfully rolled out
   ```

4. Run the `kubectl get deployments` again a few seconds later.
   The output is similar to this:
   ```
   NAME               READY   UP-TO-DATE   AVAILABLE   AGE
   nginx-deployment   3/3     3            3           18s
   ```
   Notice that the Deployment has created all three replicas, and all replicas are up-to-date (they contain the latest Pod template) and available.

5. To see the ReplicaSet (`rs`) created by the Deployment, run `kubectl get rs`. The output is similar to this:
   ```
   NAME                          DESIRED   CURRENT   READY   AGE
   nginx-deployment-75675f5897   3         3         3       18s
   ```
   ReplicaSet output shows the following fields:

   * `NAME` lists the names of the ReplicaSets in the namespace.
   * `DESIRED` displays the desired number of _replicas_ of the application, which you define when you create the Deployment. This is the _desired state_.
   * `CURRENT` displays how many replicas are currently running.
   * `READY` displays how many replicas of the application are available to your users.
   * `AGE` displays the amount of time that the application has been running.

   Notice that the name of the ReplicaSet is always formatted as
   `[DEPLOYMENT-NAME]-[HASH]`. This name will become the basis for the Pods
   which are created.

   The `HASH` string is the same as the `pod-template-hash` label on the ReplicaSet.

6. To see the labels automatically generated for each Pod, run `kubectl get pods --show-labels`.
   The output is similar to:
   ```
   NAME                                READY     STATUS    RESTARTS   AGE       LABELS
   nginx-deployment-75675f5897-7ci7o   1/1       Running   0          18s       app=nginx,pod-template-hash=75675f5897
   nginx-deployment-75675f5897-kzszj   1/1       Running   0          18s       app=nginx,pod-template-hash=75675f5897
   nginx-deployment-75675f5897-qqcnn   1/1       Running   0          18s       app=nginx,pod-template-hash=75675f5897
   ```
   The created ReplicaSet ensures that there are three `nginx` Pods.

{{< note >}}
You must specify an appropriate selector and Pod template labels in a Deployment
(in this case, `app: nginx`).

Do not overlap labels or selectors with other controllers (including other Deployments and StatefulSets). Kubernetes doesn't stop you from overlapping, and if multiple controllers have overlapping selectors those controllers might conflict and behave unexpectedly.
{{< /note >}}

### Pod-template-hash label

{{< caution >}}
Do not change this label.
{{< /caution >}}

The `pod-template-hash` label is added by the Deployment controller to every ReplicaSet that a Deployment creates or adopts.

This label ensures that child ReplicaSets of a Deployment do not overlap. It is generated by hashing the `PodTemplate` of the ReplicaSet and using the resulting hash as the label value that is added to the ReplicaSet selector, Pod template labels,
and in any existing Pods that the ReplicaSet might have.

## Updating a Deployment

{{< note >}}
A Deployment's rollout is triggered if and only if the Deployment's Pod template (that is, `.spec.template`)
is changed, for example if the labels or container images of the template are updated. Other updates, such as scaling the Deployment, do not trigger a rollout.
{{< /note >}}

Follow the steps given below to update your Deployment:

1. Let's update the nginx Pods to use the `nginx:1.16.1` image instead of the `nginx:1.14.2` image.

   ```shell
   kubectl set image deployment.v1.apps/nginx-deployment nginx=nginx:1.16.1
   ```

   or use the following command:

   ```shell
   kubectl set image deployment/nginx-deployment nginx=nginx:1.16.1
   ```
   where `deployment/nginx-deployment` indicates the Deployment,
   `nginx` indicates the Container the update will take place and
   `nginx:1.16.1` indicates the new image and its tag.


   The output is similar to:

   ```
   deployment.apps/nginx-deployment image updated
   ```

   Alternatively, you can `edit` the Deployment and change `.spec.template.spec.containers[0].image` from `nginx:1.14.2` to `nginx:1.16.1`:

   ```shell
   kubectl edit deployment/nginx-deployment
   ```

   The output is similar to:

   ```
   deployment.apps/nginx-deployment edited
   ```

2. To see the rollout status, run:

   ```shell
   kubectl rollout status deployment/nginx-deployment
   ```

   The output is similar to this:

   ```
   Waiting for rollout to finish: 2 out of 3 new replicas have been updated...
   ```

   or

   ```
   deployment "nginx-deployment" successfully rolled out
   ```

Get more details on your updated Deployment:

* After the rollout succeeds, you can view the Deployment by running `kubectl get deployments`.
  The output is similar to this:

  ```
  NAME               READY   UP-TO-DATE   AVAILABLE   AGE
  nginx-deployment   3/3     3            3           36s
  ```

* Run `kubectl get rs` to see that the Deployment updated the Pods by creating a new ReplicaSet and scaling it
up to 3 replicas, as well as scaling down the old ReplicaSet to 0 replicas.

  ```shell
  kubectl get rs
  ```

  The output is similar to this:
  ```
  NAME                          DESIRED   CURRENT   READY   AGE
  nginx-deployment-1564180365   3         3         3       6s
  nginx-deployment-2035384211   0         0         0       36s
  ```

* Running `get pods` should now show only the new Pods:

  ```shell
  kubectl get pods
  ```

  The output is similar to this:
  ```
  NAME                                READY     STATUS    RESTARTS   AGE
  nginx-deployment-1564180365-khku8   1/1       Running   0          14s
  nginx-deployment-1564180365-nacti   1/1       Running   0          14s
  nginx-deployment-1564180365-z9gth   1/1       Running   0          14s
  ```

  Next time you want to update these Pods, you only need to update the Deployment's Pod template again.

  Deployment ensures that only a certain number of Pods are down while they are being updated. By default,
  it ensures that at least 75% of the desired number of Pods are up (25% max unavailable).

  Deployment also ensures that only a certain number of Pods are created above the desired number of Pods.
  By default, it ensures that at most 125% of the desired number of Pods are up (25% max surge).

  For example, if you look at the above Deployment closely, you will see that it first creates a new Pod,
  then deletes an old Pod, and creates another new one. It does not kill old Pods until a sufficient number of
  new Pods have come up, and does not create new Pods until a sufficient number of old Pods have been killed.
  It makes sure that at least 3 Pods are available and that at max 4 Pods in total are available. In case of
  a Deployment with 4 replicas, the number of Pods would be between 3 and 5.

* Get details of your Deployment:
  ```shell
  kubectl describe deployments
  ```
  The output is similar to this:
  ```
  Name:                   nginx-deployment
  Namespace:              default
  CreationTimestamp:      Thu, 30 Nov 2017 10:56:25 +0000
  Labels:                 app=nginx
  Annotations:            deployment.kubernetes.io/revision=2
  Selector:               app=nginx
  Replicas:               3 desired | 3 updated | 3 total | 3 available | 0 unavailable
  StrategyType:           RollingUpdate
  MinReadySeconds:        0
  RollingUpdateStrategy:  25% max unavailable, 25% max surge
  Pod Template:
    Labels:  app=nginx
     Containers:
      nginx:
        Image:        nginx:1.16.1
        Port:         80/TCP
        Environment:  <none>
        Mounts:       <none>
      Volumes:        <none>
    Conditions:
      Type           Status  Reason
      ----           ------  ------
      Available      True    MinimumReplicasAvailable
      Progressing    True    NewReplicaSetAvailable
    OldReplicaSets:  <none>
    NewReplicaSet:   nginx-deployment-1564180365 (3/3 replicas created)
    Events:
      Type    Reason             Age   From                   Message
      ----    ------             ----  ----                   -------
      Normal  ScalingReplicaSet  2m    deployment-controller  Scaled up replica set nginx-deployment-2035384211 to 3
      Normal  ScalingReplicaSet  24s   deployment-controller  Scaled up replica set nginx-deployment-1564180365 to 1
      Normal  ScalingReplicaSet  22s   deployment-controller  Scaled down replica set nginx-deployment-2035384211 to 2
      Normal  ScalingReplicaSet  22s   deployment-controller  Scaled up replica set nginx-deployment-1564180365 to 2
      Normal  ScalingReplicaSet  19s   deployment-controller  Scaled down replica set nginx-deployment-2035384211 to 1
      Normal  ScalingReplicaSet  19s   deployment-controller  Scaled up replica set nginx-deployment-1564180365 to 3
      Normal  ScalingReplicaSet  14s   deployment-controller  Scaled down replica set nginx-deployment-2035384211 to 0
  ```
  Here you see that when you first created the Deployment, it created a ReplicaSet (nginx-deployment-2035384211)
  and scaled it up to 3 replicas directly. When you updated the Deployment, it created a new ReplicaSet
  (nginx-deployment-1564180365) and scaled it up to 1 and waited for it to come up. Then it scaled down the old ReplicaSet
  to 2 and scaled up the new ReplicaSet to 2 so that at least 3 Pods were available and at most 4 Pods were created at all times.
  It then continued scaling up and down the new and the old ReplicaSet, with the same rolling update strategy.
  Finally, you'll have 3 available replicas in the new ReplicaSet, and the old ReplicaSet is scaled down to 0.

{{< note >}}
Kubernetes doesn't count terminating Pods when calculating the number of `availableReplicas`, which must be between
`replicas - maxUnavailable` and `replicas + maxSurge`. As a result, you might notice that there are more Pods than
expected during a rollout, and that the total resources consumed by the Deployment is more than `replicas + maxSurge`
until the `terminationGracePeriodSeconds` of the terminating Pods expires.
{{< /note >}}

### Rollover (aka multiple updates in-flight)

Each time a new Deployment is observed by the Deployment controller, a ReplicaSet is created to bring up
the desired Pods. If the Deployment is updated, the existing ReplicaSet that controls Pods whose labels
match `.spec.selector` but whose template does not match `.spec.template` is scaled down. Eventually, the new
ReplicaSet is scaled to `.spec.replicas` and all old ReplicaSets is scaled to 0.

If you update a Deployment while an existing rollout is in progress, the Deployment creates a new ReplicaSet
as per the update and start scaling that up, and rolls over the ReplicaSet that it was scaling up previously
-- it will add it to its list of old ReplicaSets and start scaling it down.

For example, suppose you create a Deployment to create 5 replicas of `nginx:1.14.2`,
but then update the Deployment to create 5 replicas of `nginx:1.16.1`, when only 3
replicas of `nginx:1.14.2` had been created. In that case, the Deployment immediately starts
killing the 3 `nginx:1.14.2` Pods that it had created, and starts creating
`nginx:1.16.1` Pods. It does not wait for the 5 replicas of `nginx:1.14.2` to be created
before changing course.

### Label selector updates

It is generally discouraged to make label selector updates and it is suggested to plan your selectors up front.
A Deployment's label selector is **immutable** after creation;
it cannot be updated via `kubectl patch`, `kubectl edit`, `kubectl apply`, or tools like `helm upgrade`.

If you must change the selector, you have to delete the Deployment and recreate it.
By default, deleting the Deployment also deletes its running Pods, causing downtime; use
`--cascade=orphan` if you need those Pods to keep running while you recreate the Deployment
(see the implications below).
Exercise great caution and ensure you grasp the following implications:

* **Additions:** When you create a new Deployment with a narrower selector, the new Deployment **must** also have a suitable Pod template.
  If you have an existing manifest and you edit the manifest to narrow the selector, you need to edit the metadata of the Pod template inside that Deployment, adding the
  new labels
  to match, as otherwise the API server returns a validation error. This is a _non-overlapping_ change:
  the new Deployment will not "see" the old Pods (which lack the new label), causing the old
  ReplicaSet to be **orphaned** and a brand-new ReplicaSet to be created.
* **Value Updates:** Changing the existing value in a selector key (e.g., from `v1` to `v2`)
  results in the same behavior as additions (orphaning and recreation).
* **Removals:** Removing an existing key from the Deployment selector does not require any changes
  in the Pod template labels. This is an _overlapping_ change: the new, broader selector would
  match the old Pods. Existing ReplicaSets are not orphaned, and a new ReplicaSet is not created,
  but note that the removed label still exists in any existing Pods and ReplicaSets.
  You can clean that up by triggering a rollout for the Deployment.

## Rolling Back a Deployment

Sometimes, you may want to rollback a Deployment; for example, when the Deployment is not stable, such as crash looping.
By default, all of the Deployment's rollout history is kept in the system so that you can rollback anytime you want
(you can change that by modifying revision history limit).

{{< note >}}
A Deployment's revision is created when a Deployment's rollout is triggered. This means that the
new revision is created if and only if the Deployment's Pod template (`.spec.template`) is changed,
for example if you update the labels or container images of the template. Other updates, such as scaling the Deployment,
do not create a Deployment revision, so that you can facilitate simultaneous manual- or auto-scaling.
This means that when you roll back to an earlier revision, only the Deployment's Pod template part is
rolled back.
{{< /note >}}

* Suppose that you made a typo while updating the Deployment, by putting the image name as `nginx:1.161` instead of `nginx:1.16.1`:

  ```shell
  kubectl set image deployment/nginx-deployment nginx=nginx:1.161
  ```

  The output is similar to this:
  ```
  deployment.apps/nginx-deployment image updated
  ```

* The rollout gets stuck. You can verify it by checking the rollout status:

  ```shell
  kubectl rollout status deployment/nginx-deployment
  ```

  The output is similar to this:
  ```
  Waiting for rollout to finish: 1 out of 3 new replicas have been updated...
  ```

* Press Ctrl-C to stop the above rollout status watch. For more information on stuck rollouts,
[read more here](#deployment-status).

* You see that the number of old replicas (adding the replica count from
  `nginx-deployment-1564180365` and `nginx-deployment-2035384211`) is 3, and the number of
  new replicas (from `nginx-deployment-3066724191`) is 1.

  ```shell
  kubectl get rs
  ```

  The output is similar to this:
  ```
  NAME                          DESIRED   CURRENT   READY   AGE
  nginx-deployment-1564180365   3         3         3       25s
  nginx-deployment-2035384211   0         0         0       36s
  nginx-deployment-3066724191   1         1         0       6s
  ```

* Looking at the Pods created, you see that 1 Pod created by new ReplicaSet is stuck in an image pull loop.

  ```shell
  kubectl get pods
  ```

  The output is similar to this:
  ```
  NAME                                READY     STATUS             RESTARTS   AGE
  nginx-deployment-1564180365-70iae   1/1       Running            0          25s
  nginx-deployment-1564180365-jbqqo   1/1       Running            0          25s
  nginx-deployment-1564180365-hysrc   1/1       Running            0          25s
  nginx-deployment-3066724191-08mng   0/1       ImagePullBackOff   0          6s
  ```

  {{< note >}}
  The Deployment controller stops the bad rollout automatically, and stops scaling up the new ReplicaSet. This depends on the rollingUpdate parameters (`maxUnavailable` specifically) that you have specified. Kubernetes by default sets the value to 25%.
  {{< /note >}}

* Get the description of the Deployment:
  ```shell
  kubectl describe deployment
  ```

  The output is similar to this:
  ```
  Name:           nginx-deployment
  Namespace:      default
  CreationTimestamp:  Tue, 15 Mar 2016 14:48:04 -0700
  Labels:         app=nginx
  Selector:       app=nginx
  Replicas:       3 desired | 1 updated | 4 total | 3 available | 1 unavailable
  StrategyType:       RollingUpdate
  MinReadySeconds:    0
  RollingUpdateStrategy:  25% max unavailable, 25% max surge
  Pod Template:
    Labels:  app=nginx
    Containers:
     nginx:
      Image:        nginx:1.161
      Port:         80/TCP
      Host Port:    0/TCP
      Environment:  <none>
      Mounts:       <none>
    Volumes:        <none>
  Conditions:
    Type           Status  Reason
    ----           ------  ------
    Available      True    MinimumReplicasAvailable
    Progressing    True    ReplicaSetUpdated
  OldReplicaSets:     nginx-deployment-1564180365 (3/3 replicas created)
  NewReplicaSet:      nginx-deployment-3066724191 (1/1 replicas created)
  Events:
    FirstSeen LastSeen    Count   From                    SubObjectPath   Type        Reason              Message
    --------- --------    -----   ----                    -------------   --------    ------              -------
    1m        1m          1       {deployment-controller }                Normal      ScalingReplicaSet   Scaled up replica set nginx-deployment-2035384211 to 3
    22s       22s         1       {deployment-controller }                Normal      ScalingReplicaSet   Scaled up replica set nginx-deployment-1564180365 to 1
    22s       22s         1       {deployment-controller }                Normal      ScalingReplicaSet   Scaled down replica set nginx-deployment-2035384211 to 2
    22s       22s         1       {deployment-controller }                Normal      ScalingReplicaSet   Scaled up replica set nginx-deployment-1564180365 to 2
    21s       21s         1       {deployment-controller }                Normal      ScalingReplicaSet   Scaled down replica set nginx-deployment-2035384211 to 1
    21s       21s         1       {deployment-controller }                Normal      ScalingReplicaSet   Scaled up replica set nginx-deployment-1564180365 to 3
    13s       13s         1       {deployment-controller }                Normal      ScalingReplicaSet   Scaled down replica set nginx-deployment-2035384211 to 0
    13s       13s         1       {deployment-controller }                Normal      ScalingReplicaSet   Scaled up replica set nginx-deployment-3066724191 to 1
  ```

  To fix this, you need to rollback to a previous revision of Deployment that is stable.

### Checking Rollout History of a Deployment

Follow the steps given below to check the rollout history:

1. First, check the revisions of this Deployment:
   ```shell
   kubectl rollout history deployment/nginx-deployment
   ```
   The output is similar to this:
   ```
   deployments "nginx-deployment"
   REVISION    CHANGE-CAUSE
   1           <none>
   2           <none>
   3           <none>
   ```

   `CHANGE-CAUSE` is copied from the Deployment annotation `kubernetes.io/change-cause` to its revisions upon creation. You can specify the`CHANGE-CAUSE` message by:

   * Annotating the Deployment with `kubectl annotate deployment/nginx-deployment kubernetes.io/change-cause="image updated to 1.16.1"`
   * Manually editing the manifest of the resource.
   * Using tooling that sets the annotation automatically.

   {{< note >}}
   In older versions of Kubernetes, you could use the `--record` flag with kubectl commands to automatically populate the `CHANGE-CAUSE` field. This flag is deprecated and will be removed in a future release.
   {{< /note >}}

2. To see the details of each revision, run:
   ```shell
   kubectl rollout history deployment/nginx-deployment --revision=2
   ```

   The output is similar to this:
   ```
   deployments "nginx-deployment" revision 2
     Labels:       app=nginx
             pod-template-hash=1159050644
     Containers:
      nginx:
       Image:      nginx:1.16.1
       Port:       80/TCP
        QoS Tier:
           cpu:      BestEffort
           memory:   BestEffort
       Environment Variables:      <none>
     No volumes.
   ```

### Rolling Back to a Previous Revision
Follow the steps given below to rollback the Deployment from the current version to the previous version, which is version 2.

1. Now you've decided to undo the current rollout and rollback to the previous revision:
   ```shell
   kubectl rollout undo deployment/nginx-deployment
   ```

   The output is similar to this:
   ```
   deployment.apps/nginx-deployment rolled back
   ```
   Alternatively, you can rollback to a specific revision by specifying it with `--to-revision`:

   ```shell
   kubectl rollout undo deployment/nginx-deployment --to-revision=2
   ```

   The output is similar to this:
   ```
   deployment.apps/nginx-deployment rolled back
   ```

   For more details about rollout related commands, read [`kubectl rollout`](/docs/reference/generated/kubectl/kubectl-commands#rollout).

   The Deployment is now rolled back to a previous stable revision. As you can see, a `DeploymentRollback` event
   for rolling back to revision 2 is generated from Deployment controller.

2. Check if the rollback was successful and the Deployment is running as expected, run:
   ```shell
   kubectl get deployment nginx-deployment
   ```

   The output is similar to this:
   ```
   NAME               READY   UP-TO-DATE   AVAILABLE   AGE
   nginx-deployment   3/3     3            3           30m
   ```
3. Get the description of the Deployment:
   ```shell
   kubectl describe deployment nginx-deployment
   ```
   The output is similar to this:
   ```
   Name:                   nginx-deployment
   Namespace:              default
   CreationTimestamp:      Sun, 02 Sep 2018 18:17:55 -0500
   Labels:                 app=nginx
   Annotations:            deployment.kubernetes.io/revision=

<!-- … truncated … -->
