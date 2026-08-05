#!/usr/bin/env python3
"""Diagnose a local published-site failure without exposing response content."""

import argparse
import json
import socket
import urllib.error
import urllib.parse
import urllib.request


def validate_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise argparse.ArgumentTypeError("URL must use http or https")
    if parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("URL must not contain credentials")
    return value


def probe_http(url: str, timeout: float) -> int:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def probe_tcp(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def classify(http_status: int, renderer_reachable: bool) -> str:
    if http_status >= 500 and not renderer_reachable:
        return "renderer_unavailable"
    if http_status >= 400:
        return "site_error"
    return "ready"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", type=validate_url)
    parser.add_argument("--renderer-host", default="127.0.0.1")
    parser.add_argument("--renderer-port", type=int, default=4040)
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()

    status = probe_http(args.url, args.timeout)
    renderer_reachable = probe_tcp(
        args.renderer_host, args.renderer_port, args.timeout
    )
    result = {
        "diagnosis": classify(status, renderer_reachable),
        "httpStatus": status,
        "renderer": {
            "host": args.renderer_host,
            "port": args.renderer_port,
            "reachable": renderer_reachable,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
