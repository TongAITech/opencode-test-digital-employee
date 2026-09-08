#!/usr/bin/env python3
"""Bounded synthetic CDP startup diagnostics; this is never qualification evidence."""
from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import ProxyHandler, build_opener


COMPAT_FLAGS = [
    "--disable-features=RenderDocument,AutoDeElevate,OptimizationHints",
    "--disable-extensions", "--disable-background-networking",
    "--disable-component-update", "--no-first-run", "--no-default-browser-check",
]

# Copied from the shipped Playwright 1.62.0 chromiumSwitches.ts and headless
# _innerDefaultArgs. Use a TCP debugging endpoint instead of its debugging pipe.
# The sandbox exception is confined to this synthetic diagnostic variant.
PLAYWRIGHT_162_FLAGS = [
    "--disable-field-trial-config", "--disable-background-networking",
    "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
    "--disable-back-forward-cache", "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-extensions-with-background-pages", "--disable-component-update",
    "--no-default-browser-check", "--disable-default-apps", "--disable-dev-shm-usage",
    "--disable-edgeupdater", "--disable-extensions",
    "--disable-features=AvoidUnnecessaryBeforeUnloadCheckSync,BoundaryEventDispatchTracksNodeRemoval,"
    "DestroyProfileOnBrowserClose,DialMediaRouteProvider,GlobalMediaControls,HttpsUpgrades,"
    "LensOverlay,MediaRouter,PaintHolding,ThirdPartyStoragePartitioning,"
    "BlockOriginHeaderModificationOnRedirect,Translate,AutoDeElevate,OptimizationHints,"
    "msForceBrowserSignIn,msEdgeUpdateLaunchServicesPreferredVersion",
    "--enable-features=CDPScreenshotNewSurface", "--allow-pre-commit-input",
    "--disable-hang-monitor", "--disable-ipc-flooding-protection", "--disable-popup-blocking",
    "--disable-prompt-on-repost", "--disable-renderer-backgrounding",
    "--disable-updater-scheduler", "--force-color-profile=srgb", "--metrics-recording-only",
    "--no-first-run", "--password-store=basic", "--use-mock-keychain",
    "--no-service-autorun", "--export-tagged-pdf", "--disable-search-engine-choice-screen",
    "--unsafely-disable-devtools-self-xss-warnings", "--edge-skip-compat-layer-relaunch",
    "--disable-infobars", "--disable-sync", "--enable-unsafe-swiftshader",
    "--hide-scrollbars", "--mute-audio", "--no-sandbox",
    "--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4",
]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tail(path: Path, limit: int = 24000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - limit))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def fetch_json(url: str):
    # Synthetic loopback traffic must not inherit an authenticating HTTP proxy.
    with build_opener(ProxyHandler({})).open(url, timeout=1) as response:
        return json.load(response)


def stop_tree(pid: int | None) -> None:
    if not pid:
        return
    if os.name == "nt":
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGTERM)


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>AITest synthetic CDP probe</title><main id='ready'>READY</main>"
        self.server.requests.append({"path": self.path, "at": round(time.monotonic(), 3)})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def worker(args) -> int:
    directory = args.work
    result_path = directory / "result.json"
    report = {"variant": args.worker, "status": "RUNNING", "phase": "fixture_startup"}
    started = time.monotonic()
    process = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}/"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    flags = PLAYWRIGHT_162_FLAGS if args.worker == "full_162_blank" else COMPAT_FLAGS
    initial_url = origin if args.worker in ("compat_origin", "compat_origin_no_defaults") else "about:blank"
    argv = [str(args.chrome), "--headless=new", *flags,
            f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={directory / 'profile'}", initial_url]
    report.update({"endpoint": endpoint, "origin": origin, "initial_url": initial_url,
                   "chrome_argv": argv, "python": sys.version, "synthetic_only": True})

    def checkpoint(phase: str) -> None:
        report["phase"] = phase
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(result_path, report)

    browser_log = (directory / "chrome.log").open("wb")
    try:
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=browser_log, stderr=browser_log, **options)
        write_json(directory / "process.json", {"pid": process.pid})
        checkpoint("endpoint_startup")
        deadline = time.monotonic() + 10
        while True:
            try:
                report["version_endpoint"] = fetch_json(endpoint + "/json/version")
                report["targets_before_attach"] = fetch_json(endpoint + "/json/list")
                break
            except Exception:
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"CDP endpoint unavailable; Chrome exit={process.poll()}")
                time.sleep(0.1)
        from playwright.sync_api import sync_playwright
        report["playwright_version"] = importlib.metadata.version("playwright")
        checkpoint("playwright_driver_startup")
        with sync_playwright() as driver:
            checkpoint("connect_over_cdp")
            attach_started = time.monotonic()
            connect_options = {"timeout": 25000}
            if args.worker == "compat_origin_no_defaults":
                if "no_defaults" not in inspect.signature(driver.chromium.connect_over_cdp).parameters:
                    report.update({"status": "UNSUPPORTED", "error": "This installed Playwright does not expose no_defaults"})
                    checkpoint("unsupported_no_defaults")
                    return 0
                connect_options["no_defaults"] = True
            report["connect_options"] = connect_options
            browser = driver.chromium.connect_over_cdp(endpoint, **connect_options)
            report["attach_seconds"] = round(time.monotonic() - attach_started, 3)
            report["browser_version"] = browser.version
            report["contexts"] = len(browser.contexts)
            checkpoint("navigate_synthetic_page")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(origin, wait_until="domcontentloaded", timeout=8000)
            report["page_url"] = page.url
            report["page_text"] = page.locator("#ready").inner_text(timeout=3000)
            if report["page_text"] != "READY":
                raise AssertionError("Synthetic page marker missing")
            report["status"] = "PASS"
            checkpoint("complete")
            # Disconnect from the external browser; process ownership stays here.
            browser.close()
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()[-10000:]
    finally:
        for name, route in (("targets_after_attempt", "/json/list"), ("version_after_attempt", "/json/version")):
            try:
                report[name] = fetch_json(endpoint + route)
            except Exception as error:
                report[name] = {"error": f"{type(error).__name__}: {error}"}
        report["fixture_requests"] = server.requests
        report["chrome_exit_before_cleanup"] = process.poll() if process else None
        stop_tree(process.pid if process else None)
        if process:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=3)
        browser_log.close()
        report["chrome_log_tail"] = tail(directory / "chrome.log", 16000)
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(result_path, report)
        server.shutdown()
        server.server_close()
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", choices=["compat_blank", "compat_origin", "full_162_blank", "compat_origin_no_defaults"], help=argparse.SUPPRESS)
    parser.add_argument("--work", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.chrome = args.chrome.resolve()
    args.output = args.output.resolve()
    if args.worker:
        return worker(args)
    report = {"schema_version": 1, "classification": "SYNTHETIC_DIAGNOSTIC_ONLY",
              "qualification": "NOT_QUALIFICATION", "bank_validation": "NOT_PERFORMED",
              "chrome": str(args.chrome), "variant_timeout_seconds": 45, "variants": [],
              "full_args_source": "https://github.com/microsoft/playwright/blob/v1.62.0/packages/playwright-core/src/server/chromium/chromiumSwitches.ts"}
    if not args.chrome.is_file():
        report.update({"status": "FAIL", "error": "Supplied Chrome executable does not exist"})
        write_json(args.output, report)
        return 2
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="aitest-cdp-probe-") as temporary:
        for variant in ("compat_blank", "compat_origin", "full_162_blank", "compat_origin_no_defaults"):
            directory = Path(temporary) / variant
            directory.mkdir()
            environment = dict(os.environ, DEBUG="pw:protocol", PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--chrome", str(args.chrome),
                       "--output", str(args.output), "--worker", variant, "--work", str(directory)]
            with (directory / "protocol.log").open("wb") as log:
                child = subprocess.Popen(command, stdout=log, stderr=log, env=environment)
                expired = False
                try:
                    child.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    expired = True
                    partial = read_json(directory / "result.json")
                    endpoint = partial.get("endpoint")
                    if endpoint:
                        with contextlib.suppress(Exception):
                            partial["targets_on_deadline"] = fetch_json(endpoint + "/json/list")
                    stop_tree(read_json(directory / "process.json").get("pid"))
                    child.kill()
                    child.wait(timeout=5)
                    write_json(directory / "result.json", partial)
            result = read_json(directory / "result.json")
            missing_result = not result
            result.setdefault("variant", variant)
            if expired or missing_result:
                result.update({"status": "FAIL", "error": "Diagnostic worker exceeded 45 second deadline" if expired else "Diagnostic worker did not produce a report"})
            elif result.get("status") == "RUNNING":
                result.update({"status": "FAIL", "error": "Diagnostic worker exited before completion"})
            result["worker_exit_code"] = child.returncode
            result["protocol_tail"] = tail(directory / "protocol.log")
            result["chrome_log_tail"] = tail(directory / "chrome.log", 16000)
            stop_tree(read_json(directory / "process.json").get("pid"))
            report["variants"].append(result)
            write_json(args.output, report)
            print(f"{variant}: {result.get('status', 'FAIL')} phase={result.get('phase', 'unknown')}", flush=True)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["status"] = "DIAGNOSTIC_COMPLETED"
    report["passing_variants"] = [item["variant"] for item in report["variants"] if item.get("status") == "PASS"]
    write_json(args.output, report)
    # A completed diagnostic can contain failing variants; consume the JSON.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
