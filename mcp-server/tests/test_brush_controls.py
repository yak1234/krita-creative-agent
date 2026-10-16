import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'..'/'plugin'/'kritamcp'))
from brush_controls import control_changes, CONTROL_MAP
class BrushControlsTests(unittest.TestCase):
    def setUp(self):
        self.props={p for pair in CONTROL_MAP.values() for p in pair if p}
    def test_constant_pigment_keeps_deposition_enabled(self):
        out=control_changes({'pigment':.85,'pigment_dynamics':False}, self.props)
        self.assertIs(out['PressureColorRate'],True)
        self.assertIs(out['ColorRateUseCurve'],False)
    def test_zero_blend_keeps_engine_option_enabled(self):
        self.assertEqual(control_changes({'blend':0},self.props),{'SmudgeRateValue':0,'PressureSmudgeRate':True})
    def test_bad_values_and_unsupported_controls(self):
        for value in [True,-1,2,float('nan'),'0.5']:
            with self.assertRaises(ValueError): control_changes({'pigment':value},self.props)
        with self.assertRaises(ValueError): control_changes({'pigment':.5},set())
        with self.assertRaises(ValueError): control_changes({'pigment_dynamics':1},self.props)
        with self.assertRaises(ValueError): control_changes({'unknown':.5},self.props)
    def test_new_commands_are_exposed_over_http(self):
        import ast
        tree=ast.parse((Path(__file__).resolve().parents[1]/'../plugin/kritamcp/__init__.py').read_text())
        allowed=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ALL_COMMANDS' for t in n.targets))
        self.assertTrue({'brush_controls','brush_probe','selection','curve_stroke','compare_region','duplicate_document','layer_settings','duplicate_layer','move_layer','modify_selection'} <= set(allowed))
