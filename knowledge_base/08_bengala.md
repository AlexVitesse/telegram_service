# Bengala de Humo - Sentinel Guard

## Que es la bengala

La bengala es un dispositivo de disuasion visual que libera una cortina de humo no toxico con cobertura de 20 metros cuadrados. Esta diseñada para desorientar a intrusos y dificultar la vision dentro del area protegida. Requiere alimentacion electrica continua para funcionar correctamente.

## Modos de configuracion

La bengala tiene 3 modos de operacion, configurables desde la app movil -en la ficha del equipo, tocando su tarjeta en la pantalla principal- o desde Telegram.

Desde el chat de Senti dentro de la app la bengala todavia NO se maneja: si se lo pides, te dira que se hace en la ficha del equipo o por Telegram.

## Modo Auto

Selecciona "Auto" en la app o usa el comando /auto en Telegram. En este modo, la bengala se dispara automaticamente al detectar una intrusion, sin intervencion humana. Es el maximo nivel de proteccion. Al activarse, el cartucho de humo se detona de forma instantanea e irreversible.

## Modo Pregunta

Selecciona "Pregunta" en la app o usa el comando /preguntar en Telegram. Al detectar una intrusion, el sistema pausa la bengala y envia una notificacion interactiva al chat de Telegram con las siguientes opciones:

- "Disparar bengala": detona la bengala.
- "Dejar armado": detiene la sirena sin disparar la bengala y el sistema sigue armado.
- "Desactivar sistema": desarma el sistema.

Este modo permite evaluar la situacion antes de actuar, por ejemplo revisando camaras de seguridad. La sirena si suena inmediatamente independientemente de la decision sobre la bengala. La respuesta se da tocando uno de los botones del propio mensaje de Telegram; NO existen los comandos /si ni /no. Mientras la alarma siga activa, el bot repite el aviso "ALARMA SIGUE ACTIVA" con los mismos botones cada minuto en el chat privado. Si nadie contesta en 3 minutos, el Master apaga la sirena, el sistema sigue armado y la bengala no se dispara. En los grupos de Telegram el aviso llega sin botones.

## Modo Deshabilitado

Selecciona "Apagada" en la app o usa el comando /deshabilitar (o "Deshabilitar" en el menu /bengala) en Telegram. En este modo, la bengala no se dispara nunca, sin importar el tipo de evento. Los sensores siguen detectando y enviando notificaciones normalmente, y la sirena funciona con normalidad. Ideal para cuando estas en casa pero con la alarma armada.

## Menu bengala en Telegram

El comando /bengala muestra el modo actual de la bengala y los botones "Modo Auto", "Modo Pregunta" y "Deshabilitar". Con varios equipos, primero eliges el equipo o "Configurar TODOS".

## Indicadores LED de la bengala

- **LED Verde**: La bengala esta instalada correctamente y lista para funcionar.
- **LED Rojo**: No se detecta la bengala o esta mal colocada. Verificar la instalacion.
- El LED enciende al momento de detonar el cartucho.

## Precauciones de seguridad

- Una vez activada, la bengala no se puede detener. El cartucho se consume completamente en 10 a 20 segundos.
- No tocar el cartucho usado por al menos 10 minutos, ya que queda muy caliente.
- Si la bengala se activa por error: agacharse, cubrir boca y nariz, y buscar la salida mas cercana.
- Para disipar el humo, abrir puertas y ventanas. El humo se disipa en 3 a 10 minutos dependiendo de la ventilacion.
- El humo de la bengala puede activar detectores de humo convencionales instalados en el area.

## Persistencia de configuracion

El modo de la bengala se guarda en el propio Master y en la nube, y persiste entre reinicios y cortes de luz. Al encender el Master, recupera automaticamente el ultimo modo configurado. Un reset de fabrica del Master (clip 10 segundos o mas) borra esta configuracion.
