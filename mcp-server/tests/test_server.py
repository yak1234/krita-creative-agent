import ast
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

import httpx

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('krita_mcp_server', ROOT / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def tool(fn):
    """FastMCP may wrap tools; call the underlying function."""
    return getattr(fn, 'fn', fn)


def reply(data, status=200):
    return httpx.Response(status, json=data, request=httpx.Request('POST', server.KRITA_URL))


class FakeBridge:
    """Records posts and answers like the plugin, including native batch results."""
    def __init__(self, handler=None):
        self.posts = []
        self.handler = handler or (lambda action, params: {'status': 'ok'})

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.posts.append({'json': json, 'headers': headers, 'timeout': timeout})
        action, params = json['action'], json['params']
        if action == 'batch':
            results = []
            for i, c in enumerate(params['commands']):
                res = self.handler(c['action'], c['params'])
                ok = not res.get('error') and res.get('status') in (None, 'ok')
                results.append({'index': i, 'action': c['action'], 'ok': ok, 'result': res})
            failures = [{'index': r['index'], 'error': r['result'].get('error')}
                        for r in results if not r['ok']]
            return reply({'status': 'partial' if failures else 'ok', 'errors': len(failures),
                          'failures': failures, 'results': results})
        return reply(self.handler(action, params))


class SendCommand(unittest.TestCase):
    def test_body_timeout_and_http_margin(self):
        bridge = FakeBridge()
        with mock.patch.object(server.httpx, 'post', bridge):
            server.send_command('stroke', {})
            server.send_command('open_file', {'path': 'x'})
        stroke, open_file = bridge.posts
        self.assertEqual(stroke['json']['timeout'], 120.0)
        self.assertEqual(stroke['timeout'].read, 140.0)
        self.assertEqual(open_file['json']['timeout'], 300.0)
        self.assertEqual(open_file['timeout'].read, 320.0)

    def test_long_running_tools(self):
        bridge = FakeBridge(lambda a, p: {'status': 'ok', 'path': '/tmp/x.png'})
        with mock.patch.object(server.httpx, 'post', bridge):
            tool(server.krita_get_canvas)()
            tool(server.krita_save)('/tmp/x.png')
            tool(server.krita_open_file)('/tmp/x.kra')
            tool(server.krita_flood_fill)(1, 1)
        self.assertEqual([p['json']['timeout'] for p in bridge.posts], [300.0] * 4)

    def test_connect_error_is_unreachable(self):
        with mock.patch.object(server.httpx, 'post', side_effect=httpx.ConnectError('refused')):
            result = server.send_command('stroke', {})
        self.assertEqual(result['error_code'], 'unreachable')

    def test_lost_reply_on_mutation_is_unknown(self):
        with mock.patch.object(server.httpx, 'post', side_effect=httpx.ReadTimeout('slow')):
            result = server.send_command('stroke', {})
        self.assertEqual(result['error_code'], 'outcome_unknown')
        self.assertIn('inspect the canvas', result['error'])

    def test_lost_reply_on_read_is_plain_error(self):
        with mock.patch.object(server.httpx, 'post', side_effect=httpx.ReadTimeout('slow')):
            result = server.send_command('get_color_at', {})
        self.assertNotIn('error_code', result)

    def test_bridge_timeout_on_mutation_is_unknown(self):
        timeout = {'error': 'Timeout waiting for command execution after 120s', 'error_code': 'timeout'}
        with mock.patch.object(server.httpx, 'post', return_value=reply(timeout, 500)):
            result = server.send_command('stroke', {})
        self.assertEqual(result['error_code'], 'outcome_unknown')

    def test_unauthorized(self):
        with mock.patch.object(server.httpx, 'post', return_value=reply({'error': 'unauthorized'}, 401)):
            result = server.send_command('stroke', {})
        self.assertEqual(result['error_code'], 'unauthorized')

    def test_token_header(self):
        bridge = FakeBridge()
        with mock.patch.object(server, 'KRITA_TOKEN', 'secret'), \
             mock.patch.object(server.httpx, 'post', bridge):
            server.send_command('stroke', {})
        self.assertEqual(bridge.posts[0]['headers'], {'Authorization': 'Bearer secret'})


class Health(unittest.TestCase):
    def check(self, **kw):
        with mock.patch.object(server.httpx, 'get', **kw):
            return tool(server.krita_health)()

    def test_ok(self):
        text = self.check(return_value=reply({'status': 'ok', 'plugin': 'kritamcp', 'version': '2.3.0'}))
        self.assertIn('kritamcp 2.3.0', text)

    def test_unreachable(self):
        self.assertIn('Cannot connect', self.check(side_effect=httpx.ConnectError('refused')))

    def test_unauthorized(self):
        self.assertIn('authorization', self.check(return_value=reply({'error': 'unauthorized'}, 401)))

    def test_non_json(self):
        bad = httpx.Response(200, text='<html>', request=httpx.Request('GET', server.KRITA_URL))
        self.assertIn('non-JSON', self.check(return_value=bad))


class Batch(unittest.TestCase):
    def run_batch(self, commands, handler=None, post=None):
        bridge = FakeBridge(handler)
        with mock.patch.object(server.httpx, 'post', post or bridge):
            return tool(server.krita_batch)(commands).splitlines(), bridge

    def test_native_actions_match_plugin(self):
        source = (ROOT / '../plugin/kritamcp/__init__.py').read_text()
        method = next(n for n in ast.walk(ast.parse(source))
                      if isinstance(n, ast.FunctionDef) and n.name == 'cmd_batch')
        table = next(n.value for n in ast.walk(method)
                     if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'handlers')
        self.assertEqual({k.value for k in table.keys}, server.NATIVE_BATCH_ACTIONS)

    def test_chunks_paint_commands(self):
        commands = [{'action': 'stroke', 'params': {'points': [[0, 0], [1, 1]]}}] * 150
        lines, bridge = self.run_batch(commands)
        self.assertEqual([p['json']['action'] for p in bridge.posts], ['batch'] * 3)
        self.assertEqual([len(p['json']['params']['commands']) for p in bridge.posts], [64, 64, 22])
        self.assertEqual(len(lines), 151)
        self.assertEqual(lines[-1], '150 commands, 0 failed, 0 unknown')

    def test_mixed_order(self):
        commands = [{'action': 'stroke'}, {'action': 'get_color_at', 'params': {'x': 1, 'y': 1}},
                    {'action': 'stroke'}]
        lines, bridge = self.run_batch(commands, lambda a, p: {'status': 'ok', 'color': '#ffffff'}
                                       if a == 'get_color_at' else {'status': 'ok'})
        self.assertEqual([p['json']['action'] for p in bridge.posts], ['batch', 'get_color_at', 'batch'])
        self.assertTrue(lines[0].startswith('0: stroke ok'))
        self.assertIn('#ffffff', lines[1])
        self.assertTrue(lines[2].startswith('2: stroke ok'))

    def test_partial_and_nested_failures(self):
        def handler(action, params):
            if action == 'paint_pixels':
                return {'status': 'partial', 'painted': 1, 'total': 2}
            return {'error': 'bad points'} if action == 'curve_stroke' else {'status': 'ok'}
        lines, _ = self.run_batch(
            [{'action': 'paint_pixels'},
             {'action': 'batch', 'params': {'commands': [{'action': 'curve_stroke', 'params': {}}]}}],
            handler)
        self.assertIn('0: paint_pixels FAILED', lines[0])
        self.assertIn('1: batch FAILED', lines[1])
        self.assertIn('bad points', lines[1])
        self.assertEqual(lines[-1], '2 commands, 2 failed, 0 unknown')

    def test_unknown_action_continues(self):
        def handler(action, params):
            return {'error': "unknown action 'nope'"} if action == 'nope' else {'status': 'ok'}
        lines, _ = self.run_batch([{'action': 'nope'}, {'action': 'stroke'}], handler)
        self.assertIn('0: nope FAILED', lines[0])
        self.assertIn('1: stroke ok', lines[1])

    def test_chunk_timeout_marks_every_command_unknown(self):
        commands = [{'action': 'stroke'}] * 3
        lines, _ = self.run_batch(commands, post=mock.Mock(side_effect=httpx.ReadTimeout('slow')))
        self.assertTrue(all('UNKNOWN-OUTCOME' in line for line in lines[:3]))
        self.assertEqual(lines[-1], '3 commands, 0 failed, 3 unknown')

    def test_diagnostics_not_truncated(self):
        long = {'status': 'ok', 'canvas_path': '/tmp/' + 'x' * 200 + '.png'}
        lines, _ = self.run_batch([{'action': 'compare_region'}], lambda a, p: long)
        self.assertIn(long['canvas_path'], lines[0])


if __name__ == '__main__':
    unittest.main()
