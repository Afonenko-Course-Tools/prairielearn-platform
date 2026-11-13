import importlib.util
import pathlib
import unittest


class Patch(unittest.TestCase):
    def test_pinned_body_is_wrapped_and_memory_is_bounded(self):
        root = pathlib.Path(__file__).parents[2]
        spec = importlib.util.spec_from_file_location(
            "patch", root / "images/prairielearn/patch-local-grader.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for suffix in ["ts", "js"]:
            source = (
                root
                / f"tests/fixtures/native-grader-upstream/externalGraderLocal.{suffix}"
            ).read_text()
            result = module.patch(source)
            self.assertIn("await acquireLocalGrader()", result)
            self.assertIn("finally", result)
            self.assertIn("Memory: 512 * 1024 * 1024", result)
            self.assertIn("MemorySwap: 512 * 1024 * 1024", result)
            with self.assertRaises(ValueError):
                module.patch(result)
            with self.assertRaises(ValueError):
                module.patch(
                    source.replace(
                        "const container = await docker.createContainer({",
                        "const changed = await docker.createContainer({",
                    )
                )
        with self.assertRaises(ValueError):
            module.patch("changed source")


if __name__ == "__main__":
    unittest.main()
