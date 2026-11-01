#!/usr/bin/env python3
"""Print everything needed to run the multi-laptop demo, for copy and paste.

Run on the SERVER laptop:

    python scripts/print_demo_setup.py

It finds this laptop's address on the network, checks backend/.env and
frontend/.env, and prints the one command to paste on each hospital laptop,
including that hospital's token. The default layout is three laptops: this
server, one laptop running Hospitals A and B, one running Hospitals C and D.

    python scripts/print_demo_setup.py --ip 100.101.102.103      # e.g. a Tailscale address
    python scripts/print_demo_setup.py --layout "a,b,c,d"         # all four on one hospital laptop
    python scripts/print_demo_setup.py --layout "a;b;c;d"         # one laptop per hospital

It changes nothing; edit the .env files yourself and restart the server.
"""

import argparse
import ipaddress
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values  # noqa: E402

from app.utils.hashing import hmac_token  # noqa: E402


def lan_addresses() -> list:
    """IPv4 addresses of this machine other than loopback; the one with the default route first."""
    found = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))  # no packet is sent; this only picks the outgoing interface
        found.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    unique = []
    for address in found:
        if address not in unique and not address.startswith("127."):
            unique.append(address)
    return unique


def is_tailscale(address: str) -> bool:
    return ipaddress.ip_address(address) in ipaddress.ip_network("100.64.0.0/10")


def check(label: str, current, wanted) -> str:
    ok = (current or "") == wanted
    shown = current if current else "(not set)"
    return f"  {'OK    ' if ok else 'CHANGE'}  {label}={wanted}" + ("" if ok else f"      (now: {shown})")


def main() -> None:
    # '·' and '…' must never crash a console with a narrow code page.
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ip", help="Address the other laptops use to reach this one (default: detected)")
    parser.add_argument("--port", type=int, default=None, help="API port (default: API_PORT in backend/.env, or 8000)")
    parser.add_argument("--web-port", type=int, default=5173, help="Dashboard port (default 5173)")
    parser.add_argument(
        "--layout",
        default="a,b;c,d",
        help='Hospitals per laptop: ";" separates laptops, "," hospitals on one laptop (default "a,b;c,d")',
    )
    args = parser.parse_args()

    backend_env = dotenv_values(ROOT / "backend" / ".env") if (ROOT / "backend" / ".env").exists() else {}
    frontend_env = dotenv_values(ROOT / "frontend" / ".env") if (ROOT / "frontend" / ".env").exists() else {}
    addresses = lan_addresses()
    ip = args.ip or (addresses[0] if addresses else None)
    if not ip:
        sys.exit("Could not find this laptop's network address. Connect to the Wi-Fi or hotspot, or pass --ip.")
    port = args.port or int(backend_env.get("API_PORT") or 8000)
    api, web = f"http://{ip}:{port}", f"http://{ip}:{args.web_port}"
    backend_name = backend_env.get("ML_BACKEND") or "auto"
    secret = (backend_env.get("NODE_TOKEN_SECRET") or "").strip()
    origins = f"http://localhost:{args.web_port},http://127.0.0.1:{args.web_port},{web}"

    print(f"FL-Healthcare demo · server laptop {socket.gethostname()}")
    print(f"Address for the other laptops: {ip}" + ("  (Tailscale)" if is_tailscale(ip) else ""))
    others = [a for a in addresses if a != ip]
    if others:
        print("Other addresses of this laptop: " + ", ".join(a + (" (Tailscale)" if is_tailscale(a) else "") for a in others))
    print()

    print("1. backend/.env on this laptop (then restart: python run.py)")
    print(check("HOSPITAL_NODES", backend_env.get("HOSPITAL_NODES"), "external"))
    print(check("API_HOST", backend_env.get("API_HOST"), "0.0.0.0"))
    print(check("CORS_ORIGINS", backend_env.get("CORS_ORIGINS"), origins))
    print(f"  {'OK    ' if secret else 'CHANGE'}  NODE_TOKEN_SECRET=" + ("(set; keep it fixed)" if secret else "<a long random value>"))
    print(f"  {'OK    ' if (backend_env.get('DEMO_JWT_SECRET') or '').strip() else 'CHANGE'}  DEMO_JWT_SECRET="
          + ("(set)" if (backend_env.get("DEMO_JWT_SECRET") or "").strip() else "<another long random value>"))
    print(f"  INFO    ML_BACKEND={backend_name}   (every hospital laptop uses the same; passed in the commands below)")
    print()
    print("2. frontend/.env on this laptop (then restart: cd frontend && npm run dev -- --host)")
    print(check("VITE_API_BASE_URL", frontend_env.get("VITE_API_BASE_URL"), api))
    print()
    print("3. Windows firewall on this laptop: allow the prompts for Python and Node, or in an Administrator terminal:")
    print(f'  netsh advfirewall firewall add rule name="FL-Healthcare API" dir=in action=allow protocol=TCP localport={port} profile=any')
    print(f'  netsh advfirewall firewall add rule name="FL-Healthcare dashboard" dir=in action=allow protocol=TCP localport={args.web_port} profile=any')
    print()

    if not secret:
        print("NODE_TOKEN_SECRET is not set, so tokens would change at every server start. Add it, for example:")
        import secrets

        print(f"  NODE_TOKEN_SECRET={secrets.token_hex(32)}")
        print("then run this script again to get the hospital commands.")
        return

    print("4. On each hospital laptop: open a terminal in the project folder (with its .venv) and paste its block.")
    print("   Each hospital opens in its own window, titled with its name. Later runs need only the hospital id.")
    for number, group in enumerate(args.layout.split(";"), start=2):
        letters = [x.strip().lower() for x in group.split(",") if x.strip()]
        print(f"\n   Laptop {number} · Hospital {' + '.join(x.upper() for x in letters)}")
        for letter in letters:
            hospital_id = f"hospital_{letter}"
            token = hmac_token(secret, f"hospital-node:{hospital_id}")
            print(
                f'   start "Hospital {letter.upper()}" cmd /k .venv\\Scripts\\python scripts\\setup_hospital.py '
                f"{hospital_id} --server {api} --token {token} --ml-backend {backend_name}"
            )
    print()
    print(f"5. Dashboard from any laptop: {web}")
    print("   Admin: admin@fl-healthcare.demo · hospital operators: hospital_a@fl-healthcare.demo ... hospital_d@...")
    print(f"   Check from a hospital laptop first: {api}/api/health should show \"status\":\"ok\".")


if __name__ == "__main__":
    main()
