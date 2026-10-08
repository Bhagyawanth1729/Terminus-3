"use strict";

const cdk = require("aws-cdk-lib");
const ec2 = require("aws-cdk-lib/aws-ec2");
const logs = require("aws-cdk-lib/aws-logs");
const iam = require("aws-cdk-lib/aws-iam");
const { Construct } = require("constructs");

const SUBNET_TIERS = new Set(["public", "private", "database", "intra"]);
const GATEWAY_ENDPOINTS = new Set(["s3", "dynamodb"]);
const INTERFACE_ENDPOINTS = new Set(["ssm", "ssmmessages", "ec2messages", "kms", "logs", "secretsmanager"]);

function stableName(...parts) {
  return parts
    .filter((part) => part !== undefined && part !== null && String(part).length > 0)
    .map((part) => {
      const cleaned = String(part).replace(/[^A-Za-z0-9]/g, " ");
      return cleaned
        .split(/\s+/)
        .filter(Boolean)
        .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
        .join("");
    })
    .join("");
}

function tagList(tags) {
  return Object.keys(tags)
    .sort()
    .map((key) => ({ key, value: String(tags[key]) }));
}

function parseCidr(cidr) {
  const match = /^(\d+)\.(\d+)\.(\d+)\.(\d+)\/(\d+)$/.exec(cidr || "");
  if (!match) {
    throw new Error(`invalid IPv4 CIDR: ${cidr}`);
  }
  const octets = match.slice(1, 5).map((value) => Number(value));
  const prefix = Number(match[5]);
  if (octets.some((value) => value < 0 || value > 255) || prefix < 0 || prefix > 32) {
    throw new Error(`invalid IPv4 CIDR: ${cidr}`);
  }
  const ip = (((octets[0] << 24) >>> 0) + (octets[1] << 16) + (octets[2] << 8) + octets[3]) >>> 0;
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
  return { start: ip & mask, end: (ip & mask) + (0xffffffff >>> prefix), prefix, cidr };
}

function cidrContains(parent, child) {
  return child.start >= parent.start && child.end <= parent.end;
}

function cidrOverlaps(left, right) {
  return left.start <= right.end && right.start <= left.end;
}

function requireArray(value, field) {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`${field} must be a non-empty array`);
  }
  return value;
}

function serviceName(region, service) {
  return `com.amazonaws.${region}.${service}`;
}

class NetworkFabric extends Construct {
  constructor(scope, id, config) {
    super(scope, id);
    const normalized = validateConfig(config);
    const name = normalized.name;
    const tags = normalized.tags;
    const region = normalized.region;

    const vpc = new ec2.CfnVPC(this, "Vpc", {
      cidrBlock: normalized.cidr,
      enableDnsHostnames: true,
      enableDnsSupport: true,
      tags: tagList({ Name: name, ...tags, ...(normalized.vpcTags || {}) })
    });
    this.vpc = vpc;

    for (const [index, cidr] of normalized.secondaryCidrs.entries()) {
      new ec2.CfnVPCCidrBlock(this, stableName("SecondaryCidr", index), {
        vpcId: vpc.ref,
        cidrBlock: cidr
      });
    }

    let ipv6Block;
    if (normalized.enableIpv6) {
      ipv6Block = new ec2.CfnVPCCidrBlock(this, "AmazonProvidedIpv6", {
        vpcId: vpc.ref,
        amazonProvidedIpv6CidrBlock: true
      });
    }

    const igw = new ec2.CfnInternetGateway(this, "InternetGateway", {
      tags: tagList({ Name: `${name}-igw`, ...tags })
    });
    const igwAttachment = new ec2.CfnVPCGatewayAttachment(this, "InternetGatewayAttachment", {
      vpcId: vpc.ref,
      internetGatewayId: igw.ref
    });

    let eigw;
    if (normalized.enableIpv6 && normalized.privateIpv6Egress) {
      eigw = new ec2.CfnEgressOnlyInternetGateway(this, "EgressOnlyInternetGateway", {
        vpcId: vpc.ref
      });
    }

    const subnetRecords = this.createSubnets(normalized, vpc, ipv6Block);
    const routeTables = this.createRouteTables(normalized, vpc, subnetRecords);
    this.createInternetRoutes(normalized, routeTables, igw, igwAttachment, eigw);
    this.createNatGateways(normalized, subnetRecords, routeTables, tags);
    this.createNetworkAcls(normalized, vpc, subnetRecords, tags);
    const endpointSecurityGroup = this.createEndpointSecurityGroup(normalized, vpc, subnetRecords, tags);
    this.createGatewayEndpoints(normalized, vpc, routeTables, region, tags);
    this.createInterfaceEndpoints(normalized, vpc, subnetRecords, endpointSecurityGroup, region, tags);
    this.createFlowLogs(normalized, vpc, tags);
    this.createOutputs(subnetRecords, routeTables, vpc);
  }

  createSubnets(config, vpc, ipv6Block) {
    const records = [];
    for (const [index, subnet] of config.subnets.entries()) {
      const props = {
        vpcId: vpc.ref,
        cidrBlock: subnet.cidr,
        availabilityZone: subnet.az,
        mapPublicIpOnLaunch: subnet.tier === "public",
        tags: tagList({
          Name: `${config.name}-${subnet.name}`,
          Tier: subnet.tier,
          Az: subnet.az,
          ...config.tags,
          ...(config.subnetTags?.[subnet.tier] || {})
        })
      };
      if (config.enableIpv6) {
        props.assignIpv6AddressOnCreation = subnet.tier === "public";
        props.ipv6CidrBlock = cdk.Fn.select(
          subnet.ipv6Index ?? index,
          cdk.Fn.cidr(cdk.Fn.select(0, vpc.attrIpv6CidrBlocks), "256", "64")
        );
      }
      const resource = new ec2.CfnSubnet(this, stableName(subnet.name, "Subnet"), props);
      if (ipv6Block) {
        resource.addDependency(ipv6Block);
      }
      records.push({ ...subnet, index, resource });
    }
    return records;
  }

  createRouteTables(config, vpc, subnets) {
    const routeTables = [];
    for (const subnet of subnets) {
      const table = new ec2.CfnRouteTable(this, stableName(subnet.name, "RouteTable"), {
        vpcId: vpc.ref,
        tags: tagList({
          Name: `${config.name}-${subnet.name}`,
          Tier: subnet.tier,
          Az: subnet.az,
          ...config.tags
        })
      });
      const association = new ec2.CfnSubnetRouteTableAssociation(
        this,
        stableName(subnet.name, "RouteTableAssociation"),
        {
          subnetId: subnet.resource.ref,
          routeTableId: table.ref
        }
      );
      association.addDependency(table);
      routeTables.push({ tier: subnet.tier, az: subnet.az, subnetName: subnet.name, resource: table });
    }
    return routeTables;
  }

  createInternetRoutes(config, routeTables, igw, attachment, eigw) {
    for (const table of routeTables.filter((entry) => entry.tier === "public")) {
      const route = new ec2.CfnRoute(this, stableName(table.subnetName, "Ipv4InternetRoute"), {
        routeTableId: table.resource.ref,
        destinationCidrBlock: "0.0.0.0/0",
        gatewayId: igw.ref
      });
      route.addDependency(attachment);
      if (config.enableIpv6) {
        const ipv6Route = new ec2.CfnRoute(this, stableName(table.subnetName, "Ipv6InternetRoute"), {
          routeTableId: table.resource.ref,
          destinationIpv6CidrBlock: "::/0",
          gatewayId: igw.ref
        });
        ipv6Route.addDependency(attachment);
      }
    }
    if (eigw) {
      for (const table of routeTables.filter((entry) => entry.tier === "private")) {
        new ec2.CfnRoute(this, stableName(table.subnetName, "Ipv6EgressRoute"), {
          routeTableId: table.resource.ref,
          destinationIpv6CidrBlock: "::/0",
          egressOnlyInternetGatewayId: eigw.ref
        });
      }
    }
  }

  createNatGateways(config, subnets, routeTables, tags) {
    if (!config.enableNatGateway) {
      return;
    }
    const publicByAz = new Map(subnets.filter((s) => s.tier === "public").map((s) => [s.az, s]));
    const natByAz = new Map();
    const natTargets = config.singleNatGateway ? [publicByAz.get(config.availabilityZones[0])] : [...publicByAz.values()];
    for (const subnet of natTargets) {
      const eip = new ec2.CfnEIP(this, stableName(subnet.name, "NatEip"), {
        domain: "vpc",
        tags: tagList({ Name: `${config.name}-${subnet.az}-nat-eip`, ...tags })
      });
      const nat = new ec2.CfnNatGateway(this, stableName(subnet.name, "NatGateway"), {
        allocationId: eip.attrAllocationId,
        subnetId: subnet.resource.ref,
        tags: tagList({ Name: `${config.name}-${subnet.az}-nat`, Az: subnet.az, ...tags })
      });
      natByAz.set(subnet.az, nat);
    }
    const sharedNat = config.singleNatGateway ? natByAz.get(config.availabilityZones[0]) : undefined;
    for (const table of routeTables) {
      const shouldRoute =
        table.tier === "private" || (table.tier === "database" && config.databaseSubnetsRouteToNat === true);
      if (!shouldRoute) {
        continue;
      }
      const nat = sharedNat || natByAz.get(table.az);
      if (!nat) {
        throw new Error(`missing NAT gateway for ${table.az}`);
      }
      new ec2.CfnRoute(this, stableName(table.subnetName, "NatDefaultRoute"), {
        routeTableId: table.resource.ref,
        destinationCidrBlock: "0.0.0.0/0",
        natGatewayId: nat.ref
      });
    }
  }

  createNetworkAcls(config, vpc, subnets, tags) {
    for (const tier of Object.keys(config.networkAcls || {}).sort()) {
      const tierSubnets = subnets.filter((subnet) => subnet.tier === tier);
      if (tierSubnets.length === 0) {
        continue;
      }
      const acl = new ec2.CfnNetworkAcl(this, stableName(tier, "NetworkAcl"), {
        vpcId: vpc.ref,
        tags: tagList({ Name: `${config.name}-${tier}-acl`, Tier: tier, ...tags })
      });
      for (const subnet of tierSubnets) {
        new ec2.CfnSubnetNetworkAclAssociation(this, stableName(subnet.name, "AclAssociation"), {
          subnetId: subnet.resource.ref,
          networkAclId: acl.ref
        });
      }
      for (const rule of config.networkAcls[tier]) {
        new ec2.CfnNetworkAclEntry(
          this,
          stableName(tier, rule.egress ? "Egress" : "Ingress", rule.rule),
          {
            networkAclId: acl.ref,
            ruleNumber: rule.rule,
            protocol: rule.protocol,
            ruleAction: rule.action,
            egress: rule.egress,
            cidrBlock: rule.cidr,
            portRange: rule.protocol === -1 ? undefined : { from: rule.fromPort, to: rule.toPort }
          }
        );
      }
    }
  }

  createEndpointSecurityGroup(config, vpc, subnets, tags) {
    if ((config.interfaceEndpoints || []).length === 0) {
      return undefined;
    }
    const sg = new ec2.CfnSecurityGroup(this, "InterfaceEndpointSecurityGroup", {
      groupDescription: "TLS ingress from application and database tiers to VPC endpoints",
      vpcId: vpc.ref,
      securityGroupEgress: [
        {
          ipProtocol: "-1",
          cidrIp: "0.0.0.0/0"
        }
      ],
      tags: tagList({ Name: `${config.name}-interface-endpoints`, ...tags })
    });
    const allowedCidrs = subnets
      .filter((subnet) => subnet.tier === "private" || subnet.tier === "database")
      .map((subnet) => subnet.cidr);
    for (const [index, cidr] of allowedCidrs.entries()) {
      new ec2.CfnSecurityGroupIngress(this, stableName("EndpointIngress", index), {
        groupId: sg.ref,
        ipProtocol: "tcp",
        fromPort: 443,
        toPort: 443,
        cidrIp: cidr,
        description: `TLS from ${cidr}`
      });
    }
    return sg;
  }

  createGatewayEndpoints(config, vpc, routeTables, region, tags) {
    const endpointIds = [];
    for (const endpoint of config.gatewayEndpoints || []) {
      const selectedTables = routeTables.filter((table) => endpoint.tiers.includes(table.tier));
      const resource = new ec2.CfnVPCEndpoint(this, stableName(endpoint.service, "GatewayEndpoint"), {
        vpcId: vpc.ref,
        serviceName: serviceName(region, endpoint.service),
        vpcEndpointType: "Gateway",
        routeTableIds: selectedTables.map((table) => table.resource.ref),
        policyDocument: {
          Version: "2012-10-17",
          Statement: [
            {
              Effect: "Allow",
              Principal: "*",
              Action: "*",
              Resource: "*",
              Condition: {
                StringEquals: {
                  "aws:PrincipalAccount": config.account || "111122223333"
                }
              }
            }
          ]
        },
        tags: tagList({ Name: `${config.name}-${endpoint.service}`, ...tags })
      });
      endpointIds.push(resource.ref);
    }
    this.gatewayEndpointIds = endpointIds;
  }

  createInterfaceEndpoints(config, vpc, subnets, endpointSecurityGroup, region, tags) {
    for (const endpoint of config.interfaceEndpoints || []) {
      const selectedSubnets = subnets.filter((subnet) => endpoint.tiers.includes(subnet.tier));
      new ec2.CfnVPCEndpoint(this, stableName(endpoint.service, "InterfaceEndpoint"), {
        vpcId: vpc.ref,
        serviceName: serviceName(region, endpoint.service),
        vpcEndpointType: "Interface",
        privateDnsEnabled: true,
        subnetIds: selectedSubnets.map((subnet) => subnet.resource.ref),
        securityGroupIds: endpointSecurityGroup ? [endpointSecurityGroup.ref] : [],
        tags: tagList({ Name: `${config.name}-${endpoint.service}`, ...tags })
      });
    }
  }

  createFlowLogs(config, vpc, tags) {
    if (!config.flowLogs || config.flowLogs.enabled !== true) {
      return;
    }
    const group = new logs.CfnLogGroup(this, "VpcFlowLogGroup", {
      logGroupName: `/aws/vpc/${config.name}/flow`,
      retentionInDays: config.flowLogs.retentionDays || 90,
      tags: tagList({ Name: `${config.name}-flow`, ...tags })
    });
    const role = new iam.CfnRole(this, "VpcFlowLogRole", {
      assumeRolePolicyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "vpc-flow-logs.amazonaws.com" },
            Action: "sts:AssumeRole"
          }
        ]
      },
      tags: tagList({ Name: `${config.name}-flow-role`, ...tags })
    });
    new iam.CfnPolicy(this, "VpcFlowLogPolicy", {
      policyName: `${config.name}-flow-delivery`,
      roles: [role.ref],
      policyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Action: ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"],
            Resource: cdk.Fn.sub("${LogGroupArn}:*", { LogGroupArn: group.attrArn })
          }
        ]
      }
    });
    new ec2.CfnFlowLog(this, "VpcFlowLog", {
      resourceId: vpc.ref,
      resourceType: "VPC",
      trafficType: config.flowLogs.trafficType || "ALL",
      deliverLogsPermissionArn: role.attrArn,
      logDestinationType: "cloud-watch-logs",
      logGroupName: group.ref,
      tags: tagList({ Name: `${config.name}-flow`, ...tags })
    });
  }

  createOutputs(subnets, routeTables, vpc) {
    const subnetIds = (tier) => subnets.filter((subnet) => subnet.tier === tier).map((subnet) => subnet.resource.ref);
    const tableIds = (tier) => routeTables.filter((table) => table.tier === tier).map((table) => table.resource.ref);
    emitOutput(this, "VpcId", vpc.ref);
    emitOutput(this, "PublicSubnetIds", cdk.Fn.join(",", subnetIds("public")));
    emitOutput(this, "PrivateSubnetIds", cdk.Fn.join(",", subnetIds("private")));
    emitOutput(this, "DatabaseSubnetIds", cdk.Fn.join(",", subnetIds("database")));
    emitOutput(this, "IntraSubnetIds", cdk.Fn.join(",", subnetIds("intra")));
    emitOutput(this, "PrivateRouteTableIds", cdk.Fn.join(",", tableIds("private")));
    emitOutput(this, "DatabaseRouteTableIds", cdk.Fn.join(",", tableIds("database")));
    emitOutput(this, "GatewayEndpointIds", cdk.Fn.join(",", this.gatewayEndpointIds || []));
  }
}

function emitOutput(scope, logicalId, value) {
  const output = new cdk.CfnOutput(scope, logicalId, { value });
  output.overrideLogicalId(logicalId);
}

function validateConfig(config) {
  if (!config || typeof config !== "object") {
    throw new Error("configuration object is required");
  }
  const normalized = {
    ...config,
    name: config.name || "fleet",
    region: config.region || "us-east-1",
    tags: config.tags || {},
    secondaryCidrs: config.secondaryCidrs || [],
    subnets: requireArray(config.subnets, "subnets"),
    availabilityZones: requireArray(config.availabilityZones, "availabilityZones")
  };
  const vpcCidr = parseCidr(normalized.cidr);
  const secondaryCidrs = normalized.secondaryCidrs.map(parseCidr);
  const containingCidrs = [vpcCidr, ...secondaryCidrs];
  const seenSubnets = [];
  const tiersByAz = new Map();
  for (const subnet of normalized.subnets) {
    if (!SUBNET_TIERS.has(subnet.tier)) {
      throw new Error(`unknown subnet tier: ${subnet.tier}`);
    }
    if (!normalized.availabilityZones.includes(subnet.az)) {
      throw new Error(`subnet ${subnet.name} uses an AZ outside availabilityZones`);
    }
    const parsed = parseCidr(subnet.cidr);
    if (!containingCidrs.some((parent) => cidrContains(parent, parsed))) {
      throw new Error(`subnet ${subnet.name} is outside VPC CIDR boundaries`);
    }
    for (const other of seenSubnets) {
      if (cidrOverlaps(parsed, other.parsed)) {
        throw new Error(`subnet CIDR ${subnet.cidr} overlaps ${other.name}`);
      }
    }
    seenSubnets.push({ name: subnet.name, parsed });
    const azTiers = tiersByAz.get(subnet.az) || new Set();
    azTiers.add(subnet.tier);
    tiersByAz.set(subnet.az, azTiers);
  }
  if (normalized.enableNatGateway) {
    const publicAzs = new Set(normalized.subnets.filter((subnet) => subnet.tier === "public").map((subnet) => subnet.az));
    if (publicAzs.size === 0) {
      throw new Error("NAT is enabled without public subnet coverage");
    }
    if (normalized.oneNatGatewayPerAz && !normalized.singleNatGateway) {
      for (const az of normalized.availabilityZones) {
        const tiers = tiersByAz.get(az) || new Set();
        if (tiers.has("private") && !publicAzs.has(az)) {
          throw new Error(`missing NAT gateway public subnet for ${az}`);
        }
      }
    }
  }
  for (const endpoint of normalized.gatewayEndpoints || []) {
    if (!GATEWAY_ENDPOINTS.has(endpoint.service)) {
      throw new Error(`unsupported gateway endpoint service: ${endpoint.service}`);
    }
    validateEndpointTiers(endpoint);
  }
  for (const endpoint of normalized.interfaceEndpoints || []) {
    if (!INTERFACE_ENDPOINTS.has(endpoint.service)) {
      throw new Error(`unsupported interface endpoint service: ${endpoint.service}`);
    }
    validateEndpointTiers(endpoint);
  }
  return normalized;
}

function validateEndpointTiers(endpoint) {
  if (!Array.isArray(endpoint.tiers) || endpoint.tiers.length === 0) {
    throw new Error(`endpoint ${endpoint.service} must select at least one tier`);
  }
  for (const tier of endpoint.tiers) {
    if (!SUBNET_TIERS.has(tier)) {
      throw new Error(`endpoint ${endpoint.service} references unknown tier ${tier}`);
    }
  }
}

module.exports = { NetworkFabric };
