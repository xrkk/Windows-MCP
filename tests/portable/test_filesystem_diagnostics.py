"""Portable checks at the filesystem operation boundary; no Windows UI imports."""
import errno
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
views_spec = importlib.util.spec_from_file_location(
    'windows_mcp.filesystem.views', ROOT / 'src/windows_mcp/filesystem/views.py')
views = importlib.util.module_from_spec(views_spec)
desktop_utils = types.ModuleType('windows_mcp.desktop.utils')
desktop_utils.is_elevated = lambda: True
with mock.patch.dict(sys.modules, {views_spec.name: views,
                                  'windows_mcp.desktop.utils': desktop_utils}):
    views_spec.loader.exec_module(views)
    spec = importlib.util.spec_from_file_location(
        'filesystem_diagnostics', ROOT / 'src/windows_mcp/filesystem/service.py')
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)


class FilesystemDiagnostics(unittest.TestCase):
    def test_copy_and_move_preserve_both_paths_and_native_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source-管理员.txt'
            target = Path(temp) / 'target.txt'
            source.write_bytes(b'benign')
            for operation, func, primitive in (
                    ('copy', service.copy_path, 'copy2'),
                    ('move', service.move_path, 'move')):
                error = PermissionError(errno.EACCES, 'native access denied', str(source))
                error.winerror = 5
                with self.subTest(operation=operation), \
                        mock.patch.object(service.shutil, primitive, side_effect=error), \
                        self.assertLogs(service.logger, level='ERROR') as logs:
                    result = func(str(source), str(target))
                for output in [result, *logs.output]:
                    for fact in (str(source), str(target), operation,
                                 'native access denied', 'PermissionError', 'winerror', '5'):
                        self.assertIn(fact, output)
                self.assertTrue(result.startswith('Error:'))
                self.assertEqual(source.read_bytes(), b'benign')
                self.assertFalse(target.exists())

    def test_sharing_conflict_keeps_distinct_native_error(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'capture.pcap'
            source.write_bytes(b'benign')
            error = OSError(errno.EACCES, 'sharing violation', str(source))
            error.winerror = 32
            with mock.patch.object(service.shutil, 'copy2', side_effect=error), \
                    self.assertLogs(service.logger, level='ERROR'):
                result = service.copy_path(str(source), str(Path(temp) / 'copy.pcap'))
            self.assertIn('sharing violation', result)
            self.assertIn('32', result)

    def test_write_denial_does_not_log_content(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'output.txt'
            error = PermissionError(errno.EACCES, 'native access denied')
            with mock.patch('builtins.open', side_effect=error), \
                    self.assertLogs(service.logger, level='ERROR') as logs:
                result = service.write_file(str(target), 'DO-NOT-LOG-CONTENT')
            for output in [result, *logs.output]:
                self.assertIn(str(target), output)
                self.assertIn('native access denied', output)
                self.assertNotIn('DO-NOT-LOG-CONTENT', output)

    def test_successful_copy_move_and_write_keep_existing_behavior(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second, third = (Path(temp) / name for name in ('one', 'two', 'three'))
            self.assertIn('Written to', service.write_file(str(first), 'benign'))
            self.assertIn('Copied file', service.copy_path(str(first), str(second)))
            self.assertIn('Moved', service.move_path(str(second), str(third)))
            self.assertEqual(third.read_bytes(), b'benign')
            self.assertTrue(first.exists())
            self.assertFalse(second.exists())


if __name__ == '__main__':
    unittest.main()
