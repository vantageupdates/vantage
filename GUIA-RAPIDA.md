# Vantage · guía rápida

## Primer inicio

1. Abre `Vantage.exe` desde cualquier carpeta. Verás un splash breve que indica qué parte está cargando; no requiere instalación ni archivos adicionales.
2. Desde el icono de Vantage junto al reloj de Windows, elige la carpeta `Logs` de EverQuest.
3. Dentro de EverQuest ejecuta `/log on`.
4. Abre **Timers**, pulsa **Añadir** y configura nombre, respawn, tiempo estimado de kill, zona, color y sonido.

La bandeja muestra **WAITING** cuando la carpeta está vinculada pero todavía no ha llegado una línea nueva, **ONLINE** con actividad reciente, **QUIET** tras 90 segundos sin líneas y **NO LOGS** cuando falta la ruta. **Log Profiles…** enseña cada personaje y servidor por separado. Deja el cursor sobre las acciones de logs para ver la ayuda rápida, o abre la guía de vinculación para consultar los pasos completos.

Las ventanas son independientes. En la barra superior puedes fijarlas encima, cambiar opacidad, activar click-through en los overlays, enrollarlas, minimizarlas a la bandeja o redimensionarlas desde la esquina. Mercado siempre conserva mouse y teclado para que puedas escribir en la búsqueda. Cada ventana recuerda su posición y tamaño. Por defecto Vantage arranca con las ventanas enrolladas; en **Ajustes → General → Al iniciar Vantage** puedes elegir **Enrolladas**, **Minimizadas a la bandeja** o **Normales / desplegadas**. Al enrollarse, la cabecera se encoge al ancho exacto de sus controles. El título y los controles esenciales siempre conservan su espacio; si la cabecera queda estrecha, las acciones secundarias pasan a **More window actions** antes de solaparse. Todos los paneles se redibujan como controles Qt nativos para conservar líneas, texto y entrada nítidos en cualquier tamaño. La navegación lateral de Ajustes usa filas compactas, foco visible y una marca dorada discreta en la sección actual. En Quick Bar, el café y el rayo verde de una conexión `ONLINE` estable alternan icono, superficie y un destello pequeño usando timers precisos aun con EverQuest o WinEQ al frente; **Reduce motion and flashes** los deja estáticos. Smart Timers queda junto a Buffs & Triggers y las acciones de estado/recuperación quedan junto a Quit. En Buffs & Triggers, el nivel muestra `Lv` completo y los rockers arriba/abajo viven dentro del mismo campo. Deja el puntero sobre cualquier control para ver su función.

Haz clic derecho sobre el fondo o la cabecera de cualquier panel para moverlo a nueve posiciones de la pantalla, traerlo al frente, dejarlo en capa normal, enviarlo detrás, cambiar su opacidad, enrollarlo, cambiar el marco, restaurar su tamaño o enviarlo a la bandeja. Los campos de texto conservan su menú de copiar/pegar; buffs y mapa conservan sus acciones especiales.

## Smart Timers

- Por defecto, una línea `You have slain…` o `…has been slain by…` crea automáticamente el mob con el respawn de la zona detectada por zoning o `/who`.
- Si el mismo mob vuelve a morir en esa zona, Vantage reinicia su fila: no crea duplicados. La lectura sigue activa aunque la ventana esté escondida.
- El catálogo incluye las 121 zonas P99 presentes en Vantage. Cada fila automática muestra `P99 Respawn DB` como fuente; cuando la fuente no publica un tiempo, Vantage avisa y no inventa uno.
- El log de EverQuest no etiqueta “named” frente a trash. Vantage cruza cada muerte con el catálogo named de la zona activa y sólo crea timers automáticos cuando existe una coincidencia; trash desconocido no crea filas. Se puede apagar en **Ajustes → Smart Timers**.
- **Mob muerto** ancla el comienzo del respawn con la hora real.
- **Spawn ahora** inicia la fase estimada de combate.
- En modo inteligente, si dejas pasar uno o varios ciclos el timer calcula la fase actual sin perder el horario original.
- Una acción manual siempre reemplaza la estimación y vuelve a anclar el ciclo.
- En los campos de tiempo, `3` significa 3 minutos; también puedes escribir `3:50` o `1:03:50`.
- Cada fila muestra su propio volumen y tiene un botón de reinicio directo que vuelve a **LISTO**.
- Cada timer puede usar uno de los seis sonidos incluidos o un WAV propio. Su volumen individual se ajusta en la misma fila o al editarlo.
- Las tarjetas conservan bordes y separadores nítidos en tamaños compactos y escalas fraccionarias.
- La barra pulsa en ámbar durante el aviso previo y en verde durante la ventana de spawn.
- Para entregar un camp, selecciona su zona y pulsa **Share visible timers** en el encabezado, o usa `Ctrl+Shift+S`. Vantage copia uno o varios códigos: envía cada línea por `/tell`, `/say` o un mensaje externo.
- El tooltip de **Share visible timers** explica el flujo completo. El receptor no tiene que importar nada: sólo necesita Vantage y `/log on`; su app reconoce el código en el log, descuenta los segundos transcurridos desde su creación y añade o actualiza los timers en la zona correcta. Los pausados no pierden tiempo y los inteligentes avanzan las fases que hayan transcurrido.
- El eco propio y los códigos repetidos se ignoran. Los códigos caducan a las 24 horas y sólo transportan nombre, zona y tiempos; los sonidos, colores y volúmenes del receptor no se sobrescriben.

## Buffs, triggers y combate

- Ajusta el aviso de fading, la galería de sonido y el volumen desde **Ajustes → Buffs y triggers**.
- Los seis sonidos cortos incluidos fueron rediseñados para Vantage y se distribuyen bajo CC0; también puedes importar WAV propios.
- Haz clic derecho sobre un buff para escoger un sonido incluido, importar un WAV, probarlo o silenciarlo.
- El nombre y el tiempo se pintan dentro de la barra compacta. Su color dominante conserva el matiz del icono con una saturación un poco más marcada y contraste seguro para el texto; una profundidad vertical suave mejora la separación sin volverla pesada. Warning, crítico y `FADED` siguen siendo claros.
- Si vuelves a lanzar un buff propio, Vantage refresca y revive la misma fila, cancela el retiro pendiente e ignora el fade inmediato de la copia que acabas de reemplazar.
- En una ventana estrecha, las acciones secundarias pasan a **More spell tools** para conservar el título y los controles principales sin solaparse.
- La biblioteca incluye avisos editables para invis por caer, charm/root/fear roto, fizzle, resist, mez resistido, cast interrumpido, notas fallidas y mobs enraged.
- Al crear un trigger, el selector muestra los tokens disponibles y su significado.
- **Import Trigger Pack…** acepta `.gtp`, `ShareData.xml`, XML o `.gtt`. Todo entra apagado; revisa y activa sólo lo necesario. Las rutas de audio externas se descartan y se sustituyen por sonidos incluidos.
- Cada trigger puede pertenecer a una categoría, dirigirse a **Alerts** o **Timer Alerts**, conservar/reiniciar/duplicar el timer y terminar antes con un patrón independiente. **Match Log** explica exactamente qué línea activó qué trigger.
- Combat incluye Overview, Player DPS, Tanking, Spells, Healing, Fights, Loot, Chat y búsqueda histórica. Selecciona varias peleas en **Fights** y ábrelas para ver el combinado; la búsqueda recorre los logs originales en segundo plano y nunca los modifica.

## Heal Chain

- Abre **Heals** desde la bandeja. El panel muestra tanque, orden, clérigo, barra de cast, tiempo restante, estado y quién sigue.
- El formato predeterminado reconoce mensajes como `AAA - CH - Vulak`. En **Ajustes → Heal Chain** usa `###` para el orden del clérigo y `tankname` para el tanque; también acepta formatos como `ST CCC CH -- Dain`.
- Un mensaje `!KI1` a `!KI9` cambia el intervalo de la cadena. Las interrupciones quedan marcadas en Live e History.
- Escribe tu orden —por ejemplo `AAA`— o deja el campo vacío para aprenderlo de una llamada propia; Vantage puede avisarte cuando quedas próximo.
- Todo se procesa localmente desde el log vinculado. El módulo no envía la rotación ni datos de raid a ningún servidor externo.

En **Ajustes → Sounds** puedes escoger cada sonido automático, cambiar las acciones de sonido de los triggers, probar 20 tonos originales CC0 o cargar un WAV propio. Los timers guardados conservan su alarma individual en Edit. El riel del Quick Bar dice qué ocurrió y desaparece al cruzar; no sustituye el mensaje por el nombre de una ventana o archivo de sonido. En **Ajustes → General → Notification overlays → Arrange** aparecen las superficies **Alerts** y **Timer Alerts**: arrastra la cabecera, cambia el tamaño desde la esquina y pulsa **Lock**. El mute maestro de Quick Bar es el corte final del backend: detiene WAV y TTS activos o pendientes y bloquea pruebas y repeticiones hasta desactivarlo. El menú de la bandeja conserva **LAST SOUND**. En **Ajustes → General** también puedes activar **Reduce motion and flashes**.

## Market: Green y Blue

PigParse es la fuente de verdad para precios. El selector Green/Blue tiene nombre accesible y recuerda tu elección. La lista, el historial de PigParse, la comparación con Wiki Auction Tracker y sus cachés se guardan por separado para cada servidor. Puedes filtrar por WTS/WTB, clase, raza y slot; clase/raza/slot provienen del índice comunitario P99 Wiki. Al abrir el nombre dorado o **Ficha + precio Wiki**, Vantage consulta el servidor seleccionado: hace un promedio 50/50 sólo si las referencias recientes difieren 30% o menos; de lo contrario muestra ambas sin combinarlas.

**Live local** y las alertas de venta leen únicamente los mensajes `/auction` del log EQ vinculado. Ese historial local no se borra al cambiar Green/Blue y nunca se cambia de nombre ni se presenta como un feed de Internet.

Market usa controles Qt nativos sin una superficie gráfica escalada: un clic real en **Buscar item o vendedor…** entrega el foco directamente al campo. En tamaños estrechos, búsqueda, filtros y botones se apilan y sólo aparece scroll vertical.

Pulsa el nombre dorado de un item para abrir su ficha clásica dentro de Vantage. La ficha muestra icono, estadísticas, **Lo dropea** y **Dónde**. Pulsa el NPC o la zona para abrir otra ficha interna con sus datos; no necesitas salir al navegador.

## Mapas

- Vantage detecta la zona al leer mensajes de zoning, resultados de `/who` y otros estados válidos escritos en el log.
- El mapa llena el lienzo con la zona real; Vantage elimina la hoja auxiliar de glyphs de los mapas Brewall. Las etiquetas aparecen al acercarte para evitar una pared de texto en la vista general.
- Arrastra el mapa directamente con el botón izquierdo. Esto pausa el seguimiento automático para dejarlo donde lo pongas.
- Rueda = zoom; `Ctrl` + rueda = cambiar capas Z.
- Pulsa `Home` o usa **Ajustar mapa completo** en el menú contextual para recuperar la vista general.

## Teléfono

1. En **Timers**, pulsa el icono de teléfono.
2. Para usar la misma red Wi-Fi, abre o copia el enlace local.
3. Para usar Internet, crea el enlace efímero y escanea el QR.
4. En el teléfono tendrás **Spawn Timers**, **Market** y **EverQuest Live**. Market sigue el servidor Green/Blue elegido en la PC.
5. Para la vista del juego, abre **Configurar EverQuest Live…**. La ventana separada intenta detectar `eqgame.exe`; si tu instalación usa otra carpeta, elige el ejecutable manualmente.
6. Elige 2, 5 o 10 FPS. Sólo captura mientras esa pestaña está visible en el teléfono y nunca acepta mouse o teclado.
7. EverQuest Live funciona únicamente con el QR Wi-Fi local; no se publica por el túnel de Internet. Con WinEQ2, Vantage reconoce la superficie del juego aunque el wrapper use un handle hijo. Deja EverQuest al frente: la imagen se pausa al cambiar a otra aplicación para no capturarla por accidente. Usa modo ventana o ventana sin bordes.
8. Pulsa **Detener sesión** al terminar. El enlace y sus llaves dejan de funcionar.

El acceso por Internet usa un Cloudflare Quick Tunnel gratuito. No requiere cuenta ni un servidor central de Vantage, pero Cloudflare lo ofrece sin garantía de disponibilidad. La aplicación descarga el componente oficial firmado sólo después de pedir permiso.

## Modo portable, datos y privacidad

- Junto a `Vantage.exe` no se crean carpetas ni archivos auxiliares.
- La configuración se conserva en `%LOCALAPPDATA%\Vantage` para que puedas mover el único ejecutable libremente.
- Para restablecer la aplicación, ciérrala y elimina únicamente `%LOCALAPPDATA%\Vantage`.
- El programa lee únicamente el log local de EverQuest para detectar eventos.
- El móvil es de solo lectura y la sesión está apagada por defecto. La captura de EverQuest también se activa de nuevo en cada sesión.

## Nota de Windows

Esta compilación comunitaria no tiene un certificado comercial de firma de código. Windows puede mostrar “Editor desconocido”. Comprueba el archivo SHA-256 entregado junto al ejecutable.
