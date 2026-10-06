"""Exercise real tool registration with OS/transport edges isolated on any host.

Run: python -m unittest discover -s tests/portable -p test_input_receipts.py -v
This does not claim Windows input injection or real MCP transport acceptance.
"""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, *, name, **kwargs):
        def register(fn):
            self.tools[name] = fn
            return fn
        return register


class InputReceipts(unittest.TestCase):
    def setUp(self):
        stubs = {}
        for name in ('pywintypes', 'win32com', 'win32com.shell', 'fastmcp',
                     'mcp', 'mcp.types', 'windows_mcp.infrastructure'):
            stubs[name] = types.ModuleType(name)
        stubs['win32com.shell'].shell = MagicMock()
        stubs['fastmcp'].Context = object
        stubs['mcp.types'].ToolAnnotations = lambda **kw: kw
        stubs['windows_mcp.infrastructure'].with_analytics = lambda *a: lambda fn: fn
        with patch.dict(sys.modules, stubs):
            utils = load('receipt_utils', 'src/windows_mcp/desktop/utils.py')
            with patch.dict(sys.modules, {'windows_mcp.desktop.utils': utils}):
                self.input = load('receipt_input', 'src/windows_mcp/tools/input.py')
                self.multi = load('receipt_multi', 'src/windows_mcp/tools/multi.py')
        self.desktop = MagicMock()
        self.registry = Registry()
        for module in (self.input, self.multi):
            module.register(self.registry, get_desktop=lambda: self.desktop,
                            get_analytics=lambda: None)

    def test_type_preserves_action_but_does_not_echo(self):
        text = 'private text 😃 ' * 100
        out = self.registry.tools['Type'](text, loc=[10, 20], clear=True)
        self.desktop.type.assert_called_once_with(
            loc=[10, 20], text=text, caret_position='idle', clear=True, press_enter=False)
        self.assertIn(f'{len(text)} characters', out)
        self.assertIn('(10,20)', out)
        self.assertNotIn(text, out)
        self.assertIn('not verified', out)

    def test_empty_input_clear_is_reported(self):
        out = self.registry.tools['Type']('', loc=[1, 2], clear=True)
        self.assertIn('0 characters', out)
        self.assertIn('clear=True', out)

    def test_failed_input_does_not_claim_completion(self):
        self.desktop.type.side_effect = RuntimeError('input unavailable')
        with self.assertRaisesRegex(RuntimeError, 'input unavailable'):
            self.registry.tools['Type']('secret', loc=[1, 2])

    def test_multi_edit_reports_each_target_without_text(self):
        locs = [[1, 2, 'first secret'], [3, 4, 'second secret']]
        out = self.registry.tools['MultiEdit'](locs=locs)
        self.desktop.multi_edit.assert_called_once_with(locs)
        self.assertIn('(1,2): 12 characters', out)
        self.assertIn('(3,4): 13 characters', out)
        self.assertNotIn('secret', out)
        self.assertIn('not verified', out)

    def test_invalid_label_does_not_echo_input(self):
        with self.assertRaises(ValueError) as error:
            self.registry.tools['MultiEdit'](labels=[['bad-id', 'private input']])
        self.assertNotIn('private input', str(error.exception))
        self.desktop.multi_edit.assert_not_called()

    def test_registration_omits_scrape_and_keeps_other_modules(self):
        names = ['app', 'clipboard', 'control_status', 'display', 'filesystem',
                 'input', 'multi', 'notification', 'process', 'registry', 'shell', 'snapshot']
        package = types.ModuleType('windows_mcp.tools')
        for name in names:
            setattr(package, name, types.SimpleNamespace(register=MagicMock()))
        with patch.dict(sys.modules, {'windows_mcp.tools': package}):
            module = load('receipt_registration', 'src/windows_mcp/tools/__init__.py')
        module.register_all(Registry(), get_desktop=lambda: None, get_analytics=lambda: None)
        for name in names:
            getattr(package, name).register.assert_called_once()
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        self.assertNotIn('Scrape', [tool['name'] for tool in manifest['tools']])


if __name__ == '__main__':
    unittest.main()
