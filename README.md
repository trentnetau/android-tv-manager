# Android TV Manager

Web UI and API to manage an Android TV over **ADB** (network debugging): connect, list packages, disable bloatware, reinstall/enable apps, sideload APKs, and run limited shell commands.

Built for self-hosting on your server or homelab with Docker.

## Why your last tool might have failed

Common causes on Android TV:

| Issue | Fix |
|--------|-----|
| Wireless debugging never enabled | Developer options → USB debugging + network/wireless debugging |
| TV and server on different networks | Server must reach TV IP (same LAN or routed/VPN) |
| Port not 5555 | Try `5555`; some devices use wireless-debugging pairing first |
| Docker bridge isolation | Use `network_mode: host` (see `docker-compose.yml`) so ADB can reach LAN IPs |
| `unauthorized` device | Accept the RSA prompt on the TV when first connecting |
| Expecting full uninstall of system apps | Most system apps only **disable** per user (`pm disable-user`), not delete |

This project uses **host networking in Docker by default** so the container can `adb connect` to `192.168.x.x` on your LAN.

## Quick start (Docker)

```bash
cd android-tv-manager
docker compose up -d --build
```

Open **http://YOUR_SERVER_IP:8080** (with host networking, the app listens on port 8080 on the host).

1. Enter your TV’s IP (e.g. `192.168.1.50`) and click **Connect**.
2. If prompted on the TV, allow USB debugging.
3. Select the device chip, then **Load packages**.
4. Use **Disable** on bloat (prefer disable over uninstall for system packages).
5. Use **Sideload APK** to install apps.

## TV setup (one time)

1. **Settings → Device preferences → About**
2. Click **Build** (or Android version) **7 times** → Developer mode on
3. **Settings → System → Developer options**
   - **USB debugging**: ON
   - **Network debugging** / **Wireless debugging**: ON (wording varies by OEM)
4. Note the TV’s IP: **Settings → Network**

### First connection from your machine (optional test)

```bash
adb connect 192.168.1.50:5555
adb devices
```

You should see `192.168.1.50:5555    device`.

## Security

ADB is effectively **full device control**. Do not expose this app to the public internet without protection.

Set basic auth in `docker-compose.yml`:

```yaml
environment:
  AUTH_USERNAME: admin
  AUTH_PASSWORD: your-strong-password
```

Run only on a trusted network or behind a VPN (Tailscale, WireGuard, etc.).

## Local development (no Docker)

```bash
# macOS
brew install android-platform-tools

cd android-tv-manager/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=.
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080

## Debloating notes

- **Disable** is reversible; **Uninstall** for system apps often fails or bricks features.
- Disabling the wrong package can break the launcher, Play Store, or remote — disable incrementally.
- Google TV / Chromecast / Fire TV / Samsung / LG each ship different packages; search the package list for `google`, `amazon`, `vendor`, etc.
- No root is required for `pm disable-user --user 0` on many devices, but some OEM builds block it.

## API

Interactive docs: `http://localhost:8080/docs`

| Endpoint | Description |
|----------|-------------|
| `POST /api/connect` | `{ "host": "192.168.1.50", "port": 5555 }` |
| `GET /api/devices` | List connected devices |
| `GET /api/device/{serial}/packages` | List packages (`?third_party=true`, `?disabled=true`, `?q=filter`) |
| `POST /api/package/disable` | Disable package for user 0 |
| `POST /api/package/enable` | Re-enable package |
| `POST /api/package/uninstall` | Uninstall for current user |
| `POST /api/device/{serial}/install` | Multipart APK upload |

## Docker without host network

If you cannot use host networking, run the backend on the host instead of Docker, or attach the container to a Macvlan/IPvlan network on the same subnet as the TV. Standard bridge networking usually **cannot** reach `192.168.x.x` on your LAN.

## Troubleshooting

- **`ADB not found at /usr/bin/adb`**: Wrong path in Portainer/stack env. Remove `ADB_PATH` or set `ADB_PATH=/usr/local/bin/adb`, then rebuild the image.
- **Browser shows only `{"message":"Android TV Manager API"...}`**: The UI files were not found. Ensure `frontend/dist/` (with `index.html`, `app.js`, `styles.css`) is in your Git repo, redeploy/rebuild the stack, and set `STATIC_DIR=/app/frontend/dist` in the container environment.
- **Connection refused**: TV debugging off, wrong IP, or firewall on TV/router.
- **Device unauthorized**: Check TV screen for prompt; run `adb kill-server` and reconnect.
- **empty device list after connect**: Wait a few seconds and click **Refresh devices**.
- **Package not disabled**: OEM may block; try from shell tab: `pm disable-user --user 0 com.example.app`

## License

MIT — use at your own risk when modifying system packages.
