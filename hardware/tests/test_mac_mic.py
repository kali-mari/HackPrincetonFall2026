"""A disconnected listener must release the Mac microphone, including silent capture."""

import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mac_mic


class MicLifecycleTest(unittest.TestCase):
    def check_disconnect(self, code, expect_audio):
        sender, receiver = socket.socketpair()
        processes = []
        popen = subprocess.Popen

        def spawn(*args, **kwargs):
            process = popen(*args, **kwargs)
            processes.append(process)
            return process

        errors = []

        def run():
            try:
                mac_mic.stream(sender, [sys.executable, '-u', '-c', code])
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run, daemon=True)
        try:
            with patch.object(mac_mic.subprocess, 'Popen', side_effect=spawn):
                worker.start()
                if expect_audio:
                    receiver.settimeout(3)
                    self.assertEqual(receiver.recv(4), b'test')
                receiver.close()
                worker.join(4)
            self.assertFalse(worker.is_alive(), 'Capture kept running after listener disconnected')
            self.assertFalse(errors)
            self.assertEqual(len(processes), 1)
            self.assertIsNotNone(processes[0].poll(), 'Microphone process was not reaped')
        finally:
            receiver.close()
            sender.close()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_disconnect_releases_silent_or_permission_pending_capture(self):
        self.check_disconnect('import time; time.sleep(30)', expect_audio=False)

    def test_disconnect_releases_active_capture(self):
        self.check_disconnect("import sys,time; sys.stdout.buffer.write(b'test'); sys.stdout.flush(); time.sleep(30)",
                              expect_audio=True)
