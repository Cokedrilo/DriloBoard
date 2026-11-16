---
name: actualizar-driloboard
description: Saca una versión nueva de DriloBoard de principio a fin: sube VERSION, documenta el cambio (ayuda de la app y los dos README), hace commit, compila con build_macos.sh, la instala en ~/software/DriloBoard.app (la del Dock) y borra la anterior. Úsala siempre que Jorge diga "actualiza la versión", "actualiza, documenta e instala", "ponla en este ordenador", "sustituye la del Dock" o "saca la nueva versión", aunque no nombre la skill.
---

# Actualizar, documentar e instalar DriloBoard

Todo el flujo se hace sin volver a preguntar, salvo lo que se indica en el paso 5.
Trabaja en `/Users/jorgesarria/claude_scripts/DriloBoard`.

## 1. Decidir el número de versión
`VERSION = "X.Y.Z"` en `driloboard.py` (línea ~78). Mira `git log` desde el último
commit "DriloBoard X.Y.Z":
- función nueva o cambio visible importante → sube la **menor** (2.1.1 → 2.2.0);
- retoque o mejora pequeña de lo que ya había → sube el **parche** (2.1.0 → 2.1.1);
- cambio grande o que rompe cosas → la mayor (solo si Jorge lo pide).
Si Jorge dice el número, usa ese.

## 2. Documentar el cambio
Describe lo que cambió de cara al usuario en los tres sitios, en el mismo sitio donde
ya se habla de esa función (no hay changelog aparte):
- la ayuda de la app: el HTML de `help_html()` en `driloboard.py` (busca el apartado
  de la función, p. ej. `<h3>Videos</h3>`);
- `README.md` (inglés) y `README.es.md` (español), en su apartado de esa función
  y, si hay un atajo nuevo, en la tabla de atajos.
Frases cortas, en el estilo de lo que ya hay. No cambies los enlaces de descarga
del README salvo que Jorge pida publicar una release.

## 3. Comprobar
Si el cambio no tiene test, añade uno en `tests/` y apúntalo en `SUITES` de
`tests/correr_tests.py`. Ejecuta los tests que toquen (con
`QT_QPA_PLATFORM=offscreen .venv/bin/python tests/test_X.py`, con un tope de tiempo:
los de vídeo pueden colgarse al cerrar sin pantalla) y siempre `test_ayuda.py` y
`test_general.py`.

## 4. Commit
Un commit `DriloBoard X.Y.Z` con el cuerpo describiendo el cambio y la línea
`Co-Authored-By:` que indique el sistema. Si había cambios sin commitear de la
función, van en sus propios commits antes. No subas nada a GitHub ni crees release
salvo petición expresa.

## 5. Compilar
```bash
./build_macos.sh > /tmp/claude-501/build.log 2>&1; tail -3 /tmp/claude-501/build.log
```
Debe terminar con `selftest: OK` y `listo: dist/DriloBoard-X.Y.Z-portable-macos.zip`.

## 6. Instalar (la del Dock está en ~/software, NO en /Applications)
1. Mira si está abierta: `pgrep -fl "software/DriloBoard.app"`. Si lo está, **pregunta
   a Jorge si la cierras tú o la cierra él** y espera; no la mates.
2. Copia de seguridad de la biblioteca (que vive junto a la app):
   `cp ~/software/biblioteca.json ~/software/biblioteca.json.antes-X.Y.Z`
3. `rm -rf ~/software/DriloBoard.app` y
   `ditto dist/DriloBoard.app ~/software/DriloBoard.app` (mismo nombre, así el icono
   del Dock sigue funcionando).
4. Verifica: `codesign --verify --deep --strict ~/software/DriloBoard.app` y
   `defaults read ~/software/DriloBoard.app/Contents/Info CFBundleShortVersionString`.
5. No dejes copias en /Applications ni ejecutes `--selftest` sobre la app instalada
   (crea una carpeta de caché al lado). Deja en paz las carpetas archivadas
   `DriloBoard-X.Y.Z.app` de ~/software.

## 7. Cerrar
Dile a Jorge en pocas líneas: versión nueva, qué se documentó, que está instalada y
verificada, y que no se ha subido nada a GitHub.
