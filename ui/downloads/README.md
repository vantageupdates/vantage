# VantageUI completas — últimas cuatro versiones

La opción principal es **1.44.109 (VBuff)**, la última vertical publicada.
Estos ZIPs contienen la skin completa, no el actualizador: una carpeta
`VantageUI-v<versión>` con sus 186 archivos XML e imágenes. El nombre del ZIP
identifica el layout; la carpeta que P99 carga mantiene su nombre numérico.

**Para tener ambas opciones en `uifiles`:** descarga el
[paquete completo VBuff + HBuff](VantageUI-BuffPair-v1.44.109-v1.44.110.zip?raw=true).
Contiene las dos carpetas: `VantageUI-v1.44.109` (vertical) y
`VantageUI-v1.44.110` (horizontal), con 186 archivos cada una. Copia ambas
dentro de `EverQuest\uifiles` siguiendo las precauciones de instalación.
Cada futura entrega tendrá las dos opciones de la misma base UI, también
como paquete completo, manteniendo la vertical como principal.

| Descargar skin completa | Buffs | Comando en P99 |
| --- | --- | --- |
| [1.44.109 (VBuff) — vertical principal](VantageUI-v1.44.109-VBuff.zip?raw=true) | Columna vertical con nombres | `/loadskin VantageUI-v1.44.109 1` |
| [1.44.110 (HBuff)](VantageUI-v1.44.110-HBuff.zip?raw=true) | Horizontal compacta, dos filas | `/loadskin VantageUI-v1.44.110 1` |
| [1.44.108 (H)](VantageUI-v1.44.108-H.zip?raw=true) | Horizontal compacta, dos filas | `/loadskin VantageUI-v1.44.108 1` |
| [1.44.107 (H)](VantageUI-v1.44.107-H.zip?raw=true) | Horizontal anterior, una fila más ancha | `/loadskin VantageUI-v1.44.107 1` |

## Instalación manual

1. Cierra P99 y descarga el ZIP de la opción que quieras.
2. Extrae el ZIP fuera de EverQuest. Copia su carpeta `VantageUI-v<versión>`
   dentro de `EverQuest\uifiles`. No debe quedar otra carpeta anidada por dentro.
3. Si esa versión ya existe, **no la sobrescribas**. Si la instaló el
   actualizador, úsala directamente con el comando; si fue modificada, conserva
   sus cambios y consulta antes de reemplazarla.
4. Abre P99 y escribe el comando de la tabla. El `1` conserva las posiciones
   guardadas de las ventanas; no convierte la UI en un layout responsive.

Los ZIPs no cambian tus INIs, socials, otras skins ni Companion. Requieren el
cliente P99/Titanium y sus recursos de UI default. Sus archivos son idénticos
a los de las versiones publicadas; este catálogo no añade una corrección
visual nueva ni certifica el renderizado dentro del juego.

## Si prefieres el actualizador

Usa [VantageUI-Updater 1.44.110](https://github.com/vantageupdates/vantage/releases/download/vantage-ui-v1.44.110/VantageUI-Updater.exe)
y pulsa **Check for updates → Update UI**: instala/verifica 109 (VBuff) y
110 (HBuff). Después puedes cargar la vertical con el comando de arriba.

Una instalación manual **no queda registrada** como instalación administrada.
El actualizador protege las carpetas no administradas y rechaza instalar sobre
una de ellas aunque sus archivos sean originales. Si quieres actualizaciones
administradas, usa el actualizador desde el principio; no crees ni edites
marcadores o el registro para intentar adoptar una carpeta manual.

## Procedencia e integridad

[catalog.json](catalog.json) registra tamaño, SHA-256 y número de archivos de
cada ZIP manual. [releases.json](releases.json) fija los tamaños y SHA-256 de
los manifests y payloads oficiales de los que se derivaron. Los tags originales
y sus archivos publicados no se reemplazan. El ZIP manual añade únicamente
la carpeta superior y compresión; no altera los XML ni las imágenes.
El catálogo identifica además la pareja actual y su ZIP de dos carpetas.

Los manifests originales también están guardados byte por byte en Git:
[107](VantageUI-v1.44.107.manifest.json),
[108](VantageUI-v1.44.108.manifest.json),
[109](VantageUI-v1.44.109.manifest.json) y
[110](VantageUI-v1.44.110.manifest.json).

Se conservan los [avisos de los assets](../THIRD-PARTY-NOTICES.md).
El código de Vantage no cambia la licencia de los assets de terceros.

Para futuras publicaciones se mantendrán en Git las últimas cuatro skins
completas y se destacará la última vertical. Las versiones anteriores siguen
disponibles en sus releases e historial; no se borran las skins del usuario.
Las versiones históricas 107/108 conservan su layout original `(H)`;
no se crean versiones verticales falsas bajo sus tags. La pareja actual
VBuff 109 / HBuff 110 es la entrega recomendada con ambas opciones.

## Reproducir el catálogo sin instalar nada

Obtén los manifests/payloads exactos de los cuatro tags fijados, verifica sus
digests públicos y pásalos en carpetas separadas al empaquetador offline:

```powershell
python scripts/archive_ui_skins.py --catalog ui/downloads/releases.json --release-dir .artifacts/candidate-ui110 --release-dir .artifacts/candidate-ui109 --release-dir .artifacts/candidate-ui108 --release-dir .artifacts/candidate-ui107 --output ui/downloads
python -m pytest tests/test_ui_skin_archive.py tests/test_ui_skin_package.py
```

El empaquetador valida las cuatro entradas antes de crear salidas y rechaza
reescribir un ZIP o catálogo existente con contenido distinto. La compresión
es reproducible con el mismo runtime; los SHA publicados identifican los
archivos entregados, no una promesa de igualdad entre versiones de zlib.

Para una entrega futura, fija las cuatro versiones publicadas más recientes
por versión numérica, prepara los ZIPs en una carpeta de salida nueva y revisa
el catálogo antes de actualizarlo en Git. Incluye siempre la pareja VBuff/HBuff
de la misma base UI; un cambio en cualquier otro asset entre sus opciones
rechaza el paquete pareado. Los ZIPs ya publicados y los tags no se reemplazan.
