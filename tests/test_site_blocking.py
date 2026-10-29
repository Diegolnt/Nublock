"""M7: bloqueo de sitios por /etc/hosts. El script del helper se ejecuta de verdad (sin root)
sobre archivos temporales, incluyendo entradas maliciosas."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from helpers import NOON, FakeClock, RecordingNotifier, make_window

from nublock import site_blocking
from nublock.app import NublockApp
from nublock.config import Config, SiteConfig
from nublock.events import DisableRule, PauseAll, StartFocus
from nublock.site_blocking import (
    BEGIN_MARKER,
    END_MARKER,
    HELPER_SCRIPT,
    SiteBlocker,
    blocked_in_hosts,
    expand_domains,
    helper_plist,
)
from nublock.storage import Repository
from nublock.tracker.platform.fake import FakeWindowProvider

ORIGINAL_HOSTS = "127.0.0.1\tlocalhost\n255.255.255.255\tbroadcasthost\n::1             localhost"


def run_helper(tmp_path: Path, list_lines: list[str]) -> str:
    script = tmp_path / "helper.sh"
    script.write_text(HELPER_SCRIPT)
    hosts = tmp_path / "hosts"
    if not hosts.exists():
        hosts.write_text(ORIGINAL_HOSTS)  # sin salto de línea final, a propósito
    listing = tmp_path / "list.txt"
    listing.write_text("".join(f"{line}\n" for line in list_lines))
    subprocess.run(["/bin/sh", str(script), str(listing), str(hosts)], check=True)
    return hosts.read_text()


def test_helper_writes_only_valid_blocking_entries(tmp_path: Path) -> None:
    hosts = run_helper(
        tmp_path,
        [
            "youtube.com",
            "www.youtube.com",
            "evil.com 6.6.6.6",  # intento de redirigir a una IP: se descarta la línea entera
            "*.reddit.com",  # comodines no existen en hosts
            "../../etc/passwd",
            "UPPER.com",  # Nublock escribe en minúsculas: lo demás se ignora
            "",
        ],
    )
    assert hosts.startswith(ORIGINAL_HOSTS + "\n")  # lo original queda intacto
    section = hosts[hosts.index(BEGIN_MARKER) :]
    assert section.splitlines() == [
        BEGIN_MARKER,
        "0.0.0.0 youtube.com",
        ":: youtube.com",
        "0.0.0.0 www.youtube.com",
        ":: www.youtube.com",
        END_MARKER,
    ]
    assert "6.6.6.6" not in hosts


def test_helper_is_idempotent_and_removes_its_section(tmp_path: Path) -> None:
    first = run_helper(tmp_path, ["instagram.com"])
    assert run_helper(tmp_path, ["instagram.com"]) == first  # sin duplicar la sección
    changed = run_helper(tmp_path, ["tiktok.com"])
    assert "instagram.com" not in changed and "0.0.0.0 tiktok.com" in changed
    assert run_helper(tmp_path, []) == ORIGINAL_HOSTS + "\n"  # lista vacía: sin sección


def test_helper_ignores_symlinked_list(tmp_path: Path) -> None:
    script = tmp_path / "helper.sh"
    script.write_text(HELPER_SCRIPT)
    hosts = tmp_path / "hosts"
    hosts.write_text(ORIGINAL_HOSTS)
    secret = tmp_path / "secret.txt"
    secret.write_text("secret.example.com\n")
    link = tmp_path / "list.txt"
    link.symlink_to(secret)  # un symlink podría apuntar a un archivo que solo root puede leer
    subprocess.run(["/bin/sh", str(script), str(link), str(hosts)], check=True)
    assert hosts.read_text() == ORIGINAL_HOSTS


def test_blocked_in_hosts_reads_only_our_section(tmp_path: Path) -> None:
    run_helper(tmp_path, ["reddit.com"])
    hosts = tmp_path / "hosts"
    hosts.write_text(hosts.read_text() + "0.0.0.0 ajeno.com\n")
    assert blocked_in_hosts(hosts) == ["reddit.com"]


def test_expand_domains_adds_common_subdomains() -> None:
    assert expand_domains(["x.com"], ["www", "m"]) == ["m.x.com", "www.x.com", "x.com"]


def test_site_blocker_writes_only_when_the_list_changes(tmp_path: Path) -> None:
    listing = tmp_path / "list.txt"
    blocker = SiteBlocker(["www"], list_path=listing)
    assert blocker.apply(["youtube.com"])
    assert listing.read_text() == "www.youtube.com\nyoutube.com\n"
    assert not blocker.apply(["youtube.com"])  # igual: no reescribe (no despierta a launchd)
    assert blocker.apply([])
    assert listing.read_text() == ""


def test_plist_watches_the_list_and_runs_the_root_helper() -> None:
    plist = helper_plist()
    assert plist["WatchPaths"] == [str(site_blocking.LIST_PATH)]
    assert plist["ProgramArguments"] == [
        "/bin/sh",
        str(site_blocking.HELPER_PATH),
        str(site_blocking.LIST_PATH),
    ]


def test_install_runs_one_admin_command(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []

    def fake_admin(command: str) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(site_blocking, "_run_as_admin", fake_admin)
    assert site_blocking.install().returncode == 0
    (command,) = commands
    assert "install -o root -g wheel -m 755" in command  # helper de root, no modificable
    assert "'/Library/Application Support/Nublock/blocked_domains.txt'" in command  # citado
    assert command.endswith(
        "launchctl bootstrap system /Library/LaunchDaemons/local.nublock.hosts.plist"
    )


def test_site_config_normalizes_and_validates_domains() -> None:
    assert SiteConfig(domain="https://www.YouTube.com/watch?v=1").domain == "youtube.com"
    with pytest.raises(ValueError):
        SiteConfig(domain="youtube")


# --- Qué sitios bloquea el Core -----------------------------------------------------------


@dataclass
class Rig:
    app: NublockApp
    clock: FakeClock
    listing: Path
    provider: FakeWindowProvider

    def tick(self, seconds: float = 0) -> None:
        self.clock.advance(seconds)
        self.app.tick()

    def blocked(self) -> list[str]:
        return [line for line in self.listing.read_text().splitlines() if "." in line]


def make_rig(tmp_path: Path, repo: Repository, observe_only: bool = False) -> Rig:
    config = Config.model_validate(
        {
            "general": {"observe_only": observe_only},
            "rules": [
                {
                    "id": "social-limit",
                    "type": "daily_limit",
                    "target": {"subcategory": "social"},
                    "limit_minutes": 1,
                    "action": "block",
                },
                {
                    "id": "process-rule",  # target por proceso: nunca aplica a un sitio
                    "type": "daily_limit",
                    "target": {"process": "Instagram"},
                    "limit_minutes": 1,
                    "action": "block",
                },
            ],
            "classification_rules": [
                {
                    "match": {"process": "Instagram"},
                    "productivity": "distracting",
                    "subcategory": "social",
                }
            ],
            "sites": [
                {"domain": "instagram.com", "subcategory": "social"},
                {"domain": "youtube.com", "subcategory": "video"},
                {"domain": "news.example", "productivity": "neutral", "always": True},
            ],
            "site_blocking": {"subdomains": []},
        }
    )
    clock = FakeClock(NOON)
    listing = tmp_path / "list.txt"
    provider = FakeWindowProvider(make_window("Code"))
    app = NublockApp(
        config,
        provider,
        repo,
        RecordingNotifier(),
        clock=clock,
        site_blocker=SiteBlocker([], list_path=listing),
    )
    app.startup()
    app.tick()
    return Rig(app, clock, listing, provider)


def test_always_sites_are_blocked_while_running(tmp_path: Path, repo: Repository) -> None:
    rig = make_rig(tmp_path, repo)
    assert rig.blocked() == ["news.example"]
    rig.app.core.shutdown()
    assert rig.blocked() == []  # al cerrar Nublock se libera todo


def test_focus_session_blocks_distracting_sites(tmp_path: Path, repo: Repository) -> None:
    rig = make_rig(tmp_path, repo, observe_only=True)
    rig.app.bus.publish(StartFocus())
    rig.tick(1)
    assert rig.blocked() == ["instagram.com", "news.example", "youtube.com"]
    assert rig.app.live.snapshot().blocked_sites == ["instagram.com", "youtube.com", "news.example"]


def test_exceeded_limit_blocks_matching_sites(tmp_path: Path, repo: Repository) -> None:
    rig = make_rig(tmp_path, repo)
    rig.provider.window = make_window("Instagram")  # 61 s en la app de Instagram (social)
    for _ in range(61):
        rig.tick(1)
    assert "instagram.com" in rig.blocked() and "youtube.com" not in rig.blocked()
    rig.app.bus.publish(DisableRule("social-limit"))
    rig.tick(1)
    assert rig.blocked() == ["news.example"]


def test_observe_only_and_pause(tmp_path: Path, repo: Repository) -> None:
    rig = make_rig(tmp_path, repo, observe_only=True)
    assert rig.blocked() == ["news.example"]  # observe-only no aplica reglas, pero `always` sí
    rig.app.bus.publish(PauseAll(15))
    rig.tick(1)
    assert rig.blocked() == []
