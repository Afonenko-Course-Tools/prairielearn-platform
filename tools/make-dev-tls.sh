#!/bin/sh
# Local CA only; no automatic installation in a system/browser trust store.
set -eu
umask 077
case "${1:-}" in /*) target=$1 ;; *) echo 'Use a fresh absolute output directory' >&2; exit 64 ;; esac
if [ -e "$target" ]; then echo 'Refusing to replace existing TLS material' >&2; exit 65; fi
mkdir -m 700 "$target"
openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 3650 \
  -keyout "$target/ca.key" -out "$target/ca.crt" \
  -subj '/CN=PrairieLearn local development CA' \
  -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' \
  -addext 'subjectKeyIdentifier=hash'
openssl req -new -newkey rsa:3072 -nodes -sha256 \
  -keyout "$target/server.key" -out "$target/server.csr" -subj '/CN=localhost'
cat > "$target/server.ext" <<'EXT'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,IP:127.0.0.1
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EXT
openssl x509 -req -in "$target/server.csr" -CA "$target/ca.crt" -CAkey "$target/ca.key" \
  -CAcreateserial -out "$target/server.crt" -days 365 -sha256 -extfile "$target/server.ext"
openssl verify -CAfile "$target/ca.crt" -purpose sslserver "$target/server.crt"
