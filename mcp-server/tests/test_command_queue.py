import importlib.util
from pathlib import Path
import threading
import unittest
spec = importlib.util.spec_from_file_location('command_queue', Path(__file__).parents[1] / '../plugin/kritamcp/command_queue.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class CommandQueueTimeouts(unittest.TestCase):
    def test_result_returned(self):
        q = m.CommandQueue()
        q.push(1, {'action': 'stroke'})
        self.assertEqual(q.pop()[0], 1)
        q.set_result(1, {'status': 'ok'})
        self.assertEqual(q.get_result(1, timeout=0.2), {'status': 'ok'})

    def test_queued_command_removed_on_timeout(self):
        q = m.CommandQueue()
        q.push(1, {'action': 'stroke'})
        q.push(2, {'action': 'fill'})
        result = q.get_result(1, timeout=0.1)
        self.assertEqual(result['error_code'], 'timeout')
        self.assertIn('Timeout waiting for command', result['error'])
        self.assertFalse(result['started'])
        # The timed-out command never reaches the main thread; later work does.
        self.assertEqual(q.pop()[0], 2)
        self.assertIsNone(q.pop())
        self.assertEqual(q.abandoned, set())

    def test_inflight_result_discarded(self):
        q = m.CommandQueue()
        q.push(1, {'action': 'stroke'})
        q.pop()  # main thread started it
        result = q.get_result(1, timeout=0.1)
        self.assertTrue(result['started'])
        q.set_result(1, {'status': 'ok'})
        self.assertEqual(q.results, {})
        self.assertEqual(q.abandoned, set())

    def test_result_from_other_thread(self):
        q = m.CommandQueue()
        q.push(1, {'action': 'stroke'})
        def main_thread():
            cid, _ = q.pop()
            q.set_result(cid, {'status': 'ok'})
        threading.Timer(0.05, main_thread).start()
        self.assertEqual(q.get_result(1, timeout=2), {'status': 'ok'})

if __name__ == '__main__':
    unittest.main()
