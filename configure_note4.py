# /// script
# requires-python = ">=3.11"
# dependencies = ["pyserial==3.5"]
# ///
"""Configure Note4 Open Platform over USB for the calendar remote page.

  uv run configure_note4.py remote      # page source, token, schedule, remote cover
  uv run configure_note4.py wifi        # asks for SSID and password (hidden)
  uv run configure_note4.py status
"""
import getpass
import glob
import re
import secrets
import sys
import time
from pathlib import Path

import serial

HERE = Path(__file__).resolve().parent
HOST = "oscarsa.github.io"
# Every 2 h, 15 s network budget, min 20 % battery, quiet 23:00-07:00.
BACKGROUND = "connectivity background 1 7200 15000 20 1380 420"


def open_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        sys.exit("Note4 no encontrado por USB: conéctalo y pulsa DOWN para despertarlo.")
    s = serial.Serial(port=None, baudrate=115200, timeout=0.2, write_timeout=2)
    s.dtr = False
    s.rts = False
    s.port = ports[0]
    s.open()
    time.sleep(3)          # opening the port restarts Note4; wait for the CLI
    s.read(65536)
    s.write(b"\x03")
    time.sleep(0.5)
    s.read(65536)
    return s


def run(s, command, secret=False, wait=2.0):
    s.write(command.encode("utf-8") + b"\r\n")
    end, out = time.time() + wait, b""
    while time.time() < end:
        out += s.read(4096)
    text = out.decode("utf-8", "replace")
    m = re.search(r"confirm (\S+)", text)
    if m:
        s.write(f"confirm {m.group(1)}\r\n".encode())
        time.sleep(wait)
        text += s.read(65536).decode("utf-8", "replace")
    shown = "<oculto>" if secret else command
    lines = [l for l in text.splitlines() if l.strip() and command not in l and "confirm" not in l]
    print(f"> {shown}\n  " + "\n  ".join(lines[-4:]))
    return text


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    s = open_port()
    try:
        if mode == "wifi":
            ssid = input("Nombre de tu Wi-Fi (SSID, 2,4 GHz): ").strip()
            password = getpass.getpass("Contraseña (no se mostrará): ")
            if '"' in ssid or '"' in password:
                sys.exit("El nombre o la contraseña contienen comillas; dímelo y lo adaptamos.")
            run(s, "connectivity policy automatic")
            run(s, f'connectivity wifi-set "{ssid}" "{password}"', secret=True, wait=3)
        elif mode == "remote":
            page_dir = (HERE / ".page_dir").read_text().strip()
            token_file = HERE / ".device_token"
            if not token_file.exists():
                token_file.write_text(secrets.token_hex(24))
                token_file.chmod(0o600)
            run(s, "connectivity policy automatic")
            run(s, f"connectivity source {HOST} /note4-calendar/{page_dir}/note4.bin")
            run(s, f"connectivity token {token_file.read_text().strip()}", secret=True)
            run(s, BACKGROUND)
            run(s, "connectivity remote-cover 1")
        run(s, "connectivity status", wait=2)
    finally:
        s.close()


if __name__ == "__main__":
    main()
