#!/usr/bin/env python3
"""
Flask app to visualize UDP stream (16 channels, uint16, port 55151).
Run: python udp_viewer.py [--port 5000] [--udp-port 55151]
Open http://127.0.0.1:5000 and use sliders for points / decimation.
"""
import argparse
import struct
import threading
import time

import numpy as np

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("Install Flask: pip install flask")
    raise

# ---- Config ----
N_CHANNELS = 16
BUFFER_SEC = 10  # keep last N seconds
# Buffer large enough for max expected rate (e.g. 20k SPS); rate can change via STM32 SPEED
MAX_SAMPLE_RATE = 20000
MAX_FRAMES = MAX_SAMPLE_RATE * BUFFER_SEC

# Global: UDP receiver thread fills this (circular buffer)
_buf = np.zeros((N_CHANNELS, MAX_FRAMES), dtype=np.float64)
_write_idx = 0
_lock = threading.Lock()
# Snapshot for display: quick copy under lock, then decimation without lock
_display_buf = np.zeros((N_CHANNELS, MAX_FRAMES), dtype=np.float64)
_display_write_idx = 0
# Samples per second (per channel), updated every ~1s in UDP thread
_sps = 0.0
_sps_last_idx = 0
_sps_last_ts = None


def _udp_thread(host: str, port: int):
    global _write_idx, _sps, _sps_last_idx, _sps_last_ts
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.settimeout(0.1)
    frame_size = 2 * N_CHANNELS
    if _sps_last_ts is None:
        _sps_last_ts = time.time()
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            nf = len(data) // frame_size
            # Unpack outside lock to minimize time the receiver holds the lock
            frames = []
            off = 0
            for _ in range(nf):
                u = struct.unpack_from(f"{N_CHANNELS}H", data, off)
                off += frame_size
                s = (np.array(u, dtype=np.int32) - 32768) * 0.195
                frames.append(s)
            with _lock:
                for s in frames:
                    _buf[:, _write_idx % MAX_FRAMES] = s
                    _write_idx += 1
            now = time.time()
            elapsed = now - _sps_last_ts
            if elapsed >= 1.0:
                _sps = (_write_idx - _sps_last_idx) / elapsed
                _sps_last_idx = _write_idx
                _sps_last_ts = now
        except Exception:
            pass


def _get_data(points: int, decimate: int):
    """Return last `points` samples, one every `decimate`. Lock only for a quick snapshot, then build response without lock.
    Time axis uses measured _sps (STM32 rate can change via SPEED command)."""
    with _lock:
        if _write_idx == 0:
            return {"t": [], "channels": [[] for _ in range(N_CHANNELS)]}
        np.copyto(_display_buf, _buf)
        _display_write_idx = _write_idx
        sps = _sps
    # Use measured samples/sec for time axis (rate can change on STM32)
    rate = max(sps, 1.0)
    n = min(_display_write_idx, MAX_FRAMES)
    start = _display_write_idx - n
    order = np.arange(start, start + n) % MAX_FRAMES
    step = max(1, int(decimate))
    dec_idx = np.arange(0, n, step)
    take = min(points, len(dec_idx))
    dec_idx = dec_idx[-take:]
    t = (np.arange(len(dec_idx), dtype=float) / rate) * step
    channels = [_display_buf[ch, order[dec_idx]].tolist() for ch in range(N_CHANNELS)]
    return {"t": t.tolist(), "channels": channels}


# ---- Flask ----
app = Flask(__name__)


@app.route("/")
def index():
    return _HTML


@app.route("/data")
def data():
    try:
        points = max(100, min(50000, int(request.args.get("points", 2000))))
        decimate = max(1, min(100, int(request.args.get("decimate", 1))))
    except (TypeError, ValueError):
        points, decimate = 2000, 1
    out = _get_data(points, decimate)
    out["sps"] = round(_sps, 1)
    return jsonify(out)


@app.route("/stats")
def stats():
    return jsonify({"sps": round(_sps, 1)})


_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>UDP Viewer</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body { font-family: sans-serif; margin: 12px; background: #1a1a1a; color: #ddd; }
    .controls { margin-bottom: 12px; display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
    label { display: flex; align-items: center; gap: 8px; }
    input[type="range"] { width: 120px; }
    input[type="number"] { background: #333; color: #ddd; border: 1px solid #555; border-radius: 4px; padding: 4px; }
    button { background: #0e639c; color: #fff; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
    button:hover { background: #1177bb; }
    .val { min-width: 48px; color: #8af; }
    canvas { background: #111; border-radius: 4px; }
  </style>
</head>
<body>
  <h2>UDP stream — 16 canaux</h2>
  <p><strong>Samples/s par canal :</strong> <span id="spsVal">—</span></p>
  <div class="controls">
    <label>Points affichés <span class="val" id="pointsVal">2000</span>
      <input type="range" id="points" min="500" max="15000" step="500" value="2000">
    </label>
    <label>Décimation (1= tout) <span class="val" id="decVal">1</span>
      <input type="range" id="decimate" min="1" max="16" step="1" value="1">
    </label>
    <label>Rafraîchissement (ms) <span class="val" id="intervalVal">100</span>
      <input type="range" id="interval" min="50" max="500" step="50" value="100">
    </label>
    <label>Y min (µV) <input type="number" id="yMin" value="-700" step="50" style="width:70px;"> </label>
    <label>Y max (µV) <input type="number" id="yMax" value="700" step="50" style="width:70px;"> </label>
    <button type="button" id="btnAuto">Auto Y</button>
  </div>
  <div style="width:95%; max-width:1200px;">
    <canvas id="chart" height="100"></canvas>
  </div>
  <script>
    const pointsIn = document.getElementById('points');
    const decimateIn = document.getElementById('decimate');
    const intervalIn = document.getElementById('interval');
    const yMinIn = document.getElementById('yMin');
    const yMaxIn = document.getElementById('yMax');
    const btnAuto = document.getElementById('btnAuto');
    const pointsVal = document.getElementById('pointsVal');
    const decVal = document.getElementById('decVal');
    const intervalVal = document.getElementById('intervalVal');

    const colors = ['#e74c3c','#3498db','#2ecc71','#f1c40f','#9b59b6','#1abc9c','#e67e22','#34495e','#e91e63','#00bcd4','#8bc34a','#ff9800','#673ab7','#009688','#ff5722','#607d8b'];

    const ctx = document.getElementById('chart').getContext('2d');
    const chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: []
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        animation: false,
        scales: {
          x: {
            title: { display: true, text: 'temps (s)', color: '#888' },
            ticks: { color: '#888', maxTicksLimit: 12 }
          },
          y: {
            title: { display: true, text: 'µV', color: '#888' },
            ticks: { color: '#888' },
            min: -700,
            max: 700
          }
        },
        plugins: {
          legend: { labels: { color: '#ccc', boxWidth: 12 } }
        }
      }
    });

    for (let ch = 0; ch < 16; ch++) {
      chart.data.datasets.push({
        label: 'ch' + ch,
        data: [],
        borderColor: colors[ch % colors.length],
        backgroundColor: 'transparent',
        borderWidth: 1,
        pointRadius: 0
      });
    }

    let intervalMs = 100;
    let timeoutId = null;

    function fetchAndUpdate() {
      const points = parseInt(pointsIn.value, 10);
      const decimate = parseInt(decimateIn.value, 10);
      fetch('/data?points=' + points + '&decimate=' + decimate)
        .then(r => r.json())
        .then(d => {
          if (d.sps !== undefined) document.getElementById('spsVal').textContent = d.sps;
          if (!d.t || d.t.length === 0) return;
          chart.data.labels = d.t;
          d.channels.forEach((ys, i) => {
            chart.data.datasets[i].data = ys.map((y, j) => ({ x: d.t[j], y: y }));
          });
          chart.update('none');
        })
        .catch(() => {});
      timeoutId = setTimeout(fetchAndUpdate, intervalMs);
    }

    function applyYScale() {
      let lo = parseFloat(yMinIn.value);
      let hi = parseFloat(yMaxIn.value);
      if (isNaN(lo)) lo = -700;
      if (isNaN(hi)) hi = 700;
      if (lo >= hi) hi = lo + 100;
      chart.options.scales.y.min = lo;
      chart.options.scales.y.max = hi;
      chart.update('none');
    }

    pointsIn.oninput = () => { pointsVal.textContent = pointsIn.value; };
    decimateIn.oninput = () => { decVal.textContent = decimateIn.value; };
    intervalIn.oninput = () => {
      intervalVal.textContent = intervalIn.value;
      intervalMs = parseInt(intervalIn.value, 10);
    };
    yMinIn.onchange = applyYScale;
    yMaxIn.onchange = applyYScale;
    btnAuto.onclick = () => {
      const ds = chart.data.datasets;
      let lo = Infinity, hi = -Infinity;
      ds.forEach(d => {
        d.data.forEach(p => {
          if (p.y < lo) lo = p.y;
          if (p.y > hi) hi = p.y;
        });
      });
      if (lo === Infinity) { lo = -700; hi = 700; }
      else {
        const pad = (hi - lo) * 0.1 || 100;
        lo = Math.floor(lo - pad);
        hi = Math.ceil(hi + pad);
      }
      yMinIn.value = lo;
      yMaxIn.value = hi;
      applyYScale();
    };

    pointsVal.textContent = pointsIn.value;
    decVal.textContent = decimateIn.value;
    intervalVal.textContent = intervalIn.value;
    fetchAndUpdate();
  </script>
</body>
</html>
"""


def main():
    p = argparse.ArgumentParser(description="UDP stream viewer (Flask + Chart)")
    p.add_argument("--host", default="127.0.0.1", help="Flask bind address")
    p.add_argument("--port", type=int, default=5000, help="Flask port")
    p.add_argument("--udp-host", default="0.0.0.0", help="UDP bind address")
    p.add_argument("--udp-port", type=int, default=55151, help="UDP port to listen on")
    args = p.parse_args()

    t = threading.Thread(target=_udp_thread, args=(args.udp_host, args.udp_port), daemon=True)
    t.start()
    print(f"UDP listener: {args.udp_host}:{args.udp_port}")
    print(f"Open http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
