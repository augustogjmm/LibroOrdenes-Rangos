# \# 🌌 Radar HFT Pro - Motor Quantum (Modo Infalible)

# 

# Este repositorio contiene una herramienta avanzada de \*\*High-Frequency Trading (HFT)\*\* y análisis de microestructura de mercado desarrollada en \*\*Python\*\*. El motor está diseñado para identificar "imanes de liquidez" en tiempo real y proponer estrategias de \*\*Grid Trading\*\* optimizadas mediante un sistema de puntuación matemática estricta.

# 

# \## 👤 Perfil del Desarrollador

# Proyecto liderado por un profesional con más de 25 años de trayectoria en \*\*Infraestructura IT y Resiliencia Operativa\*\* en el sector bancario de Buenos Aires, Argentina. Esta herramienta traslada el rigor de los sistemas financieros tradicionales al dinámico ecosistema de las criptomonedas.

# 

# \## 🛠️ Especificaciones Técnicas del Motor

# El script `Rangos.py` integra múltiples capas de análisis de datos:

# 

# \* \*\*Identificación de Imanes de Liquidez:\*\* Escaneo del 100% del Libro de Órdenes (Order Book) para detectar muros de compra/venta y concentraciones "Maestras".

# \* \*\*Análisis de Flujo de Órdenes (Order Flow):\*\* Seguimiento de operaciones de "Ballenas" (Whales), liquidaciones de mercado en tiempo real y cálculo de CVD (Cumulative Volume Delta).

# \* \*\*Sistema de Puntuación Infalible (Score 0-100):\*\* Algoritmo que califica rangos de trading basados en liquidez relativa, equilibrio estructural, cercanía al POC (Point of Control) y confluencia con extremos de sesión.

# \* \*\*Protección "Kill Switch":\*\* Detección automática de estados parabólicos para evitar la exposición en condiciones de alta volatilidad extrema.

# \* \*\*Interfaz Visual ANSI:\*\* Motor de renderizado en consola optimizado para baja latencia con alertas visuales de color.

# 

# \## 🚀 Instalación y Configuración

# 

# 1\.  \*\*Requisitos previos:\*\*

# &#x20;   \* Python 3.10 o superior.

# &#x20;   \* Librerías necesarias: `requests`, `websocket-client`.

# 

# 2\.  \*\*Clonar y configurar:\*\*

# &#x20;   ```bash

# &#x20;   git clone https://github.com/\[TU\_USUARIO]/radar-hft-pro.git

# &#x20;   cd radar-hft-pro

# &#x20;   ```

# 

# 3\.  \*\*Gestión de Credenciales:\*\*

# &#x20;   \* Crea un archivo `config.json` en la raíz (el script lo generará automáticamente si no existe).

# &#x20;   \* \*\*IMPORTANTE:\*\* Nunca compartas ni subas tus API Keys de Binance o tokens de Telegram. Asegúrate de que tu archivo `.gitignore` incluya `config.json` o cualquier archivo `.env`.

# 

# \## 🤝 Protocolo de Colaboración (Control de Calidad)

# Como senior en tecnología, valoro la precisión. Para contribuir a este proyecto, el flujo es estrictamente profesional para evitar errores o "trampas" en la lógica:

# 

# 1\.  \*\*Fork:\*\* Crea una copia del repositorio en tu perfil.

# 2\.  \*\*Pull Request (PR):\*\* Envía tus mejoras para revisión.

# 3\.  \*\*Auditoría:\*\* Todas las solicitudes serán auditadas línea por línea. No se integrará código que no esté debidamente documentado o que incluya dependencias externas innecesarias.

# 

# \## 📊 Estrategias Soportadas

# \* \*\*Grid Neutral:\*\* Para fases de acumulación o lateralización.

# \* \*\*Grid Long/Short:\*\* Con lógica de escape protegida según la dirección del Power Score.

# 

# \---

# 

# \## ⚠️ Disclaimer (Descargo de Responsabilidad)

# Este software es exclusivamente para fines educativos y de investigación técnica. El trading de activos digitales conlleva un riesgo elevado de pérdida de capital. El autor no se responsabiliza por decisiones financieras tomadas a partir de las sugerencias del algoritmo. \*\*La gestión del riesgo es responsabilidad total del usuario.\*\*

# 

# \## 📄 Licencia

# Distribuido bajo la licencia \*\*GNU GPLv3\*\*. El conocimiento debe ser libre, pero la autoría debe respetarse.

