"""Run unchanged Task046 websites inside the experiment's shared service."""
from __future__ import annotations

import io
import os
from pathlib import Path
import signal
import socket
import subprocess
import tarfile
import time

from scripts.osworld_native_experiment import PROJECT, ROOT, digest, load, now, require_scope, write

NATIVE = ROOT / "native-web"
PRIOR = NATIVE / "runtime-probe-20261004-v3"
CANDIDATE = PROJECT / "docs/experiments/task046-native-caddy-persistence-20261004"
OWNER = "ui-kobe.native-web.run"
TEAMCHAT_IMAGE = "sha256:8380e33997ce68583520444cdbbc556458b0719fc96769bfa39998170930b2aa"
SITES = ("mailhub_web", "vaultbank_web")


def deployment_snapshot():
    """Freeze already built artifacts; never install dependencies or rebuild."""
    files = {}

    def add(path, expected=None):
        path = Path(path)
        actual = digest(path)
        if expected is not None and actual != expected:
            raise RuntimeError("Native website source/artifact changed: " + str(path))
        files[str(path)] = actual

    for site in SITES:
        record_path = NATIVE / site / "source-manifest.json"
        record = load(record_path)
        add(record_path)
        source = Path(record["source"])
        head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True)
        if head != record["commit"] or dirty:
            raise RuntimeError("Native website repository changed")
        for name, expected in record["sha256"].items():
            add(source / name, expected)
            add(Path(record["copy"]) / name, expected)
        ready_path = NATIVE / site / "backend-preparation-v2/ready.json"
        ready = load(ready_path)
        add(ready_path)
        for path in sorted(Path(ready["target"]).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                add(path)
        artifacts_path = NATIVE / site / "frontend-preparation-v2/artifacts.json"
        add(artifacts_path)
        for name, item in load(artifacts_path).items():
            add(Path(record["copy"]) / "frontend/dist" / name, item["sha256"])
    node = load(NATIVE / "node-ready.json")
    add(NATIVE / "node-ready.json")
    add(node["node"], node["node_sha256"])
    add(PRIOR / "manifest.json")
    add(PRIOR / "static.mjs")
    candidate = load(CANDIDATE / "deployment-candidate.json")
    add(CANDIDATE / "deployment-candidate.json")
    add(CANDIDATE / "native-sites.Caddyfile", candidate["base_config_sha256"])
    return {"files": files, "candidate": candidate, "teamchat_backend_image": TEAMCHAT_IMAGE,
            "caddy_lifecycle": "Run-owned proxy using validated persistent startup configuration; original proxy stays stopped",
            "service_memory_max": 2 * 1024**3, "service_swap_max": 0,
            "runtime_differences": ["Python3.12.3 vs container3.11", "uv0.12.17 vs0.12.1",
                "Node20.20.2 glibc vs Node20 Alpine", "External Node static server instead of nginx; previously tested behavior only"]}


def validate_admission(path, current_source):
    record = load(Path(path))
    if (record.get("status") != "passed" or not record.get("cleanup_ok")
            or record.get("project_source") != current_source):
        raise RuntimeError("Task046 needs a successful, cleaned setup proof for the current interface")
    for name, expected in record["evidence_sha256"].items():
        if digest(Path(name)) != expected:
            raise RuntimeError("Task046 setup admission evidence changed")
    return {"path": str(Path(path).resolve()), "sha256": digest(Path(path))}


class NativeWeb:
    def __init__(self, stage, client):
        self.stage, self.client = Path(stage), client
        self.manifest_path = self.stage / "manifest.json"
        self.manifest = load(self.manifest_path)
        self.group = require_scope(2 * 1024**3)
        self.processes, self.logs = [], []

    def save(self):
        # Only this supervisor mutates the manifest while websites start.
        write(self.manifest_path, self.manifest)

    def start(self):
        import requests

        prior = load(PRIOR / "manifest.json")
        candidate = load(CANDIDATE / "deployment-candidate.json")
        original = self.client.containers.get("osworld-local-web-caddy-1")
        web = [self.client.containers.get("osworld-local-web-teamchat_web_backend-1"),
               self.client.containers.get("osworld-local-web-teamchat_web_frontend-1")]
        for item, cap in zip([original, *web], (128, 512, 128)):
            item.reload()
            if item.status != "exited" or item.attrs["HostConfig"]["Memory"] != cap * 1024**2 or item.attrs["HostConfig"]["MemorySwap"] != cap * 1024**2:
                raise RuntimeError("Task046 website ownership or fixed resource caps differ")
        if original.attrs["Image"] != candidate["image"] or web[0].attrs["Image"] != TEAMCHAT_IMAGE:
            raise RuntimeError("Previously verified website image changed")
        for details in prior["sites"].values():
            for key in ("backend_port", "frontend_port"):
                with socket.socket() as probe:
                    probe.bind(("0.0.0.0", details[key]))
        work = self.stage / "native-web"
        work.mkdir(exist_ok=False)
        self.manifest.update(web_owned=True, web_container_ids=[item.id for item in web],
            native_web={"work": str(work), "processes": [], "volume_names": [], "proxy_id": None,
                        "original_proxy_id": original.id, "original_proxy_kept_stopped": True})
        self.save()
        for site, details in prior["sites"].items():
            cwd = work / site
            cwd.mkdir()
            (cwd / "empty.env").write_text("")
            for role in ("backend", "frontend"):
                command = [part.replace(str(PRIOR / site), str(cwd)) for part in details[role + "_command"]]
                log = (cwd / (role + ".log")).open("xb")
                self.logs.append(log)
                child = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                self.processes.append(child)
                actual = Path("/sys/fs/cgroup") / Path(f"/proc/{child.pid}/cgroup").read_text().strip().split(":")[-1].lstrip("/")
                if actual.resolve() != self.group.resolve():
                    raise RuntimeError("Native website did not inherit the shared service")
                self.manifest["native_web"]["processes"].append({"site": site, "role": role, "pid": child.pid,
                    "cgroup": str(actual), "command": command})
                self.save()
        labels = {OWNER: self.manifest["run_id"]}
        volumes = []
        for suffix in ("data", "config"):
            volume = self.client.volumes.create(name=self.manifest["run_id"] + "-caddy-" + suffix, labels=labels)
            volumes.append(volume)
            self.manifest["native_web"]["volume_names"].append(volume.name)
            self.save()
        proxy = self.client.containers.create(candidate["image"], command=candidate["command"],
            entrypoint=candidate["entrypoint"], name=self.manifest["run_id"] + "-caddy",
            environment=candidate["environment"], network="osworld-local-web",
            ports={"21280/tcp": ("127.0.0.1", 21280)}, extra_hosts={"host.docker.internal": "host-gateway"},
            volumes={volumes[0].name: {"bind": "/data", "mode": "rw"},
                     volumes[1].name: {"bind": "/config", "mode": "rw"},
                     "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "ro"}},
            labels={**labels, "com.docker.compose.project": "osworld-local-web", "com.docker.compose.service": "caddy"},
            mem_limit=128 * 1024**2, memswap_limit=128 * 1024**2, restart_policy={"Name": "no"})
        self.manifest["native_web"]["proxy_id"] = proxy.id
        self.manifest["web_container_ids"].append(proxy.id)
        self.save()
        raw = (CANDIDATE / "native-sites.Caddyfile").read_bytes()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as bundle:
            item = tarfile.TarInfo("native-sites.Caddyfile")
            item.size, item.mode = len(raw), 0o444
            bundle.addfile(item, io.BytesIO(raw))
        if not proxy.put_archive("/config", archive.getvalue()):
            raise RuntimeError("Cannot install validated Caddy startup configuration")
        for item in [*web, proxy]:
            item.start()
        deadline = time.monotonic() + 60
        receipts = []
        with requests.Session() as session:
            session.trust_env = False
            while True:
                self.check()
                from scripts.native_resource_accounting import reserve_ok, sample
                from scripts.osworld_native_experiment import host_status
                resource = {"time_utc": now(), **sample(self.client, self.manifest, host_status, self.group)}
                with (work / "startup-resources.jsonl").open("a") as stream:
                    import json
                    stream.write(json.dumps(resource) + "\n")
                if not reserve_ok(resource["windows"]):
                    raise RuntimeError("Task046 website startup reserve failed")
                try:
                    for app in ("mailhub", "vaultbank", "teamchat"):
                        response = session.get("http://127.0.0.1:21280/api/openapi.json",
                            headers={"Host": app + ".127.0.0.1.nip.io:21280"}, timeout=4)
                        response.raise_for_status()
                        response.json()
                        receipts.append({"app": app, "status": response.status_code, "time_utc": now()})
                    break
                except (requests.RequestException, ValueError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("Task046 website startup exceeded 60 seconds")
                    time.sleep(1)
        write(work / "ready.json", {"time_utc": now(), "http": receipts, "shared_cgroup": str(self.group),
            "processes": self.manifest["native_web"]["processes"], "proxy_id": proxy.id,
            "memory_max": (self.group / "memory.max").read_text().strip(), "swap_max": "0"})

    def check(self):
        if any(child.poll() is not None for child in self.processes):
            raise RuntimeError("A native Task046 website process exited; see preserved logs")

    def stop(self):
        for child in self.processes:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in self.processes:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
        for log in self.logs:
            log.close()


def cleanup_proxy(stage):
    """Remove only this run's stopped replacement proxy/volumes, not TeamChat."""
    import docker

    manifest = load(Path(stage) / "manifest.json")
    native = manifest.get("native_web")
    if not native:
        return
    client = docker.from_env(timeout=15)
    try:
        identifier = native.get("proxy_id")
        if identifier:
            try:
                proxy = client.containers.get(identifier)
                if proxy.labels.get(OWNER) != manifest["run_id"]:
                    raise RuntimeError("Native proxy ownership differs")
                if proxy.attrs["State"]["Running"]:
                    raise RuntimeError("Native proxy still running after cleanup")
                logpath = Path(stage) / "native-web/caddy.log"
                if not logpath.exists():
                    with logpath.open("xb") as log:
                        for block in proxy.logs(stream=True, follow=False):
                            log.write(block)
                proxy.remove(v=True)
            except docker.errors.NotFound:
                pass
        for name in native.get("volume_names", []):
            try:
                volume = client.volumes.get(name)
                if volume.attrs.get("Labels", {}).get(OWNER) != manifest["run_id"]:
                    raise RuntimeError("Native proxy volume ownership differs")
                volume.remove(force=False)
            except docker.errors.NotFound:
                pass
    finally:
        client.close()
