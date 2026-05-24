import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


class AdbError(Exception):
    def __init__(self, message: str, *, stdout: str = "", stderr: str = "", returncode: int = 1):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@dataclass
class Device:
    serial: str
    state: str
    product: str | None = None
    model: str | None = None
    device: str | None = None


def adb_executable() -> str:
    """Resolved path to the adb binary (for diagnostics)."""
    return _adb_bin()


def _adb_bin() -> str:
    candidates: list[str] = []
    if settings.adb_path and settings.adb_path != "adb":
        candidates.append(settings.adb_path)
    candidates.extend(
        [
            "adb",
            "/usr/local/bin/adb",
            "/usr/bin/adb",
            "/usr/lib/android-sdk/platform-tools/adb",
            "/opt/platform-tools/adb",
        ]
    )
    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path == "adb":
            found = shutil.which("adb")
            if found:
                return found
            continue
        if Path(path).is_file():
            return path
    raise AdbError(
        "ADB not found. Install android-sdk-platform-tools or set ADB_PATH "
        "(e.g. /usr/lib/android-sdk/platform-tools/adb)."
    )


def run_adb(
    *args: str,
    serial: str | None = None,
    timeout: int | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [_adb_bin()]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout or settings.command_timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdbError(f"ADB timed out after {timeout or settings.command_timeout_sec}s") from exc
    except FileNotFoundError as exc:
        raise AdbError("ADB executable missing") from exc

    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "Unknown ADB error"
        raise AdbError(detail, stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)
    return result


def parse_devices(output: str) -> list[Device]:
    devices: list[Device] = []
    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        props: dict[str, str] = {}
        if len(parts) > 2:
            for chunk in parts[2:]:
                if ":" in chunk:
                    key, _, value = chunk.partition(":")
                    props[key] = value
        devices.append(
            Device(
                serial=serial,
                state=state,
                product=props.get("product"),
                model=props.get("model"),
                device=props.get("device"),
            )
        )
    return devices


def list_devices() -> list[Device]:
    result = run_adb("devices", "-l")
    return parse_devices(result.stdout)


def connect(host: str, port: int = 5555) -> str:
    target = f"{host}:{port}"
    result = run_adb(
        "connect",
        target,
        timeout=settings.adb_connect_timeout_sec,
        check=False,
    )
    message = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0 and "connected" not in message.lower():
        raise AdbError(message or "Failed to connect", stdout=result.stdout, stderr=result.stderr)
    return message


def disconnect(target: str | None = None) -> str:
    args = ["disconnect"]
    if target:
        args.append(target)
    result = run_adb(*args, check=False)
    return (result.stdout or result.stderr or "disconnected").strip()


def get_prop(serial: str, name: str) -> str:
    result = run_adb("-s", serial, "shell", "getprop", name, check=False)
    return (result.stdout or "").strip()


def device_info(serial: str) -> dict[str, str]:
    keys = [
        "ro.product.manufacturer",
        "ro.product.model",
        "ro.product.name",
        "ro.build.version.release",
        "ro.build.version.sdk",
        "ro.build.display.id",
    ]
    info = {"serial": serial}
    for key in keys:
        short = key.rsplit(".", 1)[-1]
        info[short] = get_prop(serial, key)
    return info


def _parse_pkg_line(line: str) -> str | None:
    line = line.strip()
    if not line.startswith("package:"):
        return None
    return line.removeprefix("package:").strip()


def _pm_package_set(serial: str, *flags: str) -> set[str]:
    args = ["shell", "pm", "list", "packages", *flags]
    result = run_adb(*args, serial=serial)
    packages: set[str] = set()
    for line in result.stdout.splitlines():
        pkg = _parse_pkg_line(line)
        if pkg:
            packages.add(pkg)
    return packages


def humanize_package_name(package: str) -> str:
    """Best-effort friendly name when the device does not expose a label."""
    tail = package.rsplit(".", 1)[-1].replace("_", " ").strip()
    return tail.title() if tail else package


_label_cache: dict[str, dict[str, str]] = {}


def invalidate_label_cache(serial: str) -> None:
    _label_cache.pop(serial, None)


def _parse_labels_from_dumpsys(output: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    current_pkg: str | None = None
    for line in output.splitlines():
        pkg_match = re.match(r"^\s*Package \[([^\]]+)\]", line)
        if pkg_match:
            current_pkg = pkg_match.group(1).strip()
            continue
        if not current_pkg:
            continue
        for pattern in (
            r"applicationLabel=([^\n\r]+)",
            r"nonLocalizedLabel=([^\n\r]+)",
        ):
            match = re.search(pattern, line)
            if match:
                label = match.group(1).strip()
                if label and label not in ("null", "None"):
                    labels[current_pkg] = label
                break
    return labels


def fetch_package_labels(serial: str, *, force: bool = False) -> dict[str, str]:
    if not force and serial in _label_cache:
        return _label_cache[serial]
    result = run_adb(
        "shell",
        "dumpsys",
        "package",
        "packages",
        serial=serial,
        timeout=settings.package_dumpsys_timeout_sec,
        check=False,
    )
    labels = _parse_labels_from_dumpsys(result.stdout or "")
    _label_cache[serial] = labels
    return labels


def list_packages(
    serial: str,
    *,
    third_party_only: bool = False,
    disabled_only: bool = False,
    filter_text: str = "",
) -> list[dict[str, str]]:
    args = ["shell", "pm", "list", "packages"]
    if third_party_only:
        args.append("-3")
    if disabled_only:
        args.append("-d")
    result = run_adb(*args, serial=serial)

    packages: list[dict[str, str]] = []
    needle = filter_text.lower().strip()
    for line in result.stdout.splitlines():
        pkg = _parse_pkg_line(line)
        if not pkg:
            continue
        if needle and needle not in pkg.lower():
            continue
        packages.append({"package": pkg})
    packages.sort(key=lambda p: p["package"])
    return packages


def list_packages_enriched(
    serial: str,
    *,
    status: str = "all",
    app_type: str = "all",
    filter_text: str = "",
    include_labels: bool = True,
    refresh_labels: bool = False,
) -> list[dict[str, str | bool]]:
    """List packages with human labels, system/user type, and enabled/disabled/uninstalled state."""
    status = status.lower().strip()
    app_type = app_type.lower().strip()
    needle = filter_text.lower().strip()

    type_flags: tuple[str, ...] = ()
    if app_type == "system":
        type_flags = ("-s",)
    elif app_type == "user":
        type_flags = ("-3",)

    installed = _pm_package_set(serial, *type_flags)
    including_uninstalled = _pm_package_set(serial, "-u", *type_flags)
    uninstalled_only = including_uninstalled - installed

    disabled_packages = _pm_package_set(serial, "-d", *type_flags)
    system_packages = _pm_package_set(serial, "-s")

    if status == "enabled":
        selected = _pm_package_set(serial, "-e", *type_flags)
    elif status == "disabled":
        selected = disabled_packages
    elif status == "uninstalled":
        selected = uninstalled_only
    else:
        # "all" = installed packages only (excludes uninstalled-for-user)
        selected = installed

    labels: dict[str, str] = {}
    if include_labels:
        labels = fetch_package_labels(serial, force=refresh_labels)

    results: list[dict[str, str | bool]] = []
    for pkg in sorted(selected):
        if pkg in uninstalled_only:
            pkg_status = "uninstalled"
        elif pkg in disabled_packages:
            pkg_status = "disabled"
        else:
            pkg_status = "enabled"

        label = labels.get(pkg) or humanize_package_name(pkg)
        is_system = pkg in system_packages

        if needle and needle not in pkg.lower() and needle not in label.lower():
            continue

        results.append(
            {
                "package": pkg,
                "label": label,
                "status": pkg_status,
                "system": is_system,
                "type": "system" if is_system else "user",
            }
        )

    results.sort(key=lambda p: (str(p["label"]).lower(), str(p["package"])))
    return results


def package_label(serial: str, package: str) -> str:
    result = run_adb(
        "shell",
        "dumpsys",
        "package",
        package,
        serial=serial,
        check=False,
    )
    match = re.search(r"applicationLabel=([^\n\r]+)", result.stdout)
    if match:
        return match.group(1).strip()
    return package


def disable_package(serial: str, package: str, user_id: int = 0) -> str:
    result = run_adb(
        "shell",
        "pm",
        "disable-user",
        "--user",
        str(user_id),
        package,
        serial=serial,
    )
    invalidate_label_cache(serial)
    return (result.stdout or result.stderr or "disabled").strip()


def enable_package(serial: str, package: str, user_id: int = 0) -> str:
    result = run_adb(
        "shell",
        "pm",
        "enable",
        "--user",
        str(user_id),
        package,
        serial=serial,
    )
    invalidate_label_cache(serial)
    return (result.stdout or result.stderr or "enabled").strip()


def uninstall_package(serial: str, package: str, user_id: int = 0) -> str:
    result = run_adb(
        "shell",
        "pm",
        "uninstall",
        "--user",
        str(user_id),
        package,
        serial=serial,
    )
    invalidate_label_cache(serial)
    return (result.stdout or result.stderr or "ok").strip()


def restore_package(serial: str, package: str, user_id: int = 0) -> str:
    result = run_adb(
        "shell",
        "pm",
        "install-existing",
        "--user",
        str(user_id),
        package,
        serial=serial,
    )
    invalidate_label_cache(serial)
    return (result.stdout or result.stderr or "restored").strip()


def install_apk(serial: str, apk_path: Path) -> str:
    result = run_adb("install", "-r", str(apk_path), serial=serial, timeout=300)
    return (result.stdout or result.stderr or "Success").strip()


def shell(serial: str, command: str) -> str:
    result = run_adb("shell", command, serial=serial, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 and not output.strip():
        raise AdbError(f"Shell failed (code {result.returncode})")
    return output
