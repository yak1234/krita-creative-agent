import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('diagnostics_client', ROOT / 'diagnostics_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function
        return register


class DiagnosticsClientTest(unittest.TestCase):
    def test_three_tools_against_running_companion_socket_and_offline_evidence(self):
        registry = Registry()
        client.register_diagnostic_tools(registry)
        self.assertEqual(set(registry.tools), {'creative_inspect_state', 'creative_recent_events', 'creative_collect_report'})
        with tempfile.TemporaryDirectory() as directory:
            script = """
import {LiveDiagnostics} from './src/live-diagnostics.mjs';
const runtime={config:{output:process.argv[1]},pendingTools:new Map(),redact:s=>s,mode:'ask',busy:false};
const diagnostics=new LiveDiagnostics(runtime);await diagnostics.start();
console.log('ready');process.stdin.resume();
process.stdin.on('end',async()=>{await diagnostics.close();process.exit(0);});
"""
            process = subprocess.Popen(['node', '--input-type=module', '-e', script, directory],
                                       cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                state = registry.tools['creative_inspect_state'](directory)
                self.assertEqual(state['mode'], 'ask')
                self.assertEqual(state['pid'], process.pid)
                events = registry.tools['creative_recent_events'](directory)
                self.assertEqual(events['events'][0]['type'], 'diagnostics_started')
                report = registry.tools['creative_collect_report'](directory)
                self.assertEqual(json.loads(Path(report['path']).read_text())['live']['pid'], process.pid)
                self.assertEqual(registry.tools['creative_recent_events'](directory, limit=501)['error_code'], 'invalid_arguments')
            finally:
                process.communicate(timeout=10)
            stale = registry.tools['creative_inspect_state'](directory)
            self.assertFalse(stale['live'])
            self.assertFalse(stale['previous_report_is_live'])
            self.assertTrue(Path(stale['persisted_timeline']).is_file())


if __name__ == '__main__':
    unittest.main()
