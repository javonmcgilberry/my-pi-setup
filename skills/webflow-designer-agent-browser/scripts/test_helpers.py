#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock
from typing import Any

SCRIPT_DIR = Path(__file__).parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


discover = load("discover_designer_tabs", "discover-designer-tabs.py")
session = load("designer_session", "designer-session.py")
browser_runtime = load("browser_runtime", "browser-runtime.py")
evidence = load("sanitize_evidence", "sanitize-evidence.py")
automation_evidence = load("automation_evidence", "automation-evidence.py")
capability_catalog = load("capability_catalog", "capability-catalog.py")
site_authorization = load(
    "guarded_site_authorization",
    "guarded-site-authorization.py",
)
workspace_build = load("verify_workspace_build", "verify-workspace-build.py")
published_site = load("published_site_preflight", "published-site-preflight.py")


class DiscoverTests(unittest.TestCase):
    def test_designer_detection_and_url_sanitization(self):
        value = (
            "https://site.design.wfdev.io:8443/?pageId=abc"
            "&simulateRole=marketer&token=private#fragment"
        )
        self.assertTrue(discover.is_designer_url(value))
        self.assertEqual(
            discover.sanitize_url(value),
            "https://site.design.wfdev.io:8443/?pageId=abc"
            "&simulateRole=marketer&token=%5BREDACTED%5D",
        )

    def test_url_sanitization_removes_userinfo(self):
        self.assertEqual(
            discover.sanitize_url("https://user:secret@design.webflow.com/path"),
            "https://design.webflow.com/path",
        )

    def test_non_designer_host_is_rejected(self):
        self.assertFalse(discover.is_designer_url("https://example.com"))

    def test_ownership_diagnostic_is_read_only_and_sanitized(self):
        expected_url = (
            "https://synthetic-site.design.wfdev.io:8443/"
            "?pageId=synthetic-page&simulateRole=marketer"
        )
        sessions = [
            {
                "name": "current-synthetic-session",
                "tabs": [{"tabId": "tab-current", "url": "about:blank"}],
            },
            {
                "name": "owning-synthetic-session",
                "tabs": [{"tabId": "tab-owner", "url": expected_url}],
            },
        ]
        result = discover.diagnose_ownership(
            sessions,
            expected_url,
            "current-synthetic-session",
        )
        diagnostic = result["ownershipDiagnostic"]
        self.assertTrue(diagnostic["ownershipKnown"])
        self.assertFalse(diagnostic["currentSessionControls"])
        self.assertTrue(diagnostic["anotherKnownSessionControls"])
        self.assertEqual(diagnostic["recommendation"], "orchestrator_handoff")

        output = json.dumps(result)
        self.assertNotIn("current-synthetic-session", output)
        self.assertNotIn("owning-synthetic-session", output)
        self.assertNotIn("tab-current", output)
        self.assertNotIn("tab-owner", output)

    def test_ownership_inspection_uses_observation_commands_only(self):
        responses = [
            {"data": {"sessions": ["synthetic-session"]}},
            {"data": {"tabs": []}},
        ]
        with (
            mock.patch.object(discover.shutil, "which", return_value="/bin/tool"),
            mock.patch.object(
                discover,
                "run_agent_browser_json",
                side_effect=responses,
            ) as runner,
        ):
            sessions, unavailable = discover.inspect_agent_browser_sessions()

        self.assertEqual(sessions, [{"name": "synthetic-session", "tabs": []}])
        self.assertEqual(unavailable, 0)
        commands = [
            argument.args[0]
            for argument in runner.call_args_list
        ]
        flattened = [part for command in commands for part in command]
        for mutation in ("claim", "close", "focus", "open", "switch"):
            self.assertNotIn(mutation, flattened)

    def test_standing_authorization_selects_native_transport(self):
        config = {
            "version": 1,
            "authorization": "always_localhost",
            "host": "127.0.0.1",
            "port": 9222,
        }

        direct = discover.build_attachment_plan(
            config,
            endpoint_kind="direct_cdp",
        )
        self.assertEqual(direct["transport"], "native")
        self.assertEqual(
            direct["actions"][0]["args"],
            ["connect", "9222"],
        )
        self.assertEqual(direct["actions"][0]["sessionMode"], "fresh")
        self.assertFalse(direct["conversationPermissionRequired"])
        self.assertEqual(direct["endpointKind"], "direct_cdp")
        self.assertTrue(direct["exclusiveOwnershipRequired"])

        cli = discover.build_attachment_plan(
            config,
            endpoint_kind="direct_cdp",
            transport="cli",
        )
        self.assertEqual(cli["transport"], "cli")
        self.assertEqual(cli["actions"][0], {
            "command": "agent-browser",
            "args": ["connect", "9222"],
        })

        broker = discover.build_attachment_plan(
            config,
            endpoint_kind="chrome_remote_debugging_broker",
        )
        self.assertEqual(broker["transport"], "chrome_devtools_mcp")
        self.assertEqual(
            broker["actions"][0]["payload"]["tool"],
            "chrome_devtools_list_pages",
        )
        self.assertTrue(broker["chromeConfirmationRequired"])
        self.assertNotIn("127.0.0.1", json.dumps(broker))

    def test_standing_authorization_rejects_non_localhost_endpoint(self):
        config = {
            "version": 1,
            "authorization": "always_localhost",
            "host": "0.0.0.0",
            "port": 9222,
        }
        with self.assertRaisesRegex(ValueError, "loopback"):
            discover.validate_attachment_config(config)

    def test_attachment_verification_rejects_managed_fallbacks(self):
        with self.assertRaisesRegex(ValueError, "HeadlessChrome"):
            discover.verify_attachment_surface(
                {
                    "userAgent": "Mozilla/5.0 HeadlessChrome/151.0.0.0",
                    "tabs": [
                        {
                            "title": "Designer",
                            "url": "https://synthetic.design.wfdev.io:8443/",
                        }
                    ],
                },
                expected_runtime_mode="headed",
            )

        with self.assertRaisesRegex(ValueError, "blank"):
            discover.verify_attachment_surface(
                {
                    "userAgent": "Mozilla/5.0 Chrome/151.0.0.0",
                    "tabs": [{"title": "", "url": "about:blank"}],
                },
                expected_runtime_mode="headed",
            )

    def test_attachment_verification_returns_sanitized_proof(self):
        result = discover.verify_attachment_surface(
            {
                "userAgent": "Mozilla/5.0 Chrome/151.0.0.0",
                "tabs": [
                    {
                        "title": "Chrome DevTools MCP",
                        "url": "https://developer.chrome.com/docs/devtools/agents/",
                    },
                    {
                        "title": "Designer",
                        "url": (
                            "https://synthetic.design.wfdev.io:8443/"
                            "?pageId=synthetic-page&token=private"
                        ),
                    },
                ],
            },
            expected_title="Chrome DevTools MCP",
            expected_runtime_mode="headed",
        )
        self.assertEqual(result["classification"], "attached_browser_verified")
        self.assertEqual(result["tabCount"], 2)
        self.assertTrue(result["expectedTabMatched"])
        output = json.dumps(result)
        self.assertNotIn("private", output)
        self.assertNotIn("synthetic-page", output)

    def test_attachment_verification_accepts_explicit_headless_runtime(self):
        result = discover.verify_attachment_surface(
            {
                "userAgent": "Mozilla/5.0 HeadlessChrome/151.0.0.0",
                "tabs": [
                    {
                        "title": "Designer",
                        "url": "https://synthetic.design.wfdev.io:8443/",
                    }
                ],
            },
            expected_title="Designer",
            expected_runtime_mode="headless",
        )
        self.assertEqual(result["runtimeMode"], "headless")
        self.assertFalse(result["managedFallbackRejected"])


class SessionTests(unittest.TestCase):
    def test_attached_plan_is_read_only(self):
        args = argparse.Namespace(
            mode="attached",
            transport="native",
            session="designer-live",
            port=9222,
            tab="t2",
            url=None,
            user_agent="Chrome",
            ready_selector="#ready",
            surface="#panel",
        )
        commands = session.build_commands(args)
        flattened = [
            item for command in commands for item in command.get("args", [])
        ]
        self.assertIn("connect", flattened)
        self.assertNotIn("open", flattened)
        self.assertNotIn("close", flattened)
        self.assertEqual(commands[0]["sessionMode"], "fresh")
        self.assertEqual(
            commands[-1]["args"],
            ["snapshot", "-i", "-c", "-s", "#panel"],
        )

    def test_cli_transport_emits_agent_browser_commands(self):
        args = argparse.Namespace(
            mode="isolated",
            transport="cli",
            session="designer-cli-test",
            port=None,
            tab=None,
            url="https://design.webflow.com/",
            user_agent=None,
            ready_selector="#ready",
            surface="#panel",
        )
        commands = session.build_commands(args)
        self.assertEqual(commands[0]["command"], "agent-browser")
        self.assertNotIn("tool", commands[0])
        self.assertEqual(commands[0]["args"], ["--session", "designer-cli-test", "open", args.url])
        self.assertEqual(
            commands[-1]["args"],
            ["--session", "designer-cli-test", "snapshot", "-i", "-c", "-s", "#panel"],
        )

    def test_attached_plan_requires_direct_cdp_port(self):
        args = argparse.Namespace(
            mode="attached",
            transport="native",
            session="synthetic-session",
            port=None,
            tab=None,
            url=None,
            ready_selector="body",
            surface="body",
            user_agent=None,
        )
        with self.assertRaisesRegex(ValueError, "--port is required"):
            session.build_commands(args)

    def test_attached_plan_rejects_invalid_direct_cdp_port(self):
        args = argparse.Namespace(
            mode="attached",
            transport="native",
            session=None,
            port=70000,
            tab=None,
            url=None,
            ready_selector="body",
            surface="body",
            user_agent=None,
        )
        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            session.build_commands(args)

    def test_attached_plan_emits_mandatory_cleanup_without_spawning_browser(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = session.run(
                [
                    {
                        "tool": "agent_browser",
                        "sessionMode": "fresh",
                        "args": ["connect", "9222"],
                    }
                ],
                [],
                timeout=1,
                preflight_only=False,
                dry_run=True,
                transport="native",
            )
        plan = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(plan["cleanup"][0]["args"], ["close"])
        self.assertEqual(
            plan["cleanup"][1]["args"],
            ["release", "--consumer", "agent_browser"],
        )
        self.assertFalse(
            plan["cleanup"][2]["require"]["runtimeOwned"]
        )

    def test_isolated_plan_rejects_sensitive_url(self):
        args = argparse.Namespace(
            mode="isolated",
            transport="native",
            session="designer-check",
            port=None,
            tab=None,
            url="https://design.webflow.com/?token=private",
            user_agent="Chrome",
            ready_selector="#ready",
            surface="body",
        )
        with self.assertRaises(ValueError):
            session.build_commands(args)

    def test_cli_cleanup_uses_cli_without_silent_native_fallback(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = session.run(
                [{"command": "agent-browser", "args": ["--session", "designer-cli-test", "open", "https://design.webflow.com/"]}],
                [],
                timeout=1,
                preflight_only=False,
                dry_run=True,
                transport="cli",
            )
        plan = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(plan["transport"], "cli")
        self.assertEqual(plan["cleanup"][0], {"command": "agent-browser", "args": ["--session", "designer-cli-test", "close"]})

    def test_service_preflight_returns_sanitized_success(self):
        check = {
            "label": "Designer client",
            "kind": "tcp",
            "host": "127.0.0.1",
            "port": 43121,
        }
        connection = mock.Mock()
        with mock.patch.object(
            session.socket,
            "create_connection",
            return_value=connection,
        ):
            result = session.run_preflight([check], timeout=1)

        self.assertTrue(result["ready"])
        self.assertEqual(result["classification"], "prerequisites_ready")
        self.assertEqual(result["checks"][0]["label"], "Designer client")
        self.assertEqual(result["checks"][0]["observed"], "listener_available")
        self.assertNotIn("127.0.0.1", json.dumps(result))
        self.assertNotIn("43121", json.dumps(result))
        connection.close.assert_called_once()

    def test_service_preflight_identifies_required_failure(self):
        check = {
            "label": "Extension API",
            "kind": "http",
            "url": "http://127.0.0.1:43122/health",
            "status": 200,
        }
        with mock.patch.object(
            session.urllib.request,
            "urlopen",
            side_effect=OSError("unavailable"),
        ):
            result = session.run_preflight([check], timeout=1)

        self.assertFalse(result["ready"])
        self.assertEqual(result["classification"], "prerequisite_unavailable")
        self.assertEqual(result["checks"][0]["label"], "Extension API")
        self.assertEqual(result["checks"][0]["observed"], "connection_failed")
        self.assertNotIn("127.0.0.1", json.dumps(result))
        self.assertNotIn("43122", json.dumps(result))

    def test_service_preflight_checks_expected_http_status(self):
        check = {
            "label": "Extension client",
            "kind": "http",
            "url": "http://127.0.0.1:43123/ready",
            "status": 200,
        }
        response = mock.MagicMock()
        response.status = 204
        response.__enter__.return_value = response
        with mock.patch.object(
            session.urllib.request,
            "urlopen",
            return_value=response,
        ):
            result = session.run_preflight([check], timeout=1)

        self.assertFalse(result["ready"])
        self.assertEqual(result["checks"][0]["expected"], "http_status_200")
        self.assertEqual(result["checks"][0]["observed"], "http_status_204")

    def test_service_preflight_does_not_guess_services(self):
        args = argparse.Namespace(tcp_service=[], http_service=[])
        self.assertEqual(session.build_service_checks(args), [])


class BrowserRuntimeTests(unittest.TestCase):
    def config(self, root: Path, source: Path) -> Any:
        return browser_runtime.RuntimeConfig(
            root=root,
            source_root=source,
            source_profile="Default",
            chrome=Path(
                "/tmp/Google Chrome for Testing.app/Contents/MacOS/"
                "Google Chrome for Testing"
            ),
            host="127.0.0.1",
            port=9222,
        )

    def test_launch_plan_is_headless_dedicated_loopback_direct_cdp_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "state"
            config = self.config(root, Path(directory) / "source")
            plan = browser_runtime.build_chrome_launch_plan(config)
        self.assertIn(f"--user-data-dir={root / 'chrome-user-data'}", plan)
        self.assertIn("--remote-debugging-address=127.0.0.1", plan)
        self.assertIn("--remote-debugging-port=9222", plan)
        self.assertIn("--headless=new", plan)
        self.assertIn("--window-size=1440,1000", plan)
        self.assertNotIn("--auto-connect", plan)

    def test_automation_browser_discovery_never_selects_normal_chrome(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            chrome = (
                home
                / ".cache/puppeteer/chrome/mac_arm-151.0.7922.71"
                / "chrome-mac-arm64/Google Chrome for Testing.app"
                / "Contents/MacOS/Google Chrome for Testing"
            )
            chrome.parent.mkdir(parents=True)
            chrome.write_text("synthetic")
            with mock.patch.object(browser_runtime.Path, "home", return_value=home):
                selected = browser_runtime.discover_automation_chrome()
        self.assertEqual(selected, chrome)
        self.assertNotIn("/Applications/Google Chrome.app", str(selected))

    def test_start_rejects_normal_chrome_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            normal_chrome = base / "Google Chrome"
            normal_chrome.write_text("synthetic")
            config = replace(
                self.config(base / "state", base / "source"),
                chrome=normal_chrome,
            )
            with mock.patch.object(browser_runtime.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(
                    browser_runtime.RuntimeFailure, "unsupported_browser"
                ):
                    browser_runtime.start_runtime(config, 1)
            popen.assert_not_called()

    def test_start_rejects_renamed_normal_chrome_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            app = base / "Google Chrome for Testing.app"
            executable = (
                app / "Contents/MacOS/Google Chrome for Testing"
            )
            executable.parent.mkdir(parents=True)
            executable.write_text("synthetic")
            with (app / "Contents/Info.plist").open("wb") as file:
                browser_runtime.plistlib.dump(
                    {
                        "CFBundleIdentifier": "com.google.Chrome",
                        "CFBundleExecutable": "Google Chrome for Testing",
                    },
                    file,
                )
            config = replace(
                self.config(base / "state", base / "source"),
                chrome=executable,
            )
            with mock.patch.object(browser_runtime.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(
                    browser_runtime.RuntimeFailure, "unsupported_browser"
                ):
                    browser_runtime.start_runtime(config, 1)
            popen.assert_not_called()

    def test_runtime_rejects_symlinked_profile_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "state"
            external_profile = base / "external-profile"
            root.mkdir()
            external_profile.mkdir()
            (root / "chrome-user-data").symlink_to(
                external_profile,
                target_is_directory=True,
            )
            config = self.config(root, base / "source")
            with self.assertRaisesRegex(
                browser_runtime.RuntimeFailure, "unsafe_profile_root"
            ):
                browser_runtime.validate_config(config)
            self.assertTrue(external_profile.is_dir())

    def test_launch_plan_can_be_explicitly_headed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(
                Path(directory) / "state", Path(directory) / "source"
            )
            plan = browser_runtime.build_chrome_launch_plan(
                config, headless=False
            )
        self.assertNotIn("--headless=new", plan)
        self.assertNotIn("--window-size=1440,1000", plan)

    def test_start_rejects_mode_change_until_owned_runtime_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = self.config(base / "state", base / "source")
            with mock.patch.object(
                browser_runtime,
                "inspect_runtime",
                return_value={
                    "cdpReady": True,
                    "runtimeOwned": True,
                    "mode": "headless",
                },
            ):
                with self.assertRaisesRegex(
                    browser_runtime.RuntimeFailure, "runtime_mode_conflict"
                ):
                    browser_runtime.start_runtime(
                        config, 1, headless=False
                    )

    def test_runtime_rejects_non_loopback_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            config = browser_runtime.RuntimeConfig(
                root=Path(directory) / "state",
                source_root=Path(directory) / "source",
                source_profile="Default",
                chrome=Path("/tmp/chrome"),
                host="0.0.0.0",
                port=9222,
            )
            with self.assertRaisesRegex(
                browser_runtime.RuntimeFailure, "loopback_required"
            ):
                browser_runtime.validate_config(config)

    def test_owned_runtime_without_ready_cdp_is_not_reported_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = self.config(base / "state", base / "source")
            browser_runtime.ensure_private_root(config.root)
            browser_runtime.write_private_json(
                config.runtime_path,
                {"version": 1, "pid": 4242, "startedAt": 1},
            )
            with (
                mock.patch.object(
                    browser_runtime,
                    "process_matches_runtime",
                    return_value=True,
                ),
                mock.patch.object(browser_runtime, "cdp_ready", return_value=False),
            ):
                result = browser_runtime.inspect_runtime(config)
        self.assertEqual(result["status"], "unhealthy")
        self.assertTrue(result["runtimeOwned"])

    def test_profile_bootstrap_excludes_credentials_and_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            profile = source / "Default"
            profile.mkdir(parents=True)
            (source / "Local State").write_text("{}")
            (profile / "Cookies").write_text("synthetic-encrypted-cookie-db")
            (profile / "Cookies-wal").write_text("synthetic-cookie-sidecar")
            (profile / "Cookies-shm").write_text("synthetic-cookie-sidecar")
            (profile / "Login Data").write_text("synthetic-login-db")
            (profile / "Login Data-wal").write_text("synthetic-login-sidecar")
            (profile / "Web Data").write_text("synthetic-web-data-db")
            (profile / "Web Data-shm").write_text("synthetic-web-data-sidecar")
            (profile / "Local State").write_text("synthetic-nested-state")
            (profile / "Preferences").write_text("{}")
            (profile / "Local Storage").mkdir()
            (profile / "Local Storage" / "token").write_text("synthetic-token")
            (profile / "IndexedDB").mkdir()
            (profile / "IndexedDB" / "state").write_text("synthetic-state")
            (profile / "Network").mkdir()
            (profile / "Network" / "Cookies").write_text("synthetic-network-cookie-db")
            (profile / "Cache").mkdir()
            (profile / "Cache" / "entry").write_text("transient")
            config = self.config(base / "state", source)
            result = browser_runtime.bootstrap_profile(config, replace=False)
            copied = config.profile_root / "Default"
            self.assertEqual(result["classification"], "profile_initialized")
            self.assertTrue((copied / "Preferences").is_file())
            self.assertFalse((config.profile_root / "Local State").exists())
            self.assertFalse((copied / "Cookies").exists())
            self.assertFalse((copied / "Cookies-wal").exists())
            self.assertFalse((copied / "Cookies-shm").exists())
            self.assertFalse((copied / "Login Data").exists())
            self.assertFalse((copied / "Login Data-wal").exists())
            self.assertFalse((copied / "Web Data").exists())
            self.assertFalse((copied / "Web Data-shm").exists())
            self.assertFalse((copied / "Local State").exists())
            self.assertFalse((copied / "Network" / "Cookies").exists())
            self.assertFalse((copied / "Local Storage").exists())
            self.assertFalse((copied / "IndexedDB").exists())
            self.assertFalse((copied / "Cache").exists())
            self.assertEqual(
                json.loads(config.origin_path.read_text())["refreshPolicy"],
                "manual_login_only",
            )

    def test_profile_bootstrap_rejects_source_profile_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = replace(
                self.config(base / "state", base / "source"),
                source_profile="..",
            )
            with self.assertRaisesRegex(
                browser_runtime.RuntimeFailure, "invalid_source_profile"
            ):
                browser_runtime.bootstrap_profile(config, replace=False)

    def test_profile_bootstrap_rejects_symlink_outside_source_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            external = base / "external"
            source.mkdir()
            external.mkdir()
            (source / "Default").symlink_to(
                external,
                target_is_directory=True,
            )
            config = self.config(base / "state", source)
            with self.assertRaisesRegex(
                browser_runtime.RuntimeFailure, "invalid_source_profile"
            ):
                browser_runtime.bootstrap_profile(config, replace=False)

    def test_profile_bootstrap_rejects_nested_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            profile = source / "Default"
            external = base / "external-secret"
            profile.mkdir(parents=True)
            external.write_text("must-not-copy")
            (profile / "nested-link").symlink_to(external)
            config = self.config(base / "state", source)
            with self.assertRaisesRegex(
                browser_runtime.RuntimeFailure, "source_profile_symlink"
            ):
                browser_runtime.bootstrap_profile(config, replace=False)
            self.assertFalse(config.profile_root.exists())

    def test_profile_bootstrap_refuses_locked_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            (source / "Default").mkdir(parents=True)
            (source / "Local State").write_text("{}")
            (source / "SingletonLock").symlink_to("synthetic-running-chrome")
            config = self.config(base / "state", source)
            with self.assertRaisesRegex(
                browser_runtime.RuntimeFailure, "source_profile_locked"
            ):
                browser_runtime.bootstrap_profile(config, replace=False)

    def test_profile_bootstrap_cleans_partial_copy_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            (source / "Default").mkdir(parents=True)
            (source / "Local State").write_text("{}")
            config = self.config(base / "state", source)
            with mock.patch.object(
                browser_runtime.shutil,
                "copytree",
                side_effect=browser_runtime.shutil.Error("synthetic failure"),
            ):
                with self.assertRaisesRegex(
                    browser_runtime.RuntimeFailure, "profile_copy_failed"
                ):
                    browser_runtime.bootstrap_profile(config, replace=False)
            self.assertFalse(config.profile_root.exists())

    def test_consumer_claim_is_exclusive_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = self.config(base / "state", base / "source")
            browser_runtime.ensure_private_root(config.root)
            with mock.patch.object(
                browser_runtime,
                "inspect_runtime",
                return_value={"cdpReady": True},
            ):
                first = browser_runtime.claim_consumer(config, "agent_browser")
                repeated = browser_runtime.claim_consumer(config, "agent_browser")
                with self.assertRaisesRegex(
                    browser_runtime.RuntimeFailure, "consumer_conflict"
                ):
                    browser_runtime.claim_consumer(
                        config, "chrome_devtools_mcp"
                    )
            self.assertFalse(first["reused"])
            self.assertTrue(repeated["reused"])

    def test_consumer_release_also_stops_owned_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = self.config(base / "state", base / "source")
            browser_runtime.ensure_private_root(config.root)
            browser_runtime.write_private_json(
                config.lease_path,
                {"version": 1, "consumer": "agent_browser", "claimedAt": 1},
            )
            with mock.patch.object(
                browser_runtime,
                "stop_runtime",
                return_value={"status": "stopped"},
            ) as stop:
                result = browser_runtime.release_consumer(
                    config, "agent_browser"
                )
        stop.assert_called_once_with(config)
        self.assertEqual(result["status"], "released_and_stopped")

    def test_watchdog_stops_only_matching_owned_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = self.config(base / "state", base / "source")
            browser_runtime.ensure_private_root(config.root)
            browser_runtime.write_private_json(
                config.runtime_path,
                {"version": 1, "pid": 4242, "startedAt": 7},
            )
            browser_runtime.write_private_json(
                config.lease_path,
                {"version": 1, "consumer": "agent_browser"},
            )
            with (
                mock.patch.object(browser_runtime.time, "sleep"),
                mock.patch.object(
                    browser_runtime,
                    "process_matches_runtime",
                    return_value=True,
                ),
                mock.patch.object(
                    browser_runtime,
                    "terminate_owned_runtime",
                ) as terminate,
            ):
                browser_runtime.run_watchdog(config, 4242, 7, 60)
            terminate.assert_called_once_with(4242, config)
            self.assertFalse(config.runtime_path.exists())
            self.assertFalse(config.lease_path.exists())

    def test_owned_runtime_termination_waits_for_port_release(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = self.config(base / "state", base / "source")

            def kill_group(_pid, signal_value):
                if signal_value == 0:
                    raise ProcessLookupError

            with (
                mock.patch.object(
                    browser_runtime.os,
                    "killpg",
                    side_effect=kill_group,
                ) as mocked_kill_group,
                mock.patch.object(
                    browser_runtime,
                    "port_open",
                    return_value=False,
                ),
                mock.patch.object(browser_runtime.time, "sleep"),
            ):
                browser_runtime.terminate_owned_runtime(4242, config)
        self.assertEqual(
            mocked_kill_group.call_args_list,
            [
                mock.call(4242, browser_runtime.signal.SIGTERM),
                mock.call(4242, 0),
            ],
        )

    def test_stop_refuses_unverified_process_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = self.config(base / "state", base / "source")
            browser_runtime.ensure_private_root(config.root)
            browser_runtime.write_private_json(
                config.runtime_path,
                {"version": 1, "pid": 4242, "startedAt": 1},
            )
            with (
                mock.patch.object(browser_runtime, "pid_alive", return_value=True),
                mock.patch.object(
                    browser_runtime,
                    "process_matches_runtime",
                    return_value=False,
                ),
            ):
                with self.assertRaisesRegex(
                    browser_runtime.RuntimeFailure,
                    "runtime_ownership_unknown",
                ):
                    browser_runtime.stop_runtime(config)


class CapabilityCatalogTests(unittest.TestCase):
    def test_catalog_is_valid_and_implementations_exist(self):
        path = SCRIPT_DIR.parent / "capabilities.json"
        result = capability_catalog.validate_catalog(
            json.loads(path.read_text()), path.parent
        )
        self.assertGreaterEqual(result["capabilityCount"], 8)
        identifiers = {
            entry["id"] for entry in result["capabilities"]
        }
        self.assertIn("browser.runtime", identifiers)
        self.assertIn("evidence.review", identifiers)

    def test_catalog_rejects_missing_implementation(self):
        path = SCRIPT_DIR.parent / "capabilities.json"
        value = json.loads(path.read_text())
        value["capabilities"][0]["implementation"] = "scripts/missing.py"
        with self.assertRaisesRegex(ValueError, "missing capability implementation"):
            capability_catalog.validate_catalog(value, path.parent)


class EvidenceTests(unittest.TestCase):
    def test_redacts_secrets_and_query_values(self):
        value = {
            "authorization": "Bearer private",
            "url": "https://design.webflow.com/?pageId=abc&token=private",
            "nested": {"cookieValue": "private", "status": 200},
        }
        result = evidence.sanitize(value)
        self.assertEqual(result["authorization"], "[REDACTED]")
        self.assertEqual(result["nested"]["cookieValue"], "[REDACTED]")
        self.assertEqual(result["nested"]["status"], 200)
        self.assertEqual(
            result["url"],
            "https://design.webflow.com/?pageId=abc&token=%5BREDACTED%5D",
        )


class AutomationReviewTests(unittest.TestCase):
    @staticmethod
    def event(
        event_id: str,
        *,
        kind: str = "failure",
        occurrences: int = 1,
    ) -> dict[str, object]:
        return {
            "id": event_id,
            "kind": kind,
            "summary": f"Sanitized evidence for {event_id}",
            "occurrences": occurrences,
        }

    @staticmethod
    def candidate(
        name: str,
        event_id: str,
        *,
        occurrence_count: int = 1,
        deterministic: bool = False,
        stateful: bool = False,
        sensitive: bool = False,
        closest_existing_helper: str | None = None,
    ) -> dict[str, object]:
        return {
            "name": name,
            "known_inputs": ["sanitized explicit input"],
            "bounded_operation": "perform one bounded sanitized check",
            "observable_postcondition": "return one structured result",
            "occurrence_count": occurrence_count,
            "deterministic": deterministic,
            "stateful": stateful,
            "sensitive": sensitive,
            "closest_existing_helper": closest_existing_helper,
            "evidence": [event_id],
        }

    @staticmethod
    def full_run(
        events: list[dict[str, object]],
        candidates: list[dict[str, object]],
        *,
        reconstruction_complete: bool = True,
        inventory_complete: bool = True,
    ) -> dict[str, object]:
        return {
            "run": {
                "reconstruction_complete": reconstruction_complete,
                "inventory_complete": inventory_complete,
                "events": events,
                "candidates": candidates,
            }
        }

    def test_repeated_service_failure_must_be_adjudicated(self):
        events = [
            self.event("service-unavailable", occurrences=3),
            self.event("stale-browser-owner", occurrences=1),
        ]
        candidates = [
            self.candidate("inspect browser owner", "stale-browser-owner")
        ]
        with self.assertRaisesRegex(ValueError, "service-unavailable"):
            automation_evidence.review(self.full_run(events, candidates))

    def test_repeated_evidence_cannot_be_reclassified_as_one_off(self):
        event = self.event("service-unavailable", occurrences=3)
        candidate = self.candidate(
            "check explicit service readiness",
            "service-unavailable",
            occurrence_count=1,
            deterministic=True,
        )
        with self.assertRaisesRegex(ValueError, "understates its evidence"):
            automation_evidence.review(self.full_run([event], [candidate]))

    def test_genuine_one_off_event_remains_observe(self):
        event = self.event("unknown-modal")
        candidate = self.candidate("inspect unknown modal", "unknown-modal")
        result = automation_evidence.review(self.full_run([event], [candidate]))
        self.assertEqual(
            result["automationReview"][0]["classification"],
            "observe",
        )
        self.assertEqual(
            result["automationReview"][0]["reason"],
            "behavior_is_not_deterministic",
        )
        self.assertTrue(result["noPromotableDeterministicSequence"])

    def test_sensitive_candidate_is_not_persisted(self):
        event = self.event("provider-session-material", occurrences=4)
        candidate = self.candidate(
            "reuse provider session material",
            "provider-session-material",
            occurrence_count=4,
            deterministic=True,
            stateful=True,
            sensitive=True,
        )
        result = automation_evidence.review(self.full_run([event], [candidate]))
        self.assertEqual(
            result["automationReview"][0]["classification"],
            "do_not_persist",
        )
        self.assertEqual(
            result["automationReview"][0]["reason"],
            "depends_on_sensitive_state",
        )

    def test_existing_helper_overlap_extends_existing(self):
        event = self.event("service-unavailable", occurrences=3)
        candidate = self.candidate(
            "check explicit service readiness",
            "service-unavailable",
            occurrence_count=3,
            deterministic=True,
            closest_existing_helper="designer-session.py",
        )
        result = automation_evidence.review(self.full_run([event], [candidate]))
        self.assertEqual(
            result["automationReview"][0]["classification"],
            "extend_existing",
        )
        self.assertFalse(result["noPromotableDeterministicSequence"])

    def test_stateful_deterministic_candidate_is_guarded(self):
        event = self.event("exact-site-selection", occurrences=2)
        candidate = self.candidate(
            "select one exact site",
            "exact-site-selection",
            occurrence_count=2,
            deterministic=True,
            stateful=True,
        )
        result = automation_evidence.review(self.full_run([event], [candidate]))
        self.assertEqual(
            result["automationReview"][0]["classification"],
            "guarded_helper",
        )

    def test_incomplete_full_run_fails_clearly(self):
        event = self.event("service-unavailable", occurrences=2)
        candidate = self.candidate(
            "check explicit service readiness",
            "service-unavailable",
            occurrence_count=2,
            deterministic=True,
        )
        with self.assertRaisesRegex(ValueError, "reconstruction_complete"):
            automation_evidence.review(
                self.full_run(
                    [event],
                    [candidate],
                    reconstruction_complete=False,
                )
            )
        with self.assertRaisesRegex(ValueError, "inventory_complete"):
            automation_evidence.review(
                self.full_run(
                    [event],
                    [candidate],
                    inventory_complete=False,
                )
            )

    def test_evidence_queue_requires_repetition_before_promotion(self):
        candidate = {
            "candidateId": "runtime-readiness-check",
            "operationClass": "browser.runtime.readiness",
            "inputShape": "configured-loopback-endpoint",
            "postconditionKind": "cdp-endpoint-ready",
            "deterministic": True,
            "stateful": False,
            "sensitive": False,
            "existingHelper": "browser-runtime.py",
        }
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "evidence" / "queue.json"
            first = automation_evidence.queue_candidate(queue, candidate)
            initial = automation_evidence.review_queue(queue)
            second = automation_evidence.queue_candidate(queue, candidate)
            repeated = automation_evidence.review_queue(queue)
            self.assertEqual(queue.stat().st_mode & 0o777, 0o600)
        self.assertEqual(first["occurrences"], 1)
        self.assertEqual(second["occurrences"], 2)
        self.assertEqual(
            initial["candidates"][0]["classification"], "observe"
        )
        self.assertEqual(
            repeated["candidates"][0]["classification"],
            "extend_existing",
        )

    def test_sensitive_evidence_never_enters_queue(self):
        candidate = {
            "candidateId": "authentication-material",
            "operationClass": "browser.auth.refresh",
            "inputShape": "domain-scoped-state",
            "postconditionKind": "authenticated-surface",
            "deterministic": True,
            "stateful": True,
            "sensitive": True,
            "existingHelper": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            queue = Path(directory) / "queue.json"
            result = automation_evidence.queue_candidate(queue, candidate)
            self.assertFalse(queue.exists())
        self.assertFalse(result["queued"])
        self.assertEqual(result["classification"], "do_not_persist")


class GuardedSiteAuthorizationTests(unittest.TestCase):
    expected_site_id = "synthetic-site-target"

    @staticmethod
    def page(
        values: list[str],
        *,
        has_next: bool,
    ) -> dict[str, object]:
        return {
            "checkboxes": [
                {"value": value, "checked": False}
                for value in values
            ],
            "has_next": has_next,
        }

    @staticmethod
    def surface(
        pages: list[dict[str, object]],
        *,
        post_selection: dict[str, object] | None = None,
        callback_state: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "pages": pages,
            "post_selection": post_selection,
            "callback_state": callback_state,
        }

    def test_rejects_zero_and_duplicate_exact_matches(self):
        zero = self.surface(
            [self.page(["synthetic-site-other"], has_next=False)]
        )
        with self.assertRaisesRegex(ValueError, "no exact site match"):
            site_authorization.review_authorization(
                zero,
                self.expected_site_id,
                allow_selection=False,
                allow_authorization=False,
            )

        duplicate = self.surface(
            [
                self.page(
                    [self.expected_site_id, self.expected_site_id],
                    has_next=False,
                )
            ]
        )
        with self.assertRaisesRegex(ValueError, "duplicate exact matches"):
            site_authorization.review_authorization(
                duplicate,
                self.expected_site_id,
                allow_selection=False,
                allow_authorization=False,
            )

    def test_pagination_selects_only_expected_synthetic_site(self):
        value = self.surface(
            [
                self.page(["synthetic-site-other"], has_next=True),
                self.page([self.expected_site_id], has_next=False),
            ],
            post_selection={
                "selected_values": [self.expected_site_id],
                "authorize_enabled": True,
            },
            callback_state={"site_id": self.expected_site_id},
        )
        result = site_authorization.review_authorization(
            value,
            self.expected_site_id,
            allow_selection=True,
            allow_authorization=True,
        )
        self.assertEqual(result["pagination"]["loadNextActions"], 1)
        self.assertEqual(result["selection"]["exactMatchCount"], 1)
        self.assertEqual(result["selection"]["targetPageIndex"], 1)
        self.assertTrue(result["selection"]["postconditionVerified"])
        self.assertTrue(result["authorization"]["callbackVerified"])
        self.assertNotIn(self.expected_site_id, json.dumps(result))

    def test_mutation_requires_explicit_flags(self):
        value = self.surface(
            [self.page([self.expected_site_id], has_next=False)]
        )
        result = site_authorization.review_authorization(
            value,
            self.expected_site_id,
            allow_selection=False,
            allow_authorization=False,
        )
        self.assertFalse(result["selection"]["browserMutationAllowed"])
        self.assertFalse(result["authorization"]["browserMutationAllowed"])
        self.assertFalse(result["selection"]["browserMutationPerformedByHelper"])
        self.assertFalse(
            result["authorization"]["browserMutationPerformedByHelper"]
        )

    def test_callback_verification_rejects_mismatched_site(self):
        value = self.surface(
            [self.page([self.expected_site_id], has_next=False)],
            post_selection={
                "selected_values": [self.expected_site_id],
                "authorize_enabled": True,
            },
            callback_state={"site_id": "synthetic-site-other"},
        )
        with self.assertRaisesRegex(ValueError, "expected site"):
            site_authorization.review_authorization(
                value,
                self.expected_site_id,
                allow_selection=True,
                allow_authorization=True,
            )


class WorkspaceBuildTests(unittest.TestCase):
    def test_detects_a_stale_generated_module(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "module.ts"
            built = Path(directory) / "module.js"
            source.write_text("source")
            built.write_text("built")
            os.utime(built, ns=(1, 1))
            os.utime(source, ns=(2, 2))

            self.assertFalse(workspace_build.verify(source, built)["current"])

            os.utime(built, ns=(3, 3))

            self.assertTrue(workspace_build.verify(source, built)["current"])


class PublishedSitePreflightTests(unittest.TestCase):
    def test_classifies_missing_renderer_for_server_error(self):
        self.assertEqual(
            published_site.classify(500, False), "renderer_unavailable"
        )

    def test_does_not_blame_renderer_for_successful_site(self):
        self.assertEqual(published_site.classify(200, False), "ready")

    def test_rejects_credentials_in_url(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            published_site.validate_url("https://user:secret@example.com")


class CdpFrameEvalTests(unittest.TestCase):
    def test_rejects_non_loopback_browser_websocket(self):
        with tempfile.TemporaryDirectory() as directory:
            expression = Path(directory) / "check.js"
            expression.write_text("document.readyState")
            completed = subprocess.run(
                [
                    "node",
                    str(SCRIPT_DIR / "cdp-frame-eval.mjs"),
                    "--browser-ws-url",
                    "ws://example.com/devtools/browser/example",
                    "--page-url-needle",
                    "site.design.wfdev.io",
                    "--frame-url-needle",
                    "localhost:1337",
                    "--expression-file",
                    str(expression),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("loopback host", completed.stderr)

    def test_dry_run_suppresses_target_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            expression = Path(directory) / "check.js"
            expression.write_text("document.readyState")
            completed = subprocess.run(
                [
                    "node",
                    str(SCRIPT_DIR / "cdp-frame-eval.mjs"),
                    "--browser-ws-url",
                    "ws://127.0.0.1:9222/devtools/browser/example",
                    "--page-url-needle",
                    "site.design.wfdev.io",
                    "--frame-url-needle",
                    "localhost:1337",
                    "--expression-file",
                    str(expression),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0)
            result = json.loads(completed.stdout)
            self.assertEqual(result["expressionFile"], "check.js")
            self.assertFalse(result["targetMetadataIncluded"])
            self.assertNotIn("site.design.wfdev.io", completed.stdout)
            self.assertNotIn("localhost:1337", completed.stdout)

    def test_rejects_sensitive_targeting_values(self):
        with tempfile.TemporaryDirectory() as directory:
            expression = Path(directory) / "check.js"
            expression.write_text("document.readyState")
            completed = subprocess.run(
                [
                    "node",
                    str(SCRIPT_DIR / "cdp-frame-eval.mjs"),
                    "--browser-ws-url",
                    "ws://127.0.0.1:9222/devtools/browser/example",
                    "--page-url-needle",
                    "site.design.wfdev.io?token=value",
                    "--frame-url-needle",
                    "localhost:1337",
                    "--expression-file",
                    str(expression),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("Refusing sensitive targeting value", completed.stderr)

    def test_visible_replacement_dry_run_is_sanitized(self):
        completed = subprocess.run(
            [
                "node",
                str(SCRIPT_DIR / "cdp-frame-eval.mjs"),
                "--browser-ws-url",
                "ws://127.0.0.1:9222/devtools/browser/example",
                "--page-url-needle",
                "site.design.wfdev.io",
                "--frame-url-needle",
                "localhost:1337",
                "--visible-replacement-selector",
                "[data-synthetic-form]",
                "--observation-ms",
                "250",
                "--dry-run",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)
        result = json.loads(completed.stdout)
        self.assertEqual(result["operation"], "observe-visible-replacement")
        self.assertFalse(result["targetMetadataIncluded"])
        self.assertNotIn("data-synthetic-form", completed.stdout)

    def test_visible_replacement_summary_detects_overlap_and_blank_gap(self):
        module_url = (SCRIPT_DIR / "cdp-frame-eval.mjs").as_uri()
        script = (
            f'import {{summarizeVisibleReplacement}} from {json.dumps(module_url)};'
            'const value = summarizeVisibleReplacement('
            '[{"elapsedMs":0,"rendered":2,"total":2},'
            '{"elapsedMs":10,"rendered":3,"total":3},'
            '{"elapsedMs":20,"rendered":1,"total":2},'
            '{"elapsedMs":30,"rendered":2,"total":2}]);'
            'process.stdout.write(JSON.stringify(value));'
        )
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)
        result = json.loads(completed.stdout)
        self.assertTrue(result["overlapObserved"])
        self.assertTrue(result["blankGapObserved"])
        self.assertEqual(result["finalRendered"], 2)
        self.assertEqual(result["maximumTotal"], 3)


if __name__ == "__main__":
    unittest.main()
