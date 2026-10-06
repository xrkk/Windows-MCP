"""Real WaitFor and snapshot renderer, isolated from Windows capture/transport."""
import sys
import types
import unittest
from unittest.mock import patch, MagicMock
import test_input_receipts as receipts


class WaitFinalState(unittest.TestCase):
    def setUp(self):
        receipts.InputReceipts.setUp(self)
        desktop_module = types.ModuleType('windows_mcp.desktop.service')
        desktop_module.Desktop = types.SimpleNamespace(parse_display_selection=lambda value: value)
        desktop_module.Size = lambda **kw: kw
        image_module = types.ModuleType('fastmcp.utilities.types')
        image_module.Image = MagicMock(side_effect=AssertionError('unexpected image'))
        utils = types.ModuleType('windows_mcp.desktop.utils')
        utils.remove_private_use_chars = utils.repair_surrogates = lambda text: text
        with patch.dict(sys.modules, {'windows_mcp.desktop.service': desktop_module,
                                     'fastmcp.utilities.types': image_module,
                                     'windows_mcp.desktop.utils': utils}):
            self.delivery = receipts.load('wait_state_delivery', 'src/windows_mcp/tools/state_delivery.py')
            self.helpers = receipts.load('wait_snapshot_helpers', 'src/windows_mcp/tools/_snapshot_helpers.py')

    def state(self, text):
        tree = types.SimpleNamespace(
            interactive_elements_to_string=lambda: 'button "Save" at (1,2)',
            scrollable_elements_to_string=lambda: 'pane at (5,6)',
            semantic_tree_to_string=lambda: 'No elements', semantic_tree_root=None,
            dom_informative_nodes=[types.SimpleNamespace(text=text)],
            interactive_nodes=[], scrollable_nodes=[], truncated=False, status=True)
        return types.SimpleNamespace(
            tree_state=tree, cursor_position=(1,2), screenshot_original_size=None,
            available_displays=[], screenshot_displays=None, screenshot_region=None,
            screenshot_backend=None, screenshot=None,
            windows_to_string=lambda:'Notepad', active_window_to_string=lambda:'Notepad',
            active_desktop_to_string=lambda:'Desktop 1', desktops_to_string=lambda:'Desktop 1',
            active_window=None, windows=[], active_desktop={}, all_desktops=[])

    def test_returns_exact_final_observation_without_recapture(self):
        self.desktop.get_state.side_effect=[self.state('Loading'),self.state('Ready complete text')]
        with patch.dict(sys.modules, {'windows_mcp.tools._snapshot_helpers': self.helpers, 'windows_mcp.tools.state_delivery': self.delivery}):
            out=self.registry.tools['WaitFor']('text_exists',text='Ready',interval=.001)
        self.assertEqual(self.desktop.get_state.call_count,2)
        self.assertIn('Ready complete text',out)
        self.assertIn('button "Save"',out)
        self.assertNotIn('Loading',out)
        for call in self.desktop.get_state.call_args_list:
            self.assertFalse(call.kwargs['use_vision'])

    def test_timeout_carries_last_full_state(self):
        self.desktop.get_state.return_value=self.state('Still waiting, all text')
        with patch.dict(sys.modules, {'windows_mcp.tools._snapshot_helpers': self.helpers, 'windows_mcp.tools.state_delivery': self.delivery}):
            with self.assertRaises(TimeoutError) as error:
                self.registry.tools['WaitFor']('text_exists',text='absent',timeout=.001,interval=.001)
        self.assertIn('Still waiting, all text',str(error.exception))
        self.assertIn('Final observed state',str(error.exception))
