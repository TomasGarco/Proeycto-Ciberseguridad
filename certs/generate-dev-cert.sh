#!/bin/sh
# Genera un certificado TLS autofirmado para desarrollo local.
#
# Uso:
#   docker run --rm -v "$(pwd)/certs:/certs" alpine/openssl sh /certs/generate-dev-cert.sh
#   (o desde Windows/Git Bash, ver el comando equivalente en el README)
#
# Este certificado NO sirve para producción: al ser autofirmado, el
# navegador mostrará una advertencia de seguridad la primera vez que se
# entra a https://localhost — es esperado, hay que aceptar la excepción
# una vez. Para producción real se reemplazaría por un certificado emitido
# por una autoridad certificadora (por ejemplo, Let's Encrypt).

openssl req -x509 -nodes -days 825 \
  -newkey rsa:2048 \
  -keyout /certs/dev.key \
  -out /certs/dev.crt \
  -subj "/C=CO/ST=Local/L=Local/O=SOC-SIEM-Dev/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo "Certificado generado: certs/dev.crt / certs/dev.key (validez: 825 dias)"
