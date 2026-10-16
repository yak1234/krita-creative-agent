import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / 'plugin/kritamcp/creative_tools.py'
tree = ast.parse(SOURCE.read_text())
helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'merge_pass_record_error')
namespace = {}
exec(compile(ast.Module(body=[helper], type_ignores=[]), str(SOURCE), 'exec'), namespace)
merge = namespace['merge_pass_record_error']


class PassRecordError(unittest.TestCase):
    def test_original_error_is_kept(self):
        result = {'status': 'partial', 'error': 'Smart Patch needs a source paint layer', 'error_code': 'partial_change'}
        merged = merge(result, ValueError('That layer is no longer in this painting.'))
        self.assertTrue(merged['error'].startswith('Smart Patch needs a source paint layer'))
        self.assertIn('Pass record could not be saved', merged['error'])
        self.assertEqual(merged['error_code'], 'partial_change')

    def test_record_failure_alone(self):
        merged = merge({'status': 'ok'}, OSError('disk full'))
        self.assertEqual(merged, {'status': 'partial', 'error_code': 'partial_change', 'error': 'Pass record could not be saved: disk full'})

    def test_removed_contribution_is_not_recorded(self):
        source = SOURCE.read_text()
        self.assertIn("result.pop('layer_id', None); result.pop('group_id', None)", source)
        self.assertIn("if result.get('contribution_removed'): layer_id = None", source)


if __name__ == '__main__':
    unittest.main()
