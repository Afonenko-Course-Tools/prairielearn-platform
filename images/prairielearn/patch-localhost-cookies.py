"""Apply a narrow, fail-closed patch to the exact pinned Community guard."""
import pathlib,re,sys

def patch(source):
    first="if (!config.cookieDomain) {"
    second="if (!config.cookieDomain.startsWith('.')) {"
    if source.count(first)!=1 or source.count(second)!=1 or source.count('cookieDomain must be set in production environments')!=1:
        raise ValueError('Pinned production cookie guard differs; review upstream before rebuilding')
    source=re.sub(r'(?m)^(\s*)if \(!config.cookieDomain\) \{',lambda m:m[1]+"const localhostHostOnly = config.cookieDomain === null && config.hostname === 'localhost';\n"+m[1]+"if (!localhostHostOnly && !config.cookieDomain) {",source)
    return source.replace(second,"if (!localhostHostOnly && !config.cookieDomain?.startsWith('.')) {")

if __name__=='__main__':
    for name in sys.argv[1:]:
        path=pathlib.Path(name);path.write_text(patch(path.read_text()))
