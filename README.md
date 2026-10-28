# PresentadorFotos NAS

Presentador de fotos para Ubuntu pensado para la biblioteca del NAS de Ricardo.

- Fuente predeterminada: `smb://dsplay214.local/photo/`.
- Busca recursivamente fotos cuyo nombre contenga `copia` o `ENC` (sin distinguir mayusculas).
- Filtra por un intervalo inclusivo de anos (por ejemplo, 2003-2005).
- Duracion configurable; valor inicial: 5 segundos y minimo seguro de 2 segundos.
- Presentacion de una foto o mosaico 2x2 de cuatro fotos Full HD.
- Primero indexa todo el intervalo y despues realiza una baraja global; asi elimina el sesgo cronologico de carpetas y meses.
- Cada foto aparece una sola vez por ciclo. En el mosaico no hay duplicados y tampoco se reutilizan las cuatro fotos de la pantalla inmediatamente anterior.
- Cuenta atras visible y parada automatica configurable; el valor predeterminado es 1 hora.
- Visor a pantalla completa, sin crear copias de las fotos.
- Modo ligero v2.3: decodifica cada foto directamente al tamano de su celda
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

## Comportamiento de la v2.3

Al pulsar Iniciar, el programa termina primero el indice de todo el intervalo elegido. Puede tardar unos segundos si el NAS contiene muchas fotos, pero evita que la presentacion avance por bloques de enero, febrero, marzo, etc. Una vez terminado el indice, mezcla la coleccion completa y abre el pase a pantalla completa.

## Instalacion

```bash
./instalar-ubuntu.sh
```

El instalador crea el comando `presentador-fotos` y el acceso directo `Presentador Fotos NAS` en el escritorio y en el menu de aplicaciones.

Requisitos de Ubuntu: Python 3, PyGObject/GTK 3 y GdkPixbuf (incluidos habitualmente en Ubuntu).
