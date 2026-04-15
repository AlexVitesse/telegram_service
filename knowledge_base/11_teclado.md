# Teclado - Sentinel Guard

## Descripcion general

El teclado es un modulo LoRa inalambrico que permite armar y desarmar el sistema de alarma sin necesidad de usar el telefono. Puede utilizarse como control remoto portatil o montarse fijo en la pared, preferiblemente cerca de la puerta principal.

Importante: el teclado es un modulo independiente que se comunica con el Master via LoRa. Toda la logica de contrasenas, menus y bloqueos ocurre internamente dentro del modulo teclado. El Master solamente recibe una senal de "clave correcta" y ejecuta la accion correspondiente (armar o desarmar). El Master no conoce ni gestiona la contrasena del teclado fisico.

## Uso basico del teclado

La contrasena de fabrica es **1234**. Se recomienda cambiarla durante la primera configuracion. La contrasena debe tener entre 4 y 6 digitos.

Para armar o desarmar el sistema:

1. Ingresar la contrasena usando las teclas numericas.
2. Presionar la tecla **#** para enviar la contrasena.
3. Si la contrasena es correcta: el LED verde parpadea 3 veces y el teclado envia la senal al Master via LoRa. Si el sistema estaba desarmado, se arma. Si estaba armado, se desarma.
4. Si la contrasena es incorrecta: el LED rojo parpadea 2 veces. No se envia ninguna senal al Master.

Para borrar lo que se ha escrito (si se cometio un error al teclear), presionar la tecla **\***. El LED rojo parpadea 1 vez confirmando que la entrada fue borrada.

## Menu de configuracion del teclado

El menu de configuracion se ejecuta completamente dentro del modulo teclado, sin involucrar al Master.

Para acceder al menu, mantener presionada la tecla **\*** durante 3 segundos. El LED verde parpadea 2 veces indicando que se entro al menu.

Opciones disponibles en el menu:

- **Tecla 1**: Cambiar contrasena
- **Tecla 2**: Reset de fabrica
- **Tecla 0**: Salir del menu

El menu se cierra automaticamente tras 5 minutos sin actividad.

## Como cambiar la contrasena del teclado

Este proceso ocurre internamente en el modulo teclado:

1. Entrar al menu de configuracion (mantener * por 3 segundos).
2. Presionar la tecla **1** para seleccionar "Cambiar contrasena".
3. Ingresar la contrasena actual y presionar **#**.
4. Ingresar la nueva contrasena (debe tener entre 4 y 6 digitos) y presionar **#**.
5. Si el cambio fue exitoso, el LED verde parpadea 3 veces.

La nueva contrasena se almacena localmente en el modulo teclado.

## Reset de fabrica del teclado

El reset de fabrica devuelve la contrasena al valor original (1234) y borra cualquier configuracion personalizada del modulo teclado.

1. Entrar al menu de configuracion (mantener * por 3 segundos).
2. Presionar la tecla **2** para seleccionar "Reset de fabrica".
3. Ingresar el codigo maestro proporcionado por el proveedor y presionar **#**.
4. Si el codigo maestro es correcto, el LED verde parpadea 2 veces confirmando el reset.

Nota: el codigo maestro es exclusivo del proveedor. Contactar al proveedor si no se dispone de este codigo.

## Bloqueo por intentos fallidos

Como medida de seguridad contra intentos de intrusion (gestionado internamente por el modulo teclado):

- Si se ingresan 5 contrasenas incorrectas consecutivas, el teclado se bloquea.
- Al bloquearse, el LED rojo parpadea 5 veces.
- El bloqueo dura 10 minutos. Durante ese tiempo, ninguna tecla responde y no se envia ninguna senal al Master.
- Despues de los 10 minutos, el teclado vuelve a funcionar normalmente.
- Un ingreso correcto de contrasena reinicia el contador de intentos fallidos.

## Comunicacion con el Master

El teclado se comunica con el Master unicamente a traves de LoRa. El Master recibe dos posibles senales:

- **Valor 1 (clave correcta)**: El Master alterna el estado del sistema (si esta desarmado lo arma, si esta armado lo desarma).
- **Valor 0**: Senal no reconocida, el Master no realiza ninguna accion.

El alcance de comunicacion LoRa es de hasta 50 metros en espacio abierto, reduciendose con obstaculos (35m madera, 20m ladrillo, 5m metal).
