from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time

class StateError(RuntimeError):
    pass

@dataclass
class Artifact:
    logical_name: str
    staged_path: str
    destination: str
    sha256: str
    mode: str
    validator: str

def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def atomic_write(path: Path, payload: bytes, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        dirfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise

def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)

def stable_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()

class HostState:
    def __init__(self, root: Path, host: str):
        self.root = root
        self.host = host
        self.state_dir = root / "state" / host
        self.stage_dir = root / "staged" / host
        self.rootfs = root / "rootfs" / host
        self.history_dir = self.state_dir / "history"
        self.meta_path = self.state_dir / "current.json"
    def current(self) -> dict[str, Any]:
        return load_json(self.meta_path, {"host": self.host, "generation": 0, "artifacts": {}, "status": "empty"})
    def next_generation(self) -> int:
        return int(self.current().get("generation", 0)) + 1
    def prepare_stage(self) -> Path:
        generation = self.next_generation()
        path = self.stage_dir / str(generation)
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        return path
    def stage_text(self, relative: str, text: str, mode: int = 0o640) -> Path:
        stage = self.stage_dir / str(self.next_generation()) / relative.lstrip("/")
        stage.parent.mkdir(parents=True, exist_ok=True)
        stage.write_text(text, encoding="utf-8")
        os.chmod(stage, mode)
        return stage
    def stage_bytes(self, relative: str, data: bytes, mode: int = 0o640) -> Path:
        stage = self.stage_dir / str(self.next_generation()) / relative.lstrip("/")
        stage.parent.mkdir(parents=True, exist_ok=True)
        stage.write_bytes(data)
        os.chmod(stage, mode)
        return stage
    def build_artifact(self, logical_name: str, relative: str, validator: str = "", mode: str = "0640") -> Artifact:
        staged = self.stage_dir / str(self.next_generation()) / relative.lstrip("/")
        if not staged.is_file():
            raise StateError(f"missing staged artifact {staged}")
        return Artifact(logical_name, str(staged), "/" + relative.lstrip("/"), digest_file(staged), mode, validator)
    def validate_artifact(self, artifact: Artifact) -> None:
        path = Path(artifact.staged_path)
        if not path.is_file():
            raise StateError(f"staged file disappeared: {path}")
        if digest_file(path) != artifact.sha256:
            raise StateError(f"staged checksum changed: {artifact.logical_name}")
        if not path.read_bytes():
            raise StateError(f"staged artifact is empty: {artifact.logical_name}")
        if artifact.validator == "json":
            json.loads(path.read_text(encoding="utf-8"))
        elif artifact.validator == "yaml":
            import yaml
            yaml.safe_load(path.read_text(encoding="utf-8"))
        elif artifact.validator == "nginx":
            text = path.read_text(encoding="utf-8")
            if "upstream " not in text and "server {" not in text:
                raise StateError("proxy configuration has no upstream/server block")
            if text.count("{") != text.count("}"):
                raise StateError("proxy configuration braces are unbalanced")
        elif artifact.validator == "policy":
            priorities = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("priority "):
                    priorities.append(int(line.split()[1]))
            if priorities != sorted(priorities):
                raise StateError("policy priorities are not ordered")
            if len(priorities) != len(set(priorities)):
                raise StateError("policy priorities collide")
    def validate_set(self, artifacts: list[Artifact]) -> None:
        destinations = set()
        logical = set()
        for artifact in artifacts:
            if artifact.destination in destinations:
                raise StateError(f"duplicate destination {artifact.destination}")
            if artifact.logical_name in logical:
                raise StateError(f"duplicate logical artifact {artifact.logical_name}")
            destinations.add(artifact.destination)
            logical.add(artifact.logical_name)
            self.validate_artifact(artifact)
    def snapshot_previous(self, current: Mapping[str, Any]) -> None:
        generation = int(current.get("generation", 0))
        if generation <= 0:
            return
        atomic_write(self.history_dir / f"{generation}.json", stable_json(current), 0o600)
    def copy_atomic(self, source: Path, destination: Path, mode: str) -> None:
        atomic_write(destination, source.read_bytes(), int(mode, 8))
    def promote(self, artifacts: list[Artifact]) -> dict[str, Any]:
        self.validate_set(artifacts)
        current = self.current()
        generation = self.next_generation()
        self.snapshot_previous(current)
        manifest = {}
        changed = []
        for artifact in artifacts:
            destination = self.rootfs / artifact.destination.lstrip("/")
            before = digest_file(destination) if destination.is_file() else None
            if before != artifact.sha256:
                self.copy_atomic(Path(artifact.staged_path), destination, artifact.mode)
                changed.append(artifact.logical_name)
            manifest[artifact.logical_name] = {"destination": artifact.destination, "sha256": artifact.sha256, "mode": artifact.mode, "validator": artifact.validator}
        record = {
            "schema": "fleet-host-state/v1",
            "host": self.host,
            "generation": generation,
            "previous_generation": int(current.get("generation", 0)) or None,
            "artifacts": manifest,
            "changed": sorted(changed),
            "status": "current",
            "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        atomic_write(self.meta_path, stable_json(record), 0o600)
        return record
    def rollback(self, generation: int | None = None) -> dict[str, Any]:
        current = self.current()
        target = generation if generation is not None else current.get("previous_generation")
        if not target:
            raise StateError("no previous generation available")
        snapshot = load_json(self.history_dir / f"{int(target)}.json")
        if not snapshot:
            raise StateError(f"history generation {target} is missing")
        for name, meta in snapshot.get("artifacts", {}).items():
            destination = self.rootfs / str(meta["destination"]).lstrip("/")
            expected = str(meta["sha256"])
            if destination.exists() and digest_file(destination) == expected:
                continue
            raise StateError(f"rollback source for {name} is unavailable; refusing partial rollback")
        restored = dict(snapshot)
        restored["status"] = "rolled-back"
        restored["rolled_back_from"] = current.get("generation")
        restored["rolled_back_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        atomic_write(self.meta_path, stable_json(restored), 0o600)
        return restored
    def verify_materialized(self) -> dict[str, Any]:
        current = self.current()
        results = {}
        for name, meta in current.get("artifacts", {}).items():
            path = self.rootfs / str(meta["destination"]).lstrip("/")
            actual = digest_file(path) if path.is_file() else None
            results[name] = {"expected": meta["sha256"], "actual": actual, "ok": actual == meta["sha256"]}
        return {"host": self.host, "generation": current.get("generation", 0), "artifacts": results, "ok": all(v["ok"] for v in results.values())}

def discover_hosts(root: Path) -> list[str]:
    state = root / "state"
    return sorted(p.name for p in state.iterdir() if p.is_dir()) if state.exists() else []

def fleet_report(root: Path, hosts: list[str] | None = None) -> dict[str, Any]:
    names = hosts or discover_hosts(root)
    rows = [HostState(root, name).verify_materialized() for name in names]
    return {"schema": "fleet-state-report/v1", "hosts": rows, "ok": all(row["ok"] for row in rows)}

def promote_from_manifest(root: Path, host: str, manifest_path: Path) -> dict[str, Any]:
    raw = load_json(manifest_path)
    if not isinstance(raw, dict) or not isinstance(raw.get("artifacts"), list):
        raise StateError("promotion manifest must contain artifacts list")
    artifacts = []
    for item in raw["artifacts"]:
        artifacts.append(Artifact(logical_name=str(item["logical_name"]), staged_path=str(item["staged_path"]), destination=str(item["destination"]), sha256=str(item["sha256"]), mode=str(item.get("mode", "0640")), validator=str(item.get("validator", ""))))
    return HostState(root, host).promote(artifacts)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("hosts", nargs="*")
    promote = sub.add_parser("promote")
    promote.add_argument("host")
    promote.add_argument("manifest")
    verify = sub.add_parser("verify")
    verify.add_argument("host")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("host")
    rollback.add_argument("--generation", type=int)
    args = parser.parse_args()
    root = Path(args.root)
    if args.command == "report":
        output = fleet_report(root, args.hosts or None)
    elif args.command == "promote":
        output = promote_from_manifest(root, args.host, Path(args.manifest))
    elif args.command == "verify":
        output = HostState(root, args.host).verify_materialized()
    else:
        output = HostState(root, args.host).rollback(args.generation)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output.get("ok", True) else 1

if __name__ == "__main__":
    raise SystemExit(main())
