# Sistema General - Sentinel Guard

## Que es Sentinel Guard

Sentinel Guard es un sistema de alarma IoT profesional diseñado para proteger hogares y negocios. Combina hardware propio (sensores, sirena, bengala de humo, teclado) con conectividad en la nube, permitiendo control y monitoreo desde una app movil, Telegram o un teclado fisico.

## Componentes del sistema

- **Modulo Master (ESP32)**: Es el cerebro del sistema. Coordina todos los modulos, sensores y actuadores. Cuenta con conectividad WiFi para internet y LoRa para comunicacion inalambrica con los demas modulos. Alcance LoRa: hasta 50 metros en campo abierto.
- **Sensores PIR (movimiento)**: Detectan presencia mediante infrarrojo. Angulo de deteccion de 110 grados y alcance de 7 metros.
- **Sensores Magneticos**: Detectan apertura de puertas y ventanas. Constan de dos piezas: la pieza principal y un iman.
- **Sirena**: Actuador sonoro de 110dB con proteccion IP65 contra polvo y agua.
- **Bengala de humo**: Actuador que genera humo no toxico con cobertura de 20 metros cuadrados. Duracion del humo: 10 a 20 segundos.
- **Teclado**: Control local inalambrico para armar y desarmar el sistema. Acepta codigos de 4 a 6 digitos.

## Arquitectura del sistema

El flujo de comunicacion sigue esta cadena:

ESP32 (Master) <-> MQTT (HiveMQ con TLS) <-> Servidor Python en VPS <-> Telegram Bot + Firebase <-> App Ionic

El protocolo MQTT con cifrado TLS garantiza comunicacion segura entre el hardware y la nube. El servidor VPS en Python actua como puente central, procesando comandos y distribuyendo notificaciones.

## Flujo de datos ante una deteccion

1. Un sensor detecta un evento (movimiento, apertura de puerta, etc.)
2. El Master recibe la señal del sensor via LoRa y procesa la alerta
3. El Master envia el evento al broker MQTT (HiveMQ)
4. El servidor VPS recibe el mensaje MQTT
5. El VPS notifica al usuario via Telegram y actualiza Firebase
6. La app movil Ionic recibe la actualizacion desde Firebase

## Comunicacion LoRa entre modulos

La comunicacion LoRa entre el Master y los modulos (sensores, sirena, bengala, teclado) tiene los siguientes alcances segun el material:

- Campo abierto: hasta 50 metros
- A traves de madera: hasta 35 metros
- A traves de ladrillo: hasta 20 metros
- A traves de metal: hasta 5 metros

## Formas de control del sistema

El usuario puede controlar Sentinel Guard desde tres interfaces:

- **App movil Sentinel Guard**: Aplicacion Ionic con control completo, estado en tiempo real y configuracion.
- **Telegram**: Chatbot para recibir alertas, armar/desarmar y consultar estado.
- **Teclado fisico**: Control local para armar y desarmar ingresando la contrasena, sin necesidad de telefono.
