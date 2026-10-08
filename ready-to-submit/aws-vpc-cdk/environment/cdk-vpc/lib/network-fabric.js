"use strict";

const cdk = require("aws-cdk-lib");
const ec2 = require("aws-cdk-lib/aws-ec2");
const { Construct } = require("constructs");

function stableName(...parts) {
  return parts
    .filter((part) => part !== undefined && part !== null && String(part).length > 0)
    .map((part) => String(part).replace(/[^A-Za-z0-9]/g, ""))
    .join("");
}

class NetworkFabric extends Construct {
  constructor(scope, id, config) {
    super(scope, id);
    if (!config || typeof config !== "object") {
      throw new Error("configuration object is required");
    }
    const tags = { ...(config.tags || {}) };
    const name = config.name || "fleet";
    const region = config.region || "us-east-1";

    const vpc = new ec2.CfnVPC(this, "Vpc", {
      cidrBlock: config.cidr,
      enableDnsHostnames: true,
      enableDnsSupport: true,
      tags: tagList({ Name: name, ...tags, ...(config.vpcTags || {}) })
    });

    const igw = new ec2.CfnInternetGateway(this, "InternetGateway", {
      tags: tagList({ Name: `${name}-igw`, ...tags })
    });
    new ec2.CfnVPCGatewayAttachment(this, "InternetGatewayAttachment", {
      vpcId: vpc.ref,
      internetGatewayId: igw.ref
    });

    const subnets = [];
    for (const [index, subnet] of (config.subnets || []).entries()) {
      if (subnet.tier === "database" || subnet.tier === "intra") {
        continue;
      }
      const resource = new ec2.CfnSubnet(this, stableName(subnet.name, "Subnet"), {
        vpcId: vpc.ref,
        cidrBlock: subnet.cidr,
        availabilityZone: subnet.az,
        mapPublicIpOnLaunch: subnet.tier === "public",
        tags: tagList({ Name: `${name}-${subnet.name}`, Tier: subnet.tier, Az: subnet.az, ...tags })
      });
      subnets.push({ ...subnet, index, resource });
    }

    const routeTables = [];
    const publicTable = new ec2.CfnRouteTable(this, "PublicRouteTable", {
      vpcId: vpc.ref,
      tags: tagList({ Name: `${name}-public`, Tier: "public", ...tags })
    });
    routeTables.push({ tier: "public", az: "shared", resource: publicTable });
    new ec2.CfnRoute(this, "PublicDefaultIpv4", {
      routeTableId: publicTable.ref,
      destinationCidrBlock: "0.0.0.0/0",
      gatewayId: igw.ref
    });

    for (const subnet of subnets) {
      if (subnet.tier === "public") {
        new ec2.CfnSubnetRouteTableAssociation(this, stableName(subnet.name, "Association"), {
          subnetId: subnet.resource.ref,
          routeTableId: publicTable.ref
        });
      }
      if (subnet.tier === "private") {
        const table = new ec2.CfnRouteTable(this, stableName(subnet.name, "RouteTable"), {
          vpcId: vpc.ref,
          tags: tagList({ Name: `${name}-${subnet.name}`, Tier: "private", Az: subnet.az, ...tags })
        });
        routeTables.push({ tier: "private", az: subnet.az, resource: table });
        new ec2.CfnSubnetRouteTableAssociation(this, stableName(subnet.name, "PrivateAssociation"), {
          subnetId: subnet.resource.ref,
          routeTableId: table.ref
        });
      }
    }

    const publicSubnetIds = subnets.filter((s) => s.tier === "public").map((s) => s.resource.ref);
    const privateSubnetIds = subnets.filter((s) => s.tier === "private").map((s) => s.resource.ref);
    new cdk.CfnOutput(this, "VpcId", { value: vpc.ref });
    new cdk.CfnOutput(this, "PublicSubnetIds", { value: cdk.Fn.join(",", publicSubnetIds) });
    new cdk.CfnOutput(this, "PrivateSubnetIds", { value: cdk.Fn.join(",", privateSubnetIds) });
    new cdk.CfnOutput(this, "RouteTableIds", {
      value: cdk.Fn.join(",", routeTables.map((table) => table.resource.ref))
    });

    this.vpc = vpc;
  }
}

function tagList(tags) {
  return Object.keys(tags)
    .sort()
    .map((key) => ({ key, value: String(tags[key]) }));
}

module.exports = { NetworkFabric };
