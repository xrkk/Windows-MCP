"""Portable, deterministic process listing checks; no real process mutation."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('process_listing', ROOT / 'src/windows_mcp/process/service.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class ProcessListing(unittest.TestCase):
    def run_list(self, **kwargs):
        psutil = types.ModuleType('psutil')
        psutil.NoSuchProcess = psutil.AccessDenied = RuntimeError
        psutil.process_iter = lambda attrs: [types.SimpleNamespace(info={
            'pid': pid, 'name': name, 'cpu_percent': 0,
            'memory_info': types.SimpleNamespace(rss=1024*1024*pid),
        }) for pid, name in [(1, 'one'), (2, 'two'), (3, 'three')]]
        tabulate = types.ModuleType('tabulate')
        tabulate.tabulate = lambda rows, **kw: repr(rows)
        with patch.dict(sys.modules, {'psutil': psutil, 'tabulate': tabulate}):
            return service.list_processes(**kwargs)

    def test_exact_pid(self):
        out = self.run_list(pid=2)
        self.assertIn("'two'", out)
        self.assertNotIn("'one'", out)
        self.assertIn('1 shown of 1', out)
        self.assertIn('truncated=False', out)

    def test_truncation_is_explicit(self):
        out = self.run_list(limit=1)
        self.assertIn('1 shown of 3', out)
        self.assertIn('truncated=True', out)

    def test_absent_pid_has_no_unrelated_rows(self):
        self.assertIn('0 observed matches', self.run_list(pid=99))

    def test_invalid_limit_rejected(self):
        for value in (0, -1, True):
            with self.assertRaises(ValueError):
                self.run_list(limit=value)
