"""The MCP's creative_test_* tools against a running test driver socket (a fake test companion behind it). Files go
to a temporary folder that is removed."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('test_driver_client', ROOT / 'test_driver_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)

FAKE_DRIVER = """
import {serveDriver} from './src/test-driver-server.ts';
const state={chat_id:'chat-1',busy:false,moves:[{number:1,status:'ready'}],canvas:'/c.png',copy:null,errors:[]};
const driver=await serveDriver({directory:process.argv[1],endpoint:process.argv[2],canvas:()=>({width:100,height:100}),make:()=>({
  start:async o=>({copy:null,krita:'Krita: a new painting will be created by the test chat'}),prompt(){},move(){},protect:async n=>({status:'ok',kept:1,name:n}),
  waitIdle:async()=>state,state:()=>state,toolCalls:()=>[{tool:'split_by_color',args:{source:'visible'}}],end:async()=>({krita:'Krita: nothing to close'})})});
console.log('ready');process.stdin.resume();process.stdin.on('end',async()=>{await driver.close();process.exit(0);});
"""


class Registry:
    def __init__(self): self.tools = {}
    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function
        return register


class TestDriverClientTest(unittest.TestCase):
    def test_the_tools_drive_a_test_chat_through_the_driver(self):
        registry = Registry()
        client.register_test_tools(registry)
        self.assertEqual(set(registry.tools), {'creative_test_start', 'creative_test_prompt', 'creative_test_move',
                                               'creative_test_state', 'creative_test_end', 'creative_test_protect'})
        with tempfile.TemporaryDirectory() as directory:
            endpoint = os.path.join(directory, 'test-driver.json')
            process = subprocess.Popen(['node', '--input-type=module', '-e', FAKE_DRIVER, directory, endpoint], cwd=ROOT,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            previous = os.environ.get('TEST_DRIVER_ENDPOINT')
            os.environ['TEST_DRIVER_ENDPOINT'] = endpoint
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                started = registry.tools['creative_test_start']('Paint Starry Night.', width=1200, height=950)
                self.assertEqual(started['status'], 'ok')
                self.assertIn('new painting', started['krita'])
                self.assertEqual(registry.tools['creative_test_prompt']('Swirl the sky more.'), {'status': 'ok'})
                self.assertEqual(registry.tools['creative_test_move']('keep'), {'status': 'ok'})
                self.assertIn('error', registry.tools['creative_test_move']('delete'))
                self.assertEqual(registry.tools['creative_test_protect']('Moon'), {'status': 'ok', 'kept': 1, 'name': 'Moon'})
                state = registry.tools['creative_test_state'](wait_seconds=5)
                self.assertEqual(state['tool_calls'], [{'tool': 'split_by_color', 'methods': ['split']}])
                self.assertIn('error', registry.tools['creative_test_state'](wait_seconds=600))
                self.assertIn('nothing to close', registry.tools['creative_test_end']()['krita'])
            finally:
                if previous is None:
                    os.environ.pop('TEST_DRIVER_ENDPOINT', None)
                else:
                    os.environ['TEST_DRIVER_ENDPOINT'] = previous
                process.communicate(timeout=10)


class TargetTests(unittest.TestCase):
    """KRITA_CREATIVE_CONFIG points the test tools at another Krita's panel config (the fork's, on its own port); its
    driver gets its own endpoint, so a stock driver already running is never reused for the fork."""
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.saved = {name: os.environ.get(name) for name in ('KRITA_CREATIVE_CONFIG', 'TEST_DRIVER_ENDPOINT')}
        self.addCleanup(self.restore)
        os.environ.pop('TEST_DRIVER_ENDPOINT', None)

    def restore(self):
        for name, value in self.saved.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value

    def config(self, port):
        path = self.root / ('config-%d.json' % port)
        path.write_text(json.dumps({'project_root': str(self.root / 'Art'), 'bridge_url': 'http://127.0.0.1:%d' % port}))
        return path

    def test_stock_config_is_the_default(self):
        os.environ.pop('KRITA_CREATIVE_CONFIG', None)
        self.assertEqual(client.panel_config(), Path.home() / 'Library/Application Support/krita/pykrita/kritamcp/creative-agent-config.json')

    def test_another_kritas_config_gets_its_own_endpoint(self):
        os.environ['KRITA_CREATIVE_CONFIG'] = str(self.config(5679))
        self.assertEqual(client.panel_config(), self.root / 'config-5679.json')
        self.assertEqual(client._endpoint_path(), self.root / 'Art/benchmark-runs/test-driver-5679.json')
        os.environ['KRITA_CREATIVE_CONFIG'] = str(self.config(5678))
        self.assertEqual(client._endpoint_path(), self.root / 'Art/benchmark-runs/test-driver.json')

    def test_the_driver_is_started_with_the_same_config_and_endpoint(self):
        os.environ['KRITA_CREATIVE_CONFIG'] = str(self.config(5679))
        environment = client._driver_environment(self.root / 'Art/benchmark-runs/test-driver-5679.json')
        self.assertEqual(environment['KRITA_CREATIVE_CONFIG'], str(self.root / 'config-5679.json'))
        self.assertEqual(environment['TEST_DRIVER_ENDPOINT'], str(self.root / 'Art/benchmark-runs/test-driver-5679.json'))


if __name__ == '__main__':
    unittest.main()
