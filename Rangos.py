import requests
import time
import os
import sys
import json
import threading
import csv
import math
from datetime import datetime
from collections import deque

# =========================================================
# ⚙️ CONFIGURACIÓN GLOBAL Y PERSISTENCIA
# =========================================================
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
BINANCE_API_KEY = ""
BINANCE_API_SECRET = ""
WHALE_THRESHOLD_USD = 50000 
ALERTAS_SONORAS = True 

try:
    import websocket
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.align import Align
    from rich import box
    from rich.text import Text
except ImportError:
    print("\033[91m¡Atención! Faltan librerías requeridas.\033[0m")
    print("\033[93mEjecuta: pip install websocket-client requests rich\033[0m")
    exit()

console = Console()

# =========================================================
# MEMORIA GLOBAL DEL MOTOR (MICRO + MACRO)
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
event_log = deque(maxlen=6) 
trade_timestamps = deque(maxlen=100) 

# Estadísticas con Persistencia
stats_sesion = {
    "compra": 0.0, "venta": 0.0, 
    "liq_buy": 0.0, "liq_sell": 0.0, 
    "cvd": 0.0, "vwap_sum": 0.0, 
    "vwap_vol": 0.0,
    "whale_buys": 0, "whale_sells": 0
}
volume_profile = {} 

# Datos Macro Institucionales
macro_data = {
    "ema200": 0.0, 
    "rsi_4h": 50.0, 
    "macro_poc": 0.0, 
    "macro_trend": "CALCULANDO...",
    "oi": 0.0,
    "ls_ratio": 1.0
}

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
atr_24h = 0.0 

simbolo_rest = "BTCUSDT" 
simbolo_ws = "btcusdt"
bin_size = 0.0 
auto_cluster_activo = False
ultimo_guardado_csv = time.time()
ultimo_telegram = 0 
funding_rate = 0.0 
microprice = 0.0

# =========================================================
# FUNCIONES MATEMÁTICAS MACRO (EMA, RSI) Y PERSISTENCIA
# =========================================================

def calculate_ema(prices, period):
    if len(prices) < period: return prices[-1] if prices else 0
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * k + ema
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1: return 50.0
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change); losses.append(0)
        else:
            gains.append(0); losses.append(abs(change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def cargar_memoria_sesion():
    global stats_sesion
    try:
        if os.path.exists('session_data.json'):
            with open('session_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                stats_sesion.update(data)
    except: pass

def guardar_memoria_sesion():
    try:
        with open('session_data.json', 'w', encoding='utf-8') as f:
            json.dump(stats_sesion, f)
    except: pass

# =========================================================
# FUNCIONES DE DIBUJO RICH
# =========================================================

def dibujar_barra_rich(cantidad, max_cantidad, color, ancho_max=12):
    if max_cantidad <= 0: return f"[dim]{'░' * ancho_max}[/]"
    longitud = max(1, int((min(cantidad, max_cantidad) / max_cantidad) * ancho_max)) if cantidad > 0 else 0
    return f"[{color}]{'█' * longitud}[/][dim]{'░' * (ancho_max - longitud)}[/]"

def dibujar_barra_sentimiento_rich(pct_compra, ancho_max=20):
    bloques_verdes = int((pct_compra / 100) * ancho_max)
    bloques_rojos = max(0, ancho_max - bloques_verdes)
    return f"[bold bright_green]{'█' * bloques_verdes}[/][bold bright_red]{'█' * bloques_rojos}[/]"

def emitir_sonido():
    if ALERTAS_SONORAS:
        sys.stdout.write('\a')
        sys.stdout.flush()

# =========================================================
# HILOS DE DATOS (API REST Y WEBSOCKETS)
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

def actualizar_datos_macro():
    """Hilo secundario para descargar contexto a largo plazo e institucional"""
    global macro_data
    while True:
        try:
            # 1. Velas Diarias (1D) -> EMA 200 y Tendencia
            res_1d = requests.get(f"https://api.binance.com/api/v3/klines?symbol={simbolo_rest}&interval=1d&limit=250").json()
            if isinstance(res_1d, list):
                closes_1d = [float(x[4]) for x in res_1d]
                ema_val = calculate_ema(closes_1d, 200)
                macro_data["ema200"] = ema_val
                
                if closes_1d:
                    cur_p = closes_1d[-1]
                    if cur_p > ema_val * 1.05: macro_data["macro_trend"] = "ALCISTA FUERTE"
                    elif cur_p > ema_val: macro_data["macro_trend"] = "ALCISTA"
                    elif cur_p < ema_val * 0.95: macro_data["macro_trend"] = "BAJISTA FUERTE"
                    else: macro_data["macro_trend"] = "BAJISTA"

            # 2. Velas de 4H (Últimos 30 días = 180 velas) -> RSI y POC Macro
            res_4h = requests.get(f"https://api.binance.com/api/v3/klines?symbol={simbolo_rest}&interval=4h&limit=180").json()
            if isinstance(res_4h, list):
                closes_4h = [float(x[4]) for x in res_4h]
                macro_data["rsi_4h"] = calculate_rsi(closes_4h, 14)
                
                vpvr_macro = {}
                m_bin = max(1, round((sum(closes_4h)/len(closes_4h)) * 0.005)) # Bin 0.5%
                for candle in res_4h:
                    c_close = float(candle[4])
                    c_vol = float(candle[5])
                    nivel = round(c_close / m_bin) * m_bin
                    vpvr_macro[nivel] = vpvr_macro.get(nivel, 0) + c_vol
                if vpvr_macro: macro_data["macro_poc"] = max(vpvr_macro, key=vpvr_macro.get)

            # 3. Datos Institucionales (Futuros) -> Open Interest y Long/Short Ratio
            res_oi = requests.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={simbolo_rest}").json()
            if 'openInterest' in res_oi:
                macro_data["oi"] = float(res_oi['openInterest']) * btc_price # Valor en USD aprox
                
            res_ls = requests.get(f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={simbolo_rest}&period=15m&limit=1").json()
            if isinstance(res_ls, list) and len(res_ls) > 0:
                macro_data["ls_ratio"] = float(res_ls[0]['longShortRatio'])

        except Exception as e: pass
        time.sleep(300) # Se actualiza cada 5 minutos

def actualizar_datos_globales():
    global funding_rate, btc_price, btc_trend, next_funding_time, atr_24h
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

            res_24 = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={simbolo_rest}").json()
            if 'highPrice' in res_24 and 'lowPrice' in res_24:
                atr_24h = float(res_24['highPrice']) - float(res_24['lowPrice'])

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
            velocity_score = (velocity_score * 0.85) + (abs(p - last_price) / last_price * 150000)
        last_price = p
        
        if p > session_high: session_high = p
        if p < session_low: session_low = p
        
        rounded_p = round(p / (bin_size if bin_size > 0 else 1)) * (bin_size if bin_size > 0 else 1)
        volume_profile[rounded_p] = volume_profile.get(rounded_p, 0) + vol
        
        if payload['m']: 
            stats_sesion["venta"] += vol; stats_sesion["cvd"] -= vol
        else: 
            stats_sesion["compra"] += vol; stats_sesion["cvd"] += vol
            
        if vol >= WHALE_THRESHOLD_USD:
            col = "bold bright_red" if payload['m'] else "bold bright_green"
            icon = "🦈" if vol < (WHALE_THRESHOLD_USD * 3) else "🐋"
            accion = "VENDIÓ" if payload['m'] else "COMPRÓ"
            event_log.append(f"[{col}]{icon} BALLENA {accion}: ${vol:,.0f}[/]")
            if payload['m']: stats_sesion["whale_sells"] += 1
            else: stats_sesion["whale_buys"] += 1
            emitir_sonido()
            
    elif '@forceOrder' in stream_name:
        o = payload['o']; vol_liq = float(o['p']) * float(o['q'])
        side = "LONG" if o['S'] == 'SELL' else "SHORT"
        col = "black on bright_yellow" if side == "LONG" else "white on bright_red"
        event_log.append(f"[{col}]💀 LIQ. {side}: ${vol_liq:,.0f}[/]")
        if side == "LONG": stats_sesion["liq_buy"] += vol_liq
        else: stats_sesion["liq_sell"] += vol_liq
        emitir_sonido()
            
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
# MOTOR GRÁFICO UX ESTRUCTURAL (MICRO + MACRO LAYOUT)
# =========================================================
def generar_interfaz(ctx):
    frames_radar = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    radar_anim = frames_radar[ctx['anim_tick'] % len(frames_radar)]

    # 1. ESTRUCTURA PRINCIPAL (LAYOUT BLINDADO)
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3)
    )
    layout["main"].split_row(
        Layout(name="left", ratio=4),
        Layout(name="right", ratio=6)
    )
    layout["left"].split_column(
        Layout(name="dom", ratio=6),
        Layout(name="term", ratio=2),
        Layout(name="events", ratio=3)
    )
    # Acomodamos la columna derecha para incluir el Panel MACRO side-by-side con MICRO
    layout["right"].split_column(
        Layout(name="dash_top", ratio=4), # Más espacio para la data Macro
        Layout(name="ranking", ratio=3),
        Layout(name="verdict", ratio=6)
    )
    layout["dash_top"].split_row(
        Layout(name="metrics", ratio=1),
        Layout(name="macro", ratio=1)
    )

    # ---------------------------------------------------------
    # HEADER GLOBAL
    # ---------------------------------------------------------
    f_hrs = int(ctx['next_funding_time']) // 60
    f_mins = int(ctx['next_funding_time']) % 60
    
    txt_h1 = f"[bold bright_cyan]{radar_anim} RADAR HFT QUANTUM[/] │ [bold white]PAR:[/] [bold bright_yellow]{ctx['simbolo']}[/] │ [bold white]PRECIO:[/] [bold bright_green]${ctx['precio_actual']:,.2f}[/] │ [bold white]MICRO:[/] [bright_cyan]${ctx['microprice']:,.2f}[/]"
    txt_h2 = f"[bold white]BTC:[/] ${ctx['btc_price']:,.0f} ({ctx['btc_trend']}) │ [bold white]FUNDING:[/] {ctx['funding_rate']:.4f}% ({f_hrs}h{f_mins}m) │ [bold white]SESIÓN:[/] {ctx['mins_transcurridos']:.1f}m"
    layout["header"].update(Panel(Align.center(txt_h1 + "\n" + txt_h2), border_style="bright_cyan", box=box.ROUNDED))

    # ---------------------------------------------------------
    # COLUMNA IZQUIERDA: DOM + TERMÓMETRO + EVENTOS
    # ---------------------------------------------------------
    dom_table = Table(box=box.SIMPLE_HEAD, expand=True, show_header=True, header_style="bold bright_white")
    dom_table.add_column("Precio", justify="left")
    dom_table.add_column("Dist", justify="right")
    dom_table.add_column("Vol", justify="right")
    dom_table.add_column("Mapa", justify="left")

    for p, q in reversed(ctx["top_v"]):
        d = ((p - ctx["precio_actual"]) / ctx["precio_actual"]) * 100
        m_tag = "[*]" if ctx["now"] - ctx["cluster_age"]['asks'].get(p, {}).get('ts', ctx["now"]) > 30 else "[+]"
        tag = " [bold bright_yellow]👑 MAESTRO[/]" if p == ctx["master_ask"][0] else f" [dim]{m_tag}[/]"
        dom_table.add_row(f"[bright_red]${p:,.2f}[/]", f"[bright_red]+{d:.2f}%[/]", f"[bright_red]{q:,.1f}{tag}[/]", dibujar_barra_rich(q, ctx['max_vol_view'], "bright_red", 12))

    dom_table.add_row(f"[dim]──────[/]", f"[dim]───[/]", f"[bold white on red]⏬ ASKS[/]", f"[dim]──────────────[/]")
    dom_table.add_row(f"[bold bright_cyan]${ctx['spread']:,.2f}[/]", f"[dim]GAP[/]", f"[bold white on green]⏫ BIDS[/]", f"[dim]──────────────[/]")

    for p, q in ctx["top_c"]:
        d = ((ctx["precio_actual"] - p) / ctx["precio_actual"]) * 100
        m_tag = "[*]" if ctx["now"] - ctx["cluster_age"]['bids'].get(p, {}).get('ts', ctx["now"]) > 30 else "[+]"
        tag = " [bold bright_yellow]👑 MAESTRO[/]" if p == ctx["master_bid"][0] else f" [dim]{m_tag}[/]"
        dom_table.add_row(f"[bright_green]${p:,.2f}[/]", f"[bright_green]-{d:.2f}%[/]", f"[bright_green]{q:,.1f}{tag}[/]", dibujar_barra_rich(q, ctx['max_vol_view'], "bright_green", 12))

    layout["dom"].update(Panel(dom_table, title="[bold white]📚 DOM (100% Top 5 Niveles)[/]", border_style="cyan", box=box.ROUNDED))

    t_col = "bright_green" if "(+)" in ctx["o_t"] else "bright_red" if "(-)" in ctx["o_t"] else "bright_yellow"
    term_str = f"[{dibujar_barra_sentimiento_rich(ctx['p_c_r'], 20)}]\nC: {ctx['p_c_r']:.0f}%  |  V: {100-ctx['p_c_r']:.0f}%\nFlujo (60s): [bold {t_col}]{ctx['o_t']}[/]"
    layout["term"].update(Panel(Align.center(term_str), title="[bold white]🌡️ TERMÓMETRO[/]", border_style="magenta", box=box.ROUNDED))

    events_str = "\n".join(reversed(ctx['event_log'])) if ctx['event_log'] else "[dim italic]Monitoreando red...[/]"
    layout["events"].update(Panel(events_str, title="[bold bright_red]🚨 EVENTOS EN VIVO[/]", border_style="bright_red", box=box.ROUNDED))

    # ---------------------------------------------------------
    # COLUMNA DERECHA: MICRO / MACRO + RANKING + VEREDICTO
    # ---------------------------------------------------------
    
    # 3A. Panel Micro (Tiempo Real)
    p_col = "bold bright_green" if ctx["power_score"] > 40 else "bold bright_red" if ctx["power_score"] < -40 else "bold bright_yellow"
    cvd_col = "bright_green" if ctx['cvd'] > 0 else "bright_red"
    met_grid = Table.grid(expand=True, padding=(0, 1))
    met_grid.add_column(justify="left")
    met_grid.add_row(f"⚡ [bold]Power:[/] [{p_col}]{ctx['power_score']:+d}[/] | 🧠 [bold]St:[/] [bold bright_magenta]{ctx['m_state']}[/]")
    met_grid.add_row(f"📉 [bold]CVD:[/] [{cvd_col}]{ctx['cvd']:+,.0f}[/] | ⚖️ [bold]VWAP:[/] ${ctx['vwap']:,.2f}")
    met_grid.add_row(f"🔥 [bold]POC Real:[/] [bright_yellow]${ctx['poc_price']:,.2f}[/]")
    met_grid.add_row(f"🐋 [bold]Whales:[/] [bright_green]{ctx['whale_buys']}[/]/[bright_red]{ctx['whale_sells']}[/] | 💀 [bold]Liqs:[/] [bright_green]${ctx['liq_buy']/1000:.0f}k[/]/[bright_red]${ctx['liq_sell']/1000:.0f}k[/]")
    layout["metrics"].update(Panel(met_grid, title="[bold white]⏱️ PULSO MICRO (Sesión)[/]", border_style="blue", box=box.ROUNDED))

    # 3B. Panel Macro (Largo Plazo & Institucional)
    m_data = ctx['macro_data']
    rsi_val = m_data['rsi_4h']
    rsi_estado = "Sobrecompra" if rsi_val > 70 else "Sobrevendida" if rsi_val < 30 else "Neutral"
    rsi_col = "bright_red" if rsi_val > 70 else "bright_green" if rsi_val < 30 else "bright_yellow"
    
    ema_val = m_data['ema200']
    ema_dist = ((ctx['precio_actual'] - ema_val) / ema_val) * 100 if ema_val > 0 else 0
    ema_col = "bright_green" if "ALCISTA" in m_data['macro_trend'] else "bright_red" if "BAJISTA" in m_data['macro_trend'] else "bright_yellow"
    
    ls_val = m_data['ls_ratio']
    ls_estado = "Peligro Longs" if ls_val > 2.5 else "Peligro Shorts" if ls_val < 0.7 else "Normal"
    ls_col = "bright_green" if ls_val > 1.5 else "bright_red" if ls_val < 0.7 else "bright_yellow"
    
    mac_grid = Table.grid(expand=True, padding=(0, 1))
    mac_grid.add_column(justify="left")
    mac_grid.add_row(f"🔭 [bold]Tendencia 1D:[/] [{ema_col}]{m_data['macro_trend']}[/] [dim]({ema_dist:+.2f}% dist)[/]")
    mac_grid.add_row(f"📈 [bold]EMA 200:[/] ${ema_val:,.2f} | 📊 [bold]RSI 4H:[/] [{rsi_col}]{rsi_val:.1f} ({rsi_estado})[/]")
    mac_grid.add_row(f"🧱 [bold]POC Histórico 30D:[/] [bright_cyan]${m_data['macro_poc']:,.2f}[/]")
    mac_grid.add_row(f"🏦 [bold]OI:[/] [dim]${m_data['oi']/1000000:.1f}M[/] | ⚖️ [bold]L/S Ratio:[/] [{ls_col}]{ls_val:.2f} ({ls_estado})[/]")
    layout["macro"].update(Panel(mac_grid, title="[bold white]🌍 VISIÓN MACRO INSTITUCIONAL[/]", border_style="bright_blue", box=box.ROUNDED))

    # 3C. RANKING TOP 5 RANGOS
    rank_table = Table(expand=True, border_style="magenta", header_style="bold bright_white", box=box.SIMPLE_HEAD)
    rank_table.add_column("#", justify="center")
    rank_table.add_column("Soporte", justify="left")
    rank_table.add_column("Resistencia", justify="left")
    rank_table.add_column("Ancho", justify="right")
    rank_table.add_column("Grillas", justify="center")
    rank_table.add_column("Score", justify="right")
    rank_table.add_column("Setup", justify="center")

    for i, rng in enumerate(ctx["mejores_rangos"]):
        p_col_grid = "bold bright_green" if rng["score"] >= 75 else "bold bright_yellow" if rng["score"] >= 50 else "bold bright_red"
        e_short = "🟢 LONG" if "LONG" in rng["estrategia"] else "🔴 SHORT" if "SHORT" in rng["estrategia"] else "🟡 NEUT"
        l_str = f"[bold black on bright_yellow] {i+1} [/]" if i == ctx["n_rec"] else str(i+1)
        num_grids = max(2, min(140, int(rng["amp"] / ctx["base_profit"])))

        rank_table.add_row(
            l_str, f"[bright_green]${rng['soporte']:,.0f}[/]", f"[bright_red]${rng['resist']:,.0f}[/]", 
            f"[bright_cyan]{rng['amp']:.1f}%[/]", f"[bold]{num_grids}[/]", f"[{p_col_grid}]{rng['score']}%[/]", e_short
        )

    layout["ranking"].update(Panel(rank_table, title="[bold bright_magenta]🏆 RANKING INFALIBLE DE GRILLAS ÓPTIMAS[/]", border_style="bright_magenta", box=box.ROUNDED))

    # 3D. VEREDICTO EXPERTO Y JUSTIFICACIÓN MACRO+MICRO
    if ctx["estrategias"]:
        e_r, c_r, s_r, r_r, g_r, score_r, logica_esc, detalles, macro_reasons = ctx["estrategias"][ctx["n_rec"]]
        
        sello = ""
        significado_sello = ""
        if score_r >= 80:
            sello = "[bold white on bright_green] ✔️ SEÑAL DE ALTA CONFIANZA [/]"
            significado_sello = "[dim bright_green]■ Rango validado Micro y Macro. Riesgo minimizado de Hold.[/]"
        elif ctx["is_parabolic"]:
            sello = "[bold white on bright_red] ⚠️ RIESGO ALTO (NO OPERAR) [/]"
            significado_sello = "[dim bright_red]■ Mercado parabólico. Riesgo inminente de Squeeze o Ruptura.[/]"
        else:
            sello = "[bold black on bright_yellow] 🛡️ RANGO ACEPTABLE [/]"
            significado_sello = "[dim bright_yellow]■ Rentabilidad posible, pero requiere monitoreo de tendencia.[/]"
        
        ancho_grid = (r_r - s_r) / g_r if g_r > 0 else 1 
        hits = ctx['atr_24h'] / ancho_grid if ancho_grid > 0 else 0
        prof = hits * (ctx['base_profit'] / 100) * 100 
        
        str_hits = "[dim]Calculando...[/]" if ctx['atr_24h'] == 0 else f"[bright_green]~{int(hits)}[/] hits/día"
        str_prof = "[dim]Calculando...[/]" if ctx['atr_24h'] == 0 else f"[bright_cyan]~{prof:.2f}%[/] diario"

        ver_grid = Table(box=None, expand=True, show_header=False, padding=(0, 1))
        ver_grid.add_column(justify="left", ratio=1)
        ver_grid.add_column(justify="left", ratio=1)
        
        ver_grid.add_row(f"🎯 [bold]Setup:[/] [bold {c_r}]{e_r}[/]", f"📍 [bold]Zona:[/] [bright_white]${s_r:,.0f} ── ${r_r:,.0f}[/]")
        ver_grid.add_row(f"⚙️ [bold]Bot:[/] {g_r} Grillas ({ctx['base_profit']}%)", f"🤖 [bold bright_cyan]ATR 24h:[/] ${ctx['atr_24h']:,.0f}")
        ver_grid.add_row(f"💡 [bold]Lógica:[/] [italic bright_yellow]{logica_esc}[/]", f"⚡ [bold]Arbs:[/] {str_hits} │ 💸 {str_prof}")
        
        # Formatear razones Macro y Micro en el panel de justificación
        macro_str = " + ".join(macro_reasons) if macro_reasons else "Neutral / Sin apoyo macro claro"
        
        just_panel = Panel(
            f"[dim]├─[/] 🛡️ [bold bright_green]Muros (Anti-Hold):[/] {ctx['anti_bag_text']}\n"
            f"[dim]├─[/] 🌍 [bold bright_green]Alineación Macro:[/] [bright_yellow]{macro_str}[/]\n"
            f"[dim]└─[/] ⚖️ [bold bright_green]Veredicto Analítico:[/] {ctx['comparativa_text']}",
            border_style="dim yellow", box=box.SIMPLE
        )
        
        layout["verdict"].update(Panel(Group(ver_grid, just_panel, Align.center(sello), Align.center(significado_sello)), title=f"[bold bright_yellow]{radar_anim} VEREDICTO OMNICIENT Y PRONÓSTICO[/]", border_style="bright_yellow", box=box.HEAVY))
    else:
        layout["verdict"].update(Panel(Align.center("\n[dim]Analizando confluencias Macro y Micro...\n[/]\n"), title="[bold bright_yellow]🤖 VEREDICTO Y PRONÓSTICO[/]", border_style="yellow", box=box.ROUNDED))

    # ---------------------------------------------------------
    # FOOTER
    # ---------------------------------------------------------
    f_grid = Table.grid(expand=True)
    f_grid.add_column(justify="left", ratio=1)
    f_grid.add_column(justify="center", ratio=1)
    f_grid.add_column(justify="right", ratio=1)

    api_status = "[bold bright_green]ON[/]" if BINANCE_API_KEY else "[dim bright_red]OFF[/]"
    f_grid.add_row(
        f"🔑 API: {api_status} | 💾 Memoria: {'[bright_green]OK[/]' if ctx['sv'] == '[bold bright_green]ÉXITO[/]' else '[bright_yellow]Cargada[/]'} | 📶 Ping: {ctx['latency']}ms",
        f"⚖️ Calidad Data: {ctx['madurez_datos']}",
        f"📊 Volatilidad Z-Score: [bright_cyan]{ctx['vol_z_score']:.3f}%[/]"
    )
    layout["footer"].update(Panel(f_grid, box=box.ROUNDED, border_style="dim white"))

    return layout

# =========================================================
# BUCLE PRINCIPAL
# =========================================================

def main():
    global simbolo_rest, simbolo_ws, bin_size, auto_cluster_activo, cluster_age, obi_history, stats_sesion, microprice, ultimo_guardado_csv, ALERTAS_SONORAS, volume_profile, start_time, ready_alert_sent, session_high, session_low, velocity_score, atr_24h
    
    cargar_configuracion()
    cargar_memoria_sesion() # Recuperar historial de CVD y Ballenas si se cerró el bot
    
    os.system('cls' if os.name == 'nt' else 'clear')
    console.print(Panel(Align.center("\n[bold bright_cyan]🛸 RADAR HFT PRO - TERMINAL OMNICIENT (MICRO + MACRO)[/]\n"), box=box.DOUBLE, border_style="bright_cyan"))
    
    par_input = console.input("[bold white]» Moneda a analizar[/] [dim](Ej: BTCUSDT)[/]: ").strip().upper()
    if par_input: simbolo_rest = par_input; simbolo_ws = par_input.lower()
    bin_input = console.input("[bold white]» Agrupación o Bin Size[/] [dim](Ej: 100. Enter=Auto)[/]: ").strip()
    if bin_input.replace('.', '', 1).isdigit(): bin_size = float(bin_input)
    else: auto_cluster_activo = True
    alert_input = console.input("[bold white]» ¿Activar alertas sonoras?[/] [dim](S/N)[/]: ").strip().upper()
    ALERTAS_SONORAS = True if alert_input == "S" else False

    console.print("\n[bold bright_green]⚡ Conectando a APIs (Spot + Futures) e inicializando IA Macro...[/]")
    threading.Thread(target=iniciar_websocket, daemon=True).start()
    threading.Thread(target=actualizar_datos_globales, daemon=True).start()
    threading.Thread(target=actualizar_datos_macro, daemon=True).start()
    while not snapshot_loaded: time.sleep(0.5)

    sv = "[dim]ESPERANDO...[/]"
    anim_tick = 0

    with Live(refresh_per_second=4, screen=True) as live:
        while True:
            time.sleep(0.25)
            anim_tick += 1
            
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

            poc_price = max(volume_profile, key=volume_profile.get) if volume_profile else precio_actual

            b_clust, a_clust = {}, {}
            for p, q in bids_local.items():
                if p < precio_actual:
                    k = math.floor(p / bin_size) * bin_size; b_clust[k] = b_clust.get(k, 0) + q
            for p, q in asks_local.items():
                if p > precio_actual:
                    k = math.ceil(p / bin_size) * bin_size; a_clust[k] = a_clust.get(k, 0) + q
                
            top_heavy_bids = sorted(b_clust.items(), key=lambda x: x[1], reverse=True)[:5]
            top_heavy_asks = sorted(a_clust.items(), key=lambda x: x[1], reverse=True)[:5]
            
            top_c = sorted(top_heavy_bids, key=lambda x: x[0], reverse=True)
            top_v = sorted(top_heavy_asks, key=lambda x: x[0])
            
            master_bid = top_heavy_bids[0] if top_heavy_bids else (precio_actual, 0)
            master_ask = top_heavy_asks[0] if top_heavy_asks else (precio_actual, 0)

            now = time.time(); mins_transcurridos = (now - start_time) / 60
            v_trades = sum(t['vol'] for t in trades_recientes)
            p_c_r = (sum(t['vol'] for t in trades_recientes if not t['is_sell']) / (v_trades or 1)) * 100
            if anim_tick % 4 == 0: obi_history.append(p_c_r)
            vwap = stats_sesion["vwap_sum"] / (stats_sesion["vwap_vol"] or 1)
            
            if mins_transcurridos < 5: madurez_datos = f"[bright_red]CALIBRANDO {int((mins_transcurridos/5)*100)}%[/]"
            elif mins_transcurridos < 15: madurez_datos = f"[bright_yellow]MEDIA ({(mins_transcurridos/15)*100:.0f}%)[/]"
            elif mins_transcurridos < 60: madurez_datos = f"[bright_green]ALTA (Óptimo)[/]"
            else: madurez_datos = f"[bright_magenta]MÁXIMA (God Mode)[/]"

            power_score = 0
            power_score += 25 if precio_actual > vwap else -25
            power_score += 25 if stats_sesion["cvd"] > 0 else -25
            power_score += 25 if btc_trend == "ALZA ↑" else -25 if btc_trend == "BAJA ↓" else 0
            power_score += 25 if book_pressure > 52 else -25 if book_pressure < 48 else 0
            
            # Advertencia extrema de Squeeze por Long/Short Ratio
            if macro_data['ls_ratio'] > 2.5:
                power_score -= 30 # Presión a la baja por Long Squeeze inminente
            elif macro_data['ls_ratio'] < 0.5:
                power_score += 30 # Presión al alza por Short Squeeze inminente

            is_parabolic = True if (velocity_score > 25 or abs(power_score) >= 85) else False
            m_state = "PARABÓLICO (KILL SWITCH)" if is_parabolic else "EXPANSIÓN" if velocity_score > 12 or abs(power_score) > 60 else "ACUMULACIÓN" if velocity_score < 4 else "LATERAL"
                
            avg_obi = sum(obi_history) / len(obi_history) if len(obi_history) > 0 else 50
            o_t = "SUBIENDO (+)" if p_c_r > avg_obi + 1 else "BAJANDO (-)" if p_c_r < avg_obi - 1 else "ESTABLE (=)"

            posibles_rangos = []
            max_comb_vol = (master_bid[1] + master_ask[1]) if (top_heavy_bids and top_heavy_asks) else 1
            base_profit = 0.18 if "ACUMULACIÓN" in m_state else 0.40 
            
            for b_p, b_v in top_heavy_bids:
                for a_p, a_v in top_heavy_asks:
                    if a_p <= b_p: continue
                    amp = ((a_p - b_p) / b_p) * 100
                    vol_total_grid = b_v + a_v
                    
                    desequilibrio_vol = ((a_v - b_v) / vol_total_grid) * 100 if vol_total_grid > 0 else 0
                    fuerza_direccional = power_score - (desequilibrio_vol * 0.5)
                    
                    if fuerza_direccional >= 35:
                        est_name = "GRID LONG"
                        logica_escape = "Escape al ALZA (USDT Protegido)"
                    elif fuerza_direccional <= -35:
                        est_name = "GRID SHORT"
                        logica_escape = "Escape a la BAJA (USDT Protegido)"
                    else:
                        est_name = "GRID NEUTRAL"
                        logica_escape = "Equilibrio (Rango seguro)"

                    # --- SCORING OMNICIENT (MICRO + MACRO + ANTI-HOLD) ---
                    is_master_bid = (b_p == master_bid[0])
                    is_master_ask = (a_p == master_ask[0])
                    master_bonus = 25 if (is_master_bid and is_master_ask) else 10 if (is_master_bid or is_master_ask) else 0

                    vol_score = (vol_total_grid / max_comb_vol) * 30 
                    balance_score = ((100 - abs(desequilibrio_vol)) / 100) * 10 
                    
                    poc_dist_s = abs(b_p - poc_price) / poc_price
                    poc_dist_r = abs(a_p - poc_price) / poc_price
                    hist_score = 10 if (poc_dist_s < 0.02 or poc_dist_r < 0.02) else 5 if (poc_dist_s < 0.05 or poc_dist_r < 0.05) else 0
                    
                    width_score = 15 if amp >= 15.0 else 10 if 5.0 <= amp < 15.0 else 5
                    
                    dir_score = 0
                    if (fuerza_direccional >= 25 and est_name == "GRID LONG") or (fuerza_direccional <= -25 and est_name == "GRID SHORT") or (-25 < fuerza_direccional < 25 and est_name == "GRID NEUTRAL"):
                        dir_score += 5
                        
                    # ========================================================
                    # INTEGRACIÓN MACRO ESTRUCTURAL EN LA DECISIÓN DEL RANGO
                    # ========================================================
                    macro_score = 0
                    macro_reasons = []
                    
                    # 1. Influencia de la Tendencia Diaria (EMA 200)
                    if "ALCISTA" in macro_data["macro_trend"]:
                        if "LONG" in est_name:
                            macro_score += 20
                            macro_reasons.append("A favor de EMA200 Diaria")
                        elif "SHORT" in est_name:
                            macro_score -= 30 # Penalización masiva por ir contra tendencia macro
                            macro_reasons.append("Peligroso: Contra EMA200")
                    elif "BAJISTA" in macro_data["macro_trend"]:
                        if "SHORT" in est_name:
                            macro_score += 20
                            macro_reasons.append("A favor de EMA200 Diaria")
                        elif "LONG" in est_name:
                            macro_score -= 30
                            macro_reasons.append("Peligroso: Contra EMA200")
                            
                    # 2. Influencia del RSI 4H (Sobrecompra / Sobreventa)
                    if macro_data["rsi_4h"] < 35 and "LONG" in est_name:
                        macro_score += 10
                        macro_reasons.append("RSI 4H en Sobrevenda (Rebote)")
                    elif macro_data["rsi_4h"] > 65 and "SHORT" in est_name:
                        macro_score += 10
                        macro_reasons.append("RSI 4H en Sobrecompra (Corrección)")
                        
                    # 3. Influencia del Long/Short Ratio y Squeezes
                    if macro_data["ls_ratio"] > 2.5 and "LONG" in est_name:
                        macro_score -= 15
                        macro_reasons.append("Riesgo Long Squeeze (Exceso L/S)")
                    elif macro_data["ls_ratio"] < 0.8 and "SHORT" in est_name:
                        macro_score -= 15
                        macro_reasons.append("Riesgo Short Squeeze (Falta L/S)")

                    # Sumamos el macro_score al total general
                    rango_score = vol_score + balance_score + hist_score + width_score + dir_score + master_bonus + macro_score
                    
                    if is_parabolic: rango_score -= 50; logica_escape = "⚠️ TENDENCIA FUERTE: NO OPERAR"

                    rango_score = max(0, min(99.9, round(rango_score, 1))) 

                    detalles = []
                    posibles_rangos.append({
                        "soporte": b_p, "resist": a_p, "amp": amp, "score": rango_score, 
                        "estrategia": est_name, "logica_escape": logica_escape, 
                        "detalles": detalles, "is_master": (is_master_bid and is_master_ask),
                        "macro_reasons": macro_reasons
                    })
            
            mejores_rangos = sorted(posibles_rangos, key=lambda x: x["score"], reverse=True)[:5]
            mejores_rangos.sort(key=lambda x: x["soporte"], reverse=True) 

            ventaja_pts = 0.0
            scores_sorted = sorted([r["score"] for r in mejores_rangos], reverse=True)
            if len(scores_sorted) > 1: ventaja_pts = scores_sorted[0] - scores_sorted[1]

            estrategias = []; n_rec, m_score = 0, -1
            for i, rng in enumerate(mejores_rangos):
                s_magnet, r_magnet = rng["soporte"], rng["resist"]
                amp, score, est_final = rng["amp"], rng["score"], rng["estrategia"]
                num_grids = max(2, min(140, int(amp / base_profit)))
                col_final = "bright_green" if "LONG" in est_final else "bright_red" if "SHORT" in est_final else "bright_yellow"
                estrategias.append((est_final, col_final, s_magnet, r_magnet, num_grids, score, rng["logica_escape"], rng["detalles"], rng["macro_reasons"]))
                if score > m_score: m_score = score; n_rec = i

            anti_bag_text = ""
            comparativa_text = ""
            
            if mejores_rangos:
                mejor_rng = mejores_rangos[n_rec]
                
                if mejor_rng['is_master']:
                    anti_bag_text = f"Blindado por los DOS muros maestros históricos del libro."
                elif "LONG" in mejor_rng['estrategia'] or "NEUTRAL" in mejor_rng['estrategia']:
                    anti_bag_text = f"Soporte base ${mejor_rng['soporte']:,.0f} contiene frente a Dumps."
                else:
                    anti_bag_text = f"Resistencia ${mejor_rng['resist']:,.0f} contiene frente a Pumps."
                    
                comparativa_text = f"Elegido sobre el rango #2 (+{ventaja_pts:.1f} pts) por mejor cruce Liquidez y Seguridad Tendencial."

            # Persistencia y notificaciones cada 60 seg
            if anim_tick % 240 == 0: # a 4 ticks/seg = 60 segundos
                guardar_memoria_sesion()
                if time.time() - ultimo_guardado_csv > 60:
                    if estrategias:
                        e_r, c_r, s_r, r_r, g_r, score_r, logica_esc, _, _ = estrategias[n_rec]
                        guardar_csv([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), simbolo_rest, round(precio_actual,2), n_rec+1, s_r, r_r, round(((r_r-s_r)/s_r)*100,2), e_r, f"{score_r}%"])
                        ultimo_guardado_csv = time.time(); sv = "[bold bright_green]ÉXITO[/]"

            # Alertas Críticas
            if anim_tick % 8 == 0: 
                if estrategias:
                    e_r, c_r, s_r, r_r, g_r, score_r, logica_esc, _, _ = estrategias[n_rec]
                    if score_r >= 85 and not is_parabolic and mins_transcurridos >= 5: emitir_sonido()
                    if mins_transcurridos >= 5 and not ready_alert_sent and not is_parabolic:
                        msg = f"🌌 <b>REPORTE OMNICIENT: {simbolo_rest}</b>\n\n🎯 <b>ESTRATEGIA: {e_r}</b>\n✅ <b>Confianza: {score_r}%</b>\n📍 Rango Óptimo: ${s_r:,.0f} - ${r_r:,.0f}\n💡 Lógica: {logica_esc}"
                        enviar_telegram(msg); ready_alert_sent = True
            
            max_vol_view = max(max([v for _, v in top_c] or [0.1]), max([v for _, v in top_v] or [0.1]))
            context = {
                "simbolo": simbolo_rest, "precio_actual": precio_actual, "poc_price": poc_price, "microprice": microprice,
                "power_score": power_score, "m_state": m_state, "madurez_datos": madurez_datos,
                "session_high": session_high, "session_low": session_low, "book_pressure": book_pressure,
                "master_bid": master_bid, "master_ask": master_ask, "top_v": top_v, "top_c": top_c, "max_vol_view": max_vol_view,
                "spread": spread, "p_c_r": p_c_r, "avg_obi": avg_obi, "o_t": o_t,
                "mejores_rangos": mejores_rangos, "estrategias": estrategias, "n_rec": n_rec,
                "is_parabolic": is_parabolic, "mins_transcurridos": mins_transcurridos,
                "base_profit": base_profit, "sv": sv, "now": now, "bin_size": bin_size,
                "vol_z_score": vol_z_score, "latency": latency, "liq_sell": stats_sesion['liq_sell'],
                "liq_buy": stats_sesion['liq_buy'], "cvd": stats_sesion["cvd"], "vwap": vwap,
                "whale_buys": stats_sesion["whale_buys"], "whale_sells": stats_sesion["whale_sells"],
                "velocity_score": velocity_score, "anim_tick": anim_tick, "atr_24h": atr_24h,
                "btc_price": btc_price, "btc_trend": btc_trend, "funding_rate": funding_rate, "next_funding_time": next_funding_time,
                "event_log": event_log, "cluster_age": cluster_age, "macro_data": macro_data,
                "anti_bag_text": anti_bag_text, "comparativa_text": comparativa_text
            }
            
            live.update(generar_interfaz(context))

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: 
        print("\n\033[91mGuardando Sesión y Cerrando...\033[0m")
        guardar_memoria_sesion()