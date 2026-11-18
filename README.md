# Libro de Órdenes y Rangos — Monitor de microestructura

Proyecto personal en Python para **investigar liquidez, flujo de operaciones y rangos de mercado** utilizando datos públicos de Binance. Es una herramienta de análisis, no un sistema institucional de high-frequency trading ni una garantía de resultados.

## Componentes principales

- Captura y procesamiento del libro de órdenes y operaciones mediante conexiones HTTP/WebSocket.
- Estimaciones de concentración de liquidez, delta acumulado y contexto de mercado.
- Interfaz de terminal con Rich, eventos y controles de sesión.
- Parámetros configurables y registros locales para análisis posterior.

## Requisitos e instalación

Python 3.10 o superior; las dependencias necesarias están en `requirements.txt`.

```bash
git clone https://github.com/augustogjmm/LibroOrdenes-Rangos.git
cd LibroOrdenes-Rangos
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python Rangos.py
```

En Windows, activar con `.venv\Scripts\activate` antes de instalar los paquetes.

## Archivos relevantes

- `Rangos.py`: implementación principal.
- `requirements.txt`: dependencias Python.
- `leeme.txt`: instrucciones adicionales de la versión original.
- `.gitignore`: archivos de ejecución y configuración que no deben versionarse.

## Seguridad y límites

El script contiene variables de configuración para integraciones opcionales. **No se deben insertar claves de API, tokens ni secretos en el código ni en archivos versionados.** Los libros de órdenes son instantáneas cambiantes; las concentraciones de liquidez no equivalen a órdenes ejecutadas ni garantizan movimientos de precio.

El proyecto es experimental y no se ha presentado una validación independiente de rendimiento, disponibilidad o rentabilidad. No constituye asesoramiento financiero.

## Sobre el autor

[Augusto García Juárez Matorras](https://www.linkedin.com/in/augustog/) — trayectoria en infraestructura y operaciones de tecnología financiera. Ver también [portfolio ejecutivo](https://github.com/augustogjmm/Radar/blob/main/PORTFOLIO.md).

Licencia: revisar [LICENSE](LICENSE).
