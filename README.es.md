# DriloBoard - Image viewer and reviewer — manual en español

> El README público del proyecto está en inglés: [README.md](README.md).
> Este es el manual completo, que es como lo leo yo.

Tablero de imágenes para preparar material de clase: arrastras carpetas, ves
sus imágenes en miniatura, las clasificas en categorías propias, comparas dos
entre sí y las anotas encima.

**La interfaz del programa está en inglés**; estas instrucciones, en español.
Los nombres de botón van *en cursiva* tal y como aparecen en pantalla.

**Nada de esto toca tus archivos.** Ni las categorías, ni los recortes, ni los
dibujos: todo son instrucciones guardadas en `biblioteca.json` que se aplican
al vuelo. Una imagen puede estar en varias categorías a la vez, cualquier
edición se deshace meses después, y para obtener archivos ya editados está el
botón *Export*.

## Arrancar

**Versión portable (lo normal).** Descomprime
`DriloBoard-1.2-portable-win64.zip` donde quieras —disco, USB, carpeta de
red— y ejecuta `DriloBoard.exe`. No instala nada ni escribe en el registro.
La biblioteca y la caché de miniaturas se crean **dentro de esa misma
carpeta**, así que copiándola te llevas también toda la clasificación.

La primera vez Windows puede avisar de que el origen es desconocido (el
ejecutable no está firmado): *Más información* → *Ejecutar de todas formas*.

**Desde el código fuente.**

- Windows: doble clic en `DriloBoard.bat`.
- Linux: `./driloboard.sh` (la primera vez crea el entorno solo).

## Volver a empaquetar

```
.venv\Scripts\python.exe -m PyInstaller DriloBoard.spec --noconfirm
```

Hace falta tener instalado también `PySide6-Addons`, que es el que trae el
vídeo; si falta, `DriloBoard.exe --selftest` lo detecta y devuelve 1.
Deja `dist/DriloBoard/` lista para comprimir. Antes de comprimir, borra
`dist/DriloBoard/cache/` si existe: la crea cualquier ejecución de prueba y no
pinta nada en el paquete. El icono se regenera desde el
propio código, no hay archivos de diseño sueltos.

## Pasar las pruebas

```
.venv\Scripts\python.exe tests\correr_tests.py
```

Once suites que corren sin abrir ninguna ventana y usan su propio archivo de
estado, así que no pueden tocar tu `biblioteca.json`. Cubren, entre otras cosas, el mapeo de
coordenadas de recortes y dibujos en 14 combinaciones de transformaciones (y 9
más con giro libre), los dos temas, el marco azul de la selección, los
vídeos y sus fotogramas clave, y
—dos veces, contrastando marca de tiempo y tamaño— que ni editar ni exportar
modifican el archivo original.

## Ayuda dentro del programa

El botón **? Help** de arriba a la derecha (o la tecla `F1`) abre una guía con
todo lo que viene a continuación, en inglés como el resto de la interfaz. Se
queda abierta mientras trabajas, así que puedes ir siguiéndola.

## Cómo se usa

**Columna izquierda — Carpetas**
- Arrastra carpetas desde el Explorador (o botón *Add…*). Si sueltas un
  archivo, se añade su carpeta.
- Entre paréntesis va el número de imágenes de cada una.
- Selecciona varias con Ctrl/Mayús para ver sus imágenes juntas. Sin nada
  seleccionado se ven todas las carpetas.
- *Include subfolders*: cada carpeta principal (en negrita) pasa a ser un
  desplegable con las subcarpetas dentro, a cualquier profundidad. Se abren
  solas al marcar la casilla. El número de la principal es el total contando
  lo que hay dentro; el de cada subcarpeta, lo suyo.
  - Solo salen las subcarpetas que tienen imágenes; las ocultas se ignoran.
  - Al elegir una carpeta entran también sus subcarpetas. Elige una
    subcarpeta para ver únicamente ese tema.
  - *Remove* solo funciona sobre las carpetas principales.
- *Refresh* (o `F5`) relee el disco, por si añades imágenes con el visor
  abierto.
- **Sort**: *Manual* (arrastra las carpetas principales para colocarlas donde
  quieras), *A → Z* o *Z → A*. Arrastrar con un orden alfabético puesto vuelve
  solo a *Manual*. Las subcarpetas no se arrastran — su orden lo pone el
  disco — pero siguen el sentido elegido.
- El orden de esta columna manda en el de las miniaturas cuando tienes varias
  carpetas seleccionadas.

**Columna central — Miniaturas y vista previa**
- El deslizador *Size* va de 64 a 420 px.
- *Preview below* (o la tecla `V`) parte la columna en dos: las
  miniaturas arriba y la imagen seleccionada, grande, debajo. La divisoria se
  arrastra para dar más sitio a una u otra, y se recuerda al cerrar.
  - Basta con moverse por las miniaturas con las flechas: la de abajo va
    siguiendo la selección.
  - Rueda para zoom, arrastrar para mover, botón *Fit* o tecla `0` para
    reencuadrar.
  - Carga a **resolución completa**, así que puedes ampliar sobre un detalle
    sin que se emborrone. La decodificación va en segundo plano: mientras se
    abre una foto grande la ventana sigue respondiendo y el pie pone
    «opening…». Si pasas rápido de una imagen a otra, solo se carga la
    última.
  - Solo se reduce si la imagen pasa de 80 megapíxeles, para no agotar la
    memoria; en ese caso el pie lo avisa.
  - *Open large* abre la misma imagen a pantalla completa.
- **Comparar dos imágenes**: elige una miniatura y pulsa *Mark A* (o la
  tecla `A`); elige otra y pulsa *Mark B* (tecla `B`). Al marcar la segunda
  la comparación arranca sola: se superponen y aparece un deslizador de
  **opacidad**: a 0 % ves solo A, a 100 % solo B, y en medio la mezcla.
  - Las marcadas llevan una insignia **A** azul o **B** naranja en la
    esquina, así que siempre sabes cuáles son aunque estén lejos en la
    rejilla o en carpetas distintas.
  - Una imagen no puede ser A y B a la vez: marcar como B la que ya era A
    mueve la marca.
  - Las marcas **no se pierden** al navegar. Elegir otra miniatura cierra la
    vista de comparación, pero *Compare A/B* (tecla `C`) la relanza cuando
    quieras. *Clear the A/B marks* está en el clic derecho.
  - Atajo: si no hay marcas puestas y tienes exactamente dos seleccionadas,
    *Compare A/B* usa esas dos.
  - *Swap* cambia cuál va encima. *Exit compare* vuelve a la imagen suelta.
  - Si son de distinto tamaño, B se encaja dentro de A centrada y sin
    deformarse.
  - *Open large* se lleva la pareja y la opacidad tal cual.
- **Vídeos** (casilla *Videos*, **apagada por defecto**): al marcarla se buscan
  también mp4, mov, webm, mkv, avi… y entran en la rejilla con un distintivo
  ▶ y su duración. La casilla se recuerda al cerrar.
  - En la vista previa y en el visor grande el vídeo **abre en pausa**, para
    que no suene nada al pasar por las miniaturas. Debajo, play/pausa, barra
    para moverse (también en pausa, se ve el fotograma), tiempo y volumen. En
    el visor grande, `Espacio` reproduce y pausa.
  - Se clasifican en categorías igual que las imágenes, y *Export…* los copia
    tal cual. El editor y la comparación A/B son solo para imágenes: con un
    vídeo avisan en la barra de estado.
  - Quitar la casilla los esconde también de las categorías, pero no los
    desclasifica: al volver a marcarla siguen donde estaban.
  - **Fotograma a fotograma**: los botones a los lados de play, o `,` y `.`,
    retroceden o avanzan un fotograma (si estaba reproduciendo, pausa). Junto
    al tiempo sale el número de fotograma.
  - **Fotogramas clave**: `-` marca el fotograma actual, `Ctrl+,` y `Ctrl+.`
    saltan a la clave anterior o siguiente, y `Ctrl+-` borra la del fotograma
    en el que estás. Salen como rombos ámbar sobre la barra de tiempo, y un
    «◆ Keyframe» avisa cuando estás encima de una. Se guardan con la
    biblioteca (también al exportarla) y se deshacen con `Ctrl+Z`, sin que el
    vídeo vuelva al principio.
  - Cada botón enseña su atajo en un bocadillo al dejar el ratón encima.
  - Desde el código fuente hace falta `pip install PySide6-Addons`; sin él la
    casilla sale desactivada y lo explica. La versión portable ya lo lleva.
- Doble clic abre el visor grande: `←`/`→` pasan imágenes, rueda hace zoom,
  arrastrar mueve, `0` reencuadra, `F` o `F11` pantalla completa, `Esc` cierra.
- Clic derecho: abrir, abrir la carpeta contenedora, copiar ruta, asignar o
  quitar de categorías.
- Las miniaturas seleccionadas llevan un **marco azul** bien visible.
- Los puntos de color en la esquina indican a qué categorías pertenece.
- *Uncategorised only* deja a la vista lo que aún no has clasificado.

**Columna derecha — Categorías**
- *New* crea al primer nivel; *Subcategory* crea dentro de la que tengas
  seleccionada. *Rename* / *Delete* (borrar no toca ninguna imagen del
  disco; si la categoría tiene subcategorías, se van con ella y el aviso te
  dice cuántas).
- **Se anidan**: arrastra una categoría **encima** de otra para meterla
  dentro, o **entre dos** para colocarla a ese nivel. No se deja meter una
  categoría dentro de sí misma ni de una hija suya.
  - El número de una categoría con hijas es el total contando lo que hay
    dentro; el desglose está en el tooltip. Una imagen que esté en la madre y
    en la hija se cuenta una vez.
  - Los nombres no se repiten en todo el árbol: son la clave con la que se
    guardan las asignaciones.
- Para asignar: arrastra las miniaturas seleccionadas sobre la categoría, o
  usa el botón *Assign to selected category*, o `Ctrl+1` … `Ctrl+9`
  para las nueve primeras.
- *Show this category only* convierte el centro en el contenido de esa
  categoría **y el de sus subcategorías**, vengan las imágenes de la carpeta
  que vengan.
- **Sort**: igual que en las carpetas — *Manual* arrastrando, o *A → Z* /
  *Z → A*, que ordena dentro de cada nivel sin deshacer el anidamiento. Ojo:
  `Ctrl+1` … `Ctrl+9` siguen el orden que veas de arriba abajo, subcategorías
  incluidas, así que reordenar cambia también los atajos.

## Importar y exportar la biblioteca

Menú **Library** ▸ *Export library…* guarda en un archivo `.driloboard` **toda
la información que has ido creando**: carpetas, categorías con su anidamiento,
qué imagen está en cada una, y las ediciones con sus dibujos. Las imágenes no
van dentro — solo la clasificación.

**Las rutas se guardan relativas a una carpeta raíz común**, así que el archivo
sirve en otro ordenador o después de mover las imágenes de sitio. Al importar,
si esa carpeta no existe aquí, DriloBoard te pregunta dónde están ahora y
reapunta la clasificación entera de un golpe.

*Import library…* te deja elegir:

- **Replace** — sustituye lo que tengas por lo del archivo.
- **Merge** — funde ambos. Las categorías con el mismo nombre se juntan en vez
  de duplicarse, y **tus ediciones no se pisan**: si una imagen ya tenía la
  tuya, se conserva y el resumen te dice cuántas se saltaron.

Si alguna imagen clasificada no aparece donde dice el archivo, se te avisa pero
**no se borra de su categoría**: quizá sea un disco externo que no está
enchufado ahora.

Todo esto se deshace con `Ctrl+Z` como cualquier otra cosa.

Para qué sirve en la práctica: llevarte la clasificación de casa al instituto,
tener una copia de seguridad de las horas de clasificar, o pasarle a un
compañero tu organización de un tema para que la use con sus propias copias de
las imágenes.

## Editar imágenes

**La edición es no destructiva: tus archivos originales nunca se tocan.** Lo
que se guarda en `biblioteca.json` es una receta por imagen (recorte, giro,
volteo, ajustes), que se aplica al vuelo a la miniatura y a la vista previa.
Cualquier edición se puede deshacer en cualquier momento, incluso semanas
después.

- **Editor** (botón *Edit…*, tecla `E`, o clic derecho ▸ *Edit*):
  - Rotar 90° a izquierda o derecha, voltear en horizontal y en vertical.
  - **Girar los grados que quieras** con *Angle*: deslizador, o el valor
    exacto en la casilla (positivo, en el sentido del reloj; `0 °` lo quita).
    Mientras giras aparece una **rejilla** para enderezar a ojo, y todo el
    giro cuenta como un solo paso de deshacer. Las esquinas que quedan al
    descubierto son transparentes (blancas al exportar a JPG); recorta
    después para quitarlas. Si ya había recorte, sigue centrado en el mismo
    punto de la imagen, y los dibujos giran con ella.
  - **Recortar**: elige *Crop* y arrastra un rectángulo sobre la imagen.
    Puedes volver a recortar sobre el resultado, y *Remove crop* devuelve
    el encuadre completo. El recorte se guarda en coordenadas del original,
    así que girar después no lo estropea.
  - Brillo, contraste y blanco y negro.
  - **Dibujar encima**, estilo Recortes de Windows: *Pen*, *Highlighter*
    (grueso y transparente, deja ver lo de debajo), *Line*, *Arrow*,
    *Rectangle*, *Ellipse* y *Text* (pinchas y escribes).
    - **Diez colores** a un clic: los ocho del arcoíris (rojo, naranja,
      amarillo, verde, cian, azul, añil y violeta) más blanco y negro. El
      botón `…` abre el selector completo si necesitas otro. Al lado, el
      grosor.
    - La *Eraser* borra **el dibujo entero sobre el que pinchas**, no raspa
      píxeles. Cada trazo es un objeto: puedes quitar la flecha y dejar el
      círculo.
    - Los dibujos se guardan en coordenadas del original, así que **siguen a
      la imagen**: si luego rotas o recortas, se rotan y se recortan con ella.
    - Van al final de la receta, por eso un rotulador rojo sigue rojo aunque
      pongas la imagen en blanco y negro.
    - `Ctrl+Z` deshace trazo a trazo. *Clear drawings* los quita todos (y
      también se deshace).
  - *Move and zoom* es el modo normal: arrastrar y hacer zoom sin pintar nada.
  - **Tamaño de salida** en píxeles, con proporción bloqueada si quieres.
    Recortar recalcula el tamaño, porque el que hubiera era para el encuadre
    anterior.
  - *Reset all* deja la imagen como estaba.
  - **Zoom**: deslizador, botones `−` / `+`, rueda del ratón, o `Ctrl` `+` /
    `Ctrl` `−`. *Fit* (tecla `0`) encaja la imagen en la ventana; *100 %*
    pone un píxel de la imagen final en un píxel de pantalla. Mover el brillo
    o el contraste no te cambia el zoom; rotar o recortar sí reencuadra,
    porque cambia la imagen.
  - El editor **abre al instante con una copia reducida y carga el original
    entero por detrás**. Mientras tanto el pie pone «afinando…»; en cuanto
    llega, lo que ves pasa a ser nítido aunque amplíes al 800 %, y el zoom no
    da un salto al cambiarse. Con imágenes de más de 80 megapíxeles se
    trabaja sobre una versión reducida, para no agotar la memoria.
  - **`Ctrl+Z` deshace** paso a paso dentro del editor (`Ctrl+Y` o
    `Ctrl+Mayús+Z` rehace). Un arrastre completo de un deslizador cuenta como
    un solo paso, no como cien.
- **Ediciones rápidas sin abrir el editor**: clic derecho ▸ *Edit* ▸ rotar o
  voltear. Se aplican a **todas las imágenes seleccionadas** de golpe, útil
  para enderezar una tanda de fotos.
- Las imágenes editadas llevan un **marco verde** en la rejilla, para que
  sepas que lo que ves no es lo que hay en el archivo.
- **Exportar** (botón *Export…*): eliges una carpeta y se escriben ahí las
  copias ya editadas, a resolución completa, con el nombre original. Nunca se
  pisa un archivo que ya exista — se numera. Esto es lo que te llevas a la
  presentación. El editor tiene además *Export a copy…* para una sola.

## Tema oscuro o claro

El botón **Light / Dark** de arriba a la derecha, el menú *View* o `Ctrl+T`
cambian toda la aplicación, editor incluido. Se recuerda al cerrar; la
primera vez sigue al tema del sistema.

## Deshacer

`Ctrl+Z` deshace, `Ctrl+Y` (o `Ctrl+Mayús+Z`) rehace, y funciona en **toda la
ventana**, no solo al editar: ediciones, asignar y quitar imágenes de
categorías, crear, renombrar, borrar y anidar categorías, y añadir, quitar o
reordenar carpetas. Se guardan los últimos 40 pasos de la sesión.

- La barra de estado dice qué se ha deshecho («Undone: rotate right
  (12 images)»), para que no haya sorpresas.
- Borrar una categoría con subcategorías y deshacer las devuelve todas.
- La selección de imágenes se conserva al deshacer, para que puedas repetir
  sobre lo mismo.
- Las marcas A/B quedan fuera a propósito: deshacer una categoría no debería
  moverte la comparación que tenías montada.
- El historial es de la sesión: al cerrar el programa se pierde (lo hecho,
  no; eso está en `biblioteca.json`).

## Detalles

- Se guarda solo: carpetas, categorías, ediciones, dibujos, tamaño de
  miniatura, tema y posición de la ventana. En `biblioteca.json`, junto al programa — cópialo y llevas contigo
  toda la clasificación.
- Las miniaturas se cachean en la carpeta `cache\` del programa. Se puede
  borrar sin miedo: se regenera sola.
- **Límites pensados para bibliotecas grandes** (constantes al principio de
  `driloboard.py`, por si quieres tocarlos):
  - `THUMB_RAM_MB = 256` — tope de miniaturas en memoria. Al pasarlo se van
    soltando las que hace más que no miras. Sin esto, recorrer 10.000
    imágenes a 420 px se comía más de 4 GB.
  - `THUMB_QUEUE_MAX = 400` — peticiones de miniatura en espera. Se atiende
    primero lo último pedido, que es lo que tienes delante, y se descartan las
    de lo que ya has dejado atrás. Sin esto, saltar al final de una carpeta
    grande te hacía esperar a que se generaran todas las de en medio.
  - `CACHE_MAX_MB = 500` — tope de la caché en disco. Se poda al arrancar, en
    segundo plano, empezando por lo más antiguo; si borra algo te lo dice en
    la barra de estado. Además, al cambiar una edición se borra al momento la
    miniatura de la versión anterior.
- Formatos: los que soporte Qt — jpg, png, gif, bmp, webp, tiff, svg…
- Respeta la orientación EXIF de las fotos.
