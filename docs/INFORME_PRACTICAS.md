# Informe de Prácticas — Plataforma SOC/SIEM con Microservicios

## Introducción

Este documento recoge lo que aprendí durante el desarrollo de este proyecto: una plataforma tipo SOC/SIEM construida con microservicios en Docker. La idea era simular un sistema real de monitoreo de seguridad — algo que recibe eventos, los analiza, detecta comportamientos sospechosos y genera alertas — y para lograrlo tuve que ir aprendiendo herramientas y conceptos sobre la marcha, muchas veces resolviendo problemas concretos que me iban apareciendo.

## Docker y Docker Compose

Lo primero que aprendí a fondo fue Docker. Antes de este proyecto lo había usado de forma superficial, pero acá entendí para qué sirve realmente: empaquetar cada servicio con todo lo que necesita (su lenguaje, sus librerías, su configuración) para que corra igual en cualquier máquina, sin el clásico problema de "en mi computadora sí funciona".

Docker Desktop terminó siendo mi herramienta principal de trabajo diario. La uso para ver de un vistazo qué contenedores están corriendo, revisar logs sin tener que escribir comandos, entrar a la terminal de un contenedor si algo falla, y reiniciar servicios individuales sin tumbar todo el stack. Es la diferencia entre depurar a ciegas por consola y tener una vista clara de todo el sistema.

De ahí pasé a Docker Compose, que es lo que me permite levantar los 9 contenedores del proyecto con un solo comando en vez de arrancar cada uno a mano. El comando que más uso es:

```
docker compose up -d --build
```

Y ahí aprendí qué hace cada parte:
- **`-d`** significa *detached*, "en segundo plano". Sin esta bandera, la terminal se queda pegada mostrando los logs de todos los contenedores y no puedo seguir usándola. Con `-d`, Docker levanta todo y me devuelve el control de la terminal, mientras los contenedores siguen corriendo por su cuenta administrados por Docker Desktop.
- **`--build`** le dice a Docker que reconstruya las imágenes antes de levantar los contenedores. Esto es necesario porque cada servicio copia su código en tiempo de build (no uso volúmenes montados para el código fuente), así que si edito algo y no reconstruyo, el contenedor sigue corriendo la versión vieja.

También aprendí el resto del ciclo de vida: `docker compose down` para detener y eliminar los contenedores, `docker compose logs -f <servicio>` para seguir los logs de uno en particular, y `docker compose build <servicio>` para reconstruir solo uno sin tocar los demás.

## La arquitectura: 5 microservicios, 9 contenedores

Uno de los aprendizajes centrales fue entender qué es un microservicio y por qué separar la lógica en piezas independientes en vez de hacer un solo programa gigante. Terminé con 5 servicios de aplicación, cada uno responsable de una sola cosa, más 4 piezas de infraestructura (bases de datos, cola de mensajes y caché), todo orquestado desde un único `docker-compose.yml`:

- **Auth Service** — el que maneja usuarios: registro, login, roles (`admin` / `analista`) y emisión de tokens JWT. Es la puerta de entrada del sistema.
- **Log Service** — recibe y guarda los eventos que genera el resto del sistema (por ejemplo, un login fallido). Los almacena en MongoDB.
- **Analysis Service** — el "cerebro" de detección: revisa los eventos que llegan y aplica reglas (por umbral, por patrón, por palabra clave) para decidir si algo es sospechoso. Si detecta algo, genera una alerta. Las reglas se pueden activar y desactivar en caliente desde el dashboard (solo el rol admin), sin reiniciar nada.
- **Alert Service** — recibe las alertas que genera Analysis y las gestiona: las guarda, les da un ciclo de vida (nueva → reconocida → cerrada) y expone la API para que el dashboard las muestre.
- **Dashboard Service** — la interfaz en React donde se ve todo: logs, alertas activas y métricas del sistema.

Y por debajo, la infraestructura que los conecta: **PostgreSQL** (usuarios e items), **MongoDB** (logs), **RabbitMQ** (mensajería entre Log→Analysis y Analysis→Alert, para que un servicio caído no tumbe a los demás) y **Redis** (caché de estadísticas, para que no se pierdan si el contenedor se reinicia, y almacén de las sesiones activas). Todo vive en el mismo repositorio, cada servicio en su propia carpeta con su propio `Dockerfile`.

## JWT — cómo protegí la autenticación

Aprendí en profundidad cómo funciona JWT (JSON Web Token) porque es el mecanismo que uso para que un usuario, después de hacer login, pueda acceder a los endpoints protegidos sin tener que volver a mandar su contraseña en cada petición.

El flujo que implementé es: el usuario manda usuario/contraseña a `/auth/login`, el Auth Service verifica la contraseña (guardada con hash, nunca en texto plano) y si es correcta genera un token firmado con `HS256` que incluye el usuario, su rol y una fecha de expiración (`exp`). Ese token se firma con una clave secreta (`JWT_SECRET_KEY`) que definí como variable de entorno — y aprendí que esa clave tiene que ser la misma en todos los servicios que necesiten verificar el token: Auth Service la usa para firmar, y Alert, Log y Analysis Service la usan para verificar los tokens antes de dejar pasar la petición (por ejemplo, Alert Service comprueba el rol `admin` antes de permitir cerrar una alerta).

De ahí entendí varias cosas importantes:
- El secreto de ejemplo que trae el repo (`changeme-super-secret-key...`) es solo para desarrollo; para algo real hay que generar uno propio de 256 bits y no subirlo nunca a Git.
- Si un usuario cambia de contraseña, los tokens viejos deberían dejar de servir — así que agregué una verificación para revocar los tokens emitidos antes del último cambio de contraseña.
- Los roles (`admin` / `analista`) viajan dentro del token, así que cada endpoint protegido puede decidir quién entra según el rol, sin tener que consultar la base de datos en cada petición.
- Un JWT puro tiene una limitación que descubrí en la práctica: una vez emitido, vale hasta que expira — no hay forma de "apagarlo". Por eso sumé Redis como **manejo de sesiones**: cada login registra una sesión con la misma vida del token, y cerrar sesión la borra del servidor, con lo que ese token deja de aceptarse al instante. De paso, un admin puede ver las sesiones activas y expulsar una sospechosa sin esperar a que expire.

## Configuración: `.env` y `.env.example`

Aprendí la importancia de separar configuración de código. Todas las variables sensibles (usuarios y contraseñas de las bases de datos, la clave JWT, los orígenes permitidos por CORS) viven en un archivo `.env` que **no se sube al repositorio** — está listado en `.gitignore` justamente por eso. En su lugar, subo un `.env.example` con la misma estructura pero con valores de ejemplo, para que cualquiera que clone el repo sepa qué variables necesita definir antes de levantar el stack.

## Certificados y HTTPS

Otro aprendizaje fue por qué un dashboard "real" no debería servir solo por HTTP. Agregué HTTPS al dashboard generando un certificado de desarrollo con OpenSSL (`certs/generate-dev-cert.sh`), y después aprendí que existe una alternativa mejor con `mkcert`: en vez de un certificado autofirmado que el navegador marca como no confiable, `mkcert` crea una autoridad certificadora local que el propio sistema operativo confía, así que el navegador no muestra ninguna advertencia. Los certificados generados (`.crt` y `.key`) no se versionan — están en `.gitignore` porque un certificado es específico de cada máquina de desarrollo, no algo que deba compartirse por Git; lo que sí se versiona son los scripts de `certs/` que permiten generarlos en cualquier máquina.

## `run_local.bat`, `test_crud.py` y `data/`

- **`run_local.bat`**: un script batch para levantar Auth Service y Log Service directamente con Python (sin Docker), cada uno en su propia ventana de consola. Lo aprendí como alternativa rápida para cuando quiero probar algo puntual sin esperar a que se reconstruyan imágenes.
- **`test_crud.py`**: un script de pruebas end-to-end que ejercita el CRUD de items contra la API real, incluyendo el flujo de autenticación (login → token → petición protegida). Tuve que adaptarlo cuando protegí el CRUD con JWT, porque antes probaba los endpoints sin token y dejaron de funcionar.
- **`data/`**: la carpeta donde caen las bases de datos SQLite (`items.db`) cuando el servicio corre sin PostgreSQL disponible — aprendí a diseñar ese *fallback* para poder seguir desarrollando localmente aunque Docker no esté levantado. Tampoco se versiona, porque son datos, no código.

## Backups

Aprendí que un sistema que guarda datos importantes necesita una estrategia de respaldo, no solo confiar en que el contenedor nunca se caiga. Armé un script de backup que, con el stack levantado, saca un volcado de las tres bases PostgreSQL (`auth_db`, `items_db`, `alerts_db`) más un archivo de la base MongoDB (`logs_db`), todo organizado por fecha y hora dentro de `backups/`. Después lo automaticé con una Tarea Programada de Windows para que corra solo, todos los días a las 3 AM, sin que yo tenga que acordarme de hacerlo a mano.

## Conclusiones personales

Este proyecto me sirvió para dejar de ver Docker, JWT o las colas de mensajes como conceptos sueltos de tutorial y entenderlos aplicados a un problema con sentido: un sistema que efectivamente detecta cosas (como varios logins fallidos seguidos) y reacciona generando una alerta visible en un dashboard. El reto más grande no fue escribir código nuevo, sino conectar piezas que ya funcionaban por separado y descubrir los detalles que solo aparecen cuando todo corre junto — por ejemplo, un bug donde un evento de auditoría nunca llegaba a registrarse porque estaba programado con una tarea en segundo plano que FastAPI descartaba al lanzar una excepción, y que tuve que corregir para que la regla de fuerza bruta realmente disparara.

Terminé el proyecto con una arquitectura completa y funcional, pero sobre todo con una idea mucho más clara de cómo se construye un sistema en producción: separar responsabilidades, no versionar secretos, documentar cada pieza y automatizar lo que se pueda (builds, backups, pruebas) para no depender de la memoria.
