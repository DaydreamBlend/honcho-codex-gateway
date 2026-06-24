"""Patch Honcho Docker Compose networking for Linux host-gateway access.

The installer keeps Honcho's stack separate from the gateway stack, but Honcho
containers need to reach the host-local gateway URL on Linux. Docker Desktop
usually provides host.docker.internal automatically; Linux Docker commonly
needs an explicit host-gateway mapping.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

HOST_GATEWAY_ENTRY = '"host.docker.internal:host-gateway"'
TARGET_SERVICES = ("api", "deriver")


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _service_ranges(lines: list[str]) -> dict[str, tuple[int, int, int]]:
    ranges: dict[str, tuple[int, int, int]] = {}
    services_index = None
    services_indent = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "services:":
            services_index = index
            services_indent = _line_indent(line)
            break
    if services_index is None or services_indent is None:
        return ranges

    service_indent = services_indent + 2
    current_name = None
    current_start = None
    for index in range(services_index + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        indent = _line_indent(line)
        if stripped and indent <= services_indent and not line.startswith(" "):
            break
        if indent == service_indent and stripped.endswith(":") and not stripped.startswith("-"):
            if current_name is not None and current_start is not None:
                ranges[current_name] = (current_start, index, service_indent)
            current_name = stripped[:-1].strip().strip('"\'')
            current_start = index
    if current_name is not None and current_start is not None:
        ranges[current_name] = (current_start, len(lines), service_indent)
    return ranges


def _patch_service_block(lines: list[str], start: int, end: int, service_indent: int) -> tuple[list[str], bool]:
    block = lines[start:end]
    extra_hosts_index = None
    extra_hosts_indent = None
    for offset, line in enumerate(block[1:], start=1):
        stripped = line.strip()
        indent = _line_indent(line)
        if indent == service_indent + 2 and stripped == "extra_hosts:":
            extra_hosts_index = start + offset
            extra_hosts_indent = indent
            break

    entry_line = " " * (service_indent + 4) + f"- {HOST_GATEWAY_ENTRY}\n"
    if extra_hosts_index is not None and extra_hosts_indent is not None:
        list_end = end
        for index in range(extra_hosts_index + 1, end):
            line = lines[index]
            stripped = line.strip()
            indent = _line_indent(line)
            if stripped and indent <= extra_hosts_indent:
                list_end = index
                break
        existing = "".join(lines[extra_hosts_index + 1 : list_end])
        if "host.docker.internal:host-gateway" in existing:
            return lines, False
        return lines[:list_end] + [entry_line] + lines[list_end:], True

    insert_at = start + 1
    extra_hosts_block = [
        " " * (service_indent + 2) + "extra_hosts:\n",
        entry_line,
    ]
    return lines[:insert_at] + extra_hosts_block + lines[insert_at:], True


def ensure_honcho_compose(honcho_dir: Path) -> tuple[Path, bool]:
    compose_path = honcho_dir / "docker-compose.yml"
    template_path = honcho_dir / "docker-compose.yml.example"
    if compose_path.exists():
        return compose_path, False
    if not template_path.exists():
        raise FileNotFoundError(
            f"Honcho docker-compose.yml does not exist and template is missing: {template_path}"
        )
    shutil.copy2(template_path, compose_path)
    return compose_path, True


def backup_file(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak.honcho-codex-gateway-{stamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def patch_honcho_compose(path: Path, services: tuple[str, ...] = TARGET_SERVICES, *, backup: bool = True) -> bool:
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    ranges = _service_ranges(lines)
    missing = [service for service in services if service not in ranges]
    if missing:
        raise ValueError(f"Could not find service(s) in {path}: {', '.join(missing)}")

    changed = False
    # Patch from bottom to top so earlier ranges remain valid when inserting.
    for service in sorted(services, key=lambda name: ranges[name][0], reverse=True):
        start, end, service_indent = ranges[service]
        lines, service_changed = _patch_service_block(lines, start, end, service_indent)
        changed = changed or service_changed
        if service_changed:
            ranges = _service_ranges(lines)

    if changed:
        if backup:
            backup_path = backup_file(path)
            print(f"Backed up existing Honcho compose to {backup_path}")
        path.write_text("".join(lines))
    return changed


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: python -m honcho_codex_gateway.honcho_compose /path/to/honcho-or-compose-yml", file=sys.stderr)
        return 2
    target = Path(argv[0]).expanduser().resolve()
    try:
        if target.is_dir():
            path, created = ensure_honcho_compose(target)
            if created:
                print(f"Created Honcho compose from template: {path}")
                changed = patch_honcho_compose(path, backup=False)
            else:
                path = target / "docker-compose.yml"
                changed = patch_honcho_compose(path)
        else:
            path = target
            if not path.exists():
                print(f"ERROR: Honcho compose file does not exist: {path}", file=sys.stderr)
                return 2
            changed = patch_honcho_compose(path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if changed:
        print(f"Applied Linux host-gateway override to {path}")
    else:
        print(f"Linux host-gateway override already present in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
