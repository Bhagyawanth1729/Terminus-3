<!-- Source: https://kubernetes.io/docs/concepts/storage/persistent-volumes.md -->
<!-- Upstream raw: https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/storage/persistent-volumes.md -->
<!-- License: Apache-2.0 (Kubernetes website / documentation) -->
<!-- Truncated locally for image size; consult upstream for full text. -->

---
reviewers:
- jsafrane
- saad-ali
- thockin
- msau42
- xing-yang
title: Persistent Volumes
api_metadata:
- apiVersion: "v1"
  kind: "PersistentVolume"
- apiVersion: "v1"
  kind: "PersistentVolumeClaim"
feature:
  title: Storage orchestration
  description: >
    Automatically mount the storage system of your choice, whether from local storage, a public cloud provider, or a network storage system such as iSCSI or NFS.
content_type: concept
weight: 20
---

<!-- overview -->

This document describes _persistent volumes_ in Kubernetes. Familiarity with
[volumes](/docs/concepts/storage/volumes/), [StorageClasses](/docs/concepts/storage/storage-classes/)
and [VolumeAttributesClasses](/docs/concepts/storage/volume-attributes-classes/) is suggested.

<!-- body -->

## Introduction

Managing storage is a distinct problem from managing compute instances.
The PersistentVolume subsystem provides an API for users and administrators
that abstracts details of how storage is provided from how it is consumed.
To do this, we introduce two new API resources: PersistentVolume and PersistentVolumeClaim.

A _PersistentVolume_ (PV) is a piece of storage in the cluster that has been
provisioned by an administrator or dynamically provisioned using
[Storage Classes](/docs/concepts/storage/storage-classes/). It is a resource in
the cluster just like a node is a cluster resource. PVs are volume plugins like
Volumes, but have a lifecycle independent of any individual Pod that uses the PV.
This API object captures the details of the implementation of the storage, be that
NFS, iSCSI, or a cloud-provider-specific storage system.

A _PersistentVolumeClaim_ (PVC) is a request for storage by a user. It is similar
to a Pod. Pods consume node resources and PVCs consume PV resources. Pods can
request specific levels of resources (CPU and Memory). Claims can request specific
size and access modes (e.g., they can be mounted ReadWriteOnce, ReadOnlyMany,
ReadWriteMany, or ReadWriteOncePod, see [AccessModes](#access-modes)).

While PersistentVolumeClaims allow a user to consume abstract storage resources,
it is common that users need PersistentVolumes with varying properties, such as
performance, for different problems. Cluster administrators need to be able to
offer a variety of PersistentVolumes that differ in more ways than size and access
modes, without exposing users to the details of how those volumes are implemented.
For these needs, there is the _StorageClass_ resource.

See the [detailed walkthrough with working examples](/docs/tutorials/configuration/configure-persistent-volume-storage).

## Lifecycle of a volume and claim

PVs are resources in the cluster. PVCs are requests for those resources and also act
as claim checks to the resource. The interaction between PVs and PVCs follows this lifecycle:

### Provisioning

There are two ways PVs may be provisioned: statically or dynamically.

#### Static

A cluster administrator creates a number of PVs. They carry the details of the
real storage, which is available for use by cluster users. They exist in the
Kubernetes API and are available for consumption.

#### Dynamic

When none of the static PVs the administrator created match a user's PersistentVolumeClaim,
the cluster may try to dynamically provision a volume specially for the PVC.
This provisioning is based on StorageClasses: the PVC must request a
[storage class](/docs/concepts/storage/storage-classes/) and
the administrator must have created and configured that class for dynamic
provisioning to occur. Claims that request the class `""` effectively disable
dynamic provisioning for themselves.

To enable dynamic storage provisioning based on storage class, the cluster administrator
needs to enable the `DefaultStorageClass`
[admission controller](/docs/reference/access-authn-authz/admission-controllers/#defaultstorageclass)
on the API server. This can be done, for example, by ensuring that `DefaultStorageClass` is
among the comma-delimited, ordered list of values for the `--enable-admission-plugins` flag of
the API server component. For more information on API server command-line flags,
check [kube-apiserver](/docs/reference/command-line-tools-reference/kube-apiserver/) documentation.

### Binding

A user creates, or in the case of dynamic provisioning, has already created,
a PersistentVolumeClaim with a specific amount of storage requested and with
certain access modes. A control loop in the control plane watches for new PVCs, finds
a matching PV (if possible), and binds them together. If a PV was dynamically
provisioned for a new PVC, the loop will always bind that PV to the PVC. Otherwise,
the user will always get at least what they asked for, but the volume may be in
excess of what was requested. Once bound, PersistentVolumeClaim binds are exclusive,
regardless of how they were bound. A PVC to PV binding is a one-to-one mapping,
using a ClaimRef which is a bi-directional binding between the PersistentVolume
and the PersistentVolumeClaim.

Claims will remain unbound indefinitely if a matching volume does not exist.
Claims will be bound as matching volumes become available. For example, a
cluster provisioned with many 50Gi PVs would not match a PVC requesting 100Gi.
The PVC can be bound when a 100Gi PV is added to the cluster.

### Using

Pods use claims as volumes. The cluster inspects the claim to find the bound
volume and mounts that volume for a Pod. For volumes that support multiple
access modes, the user specifies which mode is desired when using their claim
as a volume in a Pod.

Once a user has a claim and that claim is bound, the bound PV belongs to the
user for as long as they need it. Users schedule Pods and access their claimed
PVs by including a `persistentVolumeClaim` section in a Pod's `volumes` block.
See [Claims As Volumes](#claims-as-volumes) for more details on this.

### Storage Object in Use Protection

The purpose of the Storage Object in Use Protection feature is to ensure that
PersistentVolumeClaims (PVCs) in active use by a Pod and PersistentVolume (PVs)
that are bound to PVCs are not removed from the system, as this may result in data loss.

{{< note >}}
PVC is in active use by a Pod when a Pod object exists that is using the PVC.
{{< /note >}}

If a user deletes a PVC in active use by a Pod, the PVC is not removed immediately.
PVC removal is postponed until the PVC is no longer actively used by any Pods. Also,
if an admin deletes a PV that is bound to a PVC, the PV is not removed immediately.
PV removal is postponed until the PV is no longer bound to a PVC.

You can see that a PVC is protected when the PVC's status is `Terminating` and the
`Finalizers` list includes `kubernetes.io/pvc-protection`:

```shell
kubectl describe pvc hostpath
Name:          hostpath
Namespace:     default
StorageClass:  example-hostpath
Status:        Terminating
Volume:
Labels:        <none>
Annotations:   volume.beta.kubernetes.io/storage-class=example-hostpath
               volume.beta.kubernetes.io/storage-provisioner=example.com/hostpath
Finalizers:    [kubernetes.io/pvc-protection]
...
```

You can see that a PV is protected when the PV's status is `Terminating` and
the `Finalizers` list includes `kubernetes.io/pv-protection` too:

```shell
kubectl describe pv task-pv-volume
Name:            task-pv-volume
Labels:          type=local
Annotations:     <none>
Finalizers:      [kubernetes.io/pv-protection]
StorageClass:    standard
Status:          Terminating
Claim:
Reclaim Policy:  Delete
Access Modes:    RWO
Capacity:        1Gi
Message:
Source:
    Type:          HostPath (bare host directory volume)
    Path:          /tmp/data
    HostPathType:
Events:            <none>
```

### Reclaiming

When a user is done with their volume, they can delete the PVC objects from the
API that allows reclamation of the resource. The reclaim policy for a PersistentVolume
tells the cluster what to do with the volume after it has been released of its claim.
Currently, volumes can either be Retained, Recycled, or Deleted.

#### Retain

The `Retain` reclaim policy allows for manual reclamation of the resource.
When the PersistentVolumeClaim is deleted, the PersistentVolume still exists
and the volume is considered "released". But it is not yet available for
another claim because the previous claimant's data remains on the volume.
An administrator can manually reclaim the volume with the following steps.

1. Delete the PersistentVolume. The associated storage asset in external infrastructure
   still exists after the PV is deleted.
1. Manually clean up the data on the associated storage asset accordingly.
1. Manually delete the associated storage asset.

If you want to reuse the same storage asset, create a new PersistentVolume with
the same storage asset definition.

#### Delete

For volume plugins that support the `Delete` reclaim policy, deletion removes
both the PersistentVolume object from Kubernetes, as well as the associated
storage asset in the external infrastructure. Volumes that were dynamically provisioned
inherit the [reclaim policy of their StorageClass](#reclaim-policy), which
defaults to `Delete`. The administrator should configure the StorageClass
according to users' expectations; otherwise, the PV must be edited or
patched after it is created. See
[Change the Reclaim Policy of a PersistentVolume](/docs/tasks/administer-cluster/change-pv-reclaim-policy/).

#### Recycle

{{< warning >}}
The `Recycle` reclaim policy is deprecated. Instead, the recommended approach
is to use dynamic provisioning.
{{< /warning >}}

If supported by the underlying volume plugin, the `Recycle` reclaim policy performs
a basic scrub (`rm -rf /thevolume/*`) on the volume and makes it available again for a new claim.

However, an administrator can configure a custom recycler Pod template using
the Kubernetes controller manager command line arguments as described in the
[reference](/docs/reference/command-line-tools-reference/kube-controller-manager/).
The custom recycler Pod template must contain a `volumes` specification, as
shown in the example below:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pv-recycler
  namespace: default
spec:
  restartPolicy: Never
  volumes:
  - name: vol
    hostPath:
      path: /any/path/it/will/be/replaced
  containers:
  - name: pv-recycler
    image: "registry.k8s.io/busybox"
    command: ["/bin/sh", "-c", "test -e /scrub && rm -rf /scrub/..?* /scrub/.[!.]* /scrub/*  && test -z \"$(ls -A /scrub)\" || exit 1"]
    volumeMounts:
    - name: vol
      mountPath: /scrub
```

However, the particular path specified in the custom recycler Pod template in the
`volumes` part is replaced with the particular path of the volume that is being recycled.

### PersistentVolume deletion protection finalizer
{{< feature-state feature_gate_name="HonorPVReclaimPolicy" >}}

Finalizers can be added on a PersistentVolume to ensure that PersistentVolumes
having `Delete` reclaim policy are deleted only after the backing storage are deleted.

The finalizer `external-provisioner.volume.kubernetes.io/finalizer`(introduced
in  v1.31) is added to both dynamically provisioned and statically provisioned
CSI volumes.

The finalizer `kubernetes.io/pv-controller`(introduced in v1.31) is added to 
dynamically provisioned in-tree plugin volumes and skipped for statically 
provisioned in-tree plugin volumes.

The following is an example of dynamically provisioned in-tree plugin volume:

```shell
kubectl describe pv pvc-74a498d6-3929-47e8-8c02-078c1ece4d78
Name:            pvc-74a498d6-3929-47e8-8c02-078c1ece4d78
Labels:          <none>
Annotations:     kubernetes.io/createdby: vsphere-volume-dynamic-provisioner
                 pv.kubernetes.io/bound-by-controller: yes
                 pv.kubernetes.io/provisioned-by: kubernetes.io/vsphere-volume
Finalizers:      [kubernetes.io/pv-protection kubernetes.io/pv-controller]
StorageClass:    vcp-sc
Status:          Bound
Claim:           default/vcp-pvc-1
Reclaim Policy:  Delete
Access Modes:    RWO
VolumeMode:      Filesystem
Capacity:        1Gi
Node Affinity:   <none>
Message:
Source:
    Type:               vSphereVolume (a Persistent Disk resource in vSphere)
    VolumePath:         [vsanDatastore] d49c4a62-166f-ce12-c464-020077ba5d46/kubernetes-dynamic-pvc-74a498d6-3929-47e8-8c02-078c1ece4d78.vmdk
    FSType:             ext4
    StoragePolicyName:  vSAN Default Storage Policy
Events:                 <none>
```

The finalizer `external-provisioner.volume.kubernetes.io/finalizer` is added for CSI volumes.
The following is an example:

```shell
Name:            pvc-2f0bab97-85a8-4552-8044-eb8be45cf48d
Labels:          <none>
Annotations:     pv.kubernetes.io/provisioned-by: csi.vsphere.vmware.com
Finalizers:      [kubernetes.io/pv-protection external-provisioner.volume.kubernetes.io/finalizer]
StorageClass:    fast
Status:          Bound
Claim:           demo-app/nginx-logs
Reclaim Policy:  Delete
Access Modes:    RWO
VolumeMode:      Filesystem
Capacity:        200Mi
Node Affinity:   <none>
Message:
Source:
    Type:              CSI (a Container Storage Interface (CSI) volume source)
    Driver:            csi.vsphere.vmware.com
    FSType:            ext4
    VolumeHandle:      44830fa8-79b4-406b-8b58-621ba25353fd
    ReadOnly:          false
    VolumeAttributes:      storage.kubernetes.io/csiProvisionerIdentity=1648442357185-8081-csi.vsphere.vmware.com
                           type=vSphere CNS Block Volume
Events:                <none>
```

When the `CSIMigration{provider}` feature flag is enabled for a specific in-tree volume plugin,
the `kubernetes.io/pv-controller` finalizer is replaced by the
`external-provisioner.volume.kubernetes.io/finalizer` finalizer.

The finalizers ensure that the PV object is removed only after the volume is deleted
from the storage backend provided the reclaim policy of the PV is `Delete`. This
also ensures that the volume is deleted from storage backend irrespective of the
order of deletion of PV and PVC.

### Reserving a PersistentVolume

The control plane can [bind PersistentVolumeClaims to matching PersistentVolumes](#binding)
in the cluster. However, if you want a PVC to bind to a specific PV, you need to pre-bind them.

By specifying a PersistentVolume in a PersistentVolumeClaim, you declare a binding
between that specific PV and PVC. If the PersistentVolume exists and has not reserved
PersistentVolumeClaims through its `claimRef` field, then the PersistentVolume and
PersistentVolumeClaim will be bound.

The binding happens regardless of some volume matching criteria, including node affinity.
The control plane still checks that [storage class](/docs/concepts/storage/storage-classes/),
access modes, and requested storage size are valid.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: foo-pvc
  namespace: foo
spec:
  storageClassName: "" # Empty string must be explicitly set otherwise default StorageClass will be set
  volumeName: foo-pv
  ...
```

This method does not guarantee any binding privileges to the PersistentVolume.
If other PersistentVolumeClaims could use the PV that you specify, you first
need to reserve that storage volume. Specify the relevant PersistentVolumeClaim
in the `claimRef` field of the PV so that other PVCs can not bind to it.

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: foo-pv
spec:
  storageClassName: ""
  claimRef:
    name: foo-pvc
    namespace: foo
  ...
```

This is useful if you want to consume PersistentVolumes that have their `persistentVolumeReclaimPolicy` set
to `Retain`, including cases where you are reusing an existing PV.

### Expanding Persistent Volumes Claims

{{< feature-state for_k8s_version="v1.24" state="stable" >}}

Support for expanding PersistentVolumeClaims (PVCs) is enabled by default. You can expand
the following types of volumes:

* {{< glossary_tooltip text="csi" term_id="csi" >}} (including some CSI migrated
volume types)
* flexVolume (deprecated)
* portworxVolume (deprecated)

You can only expand a PVC if its storage class's `allowVolumeExpansion` field is set to true.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: example-vol-default
provisioner: vendor-name.example/magicstorage
parameters:
  resturl: "http://192.168.10.100:8080"
  restuser: ""
  secretNamespace: ""
  secretName: ""
allowVolumeExpansion: true
```

To request a larger volume for a PVC, edit the PVC object and specify a larger
size. This triggers expansion of the volume that backs the underlying PersistentVolume. A
new PersistentVolume is never created to satisfy the claim. Instead, an existing volume is resized.

{{< warning >}}
Directly editing the size of a PersistentVolume can prevent an automatic resize of that volume.
If you edit the capacity of a PersistentVolume, and then edit the `.spec` of a matching
PersistentVolumeClaim to make the size of the PersistentVolumeClaim match the PersistentVolume,
then no storage resize happens.
The Kubernetes control plane will see that the desired state of both resources matches,
conclude that the backing volume size has been manually
increased and that no resize is necessary.
{{< /warning >}}

#### CSI Volume expansion

{{< feature-state for_k8s_version="v1.24" state="stable" >}}

Support for expanding CSI volumes is enabled by default but it also requires a
specific CSI driver to support volume expansion. Refer to documentation of the
specific CSI driver for more information.

#### Resizing a volume containing a file system

You can only resize volumes containing a file system if the file system is XFS, Ext3, or Ext4.

When a volume contains a file system, the file system is only resized when a new Pod is using
the PersistentVolumeClaim in `ReadWrite` mode. File system expansion is either done when a Pod is starting up
or when a Pod is running and the underlying file system supports online expansion.

FlexVolumes (deprecated since Kubernetes v1.23) allow resize if the driver is configured with the
`RequiresFSResize` capability to `true`. The FlexVolume can be resized on Pod restart.

#### Resizing an in-use PersistentVolumeClaim

{{< feature-state for_k8s_version="v1.24" state="stable" >}}

In this case, you don't need to delete and recreate a Pod or deployment that is using an existing PVC.
Any in-use PVC automatically becomes available to its Pod as soon as its file system has been expanded.
This feature has no effect on PVCs that are not in use by a Pod or deployment. You must create a Pod that
uses the PVC before the expansion can complete.

Similar to other volume types - FlexVolume volumes can also be expanded when in-use by a Pod.

{{< note >}}
FlexVolume resize is possible only when the underlying driver supports resize.
{{< /note >}}

#### Recovering from Failure when Expanding Volumes

If a user specifies a new size that is too big to be satisfied by underlying
storage system, expansion of PVC will be continuously retried until user or
cluster administrator takes some action. This can be undesirable and hence
Kubernetes provides following methods of recovering from such failures.

{{< tabs name="recovery_methods" >}}
{{% tab name="Manually with Cluster Administrator access" %}}

If expanding underlying storage fails, the cluster administrator can manually
recover the Persistent Volume Claim (PVC) state and cancel the resize requests.
Otherwise, the resize requests are continuously retried by the controller without
administrator intervention.

1. Mark the PersistentVolume(PV) that is bound to the PersistentVolumeClaim(PVC)
   with `Retain` reclaim policy.
2. Delete the PVC. Since PV has `Retain` reclaim policy - we will not lose any data
   when we recreate the PVC.
3. Delete the `claimRef` entry from PV specs, so as new PVC can bind to it.
   This should make the PV `Available`.
4. Re-create the PVC with smaller size than PV and set `volumeName` field of the
   PVC to the name of the PV. This should bind new PVC to existing PV.
5. Don't forget to restore the reclaim policy of the PV.

{{% /tab %}}
{{% tab name="By requesting expansion to smaller size" %}}

If expansion has failed for a PVC, you can retry expansion with a
smaller size than the previously requested value. To request a new expansion attempt with a
smaller proposed size, edit `.spec.resources` for that PVC and choose a value that is less than the
value you previously tried.
This is useful if expansion to a higher value did not succeed because of capacity constraint.
If that has happened, or you suspect that it might have, you can retry expansion by specifying a
size that is within the capacity limits of underlying storage provider. You can monitor status of
resize operation by watching `.status.allocatedResourceStatuses` and events on the PVC.

Note that,
although you can specify a lower amount of storage than what was requested previously,
the new value must still be higher than `.status.capacity`.
Kubernetes does not support shrinking a PVC to less than its current size.
{{% /tab %}}
{{% /tabs %}}

## Types of Persistent Volumes

PersistentVolume types are implemented as plugins. Kubernetes currently supports the following plugins:

* [`csi`](/docs/concepts/storage/volumes/#csi) - Container Storage Interface (CSI)
* [`fc`](/docs/concepts/storage/volumes/#fc) - Fibre Channel (FC) storage
* [`hostPath`](/docs/concepts/storage/volumes/#hostpath) - HostPath volume
  (for single node testing only; WILL NOT WORK in a multi-node cluster;
  consider using `local` volume instead)
* [`iscsi`](/docs/concepts/storage/volumes/#iscsi) - iSCSI (SCSI over IP) storage
* [`local`](/docs/concepts/storage/volumes/#local) - local storage devices
  mounted on nodes.
* [`nfs`](/docs/concepts/storage/volumes/#nfs) - Network File System (NFS) storage

The following types of PersistentVolume are deprecated but still available.
If you are using these volume types except for `flexVolume`, `cephfs` and `rbd`,
please install corresponding CSI drivers.

* [`awsElasticBlockStore`](/docs/concepts/storage/volumes/#awselasticblockstore) - AWS Elastic Block Store (EBS)
  (**migration on by default** starting v1.23)
* [`azureDisk`](/docs/concepts/storage/volumes/#azuredisk) - Azure Disk
  (**migration on by default** starting v1.23)
* [`azureFile`](/docs/concepts/storage/volumes/#azurefile) - Azure File
  (**migration on by default** starting v1.24)
* [`cinder`](/docs/concepts/storage/volumes/#cinder) - Cinder (OpenStack block storage)
  (**migration on by default** starting v1.21)
* [`flexVolume`](/docs/concepts/storage/volumes/#flexvolume) - FlexVolume
  (**deprecated** starting v1.23, no migration plan and no plan to remove support)
* [`gcePersistentDisk`](/docs/concepts/storage/volumes/#gcePersistentDisk) - GCE Persistent Disk
  (**migration on by default** starting v1.23)
* [`portworxVolume`](/docs/concepts/storage/volumes/#portworxvolume) - Portworx volume
  (**migration on by default** starting v1.31)
* [`vsphereVolume`](/docs/concepts/storage/volumes/#vspherevolume) - vSphere VMDK volume
  (**migration on by default** starting v1.25)

Older versions of Kubernetes also supported the following in-tree PersistentVolume types:

* [`cephfs`](/docs/concepts/storage/volumes/#cephfs)
  (**not available** starting v1.31)
* `flocker` - Flocker storage.
  (**not available** starting v1.25)
* `glusterfs` - GlusterFS storage.
  (**not available** starting v1.26)
* `photonPersistentDisk` - Photon controller persistent disk.
  (**not available** starting v1.15)
* `quobyte` - Quobyte volume.
  (**not available** starting v1.25)
* [`rbd`](/docs/concepts/storage/volumes/#rbd) - Rados Block Device (RBD) volume 
  (**not available** starting v1.31)
* `scaleIO` - ScaleIO volume.
  (**not available** starting v1.21)
* `storageos` - StorageOS volume.
  (**not available** starting v1.25)

## Persistent Volumes

Each PV contains a spec and status, which is the specification and status of the volume.
The name of a PersistentVolume object must be a valid
[DNS subdomain name](/docs/concepts/overview/working-with-objects/names#dns-subdomain-names).

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv0003
spec:
  capacity:
    storage: 5Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Recycle
  storageClassName: slow
  mountOptions:
    - hard
    - nfsvers=4.1
  nfs:
    path: /tmp
    server: 172.17.0.2
```

{{< note >}}
Helper programs relating to the volume type may be required for consumption of
a PersistentVolume within a cluster.  In this example, the PersistentVolume is
of type NFS and the helper program /sbin/mount.nfs is required to support the
mounting of NFS filesystems.
{{< /note >}}

### Capacity

Generally, a PV will have a specific storage capacity. This is set using the PV's
`capacity` attribute which is a {{< glossary_tooltip term_id="quantity" >}} value.

Currently, storage size is the only resource that can be set or requested.
Future attributes may include IOPS, throughput, etc.

### Volume Mode

{{< feature-state for_k8s_version="v1.18" state="stable" >}}

Kubernetes supports two `volumeModes` of PersistentVolumes: `Filesystem` and `Block`.

`volumeMode` is an optional API parameter.
`Filesystem` is the default mode used when `volumeMode` parameter is omitted.

A volume with `volumeMode: Filesystem` is *mounted* into Pods into a directory. If the volume
is backed by a block device and the device is empty, Kubernetes creates a filesystem
on the device before mounting it for the first time.

You can set the value of `volumeMode` to `Block` to use a volume as a raw block device.
Such volume is presented into a Pod as a block device, without any filesystem on it.
This mode is useful to provide a Pod the fastest possible way to access a volume, without
any filesystem layer between the Pod and the volume. On the other hand, the application
running in the Pod must know how to handle a raw block device.
See [Raw Block Volume Support](#raw-block-volume-support)
for an example on how to use a volume with `volumeMode: Block` in a Pod.

### Access Modes

A PersistentVolume can be mounted on a host in any way supported by the resource
provider. As shown in the table below, providers will have different capabilities
and each PV's access modes are set to the specific modes supported by that particular
volume. For example, NFS can support multiple read/write clients, but a specific
NFS PV might be exported on the server as read-only. Each PV gets its own set of
access modes describing that specific PV's capabilities.

The access modes are:

`ReadWriteOnce`
: the volume can be mounted as read-write by a single node. ReadWriteOnce access
  mode still can allow multiple pods to access (read from or write to) that volume when the pods are
  running on the same node. For single pod access, please see ReadWriteOncePod.

`ReadOnlyMany`
: the volume can be mounted as read-only by many nodes.

`ReadWriteMany`
: the volume can be mounted as read-write by many nodes.

 `ReadWriteOncePod`
: {{< feature-state for_k8s_version="v1.29" state="stable" >}}
  the volume can be mounted as read-write by a single Pod. Use ReadWriteOncePod
  access mode if you want to ensure that only one pod across the whole cluster can
  read that PVC or write to it.

{{< note >}}
The `ReadWriteOncePod` access mode is only supported for
{{< glossary_tooltip text="CSI" term_id="csi" >}} volumes and Kubernetes version
1.22+. To use this feature you will need to update the following
[CSI sidecars](https://kubernetes-csi.github.io/docs/sidecar-containers.html)
to these versions or greater:

* [csi-provisioner:v3.0.0+](https://github.com/kubernetes-csi/external-provisioner/releases/tag/v3.0.0)
* [csi-attacher:v3.3.0+](https://github.com/kubernetes-csi/external-attacher/releases/tag/v3.3.0)
* [csi-resizer:v1.3.0+](https://github.com/kubernetes-csi/external-resizer/releases/tag/v1.3.0)
{{< /note >}}

In the CLI, the access modes are a

<!-- … truncated … -->
