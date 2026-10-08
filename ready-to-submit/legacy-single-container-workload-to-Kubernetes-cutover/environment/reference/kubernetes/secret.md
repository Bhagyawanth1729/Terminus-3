<!-- Source: https://kubernetes.io/docs/concepts/configuration/secret.md -->
<!-- Upstream raw: https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/configuration/secret.md -->
<!-- License: Apache-2.0 (Kubernetes website / documentation) -->
<!-- Truncated locally for image size; consult upstream for full text. -->

---
reviewers:
  - mikedanese
title: Secrets
api_metadata:
- apiVersion: "v1"
  kind: "Secret"
content_type: concept
feature:
  title: Secret and configuration management
  description: >
    Deploy and update Secrets and application configuration without rebuilding your image
    and without exposing Secrets in your stack configuration.
weight: 30
---

<!-- overview -->

A Secret is an object that contains a small amount of sensitive data such as
a password, a token, or a key. Such information might otherwise be put in a
{{< glossary_tooltip term_id="pod" >}} specification or in a
{{< glossary_tooltip text="container image" term_id="image" >}}. Using a
Secret means that you don't need to include confidential data in your
application code.

Because Secrets can be created independently of the Pods that use them, there
is less risk of the Secret (and its data) being exposed during the workflow of
creating, viewing, and editing Pods. Kubernetes, and applications that run in
your cluster, can also take additional precautions with Secrets, such as avoiding
writing sensitive data to nonvolatile storage.

Secrets are similar to {{< glossary_tooltip text="ConfigMaps" term_id="configmap" >}}
but are specifically intended to hold confidential data.

{{< caution >}}
Kubernetes Secrets are, by default, stored unencrypted in the API server's underlying data store
(etcd). Anyone with API access can retrieve or modify a Secret, and so can anyone with access to etcd.
Additionally, anyone who is authorized to create a Pod in a namespace can use that access to read
any Secret in that namespace; this includes indirect access such as the ability to create a
Deployment.

In order to safely use Secrets, take at least the following steps:

1. [Enable Encryption at Rest](/docs/tasks/administer-cluster/encrypt-data/) for Secrets.
1. [Enable or configure RBAC rules](/docs/reference/access-authn-authz/authorization/) with
   least-privilege access to Secrets.
1. Restrict Secret access to specific containers.
1. [Consider using external Secret store providers](https://secrets-store-csi-driver.sigs.k8s.io/concepts.html#provider-for-the-secrets-store-csi-driver).

For more guidelines to manage and improve the security of your Secrets, refer to
[Good practices for Kubernetes Secrets](/docs/concepts/security/secrets-good-practices).

{{< /caution >}}

See [Information security for Secrets](#information-security-for-secrets) for more details.

<!-- body -->

## Uses for Secrets

You can use Secrets for purposes such as the following:

- [Set environment variables for a container](/docs/tasks/inject-data-application/distribute-credentials-secure/#define-container-environment-variables-using-secret-data).
- [Provide credentials such as SSH keys or passwords to Pods](/docs/tasks/inject-data-application/distribute-credentials-secure/#provide-prod-test-creds).
- [Allow the kubelet to pull container images from private registries](/docs/tasks/configure-pod-container/pull-image-private-registry/).

The Kubernetes control plane also uses Secrets; for example,
[bootstrap token Secrets](#bootstrap-token-secrets) are a mechanism to
help automate node registration.

### Use case: dotfiles in a secret volume

You can make your data "hidden" by defining a key that begins with a dot.
This key represents a dotfile or "hidden" file. For example, when the following Secret
is mounted into a volume, `secret-volume`, the volume will contain a single file,
called `.secret-file`, and the `dotfile-test-container` will have this file
present at the path `/etc/secret-volume/.secret-file`.

{{< note >}}
Files beginning with dot characters are hidden from the output of `ls -l`;
you must use `ls -la` to see them when listing directory contents.
{{< /note >}}

{{% code_sample language="yaml" file="secret/dotfile-secret.yaml" %}}

### Use case: Secret visible to one container in a Pod

Consider a program that needs to handle HTTP requests, do some complex business
logic, and then sign some messages with an HMAC. Because it has complex
application logic, there might be an unnoticed remote file reading exploit in
the server, which could expose the private key to an attacker.

This could be divided into two processes in two containers: a frontend container
which handles user interaction and business logic, but which cannot see the
private key; and a signer container that can see the private key, and responds
to simple signing requests from the frontend (for example, over localhost networking).

With this partitioned approach, an attacker now has to trick the application
server into doing something rather arbitrary, which may be harder than getting
it to read a file.

### Alternatives to Secrets

Rather than using a Secret to protect confidential data, you can pick from alternatives.

Here are some of your options:

- If your cloud-native component needs to authenticate to another application that you
  know is running within the same Kubernetes cluster, you can use a
  [ServiceAccount](/docs/reference/access-authn-authz/authentication/#service-account-tokens)
  and its tokens to identify your client.
- There are third-party tools that you can run, either within or outside your cluster,
  that manage sensitive data. For example, a service that Pods access over HTTPS,
  that reveals a Secret if the client correctly authenticates (for example, with a ServiceAccount
  token).
- For authentication, you can implement a custom signer for X.509 certificates, and use
  [CertificateSigningRequests](/docs/reference/access-authn-authz/certificate-signing-requests/)
  to let that custom signer issue certificates to Pods that need them.
- You can use a [device plugin](/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)
  to expose node-local encryption hardware to a specific Pod. For example, you can schedule
  trusted Pods onto nodes that provide a Trusted Platform Module, configured out-of-band.

You can also combine two or more of those options, including the option to use Secret objects themselves.

For example: implement (or deploy) an {{< glossary_tooltip text="operator" term_id="operator-pattern" >}}
that fetches short-lived session tokens from an external service, and then creates Secrets based
on those short-lived session tokens. Pods running in your cluster can make use of the session tokens,
and operator ensures they are valid. This separation means that you can run Pods that are unaware of
the exact mechanisms for issuing and refreshing those session tokens.

## Types of Secret {#secret-types}

When creating a Secret, you can specify its type using the `type` field of
the [Secret](/docs/reference/kubernetes-api/config-and-storage-resources/secret-v1/)
resource, or certain equivalent `kubectl` command line flags (if available).
The Secret type is used to facilitate programmatic handling of the Secret data.

Kubernetes provides several built-in types for some common usage scenarios.
These types vary in terms of the validations performed and the constraints
Kubernetes imposes on them.

| Built-in Type                         | Usage                                   |
| ------------------------------------- |---------------------------------------- |
| `Opaque`                              | arbitrary user-defined data            |
| `kubernetes.io/service-account-token` | ServiceAccount token                    |
| `kubernetes.io/dockercfg`             | serialized `~/.dockercfg` file          |
| `kubernetes.io/dockerconfigjson`      | serialized `~/.docker/config.json` file |
| `kubernetes.io/basic-auth`            | credentials for basic authentication    |
| `kubernetes.io/ssh-auth`              | credentials for SSH authentication      |
| `kubernetes.io/tls`                   | data for a TLS client or server         |
| `bootstrap.kubernetes.io/token`       | bootstrap token data                    |

You can define and use your own Secret type by assigning a non-empty string as the
`type` value for a Secret object (an empty string is treated as an `Opaque` type).

Kubernetes doesn't impose any constraints on the type name. However, if you
are using one of the built-in types, you must meet all the requirements defined
for that type.

If you are defining a type of Secret that's for public use, follow the convention
and structure the Secret type to have your domain name before the name, separated
by a `/`. For example: `cloud-hosting.example.net/cloud-api-credentials`.

### Opaque Secrets

`Opaque` is the default Secret type if you don't explicitly specify a type in
a Secret manifest. When you create a Secret using `kubectl`, you must use the
`generic` subcommand to indicate an `Opaque` Secret type. For example, the
following command creates an empty Secret of type `Opaque`:

```shell
kubectl create secret generic empty-secret
kubectl get secret empty-secret
```

The output looks like:

```
NAME           TYPE     DATA   AGE
empty-secret   Opaque   0      2m6s
```

The `DATA` column shows the number of data items stored in the Secret.
In this case, `0` means you have created an empty Secret.

### ServiceAccount token Secrets

A `kubernetes.io/service-account-token` type of Secret is used to store a
token credential that identifies a
{{< glossary_tooltip text="ServiceAccount" term_id="service-account" >}}. This
is a legacy mechanism that provides long-lived ServiceAccount credentials to
Pods.

In Kubernetes v1.22 and later, the recommended approach is to obtain a
short-lived, automatically rotating ServiceAccount token by using the
[`TokenRequest`](/docs/reference/kubernetes-api/authentication-resources/token-request-v1/)
API instead. You can get these short-lived tokens using the following methods:

* Call the `TokenRequest` API either directly or by using an API client like
  `kubectl`. For example, you can use the
  [`kubectl create token`](/docs/reference/generated/kubectl/kubectl-commands#-em-token-em-)
  command.
* Request a mounted token in a
  [projected volume](/docs/reference/access-authn-authz/service-accounts-admin/#bound-service-account-token-volume)
  in your Pod manifest. Kubernetes creates the token and mounts it in the Pod.
  The token is automatically invalidated when the Pod that it's mounted in is
  deleted. For details, see
  [Launch a Pod using service account token projection](/docs/tasks/configure-pod-container/configure-service-account/#launch-a-pod-using-service-account-token-projection).

{{< note >}}
You should only create a ServiceAccount token Secret
if you can't use the `TokenRequest` API to obtain a token,
and the security exposure of persisting a non-expiring token credential
in a readable API object is acceptable to you. For instructions, see
[Manually create a long-lived API token for a ServiceAccount](/docs/tasks/configure-pod-container/configure-service-account/#manually-create-an-api-token-for-a-serviceaccount).
{{< /note >}}

When using this Secret type, you need to ensure that the
`kubernetes.io/service-account.name` annotation is set to an existing
ServiceAccount name. If you are creating both the ServiceAccount and
the Secret objects, you should create the ServiceAccount object first.

After the Secret is created, a Kubernetes {{< glossary_tooltip text="controller" term_id="controller" >}}
fills in some other fields such as the `kubernetes.io/service-account.uid` annotation, and the
`token` key in the `data` field, which is populated with an authentication token.

The following example configuration declares a ServiceAccount token Secret:

{{% code_sample language="yaml" file="secret/serviceaccount-token-secret.yaml" %}}

After creating the Secret, wait for Kubernetes to populate the `token` key in the `data` field.

See the [ServiceAccount](/docs/concepts/security/service-accounts/)
documentation for more information on how ServiceAccounts work.
You can also check the `automountServiceAccountToken` field and the
`serviceAccountName` field of the
[`Pod`](/docs/reference/generated/kubernetes-api/{{< param "version" >}}/#pod-v1-core)
for information on referencing ServiceAccount credentials from within Pods.

### Docker config Secrets

If you are creating a Secret to store credentials for accessing a container image registry,
you must use one of the following `type` values for that Secret:

- `kubernetes.io/dockercfg`: store a serialized `~/.dockercfg` which is the
  legacy format for configuring Docker command line. The Secret
  `data` field contains a `.dockercfg` key whose value is the content of a
  base64 encoded `~/.dockercfg` file.
- `kubernetes.io/dockerconfigjson`: store a serialized JSON that follows the
  same format rules as the `~/.docker/config.json` file, which is a new format
  for `~/.dockercfg`. The Secret `data` field must contain a
  `.dockerconfigjson` key for which the value is the content of a base64
  encoded `~/.docker/config.json` file.

Below is an example for a `kubernetes.io/dockercfg` type of Secret:

{{% code_sample language="yaml" file="secret/dockercfg-secret.yaml" %}}

{{< note >}}
If you do not want to perform the base64 encoding, you can choose to use the
`stringData` field instead.
{{< /note >}}

When you create Docker config Secrets using a manifest, the API
server checks whether the expected key exists in the `data` field, and
it verifies if the value provided can be parsed as a valid JSON. The API
server doesn't validate if the JSON actually is a Docker config file.

You can also use `kubectl` to create a Secret for accessing a container
registry, such as when you don't have a Docker configuration file:

```shell
kubectl create secret docker-registry secret-tiger-docker \
  --docker-email=tiger@acme.example \
  --docker-username=tiger \
  --docker-password=pass1234 \
  --docker-server=my-registry.example:5000
```

This command creates a Secret of type `kubernetes.io/dockerconfigjson`.

Retrieve the `.data.dockerconfigjson` field from that new Secret and decode the
data:

```shell
kubectl get secret secret-tiger-docker -o jsonpath='{.data.*}' | base64 -d
```

The output is equivalent to the following JSON document (which is also a valid
Docker configuration file):

```json
{
  "auths": {
    "my-registry.example:5000": {
      "username": "tiger",
      "password": "pass1234",
      "email": "tiger@acme.example",
      "auth": "dGlnZXI6cGFzczEyMzQ="
    }
  }
}
```

{{< caution >}}
The `auth` value there is base64 encoded; it is obscured but not secret.
Anyone who can read that Secret can learn the registry access bearer token.

It is suggested to use [credential providers](/docs/tasks/administer-cluster/kubelet-credential-provider/) to dynamically and securely provide pull secrets on-demand.
{{< /caution >}}

### Basic authentication Secret

The `kubernetes.io/basic-auth` type is provided for storing credentials needed
for basic authentication. When using this Secret type, the `data` field of the
Secret must contain one of the following two keys:

- `username`: the user name for authentication
- `password`: the password or token for authentication

Both values for the above two keys are base64 encoded strings. You can
alternatively provide the clear text content using the `stringData` field in the
Secret manifest.

The following manifest is an example of a basic authentication Secret:

{{% code_sample language="yaml" file="secret/basicauth-secret.yaml" %}}

{{< note >}}
The `stringData` field for a Secret does not work well with server-side apply.
{{< /note >}}

The basic authentication Secret type is provided only for convenience.
You can create an `Opaque` type for credentials used for basic authentication.
However, using the defined and public Secret type (`kubernetes.io/basic-auth`) helps other
people to understand the purpose of your Secret, and sets a convention for what key names
to expect.

### SSH authentication Secrets

The builtin type `kubernetes.io/ssh-auth` is provided for storing data used in
SSH authentication. When using this Secret type, you will have to specify a
`ssh-privatekey` key-value pair in the `data` (or `stringData`) field
as the SSH credential to use.

The following manifest is an example of a Secret used for SSH public/private
key authentication:

{{% code_sample language="yaml" file="secret/ssh-auth-secret.yaml" %}}

The SSH authentication Secret type is provided only for convenience.
You can create an `Opaque` type for credentials used for SSH authentication.
However, using the defined and public Secret type (`kubernetes.io/ssh-auth`) helps other
people to understand the purpose of your Secret, and sets a convention for what key names
to expect.
The Kubernetes API verifies that the required keys are set for a Secret of this type.

{{< caution >}}
SSH private keys do not establish trusted communication between an SSH client and
host server on their own. A secondary means of establishing trust is needed to
mitigate "man in the middle" attacks, such as a `known_hosts` file added to a ConfigMap.
{{< /caution >}}

### TLS Secrets

The `kubernetes.io/tls` Secret type is for storing
a certificate and its associated key that are typically used for TLS.

One common use for TLS Secrets is to configure encryption in transit for
an [Ingress](/docs/concepts/services-networking/ingress/), but you can also use it
with other resources or directly in your workload.
When using this type of Secret, the `tls.key` and the `tls.crt` key must be provided
in the `data` (or `stringData`) field of the Secret configuration, although the API
server doesn't actually validate the values for each key.

As an alternative to using `stringData`, you can use the `data` field to provide
the base64 encoded certificate and private key. For details, see
[Constraints on Secret names and data](#restriction-names-data).

The following YAML contains an example config for a TLS Secret:

{{% code_sample language="yaml" file="secret/tls-auth-secret.yaml" %}}

The TLS Secret type is provided only for convenience.
You can create an `Opaque` type for credentials used for TLS authentication.
However, using the defined and public Secret type (`kubernetes.io/tls`)
helps ensure the consistency of Secret format in your project. The API server
verifies if the required keys are set for a Secret of this type.

To create a TLS Secret using `kubectl`, use the `tls` subcommand:

```shell
kubectl create secret tls my-tls-secret \
  --cert=path/to/cert/file \
  --key=path/to/key/file
```

The public/private key pair must exist before hand. The public key certificate for `--cert` must be .PEM encoded
and must match the given private key for `--key`.

### Bootstrap token Secrets

The `bootstrap.kubernetes.io/token` Secret type is for
tokens used during the node bootstrap process. It stores tokens used to sign
well-known ConfigMaps.

A bootstrap token Secret is usually created in the `kube-system` namespace and
named in the form `bootstrap-token-<token-id>` where `<token-id>` is a 6 character
string of the token ID.

As a Kubernetes manifest, a bootstrap token Secret might look like the
following:

{{% code_sample language="yaml" file="secret/bootstrap-token-secret-base64.yaml" %}}

A bootstrap token Secret has the following keys specified under `data`:

- `token-id`: A random 6 character string as the token identifier. Required.
- `token-secret`: A random 16 character string as the actual token Secret. Required.
- `description`: A human-readable string that describes what the token is
  used for. Optional.
- `expiration`: An absolute UTC time using [RFC3339](https://datatracker.ietf.org/doc/html/rfc3339) specifying when the token
  should be expired. Optional.
- `usage-bootstrap-<usage>`: A boolean flag indicating additional usage for
  the bootstrap token.
- `auth-extra-groups`: A comma-separated list of group names that will be
  authenticated as in addition to the `system:bootstrappers` group.

You can alternatively provide the values in the `stringData` field of the Secret
without base64 encoding them:

{{% co

<!-- … truncated … -->
