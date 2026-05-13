# Raspberry Pi Discovery

Find a specific Raspberry Pi running a Buildroot image on your local network.

The default target hostname is:

```text
lohi-bassline-junkie
```

The script tries that hostname first, then `lohi-bassline-junkie.local`, then scans
all active local IPv4 `/24` networks. It uses SSH on port `22` as the main active
probe and does not require root or administrator privileges.

## Install

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell, activate it with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Then install the dependency:

```bash
python -m pip install -r requirements.txt
```

## Usage

```bash
python discover_pi.py
```

Use another hostname:

```bash
python discover_pi.py --hostname lohi-bassline-junkie
```

Scan a specific network:

```bash
python discover_pi.py --network 192.168.8.0/24
```

Show every responsive host found during the scan:

```bash
python discover_pi.py --show-all
```

Tune scan behavior:

```bash
python discover_pi.py --timeout 0.4 --workers 128
```

## Upload CLI

Verify SSH access to a discovered Raspberry Pi:

```bash
python raspi_deploy.py --host 10.42.0.163 --verify
```

Upload a file to `/home/pi` and preserve its permission bits:

```bash
python raspi_deploy.py --host 10.42.0.163 --upload ./my-script.sh
```

## GUI Usage

Run the graphical application:

```bash
python discover_pi_gui.py
```

Click `Discover` to scan the network. The progress bar advances as hosts are
checked, and the results table lists Raspberry Pi candidates with IP, hostname,
MAC address, SSH reachability, confidence, and evidence.

Select a Raspberry Pi in the table to enable SSH actions:

- `Verify Connection` checks SSH login as user `pi` with password `raspberry`.
- `Select File` chooses a local file.
- `Upload` copies the selected file to `/home/pi` on the selected Raspberry Pi.
  The upload also applies the local file permission bits to the remote file.

## Build A Binary

Install the runtime and build dependencies in the virtual environment:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
```

Create the CLI single-file executable:

```bash
pyinstaller raspi-discover.spec
```

Create the GUI single-file executable:

```bash
pyinstaller raspi-discover-gui.spec
```

Create the upload CLI single-file executable:

```bash
pyinstaller raspi-deploy.spec
```

The binaries are written to:

```text
dist/raspi-discover
dist/raspi-discover-gui
dist/raspi-deploy
```

Run them with:

```bash
./dist/raspi-discover
./dist/raspi-discover-gui
./dist/raspi-deploy --host 10.42.0.163 --verify
```

PyInstaller builds are platform-specific. Build on Windows to create a Windows
binary, on macOS to create a macOS binary, and on Linux to create a Linux binary.

## How It Identifies The Device

The strongest signal is an exact match for `lohi-bassline-junkie` or
`lohi-bassline-junkie.local`.

Other signals include:

- SSH port `22` is reachable.
- Reverse DNS returns the target hostname.
- The local neighbor or ARP cache shows a Raspberry Pi MAC vendor prefix.
- A generic Raspberry Pi hostname appears as fallback evidence.

Because this is a Buildroot image, the script does not depend on Raspberry Pi OS
banners or package-specific services.

## Notes

- Cross-platform interface detection uses `psutil`.
- MAC/vendor detection is best-effort and depends on the operating system
  neighbor cache.
- If auto-detection cannot find your local network, pass `--network` explicitly.
- The scanner uses normal TCP connections only, so it should not need elevated
  privileges.
- On Linux desktops using Qt's X11 `xcb` backend, the GUI requires the system
  library `libxcb-cursor.so.0`. Install the package that provides it if the GUI
  reports an `xcb` platform plugin error:
  - Debian/Ubuntu: `sudo apt install libxcb-cursor0`
  - Fedora: `sudo dnf install xcb-util-cursor`
  - Arch: `sudo pacman -S xcb-util-cursor`
