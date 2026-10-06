"""Failure and cleanup boundaries; no real input injection."""
import unittest
from test_input_receipts import load

batch = load('tested_batch', 'src/windows_mcp/desktop/batch.py')


class BatchProgress(unittest.TestCase):
    def test_action_failure_stops_and_does_not_echo_text(self):
        calls = []
        def action(item):
            calls.append(item)
            if item == 'secret':
                raise RuntimeError('secret')
        with self.assertRaises(RuntimeError) as caught:
            batch.run_batch(['first', 'secret', 'last'], checkpoint=lambda: None, action=action)
        self.assertEqual(calls, ['first', 'secret'])
        p = caught.exception.batch_progress
        self.assertEqual(p['completed'], [0])
        self.assertEqual(p['uncertain'], [1])
        self.assertEqual(p['unexecuted'], [2])
        self.assertNotIn('secret', str(caught.exception))

    def test_checkpoint_failure_retains_ownership_type_and_status(self):
        class Blocked(RuntimeError):
            code = 'CONTROL_PREEMPTED'
            status = {'state': 'user'}
        calls = []
        def checkpoint():
            if calls:
                raise Blocked('blocked')
        with self.assertRaises(Blocked) as caught:
            batch.run_batch([1, 2, 3], checkpoint=checkpoint, action=calls.append)
        p = caught.exception.status['batch_progress']
        self.assertEqual(caught.exception.code, 'CONTROL_PREEMPTED')
        self.assertEqual(p['completed'], [0])
        self.assertEqual(p['failed_before_action'], [1])
        self.assertEqual(p['uncertain'], [])
        self.assertEqual(p['unexecuted'], [1, 2])

    def test_cleanup_failure_preserves_primary_error_and_partial_progress(self):
        def action(item):
            raise ValueError('input may have been injected')
        def cleanup():
            raise RuntimeError('release failed')
        with self.assertRaises(ValueError) as caught:
            batch.run_batch([1, 2], checkpoint=lambda: None, action=action, cleanup=cleanup)
        self.assertEqual(caught.exception.batch_progress['cleanup_error'], 'RuntimeError')
        self.assertEqual(caught.exception.batch_progress['uncertain'], [0])

    def test_cleanup_only_failure_keeps_all_completed(self):
        def cleanup():
            raise RuntimeError('release failed')
        with self.assertRaises(RuntimeError) as caught:
            batch.run_batch([1, 2], checkpoint=lambda: None, action=lambda item: None,
                            cleanup=cleanup)
        p = caught.exception.batch_progress
        self.assertEqual(p['completed'], [0, 1])
        self.assertEqual(p['unexecuted'], [])
        self.assertEqual(p['phase'], 'cleanup')

    def test_setup_failure_runs_cleanup_without_actions(self):
        calls = []
        def setup():
            raise RuntimeError('key down failure')
        with self.assertRaises(RuntimeError) as caught:
            batch.run_batch([1, 2], checkpoint=lambda: None, action=calls.append,
                            setup=setup, cleanup=lambda: calls.append('cleanup'))
        self.assertEqual(calls, ['cleanup'])
        self.assertEqual(caught.exception.batch_progress['unexecuted'], [0, 1])
