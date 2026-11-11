import importlib.util
from pathlib import Path
import unittest
import sys
from typing import Protocol, runtime_checkable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from publication_types import ImageReferences, PublishedRegistry


@runtime_checkable
class Publisher(Protocol):
    def assign_images(self, registry: object, images: ImageReferences) -> PublishedRegistry: ...

class PublishProfiles(unittest.TestCase):
    def test_each_runtime_uses_its_own_verified_image(self) -> None:
        path=Path(__file__).parents[1]/'tools/publish-metadata.py'
        self.assertTrue(path.exists(),'publisher receipt implementation missing')
        spec=importlib.util.spec_from_file_location('receipt',path)
        if spec is None or spec.loader is None:
            self.fail('Загрузчик publisher недоступен')
        m=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        if not isinstance(m, Publisher):
            self.fail('Контракт publisher недоступен')
        images: ImageReferences = {'java':'ghcr.io/example/java25-grader@sha256:'+'1'*64,'fish':'ghcr.io/example/fish-git-grader@sha256:'+'2'*64,'community':'ghcr.io/example/prairielearn-community-gateway@sha256:'+'3'*64}
        registry: dict[str, object] = {'profiles':{'java25-junit-v1':{},'java25-mutation-v1':{},'java25-gradle-junit-v1':{},'fish-git-v1':{}}}
        actual=m.assign_images(registry,images)
        self.assertEqual(actual['profiles']['fish-git-v1']['image'],images['fish'])
        self.assertEqual(actual['profiles']['java25-mutation-v1']['image'],images['java'])
        self.assertEqual(actual['profiles']['java25-gradle-junit-v1']['image'],images['java'])
        with self.assertRaises(ValueError):m.assign_images(registry,{**images,'fish':images['java']})
        with self.assertRaises(ValueError):m.assign_images({'profiles':{'unknown':{}}},images)
