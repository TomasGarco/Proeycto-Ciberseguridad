#!/bin/sh
# Alternativa a generate-dev-cert.sh: genera un certificado TLS para
# localhost firmado por una autoridad certificadora local (mkcert), en vez
# de un certificado autofirmado. El navegador confía en él automáticamente
# -- sin advertencia de seguridad -- porque mkcert instala esa CA en el
# almacén de confianza del sistema operativo.
#
# Requiere tener mkcert instalado (https://github.com/FiloSottile/mkcert):
#   choco install mkcert          (Windows, con Chocolatey)
#   scoop install mkcert          (Windows, con Scoop)
#   brew install mkcert           (macOS)
#   apt install mkcert            (Linux, si está en los repos)
# o descargar el binario directo desde las Releases del repo.
#
# Uso (una sola vez por máquina de desarrollo):
#   mkcert -install                                  # instala la CA local como confiable (pide admin/UAC una vez)
#   sh certs/generate-dev-cert-mkcert.sh              # genera certs/dev.crt y certs/dev.key

cd "$(dirname "$0")" || exit 1

mkcert -cert-file dev.crt -key-file dev.key localhost 127.0.0.1 ::1

echo "Certificado generado: certs/dev.crt / certs/dev.key (confiado por el sistema, sin advertencia de seguridad)"
