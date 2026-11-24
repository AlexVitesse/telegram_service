# Sistema General - Sentinel Guard

## Que es Sentinel Guard

Sentinel Guard (tambien escrito SentinelGuard) es un sistema de alarma inteligente diseñado para proteger hogares y negocios. Como producto, Sentinel Guard es un sistema de seguridad integral. Combina equipos propios (central, sensores, sirena, bengala de humo, teclado) con conexion a internet, permitiendo control y monitoreo desde una app movil, Telegram o un teclado fisico.

## Componentes del sistema

- **Modulo Master (la central)**: Es el cerebro del sistema. Coordina todos los modulos, sensores y actuadores. Se conecta a tu WiFi para tener internet y se comunica sin cables con los demas modulos (por radio LoRa, por eso la app habla de "Sensores LoRa"). Alcance: hasta 50 metros en campo abierto.
- **Sensores PIR (movimiento)**: Detectan presencia mediante infrarrojo. Angulo de deteccion de 110 grados y alcance de 7 metros.
- **Sensores Magneticos**: Detectan apertura de puertas y ventanas. Constan de dos piezas: la pieza principal y un iman.
- **Sirena**: Alarma sonora de 110dB con proteccion IP65 contra polvo y agua.
- **Bengala de humo**: Libera una cortina de humo no toxico con una cobertura de hasta 20 m³, que bloquea la vision del intruso. Ver las advertencias en "Bengala de Humo".
- **Teclado**: Control local inalambrico para armar y desarmar el sistema. Acepta codigos de 4 a 6 digitos.

## Como se comunica el sistema

La central esta conectada a internet por tu WiFi. Por esa conexion, siempre cifrada, recibe las ordenes que das desde la app o desde Telegram y envia los avisos. Los ajustes (horarios, bengala, tiempo de salida) quedan guardados en la nube de Sentinel Guard y en la propia central.

Los sensores, la sirena, la bengala y el teclado hablan directo con la central, sin internet.

## Que pasa ante una deteccion

1. Un sensor detecta un evento (movimiento, apertura de puerta, etc.).
2. La central recibe la señal del sensor y, si esta armada, activa la sirena (y la bengala segun su modo).
3. La central avisa por internet.
4. Te llega el aviso por Telegram y como notificacion en la app, con el nombre del sensor.

## Alcance inalambrico entre modulos

La comunicacion inalambrica entre el Master y los modulos (sensores, sirena, bengala, teclado) tiene los siguientes alcances segun el material:

- Campo abierto: hasta 50 metros
- A traves de madera: hasta 35 metros
- A traves de ladrillo o block: hasta 20 metros
- A traves de metal: hasta 5 metros

## Formas de control del sistema

El usuario puede controlar Sentinel Guard desde tres interfaces:

- **App movil Sentinel Guard**: Aplicacion para Android e iOS con control completo, estado en tiempo real y configuracion.
- **Telegram**: Chatbot para recibir alertas, armar/desarmar y consultar estado.
- **Teclado fisico**: Control local para armar y desarmar ingresando la contrasena, sin necesidad de telefono.
