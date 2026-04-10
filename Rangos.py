import requests
import time
import os
import json
import threading
import csv
import math
import re
import unicodedata
from datetime import datetime
from collections import deque

# =========================================================
# ⚙️ CONFIGURACIÓN GLOBAL (Cargada desde config.json)
# =========================================================
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
BINANCE_API_KEY = ""
BINANCE_API_SECRET = ""
WHALE_THRESHOLD_USD = 50000 
ALERTAS_SONORAS = True 

# =========================================================
# PALETA DE COLORES ANSI (Compatibilidad Máxima)
# =========================================================
RESET = '\033[0m'
GREEN = '\033[92m'
RED = '\033[91m'
CYAN = '\033[96m'
YELLOW = '\033[93m'
MAGENTA = '\033[95m'
BOLD = '\033[1m'
DARK_GRAY = '\033[90m'
BG_WHALE = '\033[41m' 
BG_LIQ = '\033[43m\033[30m'

if os.name == 'nt':
    os.system('color')

try:
    import websocket
except ImportError:
    print(f"{RED}¡Atención! Falta la librería 'websocket-client'.{RESET}")
    print(f"{YELLOW}Ejecuta: pip install websocket-client requests{RESET}")
    exit()

# =========================================================
# MEMORIA GLOBAL DEL MOTOR
# =========================================================
bids_local = {} 
asks_local = {}
trades_recientes = [] 
cluster_age = {'bids': {}, 'asks': {}} 
last_update_id = 0
snapshot_loaded = False
eventos_en_cola = []
obi_history = deque(maxlen=20) 
price_history = deque(maxlen=60) 
event_log = deque(maxlen=3) 
trade_timestamps = deque(maxlen=100) 
stats_sesion = {
    "compra": 0.0, "venta": 0.0, 
    "liq_buy": 0.0, "liq_sell": 0.0, 
    "cvd": 0.0, "vwap_sum": 0.0, 
    "vwap_vol": 0.0,
    "whale_buys": 0, "whale_sells": 0
}
volume_profile = {} 
liquidaciones = deque(maxlen=5)
latency = 0
start_time = time.time()
btc_price = 0.0
btc_trend = "Lateral"
next_funding_time = 0
ready_alert_sent = False 
session_high = 0.0
session_low = float('inf')
last_price = 0.0
velocity_score = 0.0 

simbolo_rest = "BTCUSDT" 
simbolo_ws = "btcusdt"
bin_size = 0.0 
auto_cluster_activo = False
ultimo_guardado_csv = time.time()
ultimo_telegram = 0 
funding_rate = 0.0 
microprice = 0.0

# =========================================================
# FUNCIONES DE DIBUJO Y ALINEACIÓN (MOTOR VISUAL BLINDADO)
# =========================================================

def largo_visible(texto):
    """Calcula la longitud visual exacta. ANSI = 0, Emojis = 2, Blocks = 1."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    texto_limpio = ansi_escape.sub('', str(texto))
    largo = 0
    for char in texto_limpio:
        if ord(char) == 0xFE0F:  # Ignorar Variation Selectors
            continue
        # Identificar Emojis y caracteres de ancho doble
        if unicodedata.east_asian_width(char) in ('W', 'F') or ord(char) > 0x2600:
            if 0x2500 <= ord(char) <= 0x25FF: # Caracteres de dibujo de cajas/bloques son ancho 1
                largo += 1
            else:
                largo += 2
        else:
            largo += 1
    return largo

def pad_texto(texto, ancho, align="center", fill=" "):
    """Alinea el texto asegurando que el ancho visual sea exactamente 'ancho'."""
    largo = largo_visible(texto)
    espacios = ancho - largo
    if espacios <= 0: return str(texto)
    
    if align == "center":
        izq = espacios // 2
        der = espacios - izq
        return (fill * izq) + str(texto) + (fill * der)
    elif align == "left":
        return str(texto) + (fill * espacios)
    else: # right
        return (fill * spaces) + str(texto)

def imprimir_linea_caja(contenido, align="center", color_borde=CYAN):
    """Dibuja una línea de caja con ancho interno estricto de 76."""
    ANCHO_INTERNO = 76
    texto_formateado = pad_texto(contenido, ANCHO_INTERNO, align=align)
    print(f"{color_borde}{BOLD}║{RESET}{texto_formateado}{color_borde}{BOLD}║{RESET}")

def imprimir_separador_caja(tipo="medio", color_borde=CYAN):
    """Dibuja separadores horizontales perfectos para ancho 76."""
    ANCHO_INTERNO = 76
    chars = {"top": ["╔", "═", "╗"], "medio": ["╠", "═", "╣"], "bot": ["╚", "═", "╝"]}
    c = chars.get(tipo)
    print(f"{color_borde}{BOLD}{c[0]}{c[1] * ANCHO_INTERNO}{c[2]}{RESET}")

def dibujar_barra_sentimiento(pct_compra, ancho_max=18):
    bloques_verdes = int((pct_compra / 100) * ancho_max)
    bloques_rojos = max(0, ancho_max - bloques_verdes)
    return f"{GREEN}{'█' * bloques_verdes}{RED}{'█' * bloques_rojos}{RESET}"

def dibujar_barra(cantidad, max_cantidad, color, ancho_max=24):
    if max_cantidad <= 0: return f"{DARK_GRAY}{'░' * ancho_max}{RESET}"
    longitud = max(1, int((min(cantidad, max_cantidad) / max_cantidad) * ancho_max)) if cantidad > 0 else 0
    return f"{color}{'█' * longitud}{DARK_GRAY}{'░' * (ancho_max - longitud)}{RESET}"

# =========================================================
# MOTOR LÓGICO Y COMUNICACIONES
# =========================================================

def calcular_auto_bin(precio):
    if precio <= 0: return 1
    raw = precio * 0.001 
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    return max(mag, round(raw / mag) * mag)

def enviar_telegram(mensaje):
    global ultimo_telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
        try:
            requests.post(url, data=data, timeout=5)
            ultimo_telegram = time.time()
        except: pass

def cargar_configuracion():
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BINANCE_API_KEY, BINANCE_API_SECRET, WHALE_THRESHOLD_USD
    archivo_config = 'config.json'
    if not os.path.exists(archivo_config):
        plantilla = {"BINANCE_API_KEY": "", "BINANCE_API_SECRET": "", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "", "WHALE_THRESHOLD_USD": 50000}
        try:
            with open(archivo_config, 'w', encoding='utf-8') as f: json.dump(plantilla, f, indent=4)
        except: pass
    else:
        try:
            with open(archivo_config, 'r', encoding='utf-8') as f:
                config = json.load(f)
                TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN", "")
                TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", "")
                BINANCE_API_KEY = config.get("BINANCE_API_KEY", "")
                BINANCE_API_SECRET = config.get("BINANCE_API_SECRET", "")
                WHALE_THRESHOLD_USD = config.get("WHALE_THRESHOLD_USD", 50000)
        except: pass

def guardar_csv(datos):
    try:
        with open('backtest_grids.csv', 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f); writer.writerow(datos)
    except: pass

def actualizar_datos_globales():
    global funding_rate, btc_price, btc_trend, next_funding_time
    while True:
        try:
            res_fut = requests.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={simbolo_rest}").json()
            if 'lastFundingRate' in res_fut:
                funding_rate = float(res_fut['lastFundingRate']) * 100
                next_funding_time = int((res_fut['nextFundingTime'] - time.time()*1000) / 60000)
            res_btc = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT").json()
            new_btc = float(res_btc['price'])
            if btc_price > 0:
                diff = new_btc - btc_price
                btc_trend = "ALZA ↑" if diff > 10 else "BAJA ↓" if diff < -10 else "ESTABLE"
            btc_price = new_btc
        except: pass
        time.sleep(15)

def obtener_snapshot():
    global bids_local, asks_local, last_update_id, snapshot_loaded
    url = f"https://api.binance.com/api/v3/depth?symbol={simbolo_rest}&limit=5000"
    try:
        response = requests.get(url); data = response.json()
        last_update_id = data['lastUpdateId']
        bids_local.clear(); asks_local.clear()
        for p, q in data['bids']: bids_local[float(p)] = float(q)
        for p, q in data['asks']: asks_local[float(p)] = float(q)
        snapshot_loaded = True
    except: pass

def on_message(ws, message):
    global snapshot_loaded, eventos_en_cola, trades_recientes, microprice, event_log, stats_sesion, trade_timestamps, volume_profile, latency, session_high, session_low, last_price, velocity_score
    data = json.loads(message)
    if 'stream' not in data: return
    stream_name = data['stream']; payload = data['data']
    if 'E' in payload: latency = int(time.time() * 1000) - payload['E']

    if '@aggTrade' in stream_name:
        p, q = float(payload['p']), float(payload['q']); vol = p * q
        trades_recientes.append({'ts': time.time(), 'vol': vol, 'is_sell': payload['m']})
        trade_timestamps.append(time.time()); price_history.append(p)
        stats_sesion["vwap_sum"] += vol; stats_sesion["vwap_vol"] += q
        if last_price > 0:
            # Multiplicador exponencial de velocidad (Detecta Pumps/Dumps instantáneos)
            velocity_score = (velocity_score * 0.85) + (abs(p - last_price) / last_price * 150000)
        last_price = p
        if p > session_high: session_high = p
        if p < session_low: session_low = p
        
        # Actualizar perfil de volumen tranzado real
        rounded_p = round(p / (bin_size if bin_size > 0 else 1)) * (bin_size if bin_size > 0 else 1)
        volume_profile[rounded_p] = volume_profile.get(rounded_p, 0) + vol
        
        if payload['m']: stats_sesion["venta"] += vol; stats_sesion["cvd"] -= vol
        else: stats_sesion["compra"] += vol; stats_sesion["cvd"] += vol
        if vol >= WHALE_THRESHOLD_USD:
            col = RED if payload['m'] else GREEN
            event_log.append(f"{col}BALLENA {'VENDIÓ' if payload['m'] else 'COMPRÓ'}: ${vol:,.0f}{RESET}")
            if payload['m']: stats_sesion["whale_sells"] += 1
            else: stats_sesion["whale_buys"] += 1
            
    elif '@forceOrder' in stream_name:
        o = payload['o']; vol_liq = float(o['p']) * float(o['q'])
        side = "LONG" if o['S'] == 'SELL' else "SHORT"
        event_log.append(f"{BG_LIQ}LIQUIDACIÓN {side}: ${vol_liq:,.0f}{RESET}")
        if side == "LONG": stats_sesion["liq_buy"] += vol_liq
        else: stats_sesion["liq_sell"] += vol_liq
            
    elif '@depth' in stream_name:
        if not snapshot_loaded: eventos_en_cola.append(payload)
        else:
            if eventos_en_cola:
                for ev in eventos_en_cola: aplicar_evento(ev)
                eventos_en_cola.clear()
            aplicar_evento(payload)

def aplicar_evento(data):
    global bids_local, asks_local, last_update_id
    if data['u'] <= last_update_id: return
    for p, q in data['b']:
        if float(q) == 0: bids_local.pop(float(p), None)
        else: bids_local[float(p)] = float(q)
    for p, q in data['a']:
        if float(q) == 0: asks_local.pop(float(p), None)
        else: asks_local[float(p)] = float(q)
    last_update_id = data['u']

def iniciar_websocket():
    while True:
        try:
            ws_url = f"wss://stream.binance.com:9443/stream?streams={simbolo_ws}@depth/{simbolo_ws}@aggTrade"
            ws_spot = websocket.WebSocketApp(ws_url, on_open=lambda w: threading.Thread(target=obtener_snapshot).start(), on_message=on_message)
            threading.Thread(target=ws_spot.run_forever, daemon=True).start()
            ws_liq_url = f"wss://fstream.binance.com/stream?streams={simbolo_ws}@forceOrder"
            ws_liq = websocket.WebSocketApp(ws_liq_url, on_message=on_message)
            ws_liq.run_forever()
        except: time.sleep(5)

# =========================================================
# BUCLE PRINCIPAL
# =========================================================

def main():
    global simbolo_rest, simbolo_ws, bin_size, auto_cluster_activo, cluster_age, obi_history, stats_sesion, microprice, ultimo_guardado_csv, ALERTAS_SONORAS, volume_profile, start_time, ready_alert_sent, session_high, session_low, velocity_score
    cargar_configuracion()
    
    os.system('cls' if os.name == 'nt' else 'clear')
    imprimir_separador_caja("top", CYAN)
    imprimir_linea_caja("RADAR HFT PRO - MOTOR QUANTUM (MODO INFALIBLE)", color_borde=CYAN)
    imprimir_separador_caja("bot", CYAN)
    
    par_input = input(f"\n» Moneda a analizar (Ej: BTCUSDT): ").strip().upper()
    if par_input: simbolo_rest = par_input; simbolo_ws = par_input.lower()
    bin_input = input(f"» Agrupación (Iguala al desplegable de Binance. Ej: 100. Enter=Auto): ").strip()
    if bin_input.replace('.', '', 1).isdigit(): bin_size = float(bin_input)
    else: auto_cluster_activo = True
    alert_input = input(f"» ¿Activar alertas sonoras (S/N)? ").strip().upper()
    ALERTAS_SONORAS = True if alert_input == "S" else False

    threading.Thread(target=iniciar_websocket, daemon=True).start()
    threading.Thread(target=actualizar_datos_globales, daemon=True).start()
    while not snapshot_loaded: time.sleep(0.5)
        
    while True:
        time.sleep(2)
        os.system('cls' if os.name == 'nt' else 'clear')
        if not bids_local or not asks_local: continue
            
        best_bid, best_ask = max(bids_local.keys()), min(asks_local.keys())
        precio_actual = (best_bid + best_ask) / 2
        microprice = ((best_bid * asks_local[best_ask]) + (best_ask * bids_local[best_bid])) / (bids_local[best_bid] + asks_local[best_ask])
        spread = best_ask - best_bid
        if auto_cluster_activo: bin_size = calcular_auto_bin(precio_actual)
            
        book_pressure = (sum(bids_local.values()) / (sum(bids_local.values()) + sum(asks_local.values()) or 1)) * 100
        precios_l = list(price_history)
        media_p = sum(precios_l) / len(precios_l) if precios_l else precio_actual
        stdev_p = math.sqrt(sum((x - media_p) ** 2 for x in precios_l) / len(precios_l)) if len(precios_l) > 1 else 0.01
        vol_z_score = (stdev_p / precio_actual) * 100

        # Punto de Control (POC) - El nivel con más volumen REAL intercambiado hoy
        poc_price = max(volume_profile, key=volume_profile.get) if volume_profile else precio_actual

        # =========================================================================
        # 🔍 MOTOR: IDENTIFICACIÓN DE IMANES AL 100% DEL LIBRO DE ÓRDENES
        # =========================================================================
        b_clust, a_clust = {}, {}
        for p, q in bids_local.items():
            if p < precio_actual:
                k = math.floor(p / bin_size) * bin_size; b_clust[k] = b_clust.get(k, 0) + q
        for p, q in asks_local.items():
            if p > precio_actual:
                k = math.ceil(p / bin_size) * bin_size; a_clust[k] = a_clust.get(k, 0) + q
            
        # Extraemos directamente las 5 concentraciones MÁS GRANDES de TODO el libro
        top_heavy_bids = sorted(b_clust.items(), key=lambda x: x[1], reverse=True)[:5]
        top_heavy_asks = sorted(a_clust.items(), key=lambda x: x[1], reverse=True)[:5]
        
        top_c = sorted(top_heavy_bids, key=lambda x: x[0], reverse=True)
        top_v = sorted(top_heavy_asks, key=lambda x: x[0])
        
        master_bid = top_heavy_bids[0] if top_heavy_bids else (precio_actual, 0)
        master_ask = top_heavy_asks[0] if top_heavy_asks else (precio_actual, 0)

        now = time.time(); mins_transcurridos = (now - start_time) / 60
        v_trades = sum(t['vol'] for t in trades_recientes)
        p_c_r = (sum(t['vol'] for t in trades_recientes if not t['is_sell']) / (v_trades or 1)) * 100
        obi_history.append(p_c_r)
        vwap = stats_sesion["vwap_sum"] / (stats_sesion["vwap_vol"] or 1)
        
        # --- NUEVO: SISTEMA DE MADUREZ DE DATOS ---
        if mins_transcurridos < 5:
            madurez_datos = f"{RED}CALIBRANDO {int((mins_transcurridos/5)*100)}%{RESET}"
        elif mins_transcurridos < 15:
            madurez_datos = f"{YELLOW}MEDIA ({(mins_transcurridos/15)*100:.0f}%){RESET}"
        elif mins_transcurridos < 60:
            madurez_datos = f"{GREEN}ALTA (Óptimo){RESET}"
        else:
            madurez_datos = f"{MAGENTA}MÁXIMA (God Mode){RESET}"

        status_motor = f"{YELLOW}{min(100, int((mins_transcurridos / 5) * 100))}%{RESET}" if mins_transcurridos < 5 else f"{GREEN}READY{RESET}"

        # PODER MACRO Y DETECCIÓN PARABÓLICA
        power_score = 0
        power_score += 25 if precio_actual > vwap else -25
        power_score += 25 if stats_sesion["cvd"] > 0 else -25
        power_score += 25 if btc_trend == "ALZA ↑" else -25 if btc_trend == "BAJA ↓" else 0
        power_score += 25 if book_pressure > 52 else -25 if book_pressure < 48 else 0
        
        # Kill Switch Activator
        is_parabolic = True if (velocity_score > 25 or abs(power_score) >= 85) else False
        m_state = f"{RED}PARABÓLICO (KILL SWITCH){RESET}" if is_parabolic else "EXPANSIÓN" if velocity_score > 12 or abs(power_score) > 60 else "ACUMULACIÓN" if velocity_score < 4 else "LATERAL"
        p_col = GREEN if power_score > 40 else RED if power_score < -40 else YELLOW

        # --- PANEL SUPERIOR ---
        imprimir_separador_caja("top", CYAN)
        imprimir_linea_caja(f"PAR: {simbolo_rest} | PRECIO: ${precio_actual:,.2f} | POC (Real): ${poc_price:,.2f}")
        imprimir_linea_caja(f"POWER: {p_col}{power_score:+d}{RESET} | ESTADO: {MAGENTA}{m_state}{RESET} | DATA: {madurez_datos}")
        imprimir_separador_caja("medio", CYAN)
        imprimir_linea_caja(f"MÁX SESIÓN: ${session_high:,.1f} | MÍN SESIÓN: ${session_low:,.1f} | PRESIÓN LIBRO: {book_pressure:.1f}%")
        imprimir_linea_caja(f"IMÁN ABSOLUTO SOPORTE: {GREEN}${master_bid[0]:,.2f}{RESET} | IMÁN ABSOLUTO RESIST: {RED}${master_ask[0]:,.2f}{RESET}")
        imprimir_separador_caja("bot", CYAN); print("")

        # --- LIBRO DE ÓRDENES VISUAL ---
        print(f"{RED}{BOLD}▼ MAYORES CONCENTRACIONES DE VENTA (100% DEL LIBRO) ▼{RESET}")
        imprimir_separador_caja("top", CYAN)
        max_vol_view = max(max([v for _, v in top_c] or [0.1]), max([v for _, v in top_v] or [0.1]))
        for p, q in reversed(top_v):
            d = ((p - precio_actual) / precio_actual) * 100; m = "[*]" if now - cluster_age['asks'].get(p, {}).get('ts', now) > 30 else "[+]"
            tag = " MAESTRO" if p == master_ask[0] else m
            p_s, d_s, q_s = f"${p:,.2f}", f"+{d:.2f}%", f"{q:,.1f}{tag}"
            row = f" {RED}{p_s:<13}{RESET} │ {RED}{d_s:<9}{RESET} │ {RED}{q_s:<17}{RESET} │ {dibujar_barra(q, max_vol_view, RED, 26)} "
            imprimir_linea_caja(row, align="left", color_borde=CYAN)
        
        sep_spread = pad_texto(f"[ PRECIO ACTUAL: ${precio_actual:,.2f} | SPREAD: ${spread:,.2f} ]", 76, fill="━")
        imprimir_linea_caja(f"{CYAN}{BOLD}{sep_spread}{RESET}", color_borde=CYAN)
        
        for p, q in top_c:
            d = ((precio_actual - p) / precio_actual) * 100; m = "[*]" if now - cluster_age['bids'].get(p, {}).get('ts', now) > 30 else "[+]"
            tag = " MAESTRO" if p == master_bid[0] else m
            p_s, d_s, q_s = f"${p:,.2f}", f"-{d:.2f}%", f"{q:,.1f}{tag}"
            row = f" {GREEN}{p_s:<13}{RESET} │ {GREEN}{d_s:<9}{RESET} │ {GREEN}{q_s:<17}{RESET} │ {dibujar_barra(q, max_vol_view, GREEN, 26)} "
            imprimir_linea_caja(row, align="left", color_borde=CYAN)
        imprimir_separador_caja("bot", CYAN)
        print(f"{DARK_GRAY} LEYENDA: [*] Sólido | [+] Reciente | MAESTRO: Muro Absoluto del 100% del Libro{RESET}\n")
            
        # --- TERMÓMETRO ---
        avg_obi = sum(obi_history) / len(obi_history) if len(obi_history) > 0 else 50
        o_t = "SUBIENDO (+)" if p_c_r > avg_obi + 1 else "BAJANDO (-)" if p_c_r < avg_obi - 1 else "ESTABLE (=)"
        imprimir_separador_caja("top", CYAN)
        imprimir_linea_caja(f"{BOLD}PRESIÓN COMPRADORA VS VENDEDORA (60s){RESET}")
        imprimir_separador_caja("medio", CYAN)
        row_sent = f"[{dibujar_barra_sentimiento(p_c_r)}] Compra:{p_c_r:.0f}% Venta:{100-p_c_r:.0f}% | TREND: {GREEN if '(+)' in o_t else RED if '(-)' in o_t else YELLOW}{o_t}{RESET}"
        imprimir_linea_caja(row_sent)
        imprimir_separador_caja("bot", CYAN); print("")

        # =========================================================================
        # 🧠 NUEVO MOTOR: INFALIBILIDAD Y RANKING MATEMÁTICO ESTRÍCTO
        # =========================================================================
        posibles_rangos = []
        max_comb_vol = (master_bid[1] + master_ask[1]) if (top_heavy_bids and top_heavy_asks) else 1
        base_profit = 0.18 if "ACUMULACIÓN" in m_state else 0.40 
        
        for b_p, b_v in top_heavy_bids:
            for a_p, a_v in top_heavy_asks:
                if a_p <= b_p: continue
                amp = ((a_p - b_p) / b_p) * 100
                vol_total = b_v + a_v
                
                desequilibrio_vol = ((a_v - b_v) / vol_total) * 100 if vol_total > 0 else 0
                fuerza_direccional = power_score - (desequilibrio_vol * 0.5)
                
                if fuerza_direccional >= 35:
                    est_name = "GRID LONG"
                    logica_escape = "Escape al ALZA (USDT Protegido)"
                elif fuerza_direccional <= -35:
                    est_name = "GRID SHORT"
                    logica_escape = "Escape a la BAJA (USDT Protegido)"
                else:
                    est_name = "GRID NEUTRAL"
                    logica_escape = "Equlibrio (Rango seguro)"

                # -------------------------------------------------------------
                # SISTEMA DE PUNTUACIÓN INFALIBLE (Base 100)
                # -------------------------------------------------------------
                
                # 1. Liquidez Relativa Absoluta (Máx 40 puntos)
                vol_score = (vol_total / max_comb_vol) * 40
                
                # 2. Equilibrio Estructural (Máx 15 puntos)
                balance_score = ((100 - abs(desequilibrio_vol)) / 100) * 15
                
                # 3. Confirmación por Volumen Real Transaccionado (POC) (Máx 15 puntos)
                # Los muros son promesas, el POC es realidad. Si el muro se apoya cerca del POC, es sólido como roca.
                poc_dist_s = abs(b_p - poc_price) / poc_price
                poc_dist_r = abs(a_p - poc_price) / poc_price
                hist_score = 0
                if poc_dist_s < 0.02 or poc_dist_r < 0.02: hist_score = 15
                elif poc_dist_s < 0.05 or poc_dist_r < 0.05: hist_score = 8
                
                # 4. Amplitud Óptima para Grillas (Máx 10 puntos)
                width_score = 10 if 2.0 <= amp <= 40.0 else 5 if 0.5 <= amp < 2.0 else 0
                
                # 5. Confluencia con Extremos - Stop Loss Natural (Máx 10 puntos)
                struct_score = 0
                if b_p <= session_low * 1.002: struct_score += 5
                if a_p >= session_high * 0.998: struct_score += 5
                
                # 6. Alineación Direccional (Máx 10 puntos)
                dir_score = 0
                if (fuerza_direccional >= 25 and est_name == "GRID LONG") or \
                   (fuerza_direccional <= -25 and est_name == "GRID SHORT") or \
                   (-25 < fuerza_direccional < 25 and est_name == "GRID NEUTRAL"):
                    dir_score = 10

                # Suma base
                rango_score = vol_score + balance_score + hist_score + width_score + struct_score + dir_score
                
                # 🛑 KILL SWITCH PENALTY 🛑
                # Si el mercado está explotando o colapsando, armar una grilla es mortal.
                if is_parabolic:
                    rango_score -= 50
                    logica_escape = "⚠️ TENDENCIA FUERTE: NO OPERAR"

                rango_score = max(0, round(rango_score, 1)) # Nunca menor a 0
                
                posibles_rangos.append({
                    "soporte": b_p, "resist": a_p, "amp": amp,
                    "score": rango_score,
                    "estrategia": est_name,
                    "logica_escape": logica_escape
                })
        
        mejores_rangos = sorted(posibles_rangos, key=lambda x: x["score"], reverse=True)[:5]
        mejores_rangos.sort(key=lambda x: x["soporte"], reverse=True) 

        # --- TABLA DE GRIDS ---
        estrategias = []; n_rec, m_score = 0, -1
        
        imprimir_separador_caja("top", MAGENTA); imprimir_linea_caja(f"{BOLD}RANKING INFALIBLE DE RANGOS Y DIRECCIÓN DE ESCAPE{RESET}", color_borde=MAGENTA)
        imprimir_separador_caja("medio", MAGENTA)
        imprimir_linea_caja(f" Nvl │ Soporte  │ Resist.  │ Ancho  │ Grillas│ Score │      Estrategia      ", align="left", color_borde=MAGENTA)
        imprimir_linea_caja(f"{'─' * 5}┼{'─' * 10}┼{'─' * 10}┼{'─' * 8}┼{'─' * 8}┼{'─' * 7}┼{'─' * 22}", align="left", color_borde=MAGENTA)
        
        for i, rng in enumerate(mejores_rangos):
            s_magnet, r_magnet = rng["soporte"], rng["resist"]
            amp, score, est_final = rng["amp"], rng["score"], rng["estrategia"]
            num_grids = max(2, min(140, int(amp / base_profit)))
            
            p_col_grid = GREEN if score >= 75 else YELLOW if score >= 50 else RED
            col_final = GREEN if "LONG" in est_final else RED if "SHORT" in est_final else YELLOW
            
            estrategias.append((est_final, col_final, s_magnet, r_magnet, num_grids, score, rng["logica_escape"]))
            if score > m_score: m_score = score; n_rec = i
            
            c1_s = f">{i+1}<" if i == n_rec else str(i+1)
            c1_f = pad_texto(f"{YELLOW}{BOLD}{c1_s}{RESET}" if i == n_rec else c1_s, 5)
            row = f"{c1_f}│{pad_texto(f'{GREEN}${s_magnet:,.0f}{RESET}', 10)}│{pad_texto(f'{RED}${r_magnet:,.0f}{RESET}', 10)}│{pad_texto(f'{CYAN}{amp:.1f}%{RESET}', 8)}│{pad_texto(f'{BOLD}{num_grids}{RESET}', 8)}│{pad_texto(f'{p_col_grid}{score}%{RESET}', 7)}│{pad_texto(f'{col_final}{est_final}{RESET}', 22)}"
            imprimir_linea_caja(row, align="left", color_borde=MAGENTA)
        imprimir_separador_caja("bot", MAGENTA)
        
        # --- VEREDICTO FINAL ---
        if estrategias:
            e_r, c_r, s_r, r_r, g_r, score_r, logica_esc = estrategias[n_rec]
            sello = f" (ALTA CONFIANZA)" if score_r >= 80 else " (RIESGO PARABÓLICO)" if is_parabolic else " (RANGO VALIDADO)"
            
            imprimir_separador_caja("top", YELLOW)
            imprimir_linea_caja(f"🎯 RANGO GANADOR: {BOLD}{e_r}{RESET} (Score: {score_r}%)", color_borde=YELLOW)
            imprimir_linea_caja(f"📍 LIMITES: ${s_r:,.0f} - ${r_r:,.0f} |{sello}", color_borde=YELLOW)
            imprimir_linea_caja(f"⚙️ BINANCE BOT: {g_r} Grillas | Profit Est: {base_profit}%", color_borde=YELLOW)
            imprimir_linea_caja(f"💡 LÓGICA: {logica_esc}", color_borde=YELLOW)
            imprimir_separador_caja("bot", YELLOW)
            
            if mins_transcurridos >= 5 and not ready_alert_sent and not is_parabolic:
                msg = f"🌌 <b>REPORTE INFALIBLE: {simbolo_rest}</b>\n\n🎯 <b>ESTRATEGIA: {e_r}</b>\n✅ <b>Confianza: {score_r}%</b>\n📍 Rango Óptimo: ${s_r:,.0f} - ${r_r:,.0f}\n💡 Lógica: {logica_esc}"
                enviar_telegram(msg); ready_alert_sent = True

            if time.time() - ultimo_guardado_csv > 60:
                guardar_csv([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), simbolo_rest, round(precio_actual,2), n_rec+1, s_r, r_r, round(((r_r-s_r)/s_r)*100,2), e_r, f"{score_r}%"])
                ultimo_guardado_csv = time.time(); sv = "EXITO"
            else: sv = "ACTIVO"
        else: sv = "..."
        print(f"\n» API: {'ON' if BINANCE_API_KEY else 'OFF'} | LIQS: {RED}S:{stats_sesion['liq_sell']:.0f}{RESET} {GREEN}L:{stats_sesion['liq_buy']:.0f}{RESET} | CSV: {sv}")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print(f"\n{RED}Cerrando motor HFT...{RESET}")