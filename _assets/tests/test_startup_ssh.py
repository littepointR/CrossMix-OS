"""Check startup preserves SSH and keeps sensitive actions user initiated.

The SSH regression runs the actual startup service block with virtual paths.
It never connects to a device or runs an SSH daemon.
"""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_firmware_check import find_shell, posix_path


ROOT = Path(__file__).resolve().parents[2]
CUSTOMIZATION = ROOT / "System/starts/°customization.sh"


class StartupSshTests(unittest.TestCase):
    def run_service_block(self, existing_service=None, stock_binary=True, init_script=False):
        source = CUSTOMIZATION.read_text(encoding="utf-8")
        helper = re.search(r"crossmix_configure_ssh_service\(\) \{\n.*?\n\}", source, re.S)
        if init_script:
            block = (ROOT / "System/starts/ex_init.sh").read_text(encoding="utf-8")
        elif helper:
            block = helper.group() + "\ncrossmix_configure_ssh_service\n"
        else:
            # Drive the old call site too, so the original overwrite/disable
            # behavior is demonstrably red before the fix.
            block = re.search(r"# custom sshd initd script.*?\n(.*?)\n\s*# fix retroarch path", source, re.S).group(1)
        tools = ROOT / "_assets/tests/.tools"
        tools.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="startup-ssh-", dir=tools) as temp:
            fixture = Path(temp)
            sd, internal = fixture / "sd", fixture / "internal"
            calls = fixture / "calls"
            service = internal / "etc/init.d/sshd"
            service.parent.mkdir(parents=True)
            service_text = '#!/bin/sh\nprintf "service %s\\n" "$*" >> "' + posix_path(calls) + '"\n'
            if existing_service is not None:
                service.write_text(service_text + "# " + existing_service + "\n", encoding="utf-8", newline="\n")
                service.chmod(0o755)
            if stock_binary:
                binary = internal / "usr/sbin/sshd"
                binary.parent.mkdir(parents=True)
                binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
                binary.chmod(0o755)
            for relative, marker in [("System/usr/trimui/etc/init.d/sshd", "fallback"), ("trimui/etc/init.d/sshd", "legacy")]:
                fallback = sd / relative
                fallback.parent.mkdir(parents=True)
                fallback.write_text(service_text + "# " + marker + "\n", encoding="utf-8", newline="\n")
                fallback.chmod(0o755)
            configuration = sd / "System/etc/ex_config"
            configuration.parent.mkdir(parents=True)
            configuration.write_text('NETWORK_SSH="Y"\nNETWORK_SFTPGO="N"\n', encoding="utf-8", newline="\n")
            updater = sd / "System/bin/ex_update.sh"
            updater.parent.mkdir(parents=True)
            updater.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
            updater.chmod(0o755)
            stubs = fixture / "stubs"
            stubs.mkdir()
            nice = stubs / "nice"
            nice.write_text('#!/bin/sh\nprintf "dropbear startup %s\\n" "$*" >> "' + posix_path(calls) + '"\n', encoding="utf-8", newline="\n")
            nice.chmod(0o755)
            replacements = {"/mnt/SDCARD": posix_path(sd), "/etc": posix_path(internal / "etc"), "/usr": posix_path(internal / "usr")}
            pattern = r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(p) for p in replacements) + r')(?=/|["\s:])'
            block = re.sub(pattern, lambda match: replacements[match.group()], block)
            block = block.replace("~/.config/", '"' + posix_path(fixture / "user-config") + '/"')
            block = 'PATH="' + posix_path(stubs) + ':$PATH"\n' + block
            script = fixture / "service-test.sh"
            script.write_text(block, encoding="utf-8", newline="\n")
            result = subprocess.run([find_shell(), posix_path(script)], capture_output=True, encoding="utf-8", timeout=10)
            return result, service.read_text(encoding="utf-8") if service.exists() else "", calls.read_text(encoding="utf-8") if calls.exists() else ""

    def test_stock_service_is_preserved_without_stopping_or_disabling_it(self):
        result, service, calls = self.run_service_block(existing_service="stock service")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# stock service", service)
        self.assertEqual(calls, "")

    def test_existing_custom_service_is_also_preserved(self):
        result, service, calls = self.run_service_block(existing_service="custom service", stock_binary=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# custom service", service)
        self.assertEqual(calls, "")

    def test_missing_service_uses_system_fallback_without_enabling_or_disabling_it(self):
        result, service, calls = self.run_service_block(existing_service=None, stock_binary=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# fallback", service)
        self.assertEqual(calls, "")

    def test_boot_does_not_start_dropbear_over_stock_ssh(self):
        result, service, calls = self.run_service_block(existing_service="stock service", init_script=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# stock service", service)
        self.assertEqual(calls, "")

    def test_boot_retains_dropbear_fallback_without_stock_ssh(self):
        result, _, calls = self.run_service_block(stock_binary=False, init_script=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dropbear startup", calls)

    def test_startup_has_no_account_password_mutation(self):
        source = CUSTOMIZATION.read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*[^#\n].*\b(chpasswd|passwd)\b", source):
            self.fail("Startup must preserve existing account credentials.")

    def test_startup_does_not_automatically_flash_a_boot_logo(self):
        source = CUSTOMIZATION.read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*[^#\n].*Emus/_BootLogo/launch\.sh", source):
            self.fail("Boot logo flashing must remain a manual user action.")


if __name__ == "__main__":
    unittest.main()
