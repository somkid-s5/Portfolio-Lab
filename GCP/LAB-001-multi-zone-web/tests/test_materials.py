"""Tests the exact app embedded in startup.sh; does not provision GCP."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'scripts/probe.py'

class MaterialsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        startup = (ROOT / 'scripts/startup.sh').read_text()
        app = startup.split("<<'PYAPP'\n", 1)[1].split('\nPYAPP', 1)[0]
        cls.app_path = cls.work / 'app.py'
        cls.app_path.write_text(app)
        cls.marker = cls.work / 'unhealthy'
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        cls.url = f'http://127.0.0.1:{port}'
        cls.process = subprocess.Popen(
            [sys.executable, str(cls.app_path)],
            env={**os.environ, 'PORT': str(port), 'UNHEALTHY_FILE': str(cls.marker)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with urlopen(cls.url + '/healthz', timeout=.2) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(.05)
        cls.tearDownClass()
        raise RuntimeError('Embedded app did not become ready')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.temp.cleanup()

    def command(self, *args):
        return subprocess.run([sys.executable, str(PROBE), *args],
                              capture_output=True, text=True, timeout=20)

    def test_app_contract(self):
        with urlopen(self.url + '/api') as response:
            payload = json.load(response)
            self.assertEqual(payload['service'], 'field-notes')
            self.assertEqual(payload['version'], 'lab001-v1')
            self.assertTrue(payload['time_utc'])
            self.assertEqual(response.headers['X-Lab-Backend'], payload['hostname'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with urlopen(self.url) as response:
            self.assertIn(b'FIELD NOTES', response.read())
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.url + '/missing')
        self.assertEqual(raised.exception.code, 404)

    def test_health_fault_and_restore(self):
        self.marker.touch()
        try:
            with self.assertRaises(HTTPError) as raised:
                urlopen(self.url + '/healthz')
            self.assertEqual(raised.exception.code, 503)
            with urlopen(self.url + '/api') as response:
                self.assertEqual(response.status, 200)
        finally:
            self.marker.unlink()
        with urlopen(self.url + '/healthz') as response:
            self.assertEqual(response.status, 200)

    def test_probe_success_and_no_overwrite(self):
        prefix = self.work / 'good'
        args = ['--url', self.url, '--requests', '5', '--rate', '10',
                '--out', str(prefix)]
        result = self.command(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = prefix.with_suffix('.json').read_bytes()
        summary = json.loads(raw)
        self.assertEqual(summary['success'], 5)
        self.assertEqual(summary['failed'], 0)
        self.assertEqual(sum(summary['backend_counts'].values()), 5)
        with prefix.with_suffix('.csv').open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 5)
        self.assertEqual([int(row['request']) for row in rows], list(range(1, 6)))
        self.assertEqual(self.command(*args).returncode, 2)
        self.assertEqual(prefix.with_suffix('.json').read_bytes(), raw)

    def test_probe_bounds_and_origin_validation(self):
        for option, value in [('--requests', '601'), ('--requests', '0'),
                              ('--concurrency', '11'), ('--rate', '11'),
                              ('--rate', 'nan'), ('--timeout', '31')]:
            result = self.command('--url', self.url, '--out', str(self.work / 'invalid'),
                                  option, value)
            self.assertEqual(result.returncode, 2, result.stdout)
        for url in ['file:///tmp/x', self.url + '/api', 'http://user:pw@localhost']:
            self.assertEqual(self.command('--url', url, '--out',
                             str(self.work / 'invalid')).returncode, 2)

    def test_probe_unreachable_records_errors(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        prefix = self.work / 'failed'
        result = self.command('--url', f'http://127.0.0.1:{port}',
                              '--requests', '2', '--rate', '10', '--timeout', '.2',
                              '--out', str(prefix))
        self.assertEqual(result.returncode, 1)
        summary = json.loads(prefix.with_suffix('.json').read_text())
        self.assertEqual(summary['failed'], 2)
        self.assertIsNone(summary['p95_success_latency_ms'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
