"""PhoneCam - use your iPhone as a webcam on Windows over your private network.

The PC runs a small HTTPS server. Open the printed URL (or scan the QR code) in
Safari on the iPhone, tap Start, and the camera feed appears in a preview window
and (optionally) as a virtual webcam usable in Teams, Zoom, OBS, etc.
"""
import argparse
import asyncio
import datetime
import ipaddress
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from aiohttp import web, WSMsgType

APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
DATA_DIR = Path.home() / ".phonecam"


# ---------- networking helpers ----------
def local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packets sent
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def is_private(addr):
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def ensure_cert(ips):
    """Self-signed cert (Safari requires HTTPS for camera access)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    DATA_DIR.mkdir(exist_ok=True)
    cert_p, key_p, ips_p = DATA_DIR / "cert.pem", DATA_DIR / "key.pem", DATA_DIR / "ips.txt"
    wanted = ",".join(ips)
    if cert_p.exists() and key_p.exists() and ips_p.exists() and ips_p.read_text() == wanted:
        return cert_p, key_p
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PhoneCam")])
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_p.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    ips_p.write_text(wanted)
    return cert_p, key_p


# ---------- server ----------
class State:
    def __init__(self, token):
        self.token = token
        self.frame = None          # latest decoded BGR frame
        self.lock = threading.Lock()
        self.connected = False
        self.last_rx = 0.0


def make_app(state):
    async def index(request):
        if not is_private(request.remote or ""):
            return web.Response(status=403, text="Private networks only")
        return web.FileResponse(APP_DIR / "static" / "index.html")

    async def ws_handler(request):
        if not is_private(request.remote or "") or request.query.get("t") != state.token:
            return web.Response(status=403, text="Forbidden")
        if state.connected:
            return web.Response(status=409, text="Another phone is already connected")
        ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)
        state.connected = True
        print(f"[+] Phone connected from {request.remote}")
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    img = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        with state.lock:
                            state.frame = img
                        state.last_rx = time.time()
        finally:
            state.connected = False
            print("[-] Phone disconnected")
        return ws

    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/ws", ws_handler)])
    return app


def run_server(state, port, ssl_ctx):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runner = web.AppRunner(make_app(state))
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(web.TCPSite(runner, "0.0.0.0", port, ssl_context=ssl_ctx).start())
    loop.run_forever()


# ---------- display / virtual camera ----------
def letterbox(img, w, h):
    ih, iw = img.shape[:2]
    s = min(w / iw, h / ih)
    nw, nh = max(1, int(iw * s)), max(1, int(ih * s))
    out = np.zeros((h, w, 3), np.uint8)
    x, y = (w - nw) // 2, (h - nh) // 2
    out[y:y + nh, x:x + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    return out


def waiting_frame(w, h, lines):
    img = np.zeros((h, w, 3), np.uint8)
    for i, t in enumerate(lines):
        cv2.putText(img, t, (30, 60 + i * 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img


def main():
    ap = argparse.ArgumentParser(description="Use your iPhone as a PC webcam over your LAN")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--vcam", action="store_true", help="Output to a virtual webcam (needs OBS Virtual Camera installed)")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0, help="Rotate incoming video")
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    ips = local_ips()
    if not ips:
        sys.exit("No network connection found. Connect this PC to your Wi-Fi/LAN first.")
    cert_p, key_p = ensure_cert(ips)
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_p, key_p)

    token = secrets.token_urlsafe(6)
    state = State(token)
    threading.Thread(target=run_server, args=(state, args.port, ctx), daemon=True).start()

    url = f"https://{ips[0]}:{args.port}/?t={token}"
    print("\nOpen this on your iPhone (same Wi-Fi), accept the certificate warning, tap Start:\n")
    print("   ", url, "\n")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except Exception:
        pass
    print("Keys in preview window: q=quit  m=mirror  r=rotate 90\n")

    vcam = None
    if args.vcam:
        import pyvirtualcam
        vcam = pyvirtualcam.Camera(args.width, args.height, args.fps, fmt=pyvirtualcam.PixelFormat.BGR)
        print(f"Virtual camera active: {vcam.device}")

    rot_codes = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    rotate, mirror = args.rotate, args.mirror
    idle = waiting_frame(args.width, args.height, ["PhoneCam waiting for iPhone...", url[:60]])
    period = 1.0 / args.fps
    try:
        while True:
            t0 = time.time()
            with state.lock:
                f = None if state.frame is None else state.frame.copy()
            if f is None or time.time() - state.last_rx > 3:
                out = idle
            else:
                if rotate:
                    f = cv2.rotate(f, rot_codes[rotate])
                if mirror:
                    f = cv2.flip(f, 1)
                out = letterbox(f, args.width, args.height)
            if vcam:
                vcam.send(out)
            if not args.no_preview:
                cv2.imshow("PhoneCam", out)
                k = cv2.waitKey(1) & 0xFF
                if k == ord("q"):
                    break
                elif k == ord("m"):
                    mirror = not mirror
                elif k == ord("r"):
                    rotate = (rotate + 90) % 360
            else:
                time.sleep(0.001)
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)
    except KeyboardInterrupt:
        pass
    finally:
        if vcam:
            vcam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
