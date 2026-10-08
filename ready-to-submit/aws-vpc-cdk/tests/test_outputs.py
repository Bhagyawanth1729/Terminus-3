"""Verifier for the Node.js AWS CDK VPC module.

The tests synthesize the submitted construct with several network intents and
inspect the generated CloudFormation without using AWS credentials or deploys.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE_CONFIG = FIXTURES / "enterprise-network.json"
ARTIFACT = Path(os.environ.get("CDK_ARTIFACT", "/app/cdk-vpc"))
WORK = Path(os.environ.get("CDK_TEST_WORKDIR", "/tmp/aws-vpc-cdk-work"))
NODE_ENV = {
    **os.environ,
    "NODE_PATH": os.environ.get("NODE_PATH", "/usr/local/lib/node_modules"),
    "CDK_DISABLE_VERSION_CHECK": "1",
    "JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION": "1",
}


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=NODE_ENV, text=True, capture_output=True, check=False)


def _prepare(config: dict | None = None) -> tuple[Path, Path]:
    if WORK.exists():
        shutil.rmtree(WORK)
    project = WORK / "cdk-vpc"
    shutil.copytree(
        ARTIFACT,
        project,
        ignore=shutil.ignore_patterns("node_modules", "cdk.out", ".git", "*.log"),
    )
    cfg = config or json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    cfg_path = WORK / "network.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return project, cfg_path


def _synth(config: dict | None = None, expect_success: bool = True) -> tuple[dict | None, subprocess.CompletedProcess]:
    project, cfg_path = _prepare(config)
    out_dir = WORK / "out"
    proc = _run(["node", "bin/synth.js", "--config", str(cfg_path), "--out", str(out_dir)], cwd=project)
    if expect_success:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        template_path = out_dir / "FleetVpc.template.json"
        assert template_path.is_file(), "missing FleetVpc.template.json"
        return json.loads(template_path.read_text(encoding="utf-8")), proc
    assert proc.returncode != 0, "synthesis should fail for invalid network intent"
    return None, proc


def _resources(template: dict, resource_type: str) -> dict:
    return {
        name: resource
        for name, resource in template.get("Resources", {}).items()
        if resource.get("Type") == resource_type
    }


def _tags(resource: dict) -> dict:
    return {item["Key"]: item["Value"] for item in resource.get("Properties", {}).get("Tags", [])}


def _ref_name(value: object) -> str:
    if isinstance(value, dict) and "Ref" in value:
        return str(value["Ref"])
    return str(value)


@pytest.fixture(scope="session")
def template() -> dict:
    return _synth()[0]


def test_project_exports_a_cdk_construct_and_synth_entrypoint():
    """The submitted artifact exposes the expected CDK module and CLI entrypoint."""
    assert (ARTIFACT / "package.json").is_file()
    assert (ARTIFACT / "bin" / "synth.js").is_file()
    assert (ARTIFACT / "lib" / "network-fabric.js").is_file()
    pkg = json.loads((ARTIFACT / "package.json").read_text(encoding="utf-8"))
    assert pkg["dependencies"]["aws-cdk-lib"] == "2.155.0"
    assert pkg["dependencies"]["constructs"] == "10.3.0"


def test_vpc_core_properties_secondary_cidr_and_outputs(template: dict):
    """Core VPC resources include DNS, secondary CIDR, stable tags, and required outputs."""
    vpcs = _resources(template, "AWS::EC2::VPC")
    assert len(vpcs) == 1
    vpc = next(iter(vpcs.values()))
    assert vpc["Properties"]["CidrBlock"] == "10.80.0.0/16"
    assert vpc["Properties"]["EnableDnsHostnames"] is True
    assert vpc["Properties"]["EnableDnsSupport"] is True
    tags = _tags(vpc)
    assert tags["Name"] == "settlement-prod"
    assert tags["Application"] == "settlement"
    secondary = _resources(template, "AWS::EC2::VPCCidrBlock")
    assert any(r["Properties"].get("CidrBlock") == "10.90.0.0/16" for r in secondary.values())
    assert any(r["Properties"].get("AmazonProvidedIpv6CidrBlock") is True for r in secondary.values())
    for output in [
        "VpcId",
        "PublicSubnetIds",
        "PrivateSubnetIds",
        "DatabaseSubnetIds",
        "IntraSubnetIds",
        "PrivateRouteTableIds",
        "DatabaseRouteTableIds",
        "GatewayEndpointIds",
    ]:
        assert output in template.get("Outputs", {})


def test_all_subnet_tiers_are_synthesized_with_ipv6_and_tags(template: dict):
    """All four subnet tiers are rendered across AZs with stable tier/AZ tags."""
    subnets = _resources(template, "AWS::EC2::Subnet")
    assert len(subnets) == 12
    tiers = {}
    for logical_id, subnet in subnets.items():
        props = subnet["Properties"]
        tags = _tags(subnet)
        tiers.setdefault(tags["Tier"], []).append((logical_id, subnet))
        assert tags["Az"] == props["AvailabilityZone"]
        assert "Ipv6CidrBlock" in props
    assert {tier: len(items) for tier, items in tiers.items()} == {
        "public": 3,
        "private": 3,
        "database": 3,
        "intra": 3,
    }
    assert all(item["Properties"]["MapPublicIpOnLaunch"] is True for _, item in tiers["public"])
    assert all(item["Properties"]["MapPublicIpOnLaunch"] is False for _, item in tiers["private"])


def test_nat_routes_are_per_az_and_database_subnets_are_isolated(template: dict):
    """Private subnets route through same-AZ NAT while database and intra stay isolated."""
    nat_gateways = _resources(template, "AWS::EC2::NatGateway")
    assert len(nat_gateways) == 3
    routes = _resources(template, "AWS::EC2::Route")
    ipv4_defaults = [
        (logical_id, route)
        for logical_id, route in routes.items()
        if route["Properties"].get("DestinationCidrBlock") == "0.0.0.0/0"
    ]
    public_defaults = [r for name, r in ipv4_defaults if "Public" in name]
    private_defaults = [r for name, r in ipv4_defaults if "Private" in name]
    database_defaults = [r for name, r in ipv4_defaults if "Database" in name]
    intra_defaults = [r for name, r in ipv4_defaults if "Intra" in name]
    assert len(public_defaults) == 3
    assert len(private_defaults) == 3
    assert database_defaults == []
    assert intra_defaults == []
    nat_refs = {_ref_name(route["Properties"].get("NatGatewayId")) for route in private_defaults}
    assert len(nat_refs) == 3
    assert all("NatGateway" in ref for ref in nat_refs)


def test_gateway_and_interface_endpoints_are_scoped(template: dict):
    """Gateway endpoints use selected route tables and interface endpoints stay on private subnets."""
    endpoints = _resources(template, "AWS::EC2::VPCEndpoint")
    gateway = [r for r in endpoints.values() if r["Properties"]["VpcEndpointType"] == "Gateway"]
    interface = [r for r in endpoints.values() if r["Properties"]["VpcEndpointType"] == "Interface"]
    assert len(gateway) == 2
    assert len(interface) == 3
    s3 = next(r for r in gateway if r["Properties"]["ServiceName"].endswith(".s3"))
    ddb = next(r for r in gateway if r["Properties"]["ServiceName"].endswith(".dynamodb"))
    assert len(s3["Properties"]["RouteTableIds"]) == 6
    assert len(ddb["Properties"]["RouteTableIds"]) == 3
    assert all(len(r["Properties"]["SubnetIds"]) == 3 for r in interface)
    assert all(r["Properties"]["PrivateDnsEnabled"] is True for r in interface)
    sgs = _resources(template, "AWS::EC2::SecurityGroup")
    assert len(sgs) == 1
    ingress = _resources(template, "AWS::EC2::SecurityGroupIngress")
    assert len(ingress) == 6
    assert all(r["Properties"]["FromPort"] == 443 for r in ingress.values())
    assert not any(r["Properties"].get("CidrIp") == "0.0.0.0/0" for r in ingress.values())


def test_network_acls_and_flow_logs_are_present(template: dict):
    """Tier NACLs and least-privilege CloudWatch flow logs are synthesized."""
    assert len(_resources(template, "AWS::EC2::NetworkAcl")) == 3
    assert len(_resources(template, "AWS::EC2::SubnetNetworkAclAssociation")) == 9
    entries = _resources(template, "AWS::EC2::NetworkAclEntry")
    assert len(entries) == 6
    flow_logs = _resources(template, "AWS::EC2::FlowLog")
    assert len(flow_logs) == 1
    assert next(iter(flow_logs.values()))["Properties"]["TrafficType"] == "ALL"
    policies = _resources(template, "AWS::IAM::Policy")
    policy_doc = next(iter(policies.values()))["Properties"]["PolicyDocument"]
    actions = set(policy_doc["Statement"][0]["Action"])
    assert {"logs:CreateLogStream", "logs:PutLogEvents"} <= actions
    assert "logs:*" not in actions
    log_groups = _resources(template, "AWS::Logs::LogGroup")
    assert next(iter(log_groups.values()))["Properties"]["RetentionInDays"] == 90


def test_configuration_mutations_change_nat_behavior():
    """Single-NAT and disabled-NAT configs change synthesized routes and resources."""
    cfg = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    single_nat = copy.deepcopy(cfg)
    single_nat["singleNatGateway"] = True
    template = _synth(single_nat)[0]
    assert len(_resources(template, "AWS::EC2::NatGateway")) == 1
    private_routes = [
        route
        for name, route in _resources(template, "AWS::EC2::Route").items()
        if "Private" in name and route["Properties"].get("DestinationCidrBlock") == "0.0.0.0/0"
    ]
    assert len({_ref_name(route["Properties"]["NatGatewayId"]) for route in private_routes}) == 1

    no_nat = copy.deepcopy(cfg)
    no_nat["enableNatGateway"] = False
    template_no_nat = _synth(no_nat)[0]
    assert len(_resources(template_no_nat, "AWS::EC2::NatGateway")) == 0
    assert not [
        route
        for name, route in _resources(template_no_nat, "AWS::EC2::Route").items()
        if "Private" in name and route["Properties"].get("DestinationCidrBlock") == "0.0.0.0/0"
    ]


def test_validation_fails_before_template_for_bad_inputs():
    """Invalid CIDRs, NAT coverage, and endpoint services fail before synthesis."""
    cfg = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    overlap = copy.deepcopy(cfg)
    overlap["subnets"][3]["cidr"] = "10.80.0.128/25"
    _, proc = _synth(overlap, expect_success=False)
    assert "overlap" in (proc.stderr + proc.stdout).lower()

    bad_endpoint = copy.deepcopy(cfg)
    bad_endpoint["gatewayEndpoints"].append({"service": "sns", "tiers": ["private"]})
    _, proc2 = _synth(bad_endpoint, expect_success=False)
    assert "unsupported" in (proc2.stderr + proc2.stdout).lower()

    missing_nat = copy.deepcopy(cfg)
    missing_nat["subnets"] = [s for s in missing_nat["subnets"] if s["name"] != "public-c"]
    _, proc3 = _synth(missing_nat, expect_success=False)
    assert "missing nat" in (proc3.stderr + proc3.stdout).lower()


def test_synth_is_deterministic():
    """Two synth runs for the same intent produce identical template content."""
    first = _synth()[0]
    first_digest = hashlib.sha256(json.dumps(first, sort_keys=True).encode()).hexdigest()
    second = _synth()[0]
    second_digest = hashlib.sha256(json.dumps(second, sort_keys=True).encode()).hexdigest()
    assert first_digest == second_digest
