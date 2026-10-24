# PresentadorFotos NAS

Presentador de fotos para Ubuntu pensado para la biblioteca del NAS de Ricardo.

- Fuente predeterminada: `smb://dsplay214.local/photo/`.
- Busca recursivamente fotos cuyo nombre contenga `copia` o `ENC` (sin distinguir mayusculas).
- Filtra por ano y por uno o varios meses.
- Duracion configurable; valor inicial: 5 segundos y minimo seguro de 2 segundos.
- Presentacion aleatoria de una foto o collage de cuatro fotos.
- El orden se baraja sobre el conjunto global, no por carpetas. No hay repeticiones hasta agotar todas las fotos elegidas.
- Visor a pantalla completa, sin crear copias de las fotos.
- Modo ligero v1.1: decodifica cada foto directamente al tamano de pantalla
  (maximo 1920x1080), evita recargas durante el redimensionado y conserva solo
  40 pasos de historial.
- El lanzador usa prioridad baja y limita el proceso al 70 % de un nucleo, con
  aviso de memoria a 600 MB y limite absoluto de 850 MB para proteger GNOME.

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
