# Interaccion por Lenguaje Natural

## Como funciona

Sentinel Guard entiende mensajes escritos en texto libre, ademas de los comandos tradicionales con barra (/on, /off, etc.). Utiliza inteligencia artificial para interpretar la intencion del usuario y ejecutar la accion correspondiente.

Funciona en los DOS canales:

- **El bot de Telegram**, escribiendole al chat del bot.
- **Senti, el asistente dentro de la app**, tocando el boton flotante que aparece en todas las pantallas.

Los dos entienden las mismas frases. Lo que cambia es cuanto puede EJECUTAR cada uno, y esta detallado mas abajo: el bot ejecuta todo, y la app ejecuta lo que sabe hacer por si misma y avisa cuando algo hay que hacerlo desde otro sitio.

Cuando Senti va a desarmar, pregunta antes con dos botones y nombra el equipo: "Voy a desarmar merida. Confirmas?". Hasta que se toca "Si, desarmar" no se manda nada. El bot de Telegram desarma directo, sin ese paso.

## Que ejecuta cada canal

| Frase de este tipo | Bot de Telegram | Senti (app) |
|---|---|---|
| Armar | Si | Si |
| Desarmar | Si | Si, preguntando antes |
| Consultar estado | Si | Si, sin salir de la app |
| Listar dispositivos | Si | Si, sin salir de la app |
| Detener la sirena sin desarmar | Si | No: lo dice y remite al bot |
| Ultimo evento | Si | No: lo dice y remite al bot |
| Bengala | Si | No desde el chat: se configura en la ficha del equipo |
| Horarios | Si | No desde el chat: se configuran en la pantalla Horarios |
| Preguntas informativas | Si | Si |

Cuando Senti no puede hacer algo, lo dice y explica donde se hace. No contesta con documentacion como si hubiera ejecutado la orden.

Si el nombre del equipo no coincide con ninguno de los tuyos, ninguno de los dos canales actua sobre todos por si acaso: responden que no lo encuentran y enumeran los que si tienes.

## Ejemplos de frases para comandos

### Armar el sistema
- "activa la alarma"
- "enciende el sistema"
- "arma la de bodega"
- "prende todo"
- "activa la alarma de la oficina"

### Desarmar el sistema
- "apaga la alarma"
- "desactiva el sistema"
- "desarma la oficina"
- "apaga todo"

### Consultar estado
- "como esta la alarma?"
- "cual es el estado?"
- "esta armada?"
- "esta prendida la alarma?"

### Detener la sirena (sin desarmar)
- "apaga la sirena"
- "silencia la alarma"
- "para el ruido"
- "detener la sirena"

Nota: Esto detiene la sirena pero mantiene el sistema armado. Es diferente de desarmar (/off), que apaga todo y deja de monitorear sensores.

### Listar dispositivos
- "cuantos dispositivos tengo?"
- "cuales son mis alarmas?"
- "que dispositivos estan vinculados?"

### Ultimo evento
- "cuando fue la ultima alarma?"
- "hubo alguna alerta?"
- "paso algo hoy?"

### Bengala
- "dispara la bengala"
- "activa el humo"
- "lanza la bengala"

### Horarios
- "arma lunes a viernes de 10pm a 6am"
- "que horarios tengo?"
- "programa la alarma para las noches"

## Preguntas informativas (RAG)

Ademas de ejecutar comandos, puedes hacer preguntas informativas y el bot buscara la respuesta en su base de conocimiento:

- "como configuro la bengala?"
- "que es el modo pregunta?"
- "como agrego un usuario?"
- "como vinculo un dispositivo?"
- "que hago si la alarma no conecta?"
- "como cambio la contrasena del teclado?"
- "como funciona el sistema de horarios?"

El bot busca la informacion relevante en su documentacion interna y responde de forma clara y concisa.

## Tips para mejores resultados

- **Habla de forma natural**: El bot entiende contexto y variaciones del lenguaje. No necesitas usar frases exactas.
- **Especifica el dispositivo**: Si tienes varios dispositivos vinculados, menciona el nombre del dispositivo en tu mensaje. Ejemplo: "arma la de bodega" en lugar de solo "arma".
- **Usa comandos directos como respaldo**: Si el bot de Telegram no entiende tu mensaje en lenguaje natural, siempre puedes recurrir a los comandos tradicionales (/on, /off, /status, etc.). Dentro de la app no hay comandos con barra: ahi el respaldo son los propios controles de la pantalla, como el toggle de armado o la ficha del equipo.
- **Preguntas y acciones**: El bot distingue entre una pregunta informativa ("como configuro la bengala?") y una accion directa ("dispara la bengala"). Ambas funcionan correctamente.
