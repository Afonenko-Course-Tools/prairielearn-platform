"""Закрытый Unicode transport patch для обоих файлов pinned native callback."""
import hashlib
import pathlib
import sys

BASE_HASHES = {
    'src': '4f5154c0fd1b96ba99e29347a5d7c2caf42a7c63fd58dc761f6ec02a5789f3ff',
    'dist': '1c05cc1ac3e011cacc61de35fe9940ab7c03b3e60f32ef16b443f360b7beb6e4',
}
# Один canonical body. В TS добавляется только тип signature, без второй реализации.
DECODER = '''function decodeGatewayVerifiedName(value) {
  const invalid = () => new HttpStatusError(400, 'Некорректное подтверждённое имя Gateway');
  if (typeof value !== 'string' || value.length > 1369 || !/^v1\\.[A-Za-z0-9_-]*$/.test(value)) throw invalid();
  const payload = value.slice(3);
  if (payload.length % 4 === 1) throw invalid();
  const bytes = Buffer.from(payload, 'base64url');
  if (bytes.length > 1024 || bytes.toString('base64url') !== payload) throw invalid();
  let name;
  try { name = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes); }
  catch { throw invalid(); }
  if ([...name].length > 256 || [...name].some(c => c.charCodeAt(0) < 32)) throw invalid();
  return name;
}
'''
NAME_READ = "    const name = req.get('x-trust-auth-name') ?? null;"
NEW_NAME_READ = '''    const verifiedNameHeaders = req.rawHeaders.filter((_, index) => index % 2 === 0 && req.rawHeaders[index].toLowerCase() === 'x-trust-auth-name-utf8-b64');
    if (verifiedNameHeaders.length !== 1) throw new HttpStatusError(400, 'Некорректное подтверждённое имя Gateway');
    const name = decodeGatewayVerifiedName(req.get('x-trust-auth-name-utf8-b64'));'''


def patch(source, kind):
    if kind not in BASE_HASHES or hashlib.sha256(source.encode('utf-8')).hexdigest() != BASE_HASHES[kind]:
        raise ValueError('Pinned authCallbackShib fingerprint differs; review upstream before rebuilding')
    marker = 'const router = Router();'
    if source.count(NAME_READ) != 1 or source.count(marker) != 1 or source.count('await authnLib.loadUser(') != 1:
        raise ValueError('Pinned authCallbackShib shape differs')
    decoder = DECODER if kind == 'dist' else DECODER.replace('function decodeGatewayVerifiedName(value)', 'function decodeGatewayVerifiedName(value: unknown): string', 1)
    return source.replace(marker, decoder + '\n' + marker, 1).replace(NAME_READ, NEW_NAME_READ, 1)


def patch_files(source_path, dist_path):
    # Оба inputs проверяются до первой записи: несовпавший dist не оставляет half-patch.
    files = [(pathlib.Path(source_path), 'src'), (pathlib.Path(dist_path), 'dist')]
    changed = [(path, patch(path.read_text(), kind)) for path, kind in files]
    for path, text in changed:
        path.write_text(text)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Нужны pinned src TS и dist JS callback')
    patch_files(*sys.argv[1:])
