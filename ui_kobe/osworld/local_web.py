"""Guest website routing for the local WSL profile, outside OSWorld's source tree."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


NETWORK = "osworld-local-web"
HOST = "teamchat.127.0.0.1.nip.io"
ORIGIN = f"http://{HOST}:21280"


def ensure_guest_return_route(container, address):
    """The image NATs only eth0; Docker attaches the website network as another NIC.

    Translate only traffic to this Caddy address/port, inside this disposable VM
    container, so website responses can return to the QEMU guest subnet.
    """
    ipaddress.ip_address(address)
    rule = ["POSTROUTING", "-d", str(address), "-p", "tcp", "--dport", "21280", "-j", "MASQUERADE"]
    check = container.exec_run(["iptables", "-t", "nat", "-C", *rule])
    if check.exit_code == 0:
        return
    if check.exit_code != 1:
        raise RuntimeError("Cannot inspect the VM container's website return route")
    result = container.exec_run(["iptables", "-t", "nat", "-A", *rule])
    if result.exit_code != 0:
        raise RuntimeError("Cannot configure the VM container's website return route")


def configure_local_teamchat(env):
    return configure_local_websites(env, ("teamchat",))


def website_origins(apps):
    if not apps or len(set(apps)) != len(apps) or set(apps) - {"teamchat", "vaultbank", "mailhub"}:
        raise ValueError("Unsupported or duplicate local website")
    return tuple(f"http://{app}.127.0.0.1.nip.io:21280" for app in apps)


def configure_local_websites(env, apps):
    """Run before task reset on a fresh disposable guest. Uses the documented VM password."""
    import requests

    origins = website_origins(apps)
    client, container = env.provider.client, env.provider.container
    network = client.networks.get(NETWORK)
    proxies = client.containers.list(filters={"label": [
        "com.docker.compose.project=osworld-local-web", "com.docker.compose.service=caddy"]})
    if len(proxies) != 1:
        raise RuntimeError("Start the osworld-local-web proxy and required sites: " + ", ".join(apps))
    proxies[0].reload()
    address = proxies[0].attrs["NetworkSettings"]["Networks"][NETWORK]["IPAddress"]
    ipaddress.ip_address(address)
    container.reload()
    if NETWORK not in container.attrs["NetworkSettings"]["Networks"]:
        network.connect(container)
    ensure_guest_return_route(container, address)
    entry = f"{address} {' '.join(urlsplit(origin).hostname for origin in origins)} # ui-kobe-local-web"
    script = (
        "from pathlib import Path\nimport json, subprocess\n"
        "p = Path('/etc/hosts')\n"
        "lines = [x for x in p.read_text().splitlines() if '# ui-kobe-local-web' not in x]\n"
        f"p.write_text('\\n'.join(lines + [{entry!r}]) + '\\n')\n"
        f"policy = {{'OverrideSecurityRestrictionsOnInsecureOrigin': {list(origins)!r}, "
        f"'NotificationsAllowedForUrls': {list(origins)!r}}}\n"
        "for folder in ['/etc/opt/chrome/policies/managed', '/etc/chromium/policies/managed']:\n"
        "    directory = Path(folder)\n"
        "    directory.mkdir(parents=True, exist_ok=True)\n"
        "    directory.chmod(0o755)\n"
        "    policy_file = directory / 'ui-kobe-local-web.json'\n"
        "    policy_file.write_text(json.dumps(policy))\n"
        "    policy_file.chmod(0o644)\n"
        "subprocess.run(['pkill', '-TERM', '-u', 'user', '-x', 'chrome'], check=False)\n"
    )
    # sudo receives the guest password on stdin. The GLM API key never enters the VM.
    command = (
        "import subprocess\n"
        f"r = subprocess.run(['sudo', '-S', '-p', '', 'python3', '-c', {script!r}], "
        f"input={env.client_password + chr(10)!r}, text=True, capture_output=True)\n"
        "print('GUEST_ROUTE_OK' if r.returncode == 0 else 'GUEST_ROUTE_FAILED')\n"
        "raise SystemExit(r.returncode)\n"
    )
    with requests.Session() as session:
        session.trust_env = False

        def execute(code, marker):
            response = session.post(f"http://127.0.0.1:{env.server_port}/execute",
                                    json={"command": ["python3", "-c", code], "shell": False}, timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get("returncode") != 0 or marker not in result.get("output", ""):
                if marker == "WEBSITE_HTTP_OK":
                    raise RuntimeError("Guest cannot reach required sites: " + ", ".join(apps))
                raise RuntimeError("Guest website setup failed (check OSWORLD_CLIENT_PASSWORD and web services)")

        execute(command, "GUEST_ROUTE_OK")
        for app, origin in zip(apps, origins):
            endpoint = origin + ("/api/info" if app == "teamchat" else "/")
            execute("import urllib.request\n"
                    "opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
                    f"assert opener.open({endpoint!r}, timeout=15).status == 200\n"
                    "print('WEBSITE_HTTP_OK')\n", "WEBSITE_HTTP_OK")


def verify_local_websites(env, apps):
    """Verify all task tabs after official setup; this metadata is never model input."""
    from playwright.sync_api import sync_playwright
    origins = website_origins(apps)
    results = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{env.chromium_port}")
        for app, origin in zip(apps, origins):
            pages = [page for context in browser.contexts for page in context.pages
                     if urlsplit(page.url).netloc == urlsplit(origin).netloc]
            if not pages:
                raise RuntimeError(f"Task setup did not open {app}")
            pages[0].wait_for_load_state("domcontentloaded")
            results[app] = {"opened": True}
    return results


def verify_teamchat_browser(env):
    """Harness readiness check only. Its result is never sent to the model."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{env.chromium_port}")
        pages = [page for context in browser.contexts for page in context.pages if HOST in page.url]
        if not pages:
            raise RuntimeError("Task035 did not open the local TeamChat page")
        pages[0].wait_for_load_state("domcontentloaded")
        state = pages[0].evaluate("({secure:window.isSecureContext,notifications:Notification.permission})")
        if state != {"secure": True, "notifications": "granted"}:
            raise RuntimeError(f"Task035 notifications are not ready: {state}")
        return state
