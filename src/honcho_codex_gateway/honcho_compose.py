"""Patch Honcho Docker Compose networking for gateway-stack access.

The installer keeps Honcho's stack separate from the gateway stack. Instead of
relying on host-published ports, Honcho ``api`` and ``deriver`` join the same
external Docker network as the gateway stack and call ``http://codex-gateway``
by service DNS name. This keeps the gateway localhost-only on the host while
still allowing cross-stack container-to-container traffic.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

SHARED_NETWORK = "honcho-codex-gateway"
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


def _top_level_section_range(lines: list[str], section: str) -> tuple[int, int] | None:
    start = None
    for index, line in enumerate(lines):
        if _line_indent(line) == 0 and line.strip() == f"{section}:":
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip() and _line_indent(lines[index]) == 0:
            end = index
            break
    return start, end


def _patch_service_network(lines: list[str], start: int, end: int, service_indent: int, network: str) -> tuple[list[str], bool]:
    networks_index = None
    networks_indent = None
    for offset, line in enumerate(lines[start + 1 : end], start=start + 1):
        stripped = line.strip()
        indent = _line_indent(line)
        if indent == service_indent + 2 and stripped == "networks:":
            networks_index = offset
            networks_indent = indent
            break

    network_line = " " * (service_indent + 4) + f"- {network}\n"
    if networks_index is not None and networks_indent is not None:
        list_end = end
        for index in range(networks_index + 1, end):
            stripped = lines[index].strip()
            indent = _line_indent(lines[index])
            if stripped and indent <= networks_indent:
                list_end = index
                break
        existing = "".join(lines[networks_index + 1 : list_end])
        if f"- {network}" in existing:
            return lines, False
        return lines[:list_end] + [network_line] + lines[list_end:], True

    insert_at = start + 1
    networks_block = [
        " " * (service_indent + 2) + "networks:\n",
        " " * (service_indent + 4) + "- default\n",
        network_line,
    ]
    return lines[:insert_at] + networks_block + lines[insert_at:], True


def _patch_top_level_network(lines: list[str], network: str) -> tuple[list[str], bool]:
    section = _top_level_section_range(lines, "networks")
    if section is None:
        prefix = [] if not lines or lines[-1].endswith("\n") else ["\n"]
        block = [
            *prefix,
            "\n" if lines and lines[-1].strip() else "",
            "networks:\n",
            f"  {network}:\n",
            "    external: true\n",
        ]
        return lines + block, True

    start, end = section
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        if _line_indent(lines[index]) == 2 and stripped == f"{network}:":
            block_text = "".join(lines[index:end])
            if "external: true" in block_text:
                return lines, False
            insert_at = index + 1
            return lines[:insert_at] + ["    external: true\n"] + lines[insert_at:], True

    return lines[:end] + [f"  {network}:\n", "    external: true\n"] + lines[end:], True


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


def patch_honcho_compose(
    path: Path,
    services: tuple[str, ...] = TARGET_SERVICES,
    *,
    network: str = SHARED_NETWORK,
    backup: bool = True,
) -> bool:
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
        lines, service_changed = _patch_service_network(lines, start, end, service_indent, network)
        changed = changed or service_changed
        if service_changed:
            ranges = _service_ranges(lines)

    lines, network_changed = _patch_top_level_network(lines, network)
    changed = changed or network_changed

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
        print(f"Attached Honcho api/deriver to external Docker network '{SHARED_NETWORK}' in {path}")
    else:
        print(f"Honcho api/deriver already attached to external Docker network '{SHARED_NETWORK}' in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
