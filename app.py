#!/usr/bin/env python3
"""
Streamlit app: UDP command buttons (left) + iframes to serial terminal and UDP viewer (right).
Serial terminal and UDP viewer are separate .py; app.py can start them automatically
so everything appears in one interface, or you run them yourself via CLI.

  streamlit run app.py

  Or run separately:
  python serial_terminal.py   # http://127.0.0.1:8765
  python udp_viewer.py        # http://127.0.0.1:5000
"""
import os
import socket
import subprocess
import sys
from pathlib import Path

import streamlit as st

# Ports used by the two services (must match serial_terminal.py and udp_viewer.py)
SERIAL_TERMINAL_PORT = 8765
UDP_VIEWER_PORT = 5000
UDP_CMD_PORT = 55152

# Defaults for serial iframe URL (form pre-fill)
DEFAULT_COM = os.environ.get("SERIAL_PORT", "COM5")
DEFAULT_BAUD = os.environ.get("SERIAL_BAUD", "1000000")

def _start_children():
    """Start serial_terminal.py and udp_viewer.py as subprocesses."""
    app_dir = Path(__file__).resolve().parent
    py = sys.executable
    try:
        subprocess.Popen(
            [py, str(app_dir / "serial_terminal.py")],
            cwd=str(app_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.Popen(
            [py, str(app_dir / "udp_viewer.py")],
            cwd=str(app_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def send_udp(ip: str, port: int, cmd: str) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2.0)
            s.sendto(cmd.encode("utf-8"), (ip, port))
        return True
    except Exception:
        return False


@st.fragment
def _udp_commands_fragment():
    st.subheader("UDP commands")
    stm32_ip = st.text_input("STM32 IP", value="192.168.1.10", key="stm32_ip")
    udp_port = st.number_input("UDP command port", value=UDP_CMD_PORT, min_value=1, max_value=65535, key="udp_port")

    st.markdown("---")
    st.markdown("**Acquisition**")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("START"):
            send_udp(stm32_ip, udp_port, "START")
        if st.button("STOP"):
            send_udp(stm32_ip, udp_port, "STOP")

    st.markdown("**LEDs**")
    l1, l2, l3 = st.columns(3)
    with l1:
        if st.button("G_ON"): send_udp(stm32_ip, udp_port, "G_ON")
        if st.button("G_OFF"): send_udp(stm32_ip, udp_port, "G_OFF")
    with l2:
        if st.button("R_ON"): send_udp(stm32_ip, udp_port, "R_ON")
        if st.button("R_OFF"): send_udp(stm32_ip, udp_port, "R_OFF")
    with l3:
        if st.button("Y_ON"): send_udp(stm32_ip, udp_port, "Y_ON")
        if st.button("Y_OFF"): send_udp(stm32_ip, udp_port, "Y_OFF")

    st.markdown("**RHD / Config**")
    if st.button("SETUP"):
        send_udp(stm32_ip, udp_port, "SETUP")
    speed_val = st.number_input("SPEED (ARR)", value=999, min_value=1, max_value=65535, key="speed_val")
    if st.button("Send SPEED"):
        send_udp(stm32_ip, udp_port, f"SPEED {speed_val}")
    dest_ip = st.text_input("DEST IP", value="192.168.1.1", key="dest_ip")
    if st.button("Send DEST"):
        send_udp(stm32_ip, udp_port, f"DEST {dest_ip}")

    st.markdown("**Query**")
    q1, q2 = st.columns(2)
    with q1:
        if st.button("GET_IP"): send_udp(stm32_ip, udp_port, "GET_IP")
        if st.button("GET_SPEED"): send_udp(stm32_ip, udp_port, "GET_SPEED")
        if st.button("STATUS"): send_udp(stm32_ip, udp_port, "STATUS")
    with q2:
        if st.button("VERSION"): send_udp(stm32_ip, udp_port, "VERSION")
        if st.button("HELP"): send_udp(stm32_ip, udp_port, "HELP")

    st.markdown("**Monitor**")
    if st.button("MONITOR_ON"): send_udp(stm32_ip, udp_port, "MONITOR_ON")
    if st.button("MONITOR_OFF"): send_udp(stm32_ip, udp_port, "MONITOR_OFF")


@st.fragment
def _panels_fragment():
    """Right column: iframes to serial terminal and UDP viewer."""
    st.subheader("Serial terminal")
    st.caption("Port/baud, Open/Close, Clear are in the terminal. Run alone: `python serial_terminal.py`")
    src_serial = f"http://127.0.0.1:{SERIAL_TERMINAL_PORT}/?com={DEFAULT_COM}&baud={DEFAULT_BAUD}"
    st.markdown(
        f'<iframe src="{src_serial}" width="100%" height="380" style="border:1px solid #444; border-radius:4px;"></iframe>',
        unsafe_allow_html=True,
    )

    st.subheader("UDP viewer")
    st.caption("Points, decimation, Y scale. Run alone: `python udp_viewer.py`")
    src_udp = f"http://127.0.0.1:{UDP_VIEWER_PORT}/"
    st.markdown(
        f'<iframe src="{src_udp}" width="100%" height="550" style="border:1px solid #444; border-radius:4px;"></iframe>',
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(layout="wide", page_title="STM32 control")
    if "children_started" not in st.session_state:
        _start_children()
        st.session_state.children_started = True
    st.title("HOMUNCULUS NEUROTECHNOLOGIES SYSTEM")

    col_left, col_right = st.columns([1, 2])
    with col_left:
        _udp_commands_fragment()
    with col_right:
        _panels_fragment()


if __name__ == "__main__":
    main()
