# Vantage · guía rápida

## Primer inicio

1. Abre `Vantage.exe` desde cualquier carpeta. Verás un splash breve que indica qué parte está cargando; no requiere instalación ni archivos adicionales.
2. Desde el icono de Vantage junto al reloj de Windows, elige la carpeta `Logs` de EverQuest.
3. Dentro de EverQuest ejecuta `/log on`.
4. Abre **Timers**, pulsa **Añadir** y configura nombre, respawn, tiempo estimado de kill, zona, color y sonido.

La bandeja muestra **WAITING** cuando la carpeta está vinculada pero todavía no ha llegado una línea nueva, **ONLINE** con actividad reciente, **QUIET** tras 90 segundos sin líneas y **NO LOGS** cuando falta la ruta. **Log Profiles…** enseña cada personaje y servidor por separado. Deja el cursor sobre las acciones de logs para ver la ayuda rápida, o abre la guía de vinculación para consultar los pasos completos.

Las ventanas son independientes. En la barra superior puedes fijarlas encima, cambiar opacidad, activar click-through en los overlays, enrollarlas, minimizarlas a la bandeja o redimensionarlas desde la esquina. Mercado siempre conserva mouse y teclado para que puedas escribir en la búsqueda. Cada ventana recuerda su posición y tamaño. Por defecto Vantage arranca con las ventanas enrolladas; en **Ajustes → General → Al iniciar Vantage** puedes elegir **Enrolladas**, **Minimizadas a la bandeja** o **Normales / desplegadas**. Al enrollarse, la cabecera se encoge al ancho exacto de sus controles. Todos los paneles se redibujan como controles Qt nativos para conservar líneas, texto y entrada nítidos en cualquier tamaño. Deja el puntero sobre cualquier control para ver su función.

Haz clic derecho sobre el fondo o la cabecera de cualquier panel para moverlo a nueve posiciones de la pantalla, traerlo al frente, dejarlo en capa normal, enviarlo detrás, cambiar su opacidad, enrollarlo, cambiar el marco, restaurar su tamaño o enviarlo a la bandeja. Los campos de texto conservan su menú de copiar/pegar; buffs y mapa conservan sus acciones especiales.

## Smart Timers

- Por defecto, una línea `You have slain…` o `…has been slain by…` crea automáticamente el mob con el respawn de la zona detectada por zoning o `/who`.
- Si el mismo mob vuelve a morir en esa zona, Vantage reinicia su fila: no crea duplicados. La lectura sigue activa aunque la ventana esté escondida.
- El catálogo incluye las 121 zonas P99 presentes en Vantage. Cada fila automática muestra `P99 Respawn DB` como fuente; cuando la fuente no publica un tiempo, Vantage avisa y no inventa uno.
- El log de EverQuest no etiqueta “named” frente a trash. Para asegurar que ningún named se pierda, el modo automático escucha ambas clases de muerte; se puede apagar en **Ajustes → Smart Timers**.
- **Mob muerto** ancla el comienzo del respawn con la hora real.
- **Spawn ahora** inicia la fase estimada de combate.
- En modo inteligente, si dejas pasar uno o varios ciclos el timer calcula la fase actual sin perder el horario original.
- Una acción manual siempre reemplaza la estimación y vuelve a anclar el ciclo.
- En los campos de tiempo, `3` significa 3 minutos; también puedes escribir `3:50` o `1:03:50`.
- Cada fila muestra su propio volumen y tiene un botón de reinicio directo que vuelve a **LISTO**.
- Cada timer puede usar uno de los seis sonidos incluidos o un WAV propio. Su volumen individual se ajusta en la misma fila o al editarlo.
- La barra pulsa en ámbar durante el aviso previo y en verde durante la ventana de spawn.

## Buffs, triggers y combate

- Ajusta el aviso de fading, la galería de sonido y el volumen desde **Ajustes → Buffs y triggers**.
- Los seis sonidos cortos incluidos fueron rediseñados para Vantage y se distribuyen bajo CC0; también puedes importar WAV propios.
- Haz clic derecho sobre un buff para escoger un sonido incluido, importar un WAV, probarlo o silenciarlo.
- La barra y el borde del buff pulsan cuando entra en fading.
- El nombre y el tiempo del buff aparecen fuera de la barra, por lo que siguen legibles incluso en ventanas pequeñas.
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

Cada vez que Vantage reproduce audio, un overlay oscuro independiente muestra qué timer, buff, trigger o prueba lo originó, el nombre del sonido y el volumen. No es un globo de Windows ni vive dentro de otra ventana. En **Ajustes → General → Notification overlays → Arrange** aparecen dos superficies independientes, **Alerts** y **Timer Alerts**: arrastra la cabecera, cambia el tamaño desde la esquina y pulsa **Lock** en cada una. **Options** permite apilar avisos, agrupar títulos repetidos, invertir el orden, escoger cuántos se ven y ajustar fuente/fondo. Los timers muestran countdown y barra real. Al bloquearse vuelven a ser transparentes a los clics y no toman foco. El menú de la bandeja conserva **LAST SOUND** y ofrece silenciar todo el audio. En **Ajustes → General** también puedes activar **Reduce motion and flashes**.

## PigParse Green

PigParse es la fuente de verdad para precios. La pantalla conserva los anuncios y muestra estimaciones locales por separado. Puedes filtrar por WTS/WTB, clase, raza y slot. Clase/raza/slot provienen del índice comunitario P99 Wiki. Al abrir el nombre dorado o **Ficha + precio Wiki**, Vantage extrae también el precio Green del Wiki: hace un promedio 50/50 sólo si las referencias recientes difieren 30% o menos; de lo contrario muestra ambas sin combinarlas.

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
4. En el teléfono tendrás **Spawn Timers**, **PigParse Green** y **EverQuest Live**.
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
