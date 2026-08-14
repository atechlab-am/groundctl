import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

import ansible_runner

from app.config import settings
from app.models import Relay, Server

# ansible-runner resolves `playbook=` directly under project_dir (not a
# subdirectory) — point project_dir at playbooks/ itself. Verified empirically
# against a real ansible-runner 2.4.3 run; passing the ansible/ parent here
# instead produced "the playbook: bootstrap_client.yml could not be found".
ANSIBLE_PROJECT_DIR = str(Path(__file__).parent / "ansible" / "playbooks")

PRIVATE_KEY_PATH = settings.ansible_private_key_path


class AnsibleUnreachableError(Exception):
    """Raised when every failure in a playbook run was an SSH/transport-level
    unreachable host (runner_on_unreachable) with zero genuine task failures
    (runner_on_failed) — i.e. the run is worth retrying as-is. Callers
    (Celery tasks) catch this via autoretry_for for backoff+retry; a real
    task failure never raises this and is never retried.
    """


def _build_inventory(
    target_servers: list[Server], ssh_proxy_by_hostname: dict[str, str] | None = None
) -> dict:
    ssh_proxy_by_hostname = ssh_proxy_by_hostname or {}
    hosts = {}
    for server in target_servers:
        ssh_common_args = "-o StrictHostKeyChecking=accept-new"
        proxy = ssh_proxy_by_hostname.get(server.hostname)
        if proxy:
            # Routes this host's SSH connection through its site's relay as
            # a jump host — the primary only needs reachability to the
            # relay, not to every individual host behind it. Reuses the
            # same shared fleet key for the jump hop (per-hop key isolation
            # is Phase 6, out of scope here). Uses an explicit ProxyCommand
            # rather than the bare `-o ProxyJump=` shorthand: found via live
            # verification that ProxyJump's own implicit inner SSH hop
            # (jump-host -> final destination) does NOT inherit this
            # command's -o StrictHostKeyChecking=accept-new, so it fails
            # host-key verification against the relay's known_hosts (which
            # is empty in a freshly-provisioned fleet) — an explicit
            # ProxyCommand lets the inner hop's flags be stated directly.
            ssh_common_args += (
                f' -o ProxyCommand="ssh -i {PRIVATE_KEY_PATH} -W %h:%p '
                f'-o StrictHostKeyChecking=accept-new {proxy}"'
            )
        hosts[server.hostname] = {
            "ansible_host": server.ip_address,
            "ansible_user": server.ssh_user,
            # Falls back to the shared fleet key when a per-host key hasn't
            # been generated yet (see Server.ssh_key_path and
            # tasks.py's bootstrap_task, which generates and installs it).
            # ProxyJump's inner hop above always uses the shared key
            # regardless — that's the relay's own key, unrelated to this
            # host's per-host key for its own final SSH hop.
            "ansible_ssh_private_key_file": server.ssh_key_path or PRIVATE_KEY_PATH,
            "ansible_ssh_common_args": ssh_common_args,
        }
    return {"all": {"hosts": hosts}}


def _build_relay_inventory(relay: Relay) -> dict:
    # The primary always reaches relays directly — a relay is never itself
    # behind another relay in this phase (no multi-hop relay chains).
    return {
        "all": {
            "hosts": {
                relay.hostname: {
                    "ansible_host": relay.hostname,
                    "ansible_user": relay.ssh_user,
                    "ansible_ssh_private_key_file": PRIVATE_KEY_PATH,
                    "ansible_ssh_common_args": "-o StrictHostKeyChecking=accept-new",
                }
            }
        }
    }


def run_playbook_against_inventory(
    playbook_name: str,
    inventory: dict,
    extra_vars: dict,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[str, str, dict]:
    """Shared execution engine behind run_playbook (server-list inventory)
    and relay-sync (single-relay inventory via _build_relay_inventory) —
    one runner, two inventory-construction entry points. See run_playbook's
    docstring for the return shape and AnsibleUnreachableError semantics.
    """
    private_data_dir = tempfile.mkdtemp(prefix="groundctl-job-")
    try:
        # project_dir (not an absolute playbook path) keeps playbooks outside
        # private_data_dir — see ANSIBLE_PROJECT_DIR comment above for why it
        # points at playbooks/ specifically.
        runner = ansible_runner.run(
            playbook=playbook_name,
            project_dir=ANSIBLE_PROJECT_DIR,
            private_data_dir=private_data_dir,
            inventory=inventory,
            extravars=extra_vars,
            quiet=True,
        )

        log_lines = []
        facts_by_host: dict = {}
        unreachable_hosts: set[str] = set()
        failed_hosts: set[str] = set()
        last_progress_at = time.monotonic()
        events_since_progress = 0

        for event in runner.events:
            stdout_line = event.get("stdout")
            if stdout_line:
                log_lines.append(stdout_line)
                events_since_progress += 1

            event_type = event.get("event")
            event_data = event.get("event_data", {})
            host = event_data.get("host")

            if event_type == "runner_on_unreachable" and host:
                unreachable_hosts.add(host)
            elif event_type == "runner_on_failed" and host:
                failed_hosts.add(host)
            elif event_type == "runner_on_ok":
                res = event_data.get("res", {})
                facts = res.get("ansible_facts")
                if host and facts:
                    # Merge, don't overwrite — a playbook with multiple
                    # fact-gathering tasks (e.g. gather_facts.yml's
                    # package_facts + setup + service_facts) fires one
                    # runner_on_ok per task, each with its own partial
                    # ansible_facts dict. Assigning instead of merging here
                    # meant only the LAST task's facts survived — a real bug
                    # found via live verification once gather_facts.yml grew
                    # beyond a single fact-gathering task.
                    facts_by_host.setdefault(host, {}).update(facts)

            if on_progress is not None and (
                events_since_progress >= 25 or (time.monotonic() - last_progress_at) >= 2.0
            ):
                on_progress("\n".join(log_lines))
                events_since_progress = 0
                last_progress_at = time.monotonic()

        if on_progress is not None:
            on_progress("\n".join(log_lines))

        log_output = "\n".join(log_lines)

        if failed_hosts:
            return runner.status, log_output, facts_by_host
        if unreachable_hosts:
            raise AnsibleUnreachableError(
                f"unreachable hosts (retryable): {', '.join(sorted(unreachable_hosts))}"
            )

        return runner.status, log_output, facts_by_host
    finally:
        shutil.rmtree(private_data_dir, ignore_errors=True)


def run_playbook(
    playbook_name: str,
    target_servers: list[Server],
    extra_vars: dict,
    on_progress: Callable[[str], None] | None = None,
    ssh_proxy_by_hostname: dict[str, str] | None = None,
) -> tuple[str, str, dict]:
    """Run a playbook against target_servers. Returns (status, log_output, ansible_facts_by_host).

    ansible_facts_by_host maps hostname -> its `ansible_facts` dict (only
    populated for playbooks that gather facts, e.g. gather_facts.yml).

    Raises AnsibleUnreachableError if every failure was transport-level
    unreachable with no genuine task failures — see that class's docstring.

    on_progress, if given, is called periodically (throttled internally)
    with the log accumulated so far, so callers can stream it into Job.log_output
    during a long-running playbook instead of only writing once at the end.

    ssh_proxy_by_hostname, if given, maps hostname -> "user@relay_host" for
    any target server whose site has a healthy relay — that host's SSH
    connection is routed through the relay via ProxyJump instead of direct.
    Callers resolve this themselves (see tasks.py's _relay_proxy_for_servers)
    since this function stays a pure playbook-runner with no DB awareness.
    """
    return run_playbook_against_inventory(
        playbook_name,
        _build_inventory(target_servers, ssh_proxy_by_hostname),
        extra_vars,
        on_progress=on_progress,
    )
