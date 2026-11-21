"""Salesman print agent: prints each new order slip on a printer at the warehouse.

Runs on any Windows PC (or Linux/macOS) next to the printer. It asks Salesman
every few seconds for new slips for its branch, prints them, and reports back.
Nothing needs to be opened in the firewall: the agent only makes outgoing
HTTPS requests.

Setup (Windows):
  1. Install Python 3.10+ from python.org (tick "Add to PATH").
  2. pip install requests pywin32
  3. In Salesman: Printing > Print agents > Add agent. Copy the key (shown once).
  4. Copy config.example.ini to config.ini next to this file and fill it in.
  5. Run:  python salesman_print_agent.py --test     (prints a test slip)
     then: python salesman_print_agent.py            (keeps running)
  To start it with Windows, see README.md (Task Scheduler or NSSM).

Two ways to print:
  mode = pdf     the slip PDF is sent to the printer (any printer). On Windows
                 SumatraPDF is used when installed (silent and reliable),
                 otherwise the PDF program registered with Windows.
  mode = escpos  plain text with ESC/POS commands straight to a thermal
                 receipt printer (Epson TM, Xprinter, ...). Fastest, no PDF
                 program needed. Arabic needs mode = pdf.
"""
import argparse
import configparser
import logging
import logging.handlers
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

VERSION = "1.0.0"
HERE = Path(getattr(sys, "frozen", False) and sys.executable or __file__).resolve().parent
log = logging.getLogger("salesman-print-agent")


# ---- configuration --------------------------------------------------------------------------

class Config:
    def __init__(self, path: Path):
        if not path.exists():
            raise SystemExit(f"Config file not found: {path}. Copy config.example.ini to config.ini and fill it in.")
        p = configparser.ConfigParser()
        p.read(path, encoding="utf-8")
        s = p["salesman"]
        self.api_url = s.get("api_url", "").rstrip("/")
        self.key = s.get("agent_key", "").strip()
        self.printer = s.get("printer", "").strip()           # empty = the default printer
        self.mode = s.get("mode", "pdf").strip().lower()
        self.copies = max(1, s.getint("copies", 1))
        self.poll = max(2, s.getint("poll_seconds", 5))
        self.width = s.getint("escpos_width", 42)              # characters per line (42 for 80 mm, 32 for 58 mm)
        self.cut = s.getboolean("escpos_cut", True)
        self.sumatra = s.get("sumatra_path", "").strip()
        if not self.api_url.startswith("https://") and "localhost" not in self.api_url and "127.0.0.1" not in self.api_url:
            raise SystemExit("api_url must start with https:// (e.g. https://api.yourcompany.salesman.app/api/v1)")
        if not self.key.startswith("spa_"):
            raise SystemExit("agent_key is missing or wrong: create a print agent in Salesman and paste its key.")
        if self.mode not in ("pdf", "escpos"):
            raise SystemExit("mode must be pdf or escpos")


# ---- talking to Salesman --------------------------------------------------------------------

class Api:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = requests.Session()
        self.http.headers.update({"X-Print-Agent-Key": cfg.key, "User-Agent": f"SalesmanPrintAgent/{VERSION}"})

    def _url(self, path: str) -> str:
        return f"{self.cfg.api_url}/printing/agent/{path.lstrip('/')}"

    def _check(self, r: requests.Response) -> requests.Response:
        if r.status_code == 401:
            raise SystemExit("Salesman refused this agent's key (revoked or mistyped). Create a new agent and update config.ini.")
        r.raise_for_status()
        return r

    def heartbeat(self) -> dict:
        r = self.http.post(self._url("heartbeat"), json={"printer": self.cfg.printer or default_printer(),
                                                          "version": VERSION}, timeout=20)
        return self._check(r).json()

    def claim(self) -> list[dict]:
        return self._check(self.http.post(self._url("claim"), timeout=30)).json()

    def slip_pdf(self, job_id: str) -> bytes:
        return self._check(self.http.get(self._url(f"jobs/{job_id}/slip.pdf"), timeout=60)).content

    def report(self, job_id: str, ok: bool, error: str | None = None) -> None:
        self._check(self.http.post(self._url(f"jobs/{job_id}/report"), json={"ok": ok, "error": error}, timeout=30))


# ---- printing -------------------------------------------------------------------------------

def default_printer() -> str | None:
    if platform.system() == "Windows":
        try:
            import win32print  # type: ignore
            return win32print.GetDefaultPrinter()
        except Exception:  # noqa: BLE001
            return None
    out = subprocess.run(["lpstat", "-d"], capture_output=True, text=True) if shutil.which("lpstat") else None
    if out and ":" in out.stdout:
        return out.stdout.split(":", 1)[1].strip() or None
    return None


def _find_sumatra(cfg: Config) -> str | None:
    candidates = [cfg.sumatra, shutil.which("SumatraPDF.exe") or "",
                  os.path.expandvars(r"%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe"),
                  r"C:\Program Files\SumatraPDF\SumatraPDF.exe", str(HERE / "SumatraPDF.exe")]
    return next((c for c in candidates if c and Path(c).exists()), None)


def print_pdf(cfg: Config, data: bytes) -> None:
    printer = cfg.printer or default_printer()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        for _ in range(cfg.copies):
            if platform.system() == "Windows":
                sumatra = _find_sumatra(cfg)
                if sumatra:
                    args = [sumatra, "-silent", "-exit-when-done"]
                    args += ["-print-to", printer] if printer else ["-print-to-default"]
                    subprocess.run(args + [path], check=True, timeout=120)
                else:
                    import win32api  # type: ignore
                    win32api.ShellExecute(0, "printto" if printer else "print", path,
                                          f'"{printer}"' if printer else None, ".", 0)
                    time.sleep(8)   # the PDF program needs the file a moment longer
            else:
                args = ["lp", "-n", "1"] + (["-d", printer] if printer else []) + [path]
                subprocess.run(args, check=True, timeout=60)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


ESC, GS = b"\x1b", b"\x1d"


def render_escpos(payload: dict, business: str, width: int, cut: bool) -> bytes:
    def line(text: str = "") -> bytes:
        return text.encode("cp437", "replace") + b"\n"

    def lr(left: str, right: str) -> bytes:
        space = max(1, width - len(left) - len(right))
        return line((left + " " * space + right)[: max(width, len(right) + 1)])

    out = ESC + b"@" + ESC + b"a\x01" + ESC + b"!\x30" + line(business[:width // 2]) + ESC + b"!\x00"
    out += line("ORDER SLIP") + ESC + b"!\x10" + line(payload.get("order_number", "")) + ESC + b"!\x00"
    out += line(payload.get("created_at", "")) + ESC + b"a\x00" + line("-" * width)
    out += line(f"Customer: {payload.get('customer_name', '-')}"[:width])
    if payload.get("customer_company"):
        out += line(f"Company: {payload['customer_company']}"[:width])
    if payload.get("whatsapp_number"):
        out += line(f"WhatsApp: {payload['whatsapp_number']}"[:width])
    out += line("-" * width)
    cur = payload.get("currency", "")
    for it in payload.get("items", []):
        out += line(f"{it['quantity']} x {it['name']}"[:width])
        out += lr(f"  {it.get('sku', '')}", f"{it.get('line_total', 0):.2f}")
    out += line("-" * width) + ESC + b"!\x10" + lr("TOTAL", f"{cur} {payload.get('total_amount', 0):.2f}") + ESC + b"!\x00"
    out += line() + ESC + b"a\x01" + line("Picked by: ________") + line() * 3
    if cut:
        out += GS + b"V\x41\x03"
    return out


def print_raw(cfg: Config, data: bytes) -> None:
    printer = cfg.printer or default_printer()
    for _ in range(cfg.copies):
        if platform.system() == "Windows":
            import win32print  # type: ignore
            handle = win32print.OpenPrinter(printer)
            try:
                win32print.StartDocPrinter(handle, 1, ("Salesman slip", None, "RAW"))
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, data)
                win32print.EndPagePrinter(handle)
                win32print.EndDocPrinter(handle)
            finally:
                win32print.ClosePrinter(handle)
        else:
            subprocess.run(["lp", "-o", "raw"] + (["-d", printer] if printer else []), input=data, check=True, timeout=60)


# ---- main loop ------------------------------------------------------------------------------

def print_job(cfg: Config, api: Api, job: dict, business: str) -> None:
    if cfg.mode == "escpos":
        print_raw(cfg, render_escpos(job["payload"], business, cfg.width, cfg.cut))
    else:
        print_pdf(cfg, api.slip_pdf(job["id"]))


def run(cfg: Config, once: bool = False) -> None:
    api = Api(cfg)
    info = api.heartbeat()
    business = info.get("business") or "Salesman"
    log.info("Connected as '%s' for %s (%s). Printer: %s. Mode: %s.", info.get("agent"), info.get("branch"), business,
             cfg.printer or default_printer() or "default", cfg.mode)
    delay, last_beat = cfg.poll, time.monotonic()
    while True:
        try:
            if time.monotonic() - last_beat > 60:
                api.heartbeat()
                last_beat = time.monotonic()
            jobs = api.claim()
            for job in jobs:
                number = job["payload"].get("order_number", job["id"])
                try:
                    print_job(cfg, api, job, business)
                except Exception as exc:  # noqa: BLE001 -- report the printer problem, keep going
                    log.error("Could not print %s: %s", number, exc)
                    api.report(job["id"], ok=False, error=f"{type(exc).__name__}: {exc}"[:480])
                else:
                    api.report(job["id"], ok=True)
                    log.info("Printed %s", number)
            delay = cfg.poll
        except SystemExit:
            raise
        except requests.RequestException as exc:
            delay = min(delay * 2, 120)   # Salesman or the internet is down: back off, then retry
            log.warning("Can't reach Salesman (%s). Trying again in %s s.", exc.__class__.__name__, delay)
        if once:
            return
        time.sleep(delay)


def test_print(cfg: Config) -> None:
    payload = {"order_number": "TEST-0001", "created_at": time.strftime("%Y-%m-%d %H:%M"), "customer_name": "Test customer",
               "currency": "SAR", "total_amount": 115.0,
               "items": [{"sku": "TEST", "name": "Test item", "quantity": 1, "unit_price": 100.0, "line_total": 100.0}]}
    Api(cfg).heartbeat()   # checks the address and key first
    if cfg.mode == "escpos":
        print_raw(cfg, render_escpos(payload, "Salesman", cfg.width, cfg.cut))
    else:
        print_pdf(cfg, _tiny_pdf("Salesman print agent test page"))
    log.info("Test slip sent to %s.", cfg.printer or default_printer() or "the default printer")


def _tiny_pdf(text: str) -> bytes:
    """A one-line PDF, so the test needs nothing but the PDF program."""
    stream = f"BT /F1 12 Tf 20 760 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Salesman print agent")
    ap.add_argument("--config", default=str(HERE / "config.ini"))
    ap.add_argument("--test", action="store_true", help="print a test slip and exit")
    ap.add_argument("--once", action="store_true", help="check for slips once and exit")
    args = ap.parse_args()
    handlers = [logging.StreamHandler(),
                logging.handlers.RotatingFileHandler(HERE / "print-agent.log", maxBytes=1_000_000, backupCount=3,
                                                     encoding="utf-8")]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    cfg = Config(Path(args.config))
    if args.test:
        test_print(cfg)
        return
    log.info("Salesman print agent %s starting", VERSION)
    run(cfg, once=args.once)


if __name__ == "__main__":
    main()
