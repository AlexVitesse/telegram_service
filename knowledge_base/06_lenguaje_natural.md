# Interaccion por Lenguaje Natural

## Como funciona

El bot de Sentinel Guard entiende mensajes escritos en texto libre ademas de los comandos tradicionales con barra (/on, /off, etc.). Utiliza inteligencia artificial para interpretar la intencion del usuario y ejecutar la accion correspondiente.

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
- **Usa comandos directos como respaldo**: Si el bot no entiende tu mensaje en lenguaje natural, siempre puedes recurrir a los comandos tradicionales (/on, /off, /status, etc.).
- **Preguntas y acciones**: El bot distingue entre una pregunta informativa ("como configuro la bengala?") y una accion directa ("dispara la bengala"). Ambas funcionan correctamente.
