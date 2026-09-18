# SECURITY

## Lo que el sistema NO hace

- No hay keylogger, ni grabación de pantalla, ni captura de historial de navegación, ni escucha de teclado.
- Solo captura lo que tú disparas: guardar nota, `Ctrl+Alt+S`, botón de la extensión, `sergio-brain capture`.
- No almacena contraseñas, tokens, API keys, cookies, claves privadas ni credenciales.

## Secretos

`security.py` detecta (regex + entropía): claves Anthropic/OpenAI/AWS/GitHub/Slack/Google, JWT, bearer, asignaciones
`password= / api_key: / token=`, cookies, connection strings con credenciales, claves privadas PEM, tarjetas (Luhn),
tokens de alta entropía. El texto se **redacta antes** de: guardarlo en chunks/versiones, escribir capturas, loggear
(formatter redactor) o enviarlo a cualquier LLM. `audit` solo reporta tipos y conteos, nunca el contenido.
`documents.secret_hits` te dice qué notas contenían algo sospechoso para que lo muevas a un gestor de contraseñas.

## Privacidad por nota

`privacy: SENSITIVE` (o tag `#sensitive`) → indexada localmente, **nunca** enviada a un proveedor cloud
(`Engine.llm_allowed_for`). `do_not_index` / carpetas en `do_not_process_folders` → ni se lee.
En `LOCAL_ONLY` ningún byte sale de tu máquina.

## Red

La API escucha solo en `127.0.0.1`. CORS restringido a Obsidian, extensiones y localhost. Token opcional (`server.token`).
Las llamadas externas son únicamente a la API del proveedor que configures.

## Datos en disco

`%APPDATA%\SergioBrain\data\`: `sergio_brain.sqlite` (índice, texto redactado), `logs\`, `backups\`. Todo es tuyo,
borrable y regenerable desde Markdown. Los backups incluyen la bóveda completa (protégelos como a la bóveda).
