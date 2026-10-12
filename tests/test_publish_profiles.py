import importlib.util
from pathlib import Path
import unittest

class PublishProfiles(unittest.TestCase):
    def test_each_runtime_uses_its_own_verified_image(self):
        path=Path(__file__).parents[1]/'tools/publish-receipt.py'
        self.assertTrue(path.exists(),'publisher receipt implementation missing')
        spec=importlib.util.spec_from_file_location('receipt',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        images={'java':'ghcr.io/example/java25-grader@sha256:'+'1'*64,'fish':'ghcr.io/example/fish-git-grader@sha256:'+'2'*64,'community':'ghcr.io/example/prairielearn-community-gateway@sha256:'+'3'*64}
        registry={'profiles':{'java25-junit-v1':{},'java25-mutation-v1':{},'fish-git-v1':{}}}
        actual=m.assign_images(registry,images)
        self.assertEqual(actual['profiles']['fish-git-v1']['image'],images['fish'])
        self.assertEqual(actual['profiles']['java25-mutation-v1']['image'],images['java'])
        with self.assertRaises(ValueError):m.assign_images(registry,{**images,'fish':images['java']})
        with self.assertRaises(ValueError):m.assign_images({'profiles':{'unknown':{}}},images)
