#!/usr/bin/env python3
"""Ask a running ClamUI web view what state it is in, using only the standard library.

Use it when the ClamUI window opens but stays blank or gray. Start ClamUI with the
WebKit remote inspector enabled, then run this script from a second terminal:

    flatpak run --env=WEBKIT_INSPECTOR_HTTP_SERVER=127.0.0.1:9222 io.github.linx_systems.ClamUI
    python3 inspect-blank-window.py            # default 127.0.0.1:9222

It prints the page state, the console messages WebKit kept, uncaught errors, whether
the bundle was fetched and whether the native side answers a request. Nothing is
modified and nothing leaves the computer: the connection is local to 127.0.0.1.
Paste the whole output into the GitHub issue.
"""

import base64
import json
import os
import socket
import struct
import sys
import time

HOST, _, PORT = (sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:9222").partition(":")
PORT = int(PORT or 9222)
DEADLINE_SECONDS = 8

PROBE = r"""
(async () => {
  const out = {};
  out.readyState = document.readyState;
  out.url = location.href;
  out.userAgent = navigator.userAgent;
  out.language = navigator.language;
  out.languages = Array.from(navigator.languages || []);
  try { out.intlLocale = Intl.DateTimeFormat().resolvedOptions().locale; } catch (e) { out.intlLocale = "ERROR " + e; }
  try { out.timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { out.timeZone = "ERROR " + e; }
  out.htmlLang = document.documentElement.lang;
  out.rootChildren = document.getElementById("root") ? document.getElementById("root").childElementCount : "no #root";
  out.bodyTextStart = (document.body.innerText || "").slice(0, 200);
  out.scripts = Array.from(document.scripts).map((s) => s.src || "(inline)");
  out.stylesheets = Array.from(document.styleSheets).map((s) => s.href || "(inline)");
  out.bodyBackground = getComputedStyle(document.body).backgroundColor;
  out.tauriInternals = typeof window.__TAURI_INTERNALS__;
  out.diagnostics = window.__clamuiBoot ? JSON.stringify(window.__clamuiBoot) : "not present (older build)";
  try {
    out.resources = performance.getEntriesByType("resource").map((r) => r.name + " " + Math.round(r.duration) + "ms");
  } catch (e) { out.resources = "ERROR " + e; }
  if (window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke) {
    const started = performance.now();
    try {
      const answer = await Promise.race([
        window.__TAURI_INTERNALS__.invoke("request", { action: "i18n.catalog", args: {} }),
        new Promise((_, reject) => setTimeout(() => reject(new Error("no answer within 4 s")), 4000)),
      ]);
      out.nativeRequest = "ok in " + Math.round(performance.now() - started) + " ms, language=" + answer.language;
    } catch (e) {
      out.nativeRequest = "FAILED after " + Math.round(performance.now() - started) + " ms: " + e;
    }
  }
  return JSON.stringify(out, null, 2);
})()
"""


def fail(message):
    print("RESULT: " + message)
    sys.exit(1)


def connect():
    try:
        sock = socket.create_connection((HOST, PORT), timeout=DEADLINE_SECONDS)
    except OSError as error:
        fail(
            f"cannot connect to {HOST}:{PORT} ({error}). Is ClamUI running with "
            "--env=WEBKIT_INSPECTOR_HTTP_SERVER=" + f"{HOST}:{PORT}?"
        )
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        "GET /socket/1/1/WebPage HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode())
    header = b""
    try:
        while b"\r\n\r\n" not in header:
            chunk = sock.recv(4096)
            if not chunk:
                break
            header += chunk
    except socket.timeout:
        fail(
            "the inspector port accepts connections but never answered the handshake. "
            "The native UI thread is probably blocked."
        )
    if b" 101 " not in header.split(b"\r\n", 1)[0] + b" ":
        fail("unexpected handshake answer: " + header[:200].decode(errors="replace"))
    leftover = header.split(b"\r\n\r\n", 1)[1]
    return sock, leftover


class Reader:
    def __init__(self, sock, leftover):
        self.sock = sock
        self.buffer = leftover

    def _take(self, count):
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def message(self):
        text = b""
        while True:
            first, second = self._take(2)
            length = second & 0x7F
            if length == 126:
                (length,) = struct.unpack(">H", self._take(2))
            elif length == 127:
                (length,) = struct.unpack(">Q", self._take(8))
            payload = self._take(length)
            opcode = first & 0x0F
            if opcode == 0x8:
                raise EOFError
            if opcode in (0x9, 0xA):
                continue
            text += payload
            if first & 0x80:
                return text.decode("utf-8", errors="replace")


def send(sock, payload):
    data = payload.encode()
    mask = os.urandom(4)
    header = bytes([0x81])
    if len(data) < 126:
        header += bytes([0x80 | len(data)])
    elif len(data) < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", len(data))
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", len(data))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    sock.sendall(header + mask + masked)


def main():
    sock, leftover = connect()
    sock.settimeout(DEADLINE_SECONDS)
    reader = Reader(sock, leftover)
    target = None
    counter = [0]

    def to_target(method, params=None):
        counter[0] += 1
        inner = json.dumps({"id": counter[0], "method": method, "params": params or {}})
        send(sock, json.dumps({
            "id": 1000 + counter[0],
            "method": "Target.sendMessageToTarget",
            "params": {"targetId": target, "message": inner},
        }))
        return counter[0]

    console, answer, probe_id = [], None, None
    end = time.time() + DEADLINE_SECONDS + 6
    try:
        while time.time() < end and answer is None:
            outer = json.loads(reader.message())
            if outer.get("method") == "Target.targetCreated" and target is None:
                target = outer["params"]["targetInfo"]["targetId"]
                to_target("Console.enable")
                to_target("Runtime.enable")
                probe_id = to_target("Runtime.evaluate", {"expression": PROBE})
            elif outer.get("method") == "Target.dispatchMessageFromTarget":
                inner = json.loads(outer["params"]["message"])
                if inner.get("method") == "Console.messageAdded":
                    message = inner["params"]["message"]
                    console.append(f"[{message.get('level')}/{message.get('source')}] "
                                   f"{message.get('text')} ({message.get('url', '')}:{message.get('line', '')})")
                elif inner.get("id") == probe_id:
                    promise = inner.get("result", {}).get("result", {})
                    if inner.get("result", {}).get("wasThrown") or "objectId" not in promise:
                        answer = inner
                    else:
                        probe_id = to_target("Runtime.awaitPromise", {
                            "promiseObjectId": promise["objectId"], "returnByValue": True,
                        })
    except (OSError, EOFError):
        # socket.timeout is an OSError; a reset means the browser process went away mid-probe.
        pass

    if answer is None:
        fail("the page did not answer the probe in time (web process hung or UI thread blocked).")
    result = answer.get("result", {})
    if result.get("wasThrown"):
        fail("the probe itself threw: " + json.dumps(result.get("result"))[:400])
    print(result["result"]["value"])
    print("\nConsole messages kept by WebKit (%d):" % len(console))
    for line in console:
        print("  " + line)
    print("\nRESULT: ok")


if __name__ == "__main__":
    main()
