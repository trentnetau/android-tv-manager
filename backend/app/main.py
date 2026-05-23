import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from app import adb
from app.config import settings

app = FastAPI(title="Android TV Manager", version="1.0.0")
security = HTTPBasic(auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    if not settings.auth_username:
        return
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Basic"})
    user_ok = secrets.compare_digest(credentials.username, settings.auth_username)
    pass_ok = secrets.compare_digest(credentials.password, settings.auth_password)
    if not (user_ok and pass_ok):
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Basic"})


class ConnectRequest(BaseModel):
    host: str = Field(..., min_length=1, description="TV IP or hostname")
    port: int = Field(5555, ge=1, le=65535)


class PackageActionRequest(BaseModel):
    serial: str
    package: str = Field(..., min_length=3)


class ShellRequest(BaseModel):
    serial: str
    command: str = Field(..., min_length=1, max_length=2000)


@app.get("/api/health")
def health(_: None = Depends(require_auth)):
    try:
        adb.run_adb("version", timeout=10)
        return {"status": "ok", "adb": "available"}
    except adb.AdbError as exc:
        return {"status": "degraded", "adb": str(exc)}


@app.get("/api/devices")
def get_devices(_: None = Depends(require_auth)):
    try:
        devices = adb.list_devices()
        return {
            "devices": [
                {
                    "serial": d.serial,
                    "state": d.state,
                    "product": d.product,
                    "model": d.model,
                }
                for d in devices
            ]
        }
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/connect")
def connect_device(body: ConnectRequest, _: None = Depends(require_auth)):
    try:
        message = adb.connect(body.host, body.port)
        devices = adb.list_devices()
        return {"message": message, "devices": [d.serial for d in devices if d.state == "device"]}
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/disconnect")
def disconnect_device(target: str | None = None, _: None = Depends(require_auth)):
    try:
        message = adb.disconnect(target)
        return {"message": message}
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/device/{serial}/info")
def device_info(serial: str, _: None = Depends(require_auth)):
    try:
        return adb.device_info(serial)
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/device/{serial}/packages")
def packages(
    serial: str,
    third_party: bool = False,
    disabled: bool = False,
    q: str = "",
    labels: bool = False,
    _: None = Depends(require_auth),
):
    try:
        pkgs = adb.list_packages(
            serial,
            third_party_only=third_party,
            disabled_only=disabled,
            filter_text=q,
        )
        if labels and len(pkgs) <= 200:
            for entry in pkgs:
                entry["label"] = adb.package_label(serial, entry["package"])
        return {"packages": pkgs, "count": len(pkgs)}
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/package/disable")
def disable_pkg(body: PackageActionRequest, _: None = Depends(require_auth)):
    try:
        result = adb.disable_package(body.serial, body.package)
        return {"result": result}
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/package/enable")
def enable_pkg(body: PackageActionRequest, _: None = Depends(require_auth)):
    try:
        result = adb.enable_package(body.serial, body.package)
        return {"result": result}
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/package/uninstall")
def uninstall_pkg(body: PackageActionRequest, _: None = Depends(require_auth)):
    try:
        result = adb.uninstall_package(body.serial, body.package)
        return {"result": result}
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/device/{serial}/install")
async def install_apk(
    serial: str,
    file: UploadFile = File(...),
    _: None = Depends(require_auth),
):
    if not file.filename or not file.filename.lower().endswith(".apk"):
        raise HTTPException(400, "Upload must be an .apk file")
    dest = UPLOAD_DIR / f"{secrets.token_hex(8)}.apk"
    try:
        content = await file.read()
        if len(content) > 500 * 1024 * 1024:
            raise HTTPException(400, "APK too large (max 500MB)")
        dest.write_bytes(content)
        result = adb.install_apk(serial, dest)
        return {"result": result}
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        dest.unlink(missing_ok=True)


@app.post("/api/shell")
def run_shell(body: ShellRequest, _: None = Depends(require_auth)):
    blocked = ("reboot", "recovery", "format", "wipe", "su ", "setprop", "pm clear com.android")
    lower = body.command.lower()
    if any(token in lower for token in blocked):
        raise HTTPException(400, "Command blocked for safety")
    try:
        output = adb.shell(body.serial, body.command)
        return {"output": output}
    except adb.AdbError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Android TV Manager API", "docs": "/docs"}


@app.get("/{full_path:path}")
def spa(full_path: str):
    asset = STATIC_DIR / full_path
    if asset.is_file():
        return FileResponse(asset)
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(404, "Not found")
