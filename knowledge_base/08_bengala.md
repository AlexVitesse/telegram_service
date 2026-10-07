# Bengala de Humo - Sentinel Guard

## Que es la bengala

La bengala es un dispositivo de disuasion visual que libera una cortina de humo. Para los datos del cartucho (composicion, cobertura, duracion), consulta su ficha tecnica. Esta diseñada para desorientar a intrusos y dificultar la vision dentro del area protegida. Requiere alimentacion electrica continua para funcionar correctamente.

## Modos de configuracion

La bengala tiene 3 modos de operacion, configurables desde la app movil -en la ficha del equipo, tocando su tarjeta en la pantalla principal- o desde Telegram.

Desde el chat de Senti dentro de la app la bengala todavia NO se maneja: si se lo pides, te dira que se hace en la ficha del equipo o por Telegram.

## Modo Auto

Selecciona "Auto" en la app o usa el comando /auto en Telegram. En este modo, la bengala se dispara automaticamente al detectar una intrusion, sin intervencion humana. Es el maximo nivel de proteccion. Al activarse, el cartucho de humo se detona de forma instantanea e irreversible.

## Modo Pregunta

Selecciona "Pregunta" en la app o usa el comando /preguntar en Telegram. Al detectar una intrusion, el sistema pausa la bengala y envia una notificacion interactiva al chat de Telegram con las siguientes opciones:

- "Disparar bengala": detona la bengala.
- "Dejar armado": detiene la sirena sin disparar la bengala y el sistema sigue armado.
- "Desactivar sistema": desarma esa central.

Si tienes varias centrales, cada aviso es de una sola: sus botones actuan solo sobre la central del aviso, aunque otras esten sonando a la vez. Si tocas "Disparar bengala" en un aviso de una central que ya no esta sonando, el bot responde "Esa alarma ya no esta activa" y no dispara nada. En avisos enviados antes del 7 de octubre de 2026, si suenan varias centrales, el bot te pregunta en cual actuar.

Este modo permite evaluar la situacion antes de actuar, por ejemplo revisando camaras de seguridad. La sirena si suena inmediatamente independientemente de la decision sobre la bengala. La respuesta se da tocando uno de los botones del propio mensaje de Telegram; NO existen los comandos /si ni /no. Mientras la alarma siga activa, el bot repite el aviso "ALARMA SIGUE ACTIVA" con los mismos botones cada minuto en el chat privado, y los botones siguen sirviendo mientras la central este sonando. Si nadie contesta en 3 minutos, el Master apaga la sirena por su cuenta, el sistema sigue armado y la bengala no se dispara. A partir de ahi, si tocas "Disparar bengala" en un aviso antiguo, el bot responde "No hay dispositivos en alarma activa". En los grupos de Telegram el aviso llega sin botones.

## Modo Deshabilitado

Selecciona "Apagada" en la app o usa el comando /deshabilitar (o "Deshabilitar" en el menu /bengala) en Telegram. En este modo, la bengala no se dispara nunca, sin importar el tipo de evento. Los sensores siguen detectando y enviando notificaciones normalmente, y la sirena funciona con normalidad. Ideal para cuando estas en casa pero con la alarma armada.

## Menu bengala en Telegram

El comando /bengala muestra el modo actual de la bengala y los botones "Modo Auto", "Modo Pregunta" y "Deshabilitar". Con varios equipos, primero eliges el equipo o "Configurar TODOS".

## Indicadores LED de la bengala

- **LED Verde**: La bengala esta instalada correctamente y lista para funcionar.
- **LED Rojo**: No se detecta la bengala o esta mal colocada. Verificar la instalacion.
- El LED enciende al momento de detonar el cartucho.

## Precauciones de seguridad

- Una vez activada, la bengala no se puede detener: el cartucho se consume entero.
- Consulta la ficha tecnica del cartucho para sus datos y advertencias.
- No tocar el cartucho usado hasta que se haya enfriado.
- Mantener el modulo alejado de materiales inflamables.
- Si la bengala se activa por error: cubrir boca y nariz, salir de la zona y ventilar abriendo puertas y ventanas.
- El humo de la bengala puede activar detectores de humo convencionales instalados en el area.

## Persistencia de configuracion

El modo de la bengala se guarda en el propio Master y en la nube, y persiste entre reinicios y cortes de luz. Al encender el Master, recupera automaticamente el ultimo modo configurado. Un reset de fabrica del Master (clip 10 segundos o mas) borra esta configuracion.
