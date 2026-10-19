import importlib.util
from pathlib import Path
import unittest
path=Path(__file__).resolve().parents[2]/'krita-mcp/krita-plugin/kritamcp/native_adapter_validation.py'
spec=importlib.util.spec_from_file_location('native_adapter_validation',path)
validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(validation)
class NativeAdapterValidation(unittest.TestCase):
    def gradient(self):return dict(shape='linear',start=[0,0],end=[599,599],foreground='#001122',background='#ffeeaa',opacity=1)
    def patch(self):return dict(paths=[[[10,10],[20,20]]],diameter=30,accuracy=50,patch_radius=4)
    def test_gradient_bounds_and_degenerate_geometry_reject(self):
        for changes in [dict(end=[600,100]),dict(end=[0,0]),dict(opacity=float('nan')),dict(shape='spiral'),dict(foreground='blue'),dict(opacity=True)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):validation.validated_parameters('gradient',{**self.gradient(),**changes},600,600)
    def test_patch_limits_reject_before_layer_copy(self):
        for changes in [dict(paths=[]),dict(paths=[[[2,2]]]),dict(paths=[[[1,1],[-1,2]]]),dict(accuracy=101),dict(patch_radius=2.5),dict(diameter=0)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):validation.validated_parameters('smart_patch',{**self.patch(),**changes},600,600)
    def test_valid_native_commands_and_no_unknown_parameters(self):
        for kind,p in [('gradient',self.gradient()),('smart_patch',self.patch())]:
            self.assertEqual(validation.validated_parameters(kind,p,600,600),p)
            with self.assertRaises(ValueError):validation.validated_parameters(kind,{**p,'bypass':True},600,600)
