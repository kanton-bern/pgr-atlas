import threading
import unittest
from unittest import mock

import derivate_bbox_server
import pmtiles_server


class WatchdogTest(unittest.TestCase):
    """A sidecar whose IOLoop stops or fails takes the whole process down."""

    def _start_and_wait_for_exit(self, module, serve_forever):
        exited = threading.Event()
        exit_codes = []

        def fake_exit(code):
            exit_codes.append(code)
            exited.set()

        with (
            mock.patch.object(module, "_started", False),
            mock.patch.object(module, "_serve_forever", side_effect=serve_forever),
            mock.patch.object(module.os, "_exit", side_effect=fake_exit),
            self.assertLogs(module.__name__, "ERROR") as logs,
        ):
            module.start(18999, "127.0.0.1")
            self.assertTrue(exited.wait(5), "the process was not ended")

        return exit_codes, logs.output

    def test_ioloop_that_raises_ends_the_process_with_1(self):
        for module in (pmtiles_server, derivate_bbox_server):
            with self.subTest(module=module.__name__):
                exit_codes, logs = self._start_and_wait_for_exit(
                    module, OSError("[Errno 48] Address already in use")
                )

                self.assertEqual(exit_codes, [1])
                self.assertIn("Address already in use", "\n".join(logs))

    def test_ioloop_that_returns_ends_the_process_with_1(self):
        for module in (pmtiles_server, derivate_bbox_server):
            with self.subTest(module=module.__name__):
                exit_codes, logs = self._start_and_wait_for_exit(module, lambda *args: None)

                self.assertEqual(exit_codes, [1])
                self.assertIn("stopped", logs[0])
