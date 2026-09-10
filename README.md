# Vantage · P99 Companion

<p align="center">
  <img src="data/ui/icon-master.png" width="168" alt="Vantage Companion — gold diamond emblem inside a dark circular medallion">
</p>

Created by Mindflux / Harmflux on P99 Green Server · Discord: `mindflux99` ·
Official contact: [vantagecompanion@gmail.com](mailto:vantagecompanion@gmail.com)

Aplicación comunitaria gratuita, nativa, ligera y de un solo ejecutable para Windows. El estado de juego usado por timers, buffs, mapas, análisis y alertas proviene únicamente del log de EverQuest activado por el usuario o de archivos creados manualmente con `/outputfile`. No lee memoria del proceso, no inyecta código, no envía teclas y no automatiza acciones del personaje. Vantage combina Smart Spawn Timers, mercado Green/Blue, análisis de combate, cadenas de Complete Heal y alertas configurables en una interfaz oscura moderna, sin incrustar Chromium/WebView.

## Funciones principales

- Splash compacto con progreso real mientras carga el núcleo. Settings, Mobile, Spell Library y sus dependencias pesadas se crean sólo al abrirlas; las actualizaciones de red empiezan después de que la bandeja y los paneles están listos.
- Ventanas sin marco, redimensionables, always-on-top, opacidad de 25–100 %, click-through opcional en overlays y acceso desde la bandeja del sistema. Mercado permanece siempre interactivo para que búsqueda y filtros reciban teclado.
- Clic derecho sobre el fondo o cabecera de cualquier panel abre posición en nueve anclajes, capa normal/siempre encima/enviar detrás, opacidad, enrollado, marco, tamaño recomendado, bandeja y presets Tiny 25 %, Mini 35 %, Compact 50 %, 75 % y 100 %. Cada preset aplica su porcentaje exacto y queda marcado; enrollar, esconder en la bandeja y volver a abrir restaura ese mismo tamaño, no una geometría histórica mayor. Los menús propios de buffs, mapas y campos de texto se conservan.
- Todos los paneles conservan una superficie lógica Qt inmutable: al redimensionar desde derecha, abajo o cualquier esquina, Windows recibe un rectángulo proporcional antes de que Qt distribuya el contenido; texto, iconos, barras, filas y áreas de clic escalan juntos. No hay breakpoints ni correcciones tardías que hagan rebotar la ventana. Spawn Timers no contiene `QScrollArea`: su lienzo lógico crece para incluir cada fila y luego se reduce como una sola réplica, con tarjetas y bordes nítidos incluso en escalas compactas o fraccionarias y sin scrollbar horizontal ni vertical. El encabezado auto-oculto mantiene reservado su espacio.
- Todas las tablas permiten arrastrar cada separador del encabezado, hacer doble clic para ajustar al contenido y abrir controles de ancho con `Shift+F10`. Vantage recuerda los anchos por pantalla y por esquema de columnas entre reinicios; **Reset UI Layout** también restaura estos anchos sin borrar datos.
- Las cabeceras reservan el título y los controles esenciales; antes de que un ancho estrecho pueda solaparlos, las acciones secundarias pasan a un menú accesible. En Ajustes, la navegación lateral usa filas compactas, foco visible y un indicador dorado discreto para la sección activa.
- Inicio configurable en **Ajustes → General**: ventanas enrolladas (predeterminado), minimizadas a la bandeja o normales. Cada panel recuerda posición y tamaño.
- Botones con un subconjunto vectorial de CoreUI Icons Free (CC BY 4.0), estados claros de hover/foco/pulsado/desactivado y nombres accesibles para teclado y lectores de pantalla.
- La Quick Bar mantiene geometría fija mientras anima el café y, después de confirmar actividad `ONLINE` estable, el rayo verde de logs. Usa temporizadores precisos, alterna icono/superficie y añade un pequeño destello para que el pulso siga siendo perceptible con EverQuest o WinEQ al frente; **Reducir movimiento y flashes** conserva ambas señales en estado estático. Smart Timers queda inmediatamente junto a Buffs & Triggers, y Log Status, Reset UI Layout y Updates permanecen agrupados junto a Quit.
- Smart Spawn Timers por mob con nombre, color, respawn, kill time estimado, zona, detección de muerte por log y WAV propio. **Share visible timers** (o `Ctrl+Shift+S`) copia los timers visibles de la zona como uno o varios códigos compactos para `/tell`, `/say`, Discord u otro mensaje. El tooltip del botón explica el flujo completo: el receptor sólo necesita Vantage y `/log on`; su app reconoce cada código sin diálogo de importación, descuenta el tiempo desde la hora de creación y añade o actualiza los timers en la zona correcta.
- Timers automáticos de muerte: zoning y `/who` seleccionan la zona; cada línea `has slain` se cruza con el catálogo named de esa zona y sólo entonces crea o reinicia una fila. El selector conserva listas independientes —por ejemplo, las arañas named de Velks— hasta que el usuario borra cada fila manualmente. Los countdowns guardan deadlines absolutos y avanzan durante un cierre o reinicio; nunca desaparecen ni pierden su zona. El catálogo cubre las 121 zonas P99 incluidas, muestra la fuente en cada fila y deja los respawns no publicados como desconocidos en vez de inventarlos.
- El modo inteligente avanza de respawn a spawn, estima cuánto tarda el kill y continúa el siguiente ciclo. Una confirmación manual siempre vuelve a anclar el reloj.
- Entrada de tiempo amistosa (`3` = 3 minutos, `3:50`, `1:03:50`), barras de progreso, volumen individual visible y botones directos de reiniciar, pausar, muerte y spawn en cada fila.
- Buff/debuff timers con iconos pixel-art clásicos y nombre + tiempo dentro de barras compactas. Su color dominante conserva el matiz del icono con una saturación algo más marcada, contraste seguro para el texto claro y profundidad vertical suave; warning, crítico y `FADED` permanecen claramente diferenciados. Un clic sobre el encabezado de un nombre limpia toda su lista de buffs; el clic derecho conserva las acciones de identificación de mobs. El nivel de cada perfil usa un único campo `Lv` con rocker arriba/abajo integrado, texto completamente reservado y control por teclado. Volver a lanzar un buff propio revive y refresca la misma fila, cancela su retiro pendiente e ignora el aviso de fade inmediato que corresponda a la copia reemplazada. En anchos estrechos, **More spell tools** reúne las acciones secundarias sin tapar el título. Conserva hasta tres pills de resultados recientes al pie (`RESIST`, `WORN OFF`, `FIZZLE`, `INTERRUPTED` y `CHARM BROKE`) para que cada evento del log permanezca identificable sin ocupar una línea fija cuando no ocurre nada. Incluye aviso visual, una galería de seis sonidos originales CC0, volumen regulable, WAV personalizados y ajustes por buff.
- La ventana de buffs muestra un estado `SIN BUFFS ACTIVOS` cuando todavía no hay efectos, en vez de parecer un panel vacío o roto.
- **P99 Spells & Skills** bajo demanda desde la bandeja, Quick Bar o Buffs & Triggers. Spells conserva 1,151 hechizos de jugador en filas explícitas `Level · Spell · Class`, con niveles reales por clase, ficha Wiki interna, adquisición y precios Green/Blue. El nuevo tab Skills cubre las 14 clases: permite buscar por nombre, categoría, nivel, entrenamiento o cap; muestra cuándo se obtiene cada skill, si requiere trainer, sus caps hasta y después de nivel 50, la guía de specialization y la ficha detallada de P99 Wiki.
- **Items & Notes** desde la Quick Bar guarda snapshots separados por personaje de `/outputfile inventory`; **Find dumps** recorre de forma segura toda la carpeta configurada de EverQuest y ofrece todos los exports válidos encontrados, incluido inventario/banco en subcarpetas, sin obligar a buscar cada archivo a mano. Permite buscar, filtrar por ubicación, ajustar cantidades, quitar filas, deshacer y restaurar hasta cinco imports anteriores sin modificar el archivo de EverQuest. Las notas se guardan automáticamente fuera del ejecutable. Al escribir `@` aparece un selector de Items, Quests y Zones; la vista previa convierte las referencias en enlaces que abren las fichas internas de Vantage. **Make sticky** convierte la misma nota —sin duplicarla— en una ventana borderless pequeña, flotante y siempre visible; se mueve desde su tirador y se redimensiona desde la esquina, guarda en vivo desde ambos lugares y reaparece con su geometría después de reiniciar. Cerrar sólo la oculta y **Unpin** la devuelve a Notes sin borrar su contenido. Device Sync comparte también el texto, el estado sticky y la geometría entre las PCs enlazadas.
- **Log Searcher** tiene un botón propio en Quick Bar. Encuentra recursivamente todos los `eqlog_*.txt` de la carpeta enlazada, incluidos los archivados, y crea un índice SQLite local incremental sin modificar los originales. Permite buscar por texto, personaje/servidor, conversaciones, muertes, loot, cambios de zona, combate o sistema y por fecha; mientras Vantage escucha el log, sólo añade las líneas nuevas. Las columnas son ajustables y se pueden copiar varias filas completas.
- **Sounds** reúne las rutas automáticas y todas las acciones de sonido configuradas en triggers. Incluye 20 WAV originales CC0, prueba inmediata y carga de WAV propios a almacenamiento portable; cada Smart Timer todavía puede tener su alarma individual. El mute maestro de Quick Bar es el bloqueo final del backend de audio: detiene WAV y TTS activos o en cola y bloquea también pruebas y repeticiones mientras siga encendido. El riel del Quick Bar separa y nombra cada aviso como **Buffs / Spells**, **Combat / Timers**, **Market**, **Guild DKP**, **Chat** o **System**, describe qué ocurrió y nunca reemplaza ese dato con el nombre interno del módulo o del archivo de audio. Buffs & Triggers no suena oculto por defecto; Smart Timers conserva sus alarmas críticas en segundo plano por defecto. Una línea `worn off` nunca reproduce a la vez el sonido de la barra y el de un trigger coincidente. Los overlays independientes de alertas y timers se pueden desbloquear, mover, redimensionar y volver a fijar; permiten hasta 20 filas reales, agrupar por personaje con encabezados compactos, agrupar repetidos, escoger orden, peso/tamaño/familia tipográfica, barras y fondo. Se puede borrar incluso el último overlay para dejar cero superficies y desactivar por completo las notificaciones en pantalla; al crear otro, las rutas vuelven a estar disponibles. Una vez bloqueados no toman foco ni bloquean el juego.
- Estado de logs honesto en la bandeja: `WAITING` al vincular la carpeta, `ONLINE` cuando llegan líneas nuevas, `QUIET` tras 90 segundos sin actividad y `NO LOGS` cuando falta la ruta. `Log Profiles…` muestra cada personaje/servidor por separado. La ayuda integrada explica `/log on` y cómo seleccionar `EverQuest\Logs`.
- Ciclo de camp basado únicamente en mensajes confirmados del log: la línea exacta de “5 more seconds” inicia una confirmación de seis segundos; abandonar camp la cancela. Al completarse, Vantage conserva por personaje los buffs propios y sus segundos restantes, limpia solo esas filas y el marcador `/loc`, muestra un estado compacto sin sonido y restaura una sola vez al recibir `Welcome to EverQuest!`. Los perfiles de logs simultáneos permanecen aislados.
- Archivado horario de logs grandes, apagado por defecto. El usuario elige un umbral de 1–2,048 MB; Vantage mueve únicamente `eqlog_*_*.txt` a `EverQuest\Logs\archive` con fecha y nombre sin colisiones. No borra archivos, no toca otros `.txt` y avisa en un overlay propio si mueve algo o si Windows conserva el archivo en uso.
- **EverQuest Friends Manager** en Ajustes → General: reconoce los sufijos Green/Blue/Red/Real-Test, encuentra los INI de personajes sin incluir `UI_`, fusiona y ordena nombres sin duplicados y sincroniza exactamente `Friend0`–`Friend99`. Antes de escribir exige confirmación y guarda una copia byte por byte en el perfil recuperable con **Restore Last Push**; nunca crea archivos junto al ejecutable.
- Biblioteca propia de triggers con árbol jerárquico, estados y colores heredables por personaje, patrón, duración fija o dinámica `{ts}`, zona, perfil, alerta, regex, TTS, clipboard, sonido y overlay configurables. Incluye countdown, stopwatch y repeating; múltiples early enders; acciones Ending/Ended; contador con reset; Match Log acotado con búsqueda, filtros, prueba en seco sobre líneas reales, perfil/zona, tiempo de evaluación, copia y CSV; e importación segura de `.gtp`, XML y `.gtt` con previsualización selectiva. Cada importación empieza apagada y editable, y cada log conserva un cursor independiente.
- Espacio de combate multivista: Overview, Player DPS, Damage Breakdown, Tanking, Hit Distribution, Charts, Threat, Spells, Direct Damage, Damage over Time, Damage Mods, Timeline, Healing, Fights, Pets, Loot, Randoms, Faction, Chat y búsqueda guardable en todos los `eqlog*.txt`. Incluye gráficas nativas de daño, DPS activo, healing y tanking con línea rolling de seis segundos, copia y PNG; Healing distingue los valores observables de Full/Overheal/FHPS no disponibles en P99; `/random` agrupa sets, duplicados, empates y ganador. Spells ofrece Caster Overview, comparación de casters seleccionados y casts por tiempo; conserva fizzles, interrupts, resists, reflects y blocks por caster sin atribuir nombres que el log de P99 no muestra. Damage Mods empareja el crítico reportado con el golpe real y sólo calcula bonus o penalty cuando ambos números son observables. **Parser Diagnostics** organiza Log Details por Melee, Defense, Direct Damage, DoT, Healing y Spells, añade Unmatched, búsqueda, copia y CSV, y permanece apagado por defecto; conserva como máximo 5,000 decisiones locales en memoria y nunca duplica chat. El navegador de Chat ofrece canales principales y unidos, conversaciones individuales y All Tells, selección múltiple, perfil, tiempo, texto, limpiar vista sin borrar, copiar mensajes o URL y guardar resultados. Conserva hasta 100,000 mensajes en `%LOCALAPPDATA%\Vantage` y carga solo los 20,000 más recientes en memoria. Permite combinar encuentros, combinar por nombre, renombrar y deshacer sin alterar el log; exporta la vista a CSV, la sesión a JSON, el encuentro completo a HTML/XML y el panel visible a PNG. También copia resúmenes EQ configurables, jugadores seleccionados, casters, damage modifiers, texto detallado, BBCode y HTML. Toda salida destinada a EQ es sólo clipboard: Vantage nunca escribe ni envía input al cliente. Corrige daño entrante por oponente, aprende `/pet leader`, une pet + owner, conserva historial acotado y publica DPS/tanking live y completed en cualquier overlay del usuario.
- **Heal Chain** local: reconoce anuncios configurables como `AAA - CH - tankname`, comandos `!KI1`–`!KI9`, interrupciones y quién sigue. Presenta rieles animados de 10 segundos por tanque, intervalo marcado, historial y aviso opcional cuando toca tu orden, sin conectarse a servidores externos. El medidor local de amenaza usa armas configurables, manos, procs, skills y hechizos visibles sin leer memoria del juego.
- Mapas clásicos suministrados por el usuario, con posición, capas Z, POI, waypoints y timers de mapa. La zona cambia automáticamente al leer zoning, `/who` u otros mensajes válidos del log; el mapa se puede arrastrar directamente con el puntero. Las etiquetas POI permanecen visibles al alejar el mapa, pero usan tipografía compacta de peso medio y se distribuyen alrededor de sus puntos sin taparse; un conector fino conserva la referencia cuando una zona densa necesita mover alguna. El lienzo nativo se ajusta a la zona y omite las hojas de glyphs/leyenda que no forman parte del plano.
- Mercado Green/Blue nativo con búsqueda y teclado directos. Su selector accesible recuerda el servidor elegido; listas, historial, caché de PigParse y comparación con Wiki Auction Tracker permanecen aislados por servidor. El compositor WTS/WTB continúa como herramienta separada.
- Filtros de equipo por clase, raza y slot usando el índice comunitario de P99 Wiki. PigParse sigue siendo la fuente principal; la ficha interna añade el Auction Tracker del Wiki para el servidor seleccionado y calcula un promedio 50/50 sólo cuando ambas referencias recientes difieren 30% o menos.
- Clic en el nombre del item abre una ficha nativa compacta con icono y estadísticas clásicas. También muestra quién lo dropea y dónde; NPC y zona abren fichas internas adicionales sin enviarte al navegador.
- Feed `/auction` local en tiempo real cuando el cliente de EverQuest recibe esos mensajes. **Sale Alerts** tiene búsqueda propia sobre lo escuchado durante la sesión y deja explícito que el personaje debe estar en EC Tunnel con `/log on`; la búsqueda principal del catálogo no lo filtra. Cambiar Green/Blue no borra ni transforma este historial local. Desde cualquier fila de precios o stats, **Watch sale** crea una alerta persistente; **Test alert** comprueba de inmediato el overlay. Cada match muestra artículo, vendedor y mensaje en el riel del Quick Bar aunque el usuario haya eliminado todos los overlays.
- El constructor WTS/WTB también copia un bloque para Discord: encabezado WTS o WTB, un item por línea, enlaces clicables a P99 Wiki y precio/cantidad cuando existen. Si supera el límite de Discord, el botón avanza por bloques numerados; Vantage sólo copia al portapapeles y nunca envía al canal.
- **OpenDKP** genérico desde la Quick Bar: acepta el subdominio o la dirección `guild.opendkp.com` de cualquier guild y conserva perfiles separados. Sin login permite consultar standings, personajes, asistencia, raids, loot, ajustes e historial de subastas. Las tablas ordenan correctamente fechas, DKP, niveles y cantidades; los historiales se pueden buscar por fecha, item, personaje y raid/evento. El login opcional habilita subastas activas, watchlist con notificaciones y pujas manuales confirmadas; la contraseña nunca se guarda y el token renovable queda protegido por Windows Credential Manager. La sesión se restaura al reiniciar y un fallo temporal de red no borra el token: Vantage vuelve a intentar la conexión. Sólo un rechazo definitivo del proveedor o **Disconnect** elimina esa credencial. Vantage no ofrece auto-bid ni actúa dentro de EverQuest.
- **Zones y Quests offline-first** incluyen 122 nombres/alias de zonas del índice de mapas y 906 quests del catálogo P99 dentro del ejecutable. La selección siempre produce una ficha local útil y ofrece mapa/enlace; Vantage muestra inmediatamente la última copia cacheada y actualiza sólo la página escogida en segundo plano. Un fallo, timeout o página Wiki sin tabla dinámica ya no vacía la vista ni presenta una zona válida como inexistente. El catálogo completo de quests se actualiza una vez por sesión y cada detalle exitoso queda guardado para usos posteriores sin conexión.
- Evaluación prudente de precios mediante mediana robusta: conserva todos los valores de PigParse, reduce el peso del spam repetido y solo marca outliers.
- Vista móvil personal de solo lectura con Smart Timers, Market y **EverQuest Live**. Market sigue automáticamente el servidor Green/Blue seleccionado en la PC. Una ventana de configuración separada detecta `eqgame.exe` con una búsqueda local acotada o acepta cualquier ruta elegida por el usuario; transmite a 2/5/10 FPS sólo mientras la pestaña está abierta y nunca ofrece controles.
- Todos los controles interactivos, pestañas y encabezados de tablas tienen tooltip semántico; los controles también conservan nombre accesible, foco visible y navegación por teclado. **Reducir movimiento y flashes** mantiene las señales por texto/color/sonido sin parpadeo.
- **Device Sync** aparece como **Sync My PCs** directamente en la Quick Bar y también en Ajustes → General. Enlaza 2, 3 o más PCs con un código de una sola vez y aprobación en la PC que invita. No crea cuentas. El emparejamiento queda guardado y se reconecta automáticamente por descubrimiento directo o relay cifrado cuando ambas PCs están online. Sincroniza las preferencias seleccionadas —incluidos los opt-ins de actualización automática—, Smart Timers completos (zonas, fases y countdowns activos), tamaño/layout de ventanas, Items & Notes y únicamente los Socials WTS/WTB administrados por Vantage del mismo personaje; hace los respaldos normales antes de tocar esos INI. Rutas locales de EverQuest, logs y su índice, cachés, passwords, tokens y credenciales nunca salen de su PC.
- Enlace móvil gratuito y efímero con QR mediante Cloudflare Quick Tunnel, o acceso directo por Wi-Fi local. Cada sesión usa un token nuevo y desaparece al detenerla o cerrar la aplicación.

## Fuentes de datos y procedencia

- Fuente de verdad del mercado: [PigParse Green](https://pigparse.azurewebsites.net/ServerIndex/Green) o [PigParse Blue](https://pigparse.azurewebsites.net/ServerIndex/Blue), según el selector persistido, mediante su API pública. Sus listas, historiales y cachés nunca se mezclan entre servidores; `getall` se reconstruye cada 10 minutos.
- Referencia secundaria: [Project 1999 Wiki Auction Tracker](https://wiki.project1999.com/Special:AuctionTracker). Vantage extrae 30d/90d e historial reciente para el servidor seleccionado, lo conserva en su caché correspondiente y lo presenta por separado. Sólo participa en un estimado combinado cuando coincide razonablemente con PigParse; el promedio histórico total nunca se usa para estimar.
- Metadatos de clase, raza y slot: snapshot comunitario de P99 Wiki publicado por [P99 Planner](https://p99planner.com/). No se usa como fuente de precios.
- Feed local: archivo de log del propio cliente EverQuest.
- Respawns por zona: snapshot normalizado de un [catálogo comunitario de respawns](https://github.com/perotan/respawntimer), contrastado con los nombres cortos de las 121 zonas incluidas. Vantage conserva notas y marca los huecos de la fuente.
- Datos de guild y subastas: API pública y autenticada de [OpenDKP](https://www.opendkp.com/). Cada guild se identifica por su propio subdominio; Vantage consulta los datos directamente y no mantiene un servidor intermediario.

## Privacidad y rendimiento

El parser trabaja por eventos; no reescanea continuamente todo el log. Un único router atiende los menús de los paneles en lugar de multiplicar observadores globales, los SVG se reutilizan en caché y las ventanas principales usan el tipo Tool de Windows para no crear botones temporales en la barra de tareas. La búsqueda histórica sólo recorre los logs cuando el usuario la solicita y lo hace en segundo plano, sin reescribirlos. Combat guarda cada encuentro en SQLite hasta que el usuario elimina filas o limpia el historial, pero sólo mantiene el grupo reciente configurado en RAM. Chat, loot, Heal Chain y diagnóstico crudo conservan límites de memoria; el diagnóstico está apagado de fábrica y, al activarlo, guarda sólo 5,000 decisiones en RAM hasta cerrar la app. Los archivos locales no se crean junto al ejecutable. Los relojes se actualizan una vez por segundo y el mercado usa una tabla virtualizada. La aplicación no incluye Chromium ni WebView; Spell Library usa el visor de texto nativo de Qt y elimina scripts, formularios e imágenes remotas del contenido Wiki. La ubicación compartida viene desactivada de fábrica.

La página móvil se sirve desde la PC únicamente mientras la sesión está activa. El token viaja en el fragmento del enlace, no se guarda en los logs del servidor, y las APIs requieren ese token. EverQuest Live usa una segunda llave exclusiva del QR Wi-Fi; la llave del túnel de Internet no puede solicitar imágenes del juego. La captura está apagada en cada inicio y sólo trabaja cuando el teléfono mantiene visible esa pestaña. Con WinEQ2, Vantage reconoce la superficie activa hija o propietaria y captura directamente la ventana del juego; al cambiar de aplicación se pausa para no exponer otra ventana. El teléfono muestra el motivo real si la captura debe esperar. El modo Internet descarga `cloudflared` sólo después de una confirmación explícita, valida su firma de Windows y usa un Quick Tunnel sin cuenta.

Vantage se distribuye como un único `Vantage.exe`: no requiere instalación, DLLs sueltas ni una carpeta junto al ejecutable. La configuración, caché, sonidos copiados, grabaciones de mapa y el componente opcional de Cloudflare se conservan en `%LOCALAPPDATA%\Vantage`. Puedes mover el ejecutable sin arrastrar archivos adicionales.

## Créditos y agradecimientos

Vantage contiene código GPL-3.0 extensamente modificado derivado del
[proyecto nParse y sus contribuidores](https://github.com/nomns/nparse).
Agradecemos también a [PigParse / EqTool](https://github.com/smasherprog/EqTool),
a las comunidades de [Project 1999 Wiki](https://wiki.project1999.com/) y
[P99 Planner](https://p99planner.com/), a la comunidad de mapas
[Brewall](https://github.com/RedGuides/brewall-maps) y a los datos comunitarios
de [respawntimer](https://github.com/perotan/respawntimer) por las referencias
descritas con precisión en `SOURCE-NOTICE.md`.

GINA y GamParse se reconocen únicamente como inspiración comunitaria y para
describir compatibilidad con flujos conocidos; no se presentan como proveedores
de código o recursos de Vantage. CoreUI Icons, Phosphor Icons, Noto Sans y las
dependencias incluidas conservan sus respectivas licencias, enumeradas en
`THIRD-PARTY-NOTICES.md`.

Estos agradecimientos no implican afiliación, patrocinio, aprobación o permisos
adicionales. Vantage es un proyecto comunitario independiente; no está afiliado
ni respaldado por Daybreak Game Company, EverQuest, Project 1999 ni los proyectos
comunitarios mencionados. Los nombres y marcas pertenecen a sus respectivos
propietarios.

Contacto oficial del proyecto:
[vantagecompanion@gmail.com](mailto:vantagecompanion@gmail.com). El contacto
comunitario del creador continúa siendo Discord `mindflux99`.

## Herramienta gratuita y uso en P99

Vantage se entrega gratuitamente y con código fuente GPL-3.0. **Buy me a coffee** es estrictamente voluntario: no compra el programa, acceso, actualizaciones ni funciones. Vantage es independiente y no está afiliado ni respaldado por Project 1999, EverQuest, sus titulares, PigParse ni las aplicaciones cuyos flujos públicos se estudiaron. No incluye código, arte, sonidos o bases de datos propietarios de esas aplicaciones; la compatibilidad con formatos de packs tampoco implica afiliación.

La sección pública de [P99 Rulings](https://wiki.project1999.com/Rulings#Log_Parsing_Programs) reproduce la regla de que los programas que parsean el log están permitidos mientras no controlen, respondan, manipulen o hagan macros automáticamente por el personaje. Vantage mantiene ese límite para toda función de parsing y nunca actúa dentro del cliente. Las reglas pueden cambiar y cada usuario debe consultar las vigentes. La vista móvil opcional se declara por separado: únicamente refleja píxeles de una ventana escogida por el usuario, permanece apagada al iniciar y no participa en el parsing ni controla el juego.

## Uso

1. Ejecuta `Vantage.exe` desde cualquier carpeta.
2. En EverQuest activa el logging con `/log on`.
3. En el icono de la bandeja, elige `Select Logs Folder…` y apunta a `EverQuest\Logs`. Vantage mostrará `WAITING` mientras escucha y cambiará a `ONLINE` cuando reciba actividad real. Abre `Log Profiles…` para ver el estado de cada personaje.
4. Abre `Timers`: por defecto, cada muerte de un named reconocido en la zona activa crea o reinicia su timer. Usa el selector del encabezado para alternar entre listas guardadas por zona o ver `All zones`.
5. Para entregar un camp, deja seleccionada su zona, pulsa **Share visible timers** o `Ctrl+Shift+S` y pega en el chat cada línea copiada. El Vantage del receptor la detecta automáticamente en el log, descuenta el tiempo desde la hora de creación y guarda cada timer en su zona; no cambia la ventana ni roba el foco. Los códigos repetidos y el eco del propio mensaje se ignoran, los nombres ya existentes se actualizan y los códigos caducan tras 24 horas. Sólo contienen nombres, zonas y estado temporal; los sonidos, colores y volúmenes locales del receptor se conservan.
6. Si prefieres sólo timers manuales, desactiva **Timers automáticos al morir mobs** en Ajustes → Smart Timers. También puedes crear un mob y definir respawn + kill estimado propio.
7. En `Timers`, pulsa el icono móvil para crear el QR. El teléfono muestra timers y buffs, Market, Spells, guild/DKP con selector de guild guardada, Zones con selector estable y recarga, Quests y la vista local opcional de EverQuest. **Save to Home** explica cómo añadir el enlace a la pantalla de inicio en iPhone o Android y avisa que, como el acceso privado pertenece a la sesión actual de Vantage, puede requerir un QR nuevo después de reiniciar el programa. Los controles móviles modifican únicamente timers dentro de Vantage; nunca envían input al juego.
8. Abre `Heal Chain` desde la bandeja y configura tu formato/orden en **Ajustes → Heal Chain** si participas en una rotación de Complete Heal.
9. Para mantener la misma lista de amigos en todos tus personajes, abre **Ajustes → General → Character friends → Manage Friends**, elige el servidor, edita un nombre por línea y confirma **Push to Files**.

## Apoyar el proyecto

La bandeja, Quick Bar y la ventana **About Vantage** incluyen un botón visible
**Buy me a coffee**. El botón abre Buy Me a Coffee en el navegador predeterminado;
Vantage nunca recibe datos bancarios ni bloquea funciones según el aporte. El
botón de patrocinio del repositorio se configura mediante `.github/FUNDING.yml`.

## Desarrollo

Requiere Python 3.10+ y PySide6. Ejecuta las pruebas con `pytest`. El empaquetado para Windows usa `vantage_app.py`, `vantage.spec` y PyInstaller.

## Licencia

Distribuido bajo GNU GPL v3; consulta `LICENSE` y `SOURCE-NOTICE.md` para los avisos legales obligatorios.

## VantageUI

Companion incluye un panel independiente **VantageUI** para instalar y mantener
la skin opcional incluida en este repositorio. Cada lanzamiento UI se instala en
una carpeta propia como `EverQuest\uifiles\VantageUI-v1.44.80`; la carpeta
legada `VantageUI` permanece intacta. El actualizador verifica los archivos,
conserva solamente la selección activa y una versión anterior de respaldo, y
solo elimina versiones administradas más antiguas que sigan intactas. La activa
y el destino de restauración siempre se conservan, incluso con cambios locales. Las
carpetas modificadas se conservan con aviso y las no administradas no se adoptan
ni se inspeccionan. Por defecto EverQuest debe estar cerrado; el modo opcional
para instalar una carpeta nueva con el juego abierto siempre difiere la limpieza.
Vantage nunca termina el proceso ni modifica otras skins, enlaces, los INI de
personaje sin prefijo `UI_`, binarios del juego o la instalación de
Companion. Con **Keep every character on the installed VantageUI version** activo,
Companion crea un restore point y cambia solamente `UISkin` en todos los perfiles
P99 detectados y en `eqclient.ini`. Si EverQuest está abierto, conserva la tarea
pendiente y la ejecuta automáticamente al cerrar el juego para que EQ no pueda
sobrescribir los INI. “Activa” es la selección del actualizador, no la skin
cargada por EverQuest: después de instalar, copia el comando mostrado, por
ejemplo `/loadskin VantageUI-v1.44.80 1`, y verifica la
interfaz dentro del juego. Restaurar solo selecciona una versión anterior que
siga íntegra; nunca sobrescribe sus archivos. Consulta [la documentación de
VantageUI](ui/README.md) para detalles técnicos y avisos.

**Character UI & layouts** es una acción separada y explícita. Puede cambiar
únicamente `UISkin` en todos los archivos `UI_<personaje>_<servidor>.ini` y en
`eqclient.ini`, o copiar el layout completo de ventanas/chat de un personaje a
otros seleccionados. Nunca copia los INI de macros, socials, friends o hotkeys.
Cada lote crea primero un restore point verificado; una restauración también
respalda el estado que reemplaza. Si EverQuest está abierto, el lote queda en
cola hasta que el juego se cierre, sin intentar cerrar procesos. En carpetas
protegidas usa la solicitud normal de permiso de Windows y no altera ACLs.

La skin visual actual está sincronizada byte por byte con `ui/skin`. Cada
entrega se publica en el canal independiente de VantageUI; la instalación local
usa esa misma versión y no una copia aislada. Los controles de
archivos y geometría no sustituyen la comprobación visual dentro de EverQuest.
La publicación UI no incluye un nuevo `Vantage.exe`.
