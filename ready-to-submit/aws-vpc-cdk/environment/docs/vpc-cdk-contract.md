# VPC CDK Contract

The package in `/app/cdk-vpc` exposes `NetworkFabric`, a synthesis-only CDK construct that accepts the JSON shape used by `/app/config/payments-network.json`. `bin/synth.js` is the supported operator entrypoint and must write a stack named `FleetVpc` to the requested output directory.

The construct owns one VPC, optional secondary IPv4 CIDR associations, optional Amazon-provided IPv6, and subnet tiers named `public`, `private`, `database`, and `intra`. Every subnet receives stable `Name`, `Tier`, and `Az` tags. Public subnets map public IPv4 addresses and route IPv4 plus IPv6 internet traffic through the internet gateway. Private subnets use either one shared NAT gateway or one NAT gateway in the same availability zone; when IPv6 egress is enabled they route `::/0` through an egress-only internet gateway. Database and intra subnets remain isolated unless the input explicitly enables NAT routing for database subnets.

Gateway endpoints support `s3` and `dynamodb` only, and attach to route tables selected by the endpoint's `tiers` list. Interface endpoints support `ssm`, `ssmmessages`, `ec2messages`, `kms`, `logs`, and `secretsmanager`; they use the selected subnets and an endpoint security group that admits TLS only from private and database CIDR ranges. Tier-specific network ACLs come from the input contract and must be associated with every subnet in that tier.

Flow logs, when enabled, use a CloudWatch log group, an IAM delivery role, a least-privilege inline policy for log-stream creation and event writes, and one `AWS::EC2::FlowLog` with the configured traffic type. Outputs must include `VpcId`, `PublicSubnetIds`, `PrivateSubnetIds`, `DatabaseSubnetIds`, `IntraSubnetIds`, `PrivateRouteTableIds`, `DatabaseRouteTableIds`, and `GatewayEndpointIds`.

Validation must fail before synthesis when subnet CIDRs overlap each other or the VPC CIDR boundary, an availability zone listed in `availabilityZones` has no matching subnet tier required by NAT routing, NAT is enabled without public subnet coverage, an endpoint service is unsupported, an endpoint references an unknown tier, or a subnet tier is unknown.
