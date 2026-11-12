"""The WSL helper must refuse public binding and preserve unrelated settings."""

import io
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ollama_wsl_private import main, private_address


class WslNetworkTests(unittest.TestCase):
    def test_private_address_is_accepted(self):
        value = b"\0" * 20 + socket.inet_aton("172.25.177.163")
        with patch("scripts.ollama_wsl_private.fcntl.ioctl", return_value=value):
            self.assertEqual(private_address(), "172.25.177.163")

    def test_public_address_is_refused(self):
        value = b"\0" * 20 + socket.inet_aton("8.8.8.8")
        with (
            patch("scripts.ollama_wsl_private.fcntl.ioctl", return_value=value),
            self.assertRaisesRegex(RuntimeError, "non-private"),
        ):
            private_address()

    def test_refresh_preserves_other_configuration_and_does_not_start_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# Keep this comment\nMODEL=example\nOLLAMA_HOST_ADDRESS=172.20.1.2\nOLLAMA_BASE_URL=http://old:11434\n"
            )
            with (
                patch(
                    "scripts.ollama_wsl_private.private_address",
                    return_value="172.25.177.163",
                ),
                patch("sys.argv", ["helper", "--address", "--update-env", str(path)]),
                patch("sys.stdout", io.StringIO()),
                patch("scripts.ollama_wsl_private.os.execv") as execute,
            ):
                main()
            text = path.read_text()
            self.assertIn("# Keep this comment\nMODEL=example\n", text)
            self.assertEqual(text.count("OLLAMA_HOST_ADDRESS="), 1)
            self.assertIn("OLLAMA_BASE_URL=http://172.25.177.163:11434", text)
            execute.assert_not_called()
