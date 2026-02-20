#!/usr/bin/env python3
"""
Standalone serial terminal (Flask + SSE). Run alone or embedded in app.py via iframe.

  python serial_terminal.py                    # default port 8765
  python serial_terminal.py --port 8766
  python serial_terminal.py --com COM3 --baud 115200

Open http://127.0.0.1:8765 — port/baud, Open/Close serial, Clear, live output.
"""
import argparse
import time
import threading
from queue import Queue

try:
    from flask import Flask, Response, request, jsonify
except ImportError:
    print("Install: pip install flask pyserial")
    raise

# ---- Serial state (self-contained, no shared module) ----
serial_queue = None
serial_port = None
serial_thread = None


def _serial_reader_thread(port_name: str, baud: int, queue: Queue):
    global serial_port
    try:
        import serial
        ser = serial.Serial(port=port_name, baudrate=baud, timeout=0.02)
        serial_port = ser
        while serial_port is not None and ser.is_open:
            try:
                if ser.in_waiting:
                    line = ser.readline()
                    if not line:
                        line = ser.read(ser.in_waiting or 1)
                    if line:
                        try:
                            text = line.decode("utf-8", errors="replace")
                            queue.put(("line", text))
                        except Exception:
                            queue.put(("line", line.decode("latin-1", errors="replace")))
                else:
                    time.sleep(0.02)
            except (OSError, serial.SerialException):
                break
    except Exception as e:
        queue.put(("error", str(e)))
    finally:
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                pass
            serial_port = None


def ensure_serial(com: str, baud: int):
    global serial_queue, serial_thread, serial_port
    if serial_queue is None:
        serial_queue = Queue()
    if serial_thread is None or not serial_thread.is_alive():
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                pass
            serial_port = None
        serial_thread = threading.Thread(
            target=_serial_reader_thread,
            args=(com, baud, serial_queue),
            daemon=True,
        )
        serial_thread.start()
    return serial_queue


def _sse_stream():
    q = serial_queue
    for _ in range(50):
        if q is not None:
            break
        time.sleep(0.1)
        q = serial_queue
    if q is None:
        yield "data: [Serial not open]\n\n"
        return
    while True:
        try:
            item = q.get()
            if item[0] == "close":
                break
            if item[0] == "error":
                line = f"[Serial error] {item[1]}"
            else:
                line = item[1]
            line = line.replace("\r\n", "\n").replace("\r", "\n")
            if not line.endswith("\n"):
                line = line + "\n"
            for segment in line.split("\n"):
                yield f"data: {segment}\n"
            yield "\n"
        except Exception:
            break


# ---- Flask ----
app = Flask(__name__)

_DEFAULT_COM = "COM5"
_DEFAULT_BAUD = "1000000"


@app.route("/")
def index():
    com = request.args.get("com", _DEFAULT_COM)
    baud = request.args.get("baud", _DEFAULT_BAUD)
    html = _HTML.replace("{com}", com).replace("{baud}", str(baud))
    r = Response(html)
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    return r


@app.route("/status")
def status():
    return jsonify({"open": serial_port is not None})


@app.route("/open", methods=["POST"])
def open_serial():
    try:
        data = request.get_json(force=True, silent=True) or {}
        port = data.get("port", _DEFAULT_COM)
        baud = int(data.get("baud", 1000000))
        ensure_serial(port, baud)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/close", methods=["POST"])
def close_serial():
    global serial_queue, serial_port
    if serial_queue:
        try:
            serial_queue.put(("close", None))
        except Exception:
            pass
        serial_queue = None
    if serial_port is not None:
        try:
            serial_port.close()
        except Exception:
            pass
        serial_port = None
    return jsonify({"ok": True})


@app.route("/stream")
def stream():
    return Response(
        _sse_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Serial monitor</title>
  <style>
    body { font-family: Consolas, monospace; font-size: 13px; margin: 8px; background: #1e1e1e; color: #d4d4d4; }
    #term { white-space: pre-wrap; word-break: break-all; max-height: 65vh; overflow-y: auto; padding: 8px; }
    .bar { margin-bottom: 8px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    button { background: #0e639c; color: #fff; border: none; padding: 6px 12px; cursor: pointer; border-radius: 4px; }
    button:hover { background: #1177bb; }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    input { padding: 4px 8px; background: #333; color: #d4d4d4; border: 1px solid #555; border-radius: 4px; width: 80px; }
    label { margin-right: 4px; }
  </style>
</head>
<body>
  <div class="bar">
    <label>Port</label><input type="text" id="port" value="{com}">
    <label>Baud</label><input type="number" id="baud" value="{baud}" min="9600">
    <button id="btnOpen">Open serial</button>
    <button id="btnClose" style="display:none">Close serial</button>
    <button onclick="document.getElementById('term').textContent=''">Clear</button>
  </div>
  <pre id="term"></pre>
  <script>
    var pre = document.getElementById('term');
    var btnOpen = document.getElementById('btnOpen');
    var btnClose = document.getElementById('btnClose');
    var portInput = document.getElementById('port');
    var baudInput = document.getElementById('baud');
    var es = null;
    function append(data) { pre.textContent += data; pre.scrollTop = pre.scrollHeight; }
    function connectStream() {
      if (es) es.close();
      es = new EventSource('/stream');
      es.onmessage = function(e) { append(e.data); };
      es.onerror = function() { es.close(); setTimeout(connectStream, 2000); };
    }
    function updateButtons(open) {
      if (open) {
        btnOpen.style.display = 'none';
        btnClose.style.display = 'inline-block';
        portInput.disabled = true;
        baudInput.disabled = true;
        connectStream();
      } else {
        btnOpen.style.display = 'inline-block';
        btnClose.style.display = 'none';
        portInput.disabled = false;
        baudInput.disabled = false;
        if (es) { es.close(); es = null; }
      }
    }
    fetch('/status').then(function(r) { return r.json(); }).then(function(d) { updateButtons(d.open); }).catch(function() { updateButtons(false); });
    btnOpen.onclick = function() {
      btnOpen.disabled = true;
      fetch('/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ port: portInput.value.trim(), baud: parseInt(baudInput.value, 10) }) })
        .then(function(r) { return r.json(); }).then(function(d) {
          if (d.ok) location.reload();
          else { alert(d.error || 'Open failed'); btnOpen.disabled = false; }
        }).catch(function(e) { alert(e); btnOpen.disabled = false; });
    };
    btnClose.onclick = function() {
      btnClose.disabled = true;
      fetch('/close', { method: 'POST' }).then(function(r) { return r.json(); }).then(function() { location.reload(); }).catch(function() { btnClose.disabled = false; });
    };
  </script>
</body>
</html>
"""


def main():
    global _DEFAULT_COM, _DEFAULT_BAUD
    p = argparse.ArgumentParser(description="Serial terminal (Flask + SSE)")
    p.add_argument("--host", default="127.0.0.1", help="Bind address")
    p.add_argument("--port", type=int, default=8765, help="HTTP port")
    p.add_argument("--com", default="COM5", help="Default serial port in form")
    p.add_argument("--baud", type=int, default=1000000, help="Default baud in form")
    args = p.parse_args()
    _DEFAULT_COM = args.com
    _DEFAULT_BAUD = str(args.baud)
    print(f"Serial terminal: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
