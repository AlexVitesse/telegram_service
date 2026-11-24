# Changelog — telegram_service (VPS)

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Una entrada por día de despliegue,
con los commits de `main`. Lo más reciente, arriba.

## 2026-11-24 — `950d03d..f606570` (en producción)

### Agregado
- Bot: `/modo auto`, `/modo pregunta` y `/sensores`, como el Manual alarma 3.0; siguen `/auto`, `/preguntar` y
  `/sensors` (`4f10edf`).
- Aviso al dueño cuando la central rechaza un módulo por el tope de 5 vinculados (`cmd_ack` con `motivo: "tope"`)
  (`d77a7b8`).
- KB de Senti: instalar la app, vincular Telegram desde la app, cambiar la red WiFi, SOS sin conexión, seguridad de
  la bengala y demás temas del Manual 3.0 (`aba092f`, `854a801`).
- KB: qué es Senti y que no necesita configuración (antes "¿cómo configuro a Senti?" traía la configuración de la
  central) (`f606570`).
- Pruebas: `test_cache_eventos.py`, `test_comandos_manual3.py`, prueba anti-jerga en la KB, casos nuevos en las
  baterías de emulador (reglas 60, familia 25, vinculación 22).

### Cambiado
- La llave del modo local se guarda en `Locales/{mac}` (solo la lee el dueño); la copia en `ESP32/{mac}/Local` queda
  solo para centrales sin miembros (`af50c99`).
- `LOCAL_ROTATE` no caduca y se reenvía cada 10 min hasta el `cmd_ack` de la central (`9d15596`).
- `/start` de Telegram vincula por una ficha aleatoria de la cuenta (`Usuarios/{uid}/enlaceTelegram`); el uid a pelo
  solo vale para cuentas sin centrales ni membresías (`639307c`).
- KB y prompts de Senti en lenguaje de cliente (sin servidor, Python, MQTT, Firebase…) y con la redacción del Manual
  3.0, que es la referencia oficial (`aba092f`, `854a801`); botón de ventas «Más info» sin MQTT/TLS (`23b3b27`).

### Arreglado
- La caché del listener aplica los eventos por ruta completa: un cambio en `miembros/{uid}` dejaba la lista de
  miembros rota (`950d03d`).
- El aviso al dueño de una orden de familia sale aunque el `ts` no sea representable (`950d03d`).
- Quitar a un miembro se puede reintentar sin dejar Usuario 2 de Telegram, llave vieja ni códigos a medio canjear
  (`6bf5c9f`).
- Una orden de miembro que no se pudo publicar por MQTT ya no se da por hecha (`2a6611b`).
- Senti: un JSON inválido de Groq también prueba el Ollama de respaldo (`c07e998`).

## 2026-11-23 — `4436824..68a1ce0` (en producción por partes, última 14:47 CST)

### Agregado
- Familia #124 F1: invitar (QR 15 min o código de 24 h, un solo uso), unirse, quitar, salir, `Orden` de miembros con
  aviso al dueño y push autoritativo (`21ed520`).
- KB de familia para la app 8.2 (`823ce07`).
- Senti: Ollama local del VPS como última reserva (`fb9d883`).
- Baterías contra el emulador: reglas F0 (`4436824`), familia y vinculación (`76f7631`).

### Cambiado
- Senti con Groq de principal (`openai/gpt-oss-20b`) y Ollama local de respaldo; fuera Ollama Cloud (`fb9d883`,
  `68a1ce0`).

### Arreglado
- 503 en traspaso/quitar/salir por transacciones con `None` (`fd43650`).
- El traspaso borra también `Orden` (`60fc417`).

## Anteriores

Changelogs previos, en texto: [CHANGELOG_2026-09-02.txt](CHANGELOG_2026-09-02.txt),
[CHANGELOG_2026-09-01.txt](CHANGELOG_2026-09-01.txt), [CHANGELOG_2026-01-15.txt](CHANGELOG_2026-01-15.txt).
Entre septiembre y el 22-nov no se llevó changelog: ver `git log` y los resúmenes de sesión del proyecto.
