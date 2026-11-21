# Salesman print agent

Prints every confirmed order slip on a printer at the branch, seconds after the order is confirmed.
It runs on a PC next to the printer and only makes outgoing HTTPS requests to Salesman, so no
firewall or router changes are needed.

## Install (Windows)

1. Install Python 3.10 or newer from python.org (tick **Add python.exe to PATH**).
2. Optional but recommended for PDF printing: install SumatraPDF (free).
3. In Salesman: **Printing > Print agents > Add agent**, choose the branch, and copy the key. It is shown once.
4. Copy this folder to the PC, e.g. `C:\SalesmanPrintAgent`.
5. Copy `config.example.ini` to `config.ini` and fill in `api_url`, `agent_key` and, if not the default, `printer`.
6. Open PowerShell **as Administrator** in the folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
```

It installs the two Python packages, prints a test page, and registers a task that starts the agent with
Windows and restarts it if it stops. The agent shows as **Online** in Salesman within a minute.

## Run by hand

```powershell
python -m pip install -r requirements.txt
python salesman_print_agent.py --test   # one test page
python salesman_print_agent.py          # keeps running; Ctrl+C to stop
```

## Printing modes

| mode | Printer | Notes |
| --- | --- | --- |
| `pdf` | Any | Uses the slip PDF from Salesman. Arabic names print correctly. SumatraPDF is used when installed. |
| `escpos` | Thermal receipt printers (Epson TM, Xprinter, Rongta) | Plain text straight to the printer, fastest, cuts the paper. Latin text only. |

## How it behaves

- Asks for new slips every 5 seconds; a slip is claimed by one agent only, even with two PCs on one branch.
- A printer error (paper out, offline) is reported to Salesman and the slip is tried again, up to 3 times;
  after that it shows as **Failed** in Salesman with the error, and **Print again** re-queues it.
- If the PC is switched off mid-print, the slip is handed out again after 5 minutes.
- If Salesman or the internet is down, it waits and retries (up to every 2 minutes) without losing slips.
- Revoking the agent in Salesman stops it immediately; its unprinted slips go back to the queue.
- Log file: `print-agent.log` in this folder (rotates at 1 MB).

## Uninstall

```powershell
Unregister-ScheduledTask -TaskName "Salesman Print Agent" -Confirm:$false
```
