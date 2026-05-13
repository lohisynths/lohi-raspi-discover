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

## Build A Binary

Install the runtime and build dependencies in the virtual environment:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
```

Create a single-file executable:

```bash
pyinstaller --onefile --name raspi-discover discover_pi.py
```

The binary is written to:

```text
dist/raspi-discover
```

Run it with:

```bash
./dist/raspi-discover
```

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
