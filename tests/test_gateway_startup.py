import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


class GatewayStartup(unittest.TestCase):
    def test_invalid_native_config_rejected_before_native_init(self):
        repository = pathlib.Path(__file__).parents[1]
        for environment, config in [
            ('production', {'devMode': True, 'hasShib': True}),
            ('production', {'devMode': False, 'hasShib': False}),
            ('development', {'devMode': False, 'hasShib': True}),
        ]:
            with self.subTest(environment=environment, config=config), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                scripts = root / 'scripts'
                compiled = root / 'apps/prairielearn/dist/lib'
                scripts.mkdir()
                compiled.mkdir(parents=True)
                shutil.copytree(repository / 'bridge', root / 'apps/prairielearn/bridge')
                (root / 'package.json').write_text('{"type":"module"}')
                (root / 'config.json').write_text(json.dumps(config))
                (compiled / 'config.js').write_text('import {readFile} from "node:fs/promises"; export const config={}; export async function loadConfig(paths){Object.assign(config,JSON.parse(await readFile(paths[0],"utf8")));}')
                marker = root / 'native-started'
                init = scripts / 'init.sh'
                init.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
                init.chmod(0o755)
                result = subprocess.run(['bash', str(repository / 'images/prairielearn/start-bridge.sh')], env={**os.environ, 'PL_ROOT': str(root), 'NODE_ENV': environment}, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists(), 'Native initialization ran before strict authentication preflight')
                self.assertIn('Gateway bridge requires production', result.stderr)


if __name__ == '__main__':
    unittest.main()
