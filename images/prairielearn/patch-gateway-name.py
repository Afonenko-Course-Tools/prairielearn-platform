"""Закрытый Unicode transport patch для обоих файлов pinned native callback."""

import pathlib
import sys

# Один canonical body. В TS добавляется только тип signature, без второй реализации.
DECODER = """function decodeGatewayVerifiedName(value) {
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
"""
NAME_READ = "    const name = req.get('x-trust-auth-name') ?? null;"
NEW_NAME_READ = """    const verifiedNameHeaders = req.rawHeaders.filter((_, index) => index % 2 === 0 && req.rawHeaders[index].toLowerCase() === 'x-trust-auth-name-utf8-b64');
    if (verifiedNameHeaders.length !== 1) throw new HttpStatusError(400, 'Некорректное подтверждённое имя Gateway');
    const name = decodeGatewayVerifiedName(req.get('x-trust-auth-name-utf8-b64'));"""


def patch(source: str, kind: str) -> str:
    if kind not in ("src", "dist"):
        raise ValueError("Unknown authCallbackShib source kind")
    marker = "const router = Router();"
    if (
        source.count(NAME_READ) != 1
        or source.count(marker) != 1
        or source.count("await authnLib.loadUser(") != 1
    ):
        raise ValueError("Pinned authCallbackShib shape differs")
    decoder = (
        DECODER
        if kind == "dist"
        else DECODER.replace(
            "function decodeGatewayVerifiedName(value)",
            "function decodeGatewayVerifiedName(value: unknown): string",
            1,
        )
    )
    return source.replace(marker, decoder + "\n" + marker, 1).replace(
        NAME_READ, NEW_NAME_READ, 1
    )


def patch_files(source_path: str | pathlib.Path, dist_path: str | pathlib.Path) -> None:
    # Оба inputs проверяются до первой записи: несовпавший dist не оставляет half-patch.
    files = [(pathlib.Path(source_path), "src"), (pathlib.Path(dist_path), "dist")]
    changed = [(path, patch(path.read_text(), kind)) for path, kind in files]
    for path, text in changed:
        path.write_text(text)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Нужны pinned src TS и dist JS callback")
    patch_files(sys.argv[1], sys.argv[2])
