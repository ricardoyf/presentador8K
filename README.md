# PresentadorFotos NAS

Presentador de fotos para Ubuntu pensado para la biblioteca del NAS de Ricardo.

- Fuente predeterminada: `smb://dsplay214.local/photo/`.
- Busca recursivamente fotos cuyo nombre contenga `copia` o `ENC` (sin distinguir mayusculas).
- Filtra por ano y por uno o varios meses.
- Duracion configurable; valor inicial: 3 segundos.
- Presentacion aleatoria de una foto o collage de cuatro fotos.
- El orden se baraja sobre el conjunto global, no por carpetas. No hay repeticiones hasta agotar todas las fotos elegidas.
- Visor a pantalla completa, sin crear copias de las fotos.

## Controles

- `Espacio`: pausa/reanuda.
- Flecha derecha o clic: siguiente grupo.
- Flecha izquierda: grupo anterior.
- `F` o `F11`: alterna pantalla completa.
- `Esc` o `Q`: cierra el pase.

## Instalacion

```bash
./instalar-ubuntu.sh
```

El instalador crea el comando `presentador-fotos` y el acceso directo `Presentador Fotos NAS` en el escritorio y en el menu de aplicaciones.

Requisitos de Ubuntu: Python 3, PyGObject/GTK 3 y GdkPixbuf (incluidos habitualmente en Ubuntu).
