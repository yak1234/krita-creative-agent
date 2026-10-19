import importlib.util
import os
import pathlib
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('build_release', pathlib.Path(__file__).resolve().parents[1] / 'scripts/build-release.py')
build_release = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(build_release)


class PruneBuildsTests(unittest.TestCase):
    def test_keeps_the_new_build_and_the_newest_others_only(self):
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            for index, name in enumerate(['old-1', 'old-2', 'previous', 'new']):
                (root / name).mkdir(); (root / name / 'release-manifest.json').write_text('{}')
                os.utime(root / name, (1000 + index, 1000 + index))
            os.utime(root / 'new', (10, 10))          # even if older on disk, the new build is kept
            (root / 'notes').mkdir()                   # not a release bundle: never touched
            removed = build_release.prune_builds(root / 'new', keep=2)
            self.assertEqual(sorted(removed), ['old-1', 'old-2'])
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['new', 'notes', 'previous'])


if __name__ == '__main__':
    unittest.main()
