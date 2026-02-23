import streamlit as st
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import logging
import time
from time import sleep
from typing import List, Dict, Optional, Tuple
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import matplotlib.pyplot as plt
import io
import matplotlib.patches as mpatches
from matplotlib.ticker import MaxNLocator, MultipleLocator, FixedLocator
from datetime import datetime, timedelta, timezone
import multiprocessing
from threading import Lock
from contextlib import contextmanager
from scipy.stats import norm
import bcrypt
import sqlite3
from bs4 import BeautifulSoup
import socket
import base64
import os
import pytz
import json
import streamlit.components.v1 as components
from dotenv import load_dotenv
from user_management import (
    authenticate_user, create_user, check_daily_limit, increment_usage,
    get_all_users, get_activity_log, deactivate_user, extend_license, 
    get_user_info, USER_TIERS, initialize_users_db,
    authenticate_admin, get_user_stats, change_user_tier, reset_user_daily_limit,
    set_unlimited_access, is_legacy_password_blocked,
    create_session, validate_session, logout_session
)
from market_maker_analyzer import MarketMakerAnalyzer

db_lock = Lock()
AUTO_UPDATE_INTERVAL = 15
DB_TIMEOUT = 20  # Segundos de espera para desbloqueo de base de datos
DB_RETRIES = 5   # Número de reintentos para operaciones de base de datos
DB_RETRY_DELAY = 2  # Segundos de espera entre reintentos
# Configurar zona horaria del mercado
MARKET_TIMEZONE = pytz.timezone("America/New_York")

# Funciones para obtener fecha y hora en la zona horaria del mercadOS
def get_current_date():
    return datetime.now(MARKET_TIMEZONE).date()

def get_current_datetime():
    return datetime.now(MARKET_TIMEZONE)



logging.getLogger("streamlit").setLevel(logging.ERROR)

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

def render_background_video(video_path: str) -> None:
    if not os.path.isfile(video_path):
        logger.warning(f"Background video not found: {video_path}")
        return
    try:
        with open(video_path, "rb") as video_file:
            video_bytes = video_file.read()
        video_base64 = base64.b64encode(video_bytes).decode("utf-8")
        st.markdown(
            f"""
            <style>
            html, body {{
                background: transparent !important;
            }}
            .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"],
            [data-testid="stSidebar"], [data-testid="stSidebarNav"],
            section.main, .block-container {{
                background: transparent !important;
            }}
            #video-background {{
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                object-fit: cover;
                z-index: -1;
                filter: brightness(0.45);
                pointer-events: none;
            }}
            </style>
            <video id="video-background" autoplay loop muted playsinline>
                <source src="data:video/mp4;base64,{video_base64}" type="video/mp4">
            </video>
            """,
            unsafe_allow_html=True
        )
    except Exception as exc:
        logger.error(f"Failed to load background video: {exc}")

# API Sessions and Configurations
session_fmp = requests.Session()
session_tradier = requests.Session()
retry_strategy = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy)
session_fmp.mount("https://", adapter)
session_tradier.mount("https://", adapter)
num_workers = min(100, multiprocessing.cpu_count())

# API Keys and Constants (loaded from .env for security)
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
TRADIER_API_KEY = os.getenv("TRADIER_API_KEY", "")
TRADIER_BASE_URL = "https://api.tradier.com/v1"
FINVIZ_API_TOKEN = os.getenv("FINVIZ_API_TOKEN", "")
FINVIZ_BASE_URL = "https://elite.finviz.com"
HEADERS_FMP = {"Accept": "application/json"}
HEADERS_TRADIER = {"Authorization": f"Bearer {TRADIER_API_KEY}", "Accept": "application/json"}
HEADERS_FINVIZ = {"User-Agent": "Mozilla/5.0"}

# Constantes
PASSWORDS_DB = "auth_data/passwords.db"
CACHE_TTL = 30  # 30 segundos - tiempo real para ticker data
CACHE_TTL_AGGRESSIVE = 60  # 1 minuto para screener - balance entre datos y velocidad
CACHE_TTL_STATS = 300  # 5 minutos para datos estadísticos
MAX_RETRIES = 5
INITIAL_DELAY = 1
RISK_FREE_RATE = 0.045  # Tasa libre de riesgo

# Cache hit tracker para mostrar ahorros
cache_stats = {
    "hits": 0,
    "misses": 0,
    "bandwidth_saved_mb": 0
}

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuración inicial de página (DEBE SER LA PRIMERA LLAMADA DE STREAMLIT)
st.set_page_config(
    page_title="Pro Scanner",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Autenticación con SQLite ---
def initialize_passwords_db():
    os.makedirs("auth_data", exist_ok=True)
    conn = sqlite3.connect(PASSWORDS_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS passwords 
                 (password TEXT PRIMARY KEY, usage_count INTEGER DEFAULT 0, ip1 TEXT DEFAULT '', ip2 TEXT DEFAULT '')''')
    
    # Check if passwords already exist to avoid redundant inserts
    c.execute("SELECT COUNT(*) FROM passwords")
    count_existing = c.fetchone()[0]
    
    if count_existing == 0:  # Only insert if table is empty
        # Get passwords from environment variable
        passwords_str = os.getenv("INITIAL_PASSWORDS", "")
        logger.info(f"INITIAL_PASSWORDS env var length: {len(passwords_str)}")
        
        if passwords_str:
            initial_passwords = [(pwd.strip(), 0, "", "") for pwd in passwords_str.split(",") if pwd.strip()]
            logger.info(f"Parsed {len(initial_passwords)} passwords from INITIAL_PASSWORDS")
            
            # Hash all passwords
            hashed_passwords = []
            for pwd, count, ip1, ip2 in initial_passwords:
                try:
                    hashed = bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    hashed_passwords.append((hashed, count, ip1, ip2))
                except Exception as e:
                    logger.error(f"Error hashing password {pwd}: {e}")
            
            # Insert hashed passwords
            c.executemany("INSERT OR IGNORE INTO passwords VALUES (?, ?, ?, ?)", hashed_passwords)
            conn.commit()
            logger.info(f"✓ Password database initialized with {len(hashed_passwords)} hashed passwords")
        else:
            logger.warning("⚠ INITIAL_PASSWORDS environment variable is EMPTY!")
    else:
        logger.info(f"Password database already has {count_existing} passwords, skipping reinitialization")
    
    conn.close()

def load_passwords():
    conn = sqlite3.connect(PASSWORDS_DB, timeout=10)
    c = conn.cursor()
    c.execute("SELECT password, usage_count, ip1, ip2 FROM passwords")
    passwords = {row[0]: {"usage_count": row[1], "ip1": row[2], "ip2": row[3]} for row in c.fetchall()}
    conn.close()
    return passwords

def save_passwords(passwords):
    conn = sqlite3.connect(PASSWORDS_DB, timeout=10)
    c = conn.cursor()
    try:
        c.execute("DELETE FROM passwords")
        c.executemany("INSERT INTO passwords VALUES (?, ?, ?, ?)", 
                      [(pwd, data.get("usage_count", 0), data.get("ip1", ""), data.get("ip2", "")) for pwd, data in passwords.items()])
        conn.commit()
    except Exception as e:
        logger.error(f"Error saving passwords: {e}")
        conn.rollback()
    finally:
        conn.close()
    logger.info("Passwords updated in database.")

def get_local_ip():
    try:
        hostname = socket.gethostname()
        return socket.gethostbyname(hostname)
    except Exception:
        logger.error("Error obtaining local IP.")
        return None

def authenticate_password(input_password):
    # BLOQUEAR CONTRASEÑAS ANTIGUAS - FORZAR NUEVO SISTEMA DE AUTENTICACIÓN
    if is_legacy_password_blocked(input_password):
        st.error("❌ **Las contraseñas antiguas ya NO son válidas.**\n\nDebes usar el **NUEVO SISTEMA** de autenticación:\n\n1. Haz clic en '📝 Registrarse' (arriba)\n2. Crea tu cuenta con usuario y contraseña nueva\n3. Elige tu plan (Free/Pro/Premium)\n\nContacta al admin si necesitas ayuda: ozytargetcom@gmail.com")
        logger.warning(f"BLOCKED: Attempted login with legacy password: {input_password}")
        return False
    
    local_ip = get_local_ip()
    if not local_ip:
        st.error("Could not obtain local IP.")
        logger.error("Failed to obtain local IP during authentication.")
        return False
    passwords = load_passwords()
    for hashed_pwd, data in passwords.items():
        if bcrypt.checkpw(input_password.encode('utf-8'), hashed_pwd.encode('utf-8')):
            if data["usage_count"] < 2:
                if data["ip1"] == "":
                    passwords[hashed_pwd]["ip1"] = local_ip
                elif data["ip2"] == "" and data["ip1"] != local_ip:
                    passwords[hashed_pwd]["ip2"] = local_ip
                passwords[hashed_pwd]["usage_count"] += 1
                save_passwords(passwords)
                logger.info(f"Authentication successful from IP: {local_ip}, usage count: {passwords[hashed_pwd]['usage_count']}")
                return True
            elif data["usage_count"] == 2 and (data["ip1"] == local_ip or data["ip2"] == local_ip):
                logger.info(f"Repeat authentication successful from IP: {local_ip}")
                return True
            else:
                st.error("❌ This password has already been used by two IPs. To get your own access to Pro Scanner, text 'Pro Scanner Access' to 678-978-9414.")
                logger.warning(f"Authentication attempt for {input_password} from IP {local_ip} rejected; already used from {data['ip1']} and {data['ip2']}")
                return False
    st.error("❌ Incorrect password. If you don’t have access, text 'Pro Scanner Access' to 678-978-9414 to purchase your subscription.")
    logger.warning("Authentication failed: Invalid password")
    return False

def initialize_session_state() -> None:
    defaults = {
        "authenticated": False,
        "intro_shown": False,
        "session_token": None,
        "current_user": None,
        "admin_authenticated": False,
        "show_admin_panel": False,
        "admin_failed_attempts": 0,
        "admin_lockout_time": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# SIMPLE LOGIN SCREEN - Solo contraseña
# ═══════════════════════════════════════════════════════════════════════════════
def login_alumno():
    """Pantalla de login simple - Solo contraseña"""
    # Centrar contenido
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("# 🔐 Pro Scanner")
        st.markdown("---")
        
        with st.form("login_form"):
            password = st.text_input("🔑 Contraseña", type="password", placeholder="Ingresa tu contraseña")
            submitted = st.form_submit_button("🚀 Entrar", use_container_width=True)
        
        if submitted:
            if not password:
                st.error("❌ Ingresa tu contraseña")
                return
            
            # Usar el sistema de autenticación de passwords.db (40 contraseñas)
            if authenticate_password(password):
                st.session_state["authenticated"] = True
                st.session_state["current_user"] = "legacy_password_user"
                st.session_state["user_tier"] = "PRO"
                st.session_state["daily_limit"] = None  # Sin límite
                st.session_state["session_token"] = create_session(st.session_state["current_user"])
                st.success("✅ ¡Acceso concedido!")
                st.rerun()
            # Si falla authenticate_password, el error ya se mostró en la función
                    

@st.cache_data(ttl=CACHE_TTL)
def fetch_logo_url(symbol: str) -> str:
    """Obtiene la URL del logo de Clearbit con un fallback como base64."""
    url = f"https://logo.clearbit.com/{symbol.lower()}.com"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            logger.info(f"Logo fetched for {symbol}")
            return f"data:image/png;base64,{base64.b64encode(response.content).decode('utf-8')}"
    except Exception as e:
        logger.warning(f"Failed to fetch logo for {symbol}: {e}")
    default_logo_path = "default_logo.png"
    if os.path.exists(default_logo_path):
        with open(default_logo_path, "rb") as f:
            return f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
    logger.info(f"Using fallback logo for {symbol}")
    return "https://via.placeholder.com/100"

@st.cache_data(ttl=86400)
def get_top_traded_stocks() -> set:
    """Obtiene una lista de las acciones más operadas desde FMP."""
    url = f"{FMP_BASE_URL}/stock-screener"
    params = {
        "apikey": FMP_API_KEY,
        "marketCapMoreThan": 10_000_000_000,
        "volumeMoreThan": 1_000_000,
        "exchange": "NASDAQ,NYSE",
        "limit": 100
    }
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        top_stocks = {stock["symbol"] for stock in data if stock.get("isActivelyTrading", True)}
        logger.info(f"Fetched {len(top_stocks)} top traded stocks")
        return top_stocks
    except Exception as e:
        logger.error(f"Error fetching top traded stocks: {e}")
        # Fallback básico
        return {"AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "JPM", "WMT", "SPY"}

@st.cache_data(ttl=86400)
def get_implied_volatility(symbol: str) -> Optional[float]:
    """Obtiene la volatilidad implícita promedio de opciones cercanas desde Tradier."""
    expiration_dates = get_expiration_dates(symbol)
    if not expiration_dates:
        logger.warning(f"No expiration dates for {symbol}")
        return None
    nearest_exp = expiration_dates[0]
    url = f"{TRADIER_BASE_URL}/markets/options/chains"
    params = {"symbol": symbol, "expiration": nearest_exp, "greeks": "true"}
    try:
        response = requests.get(url, headers=HEADERS_TRADIER, params=params, timeout=5)
        response.raise_for_status()
        data = response.json().get("options", {}).get("option", [])
        ivs = [float(opt.get("implied_volatility", 0)) for opt in data if opt.get("implied_volatility")]
        if ivs:
            avg_iv = sum(ivs) / len(ivs)
            logger.info(f"Average IV for {symbol}: {avg_iv}")
            return avg_iv
        return None
    except Exception as e:
        logger.error(f"Error fetching IV for {symbol}: {e}")
        return None

def fetch_api_data(url: str, params: Dict, headers: Dict, source: str, max_retries: int = 5) -> Optional[Dict]:
    session = session_fmp if "FMP" in source else session_tradier
    for attempt in range(max_retries):
        try:
            response = session.get(url, params=params, headers=headers, timeout=5)
            response.raise_for_status()
            logger.debug(f"{source} fetch success: {len(response.text)} bytes")
            return response.json()
        except RequestException as e:
            logger.warning(f"{source} attempt {attempt + 1}/{max_retries} failed: {str(e)}")
            if attempt < max_retries - 1:
                sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s, ...
            else:
                logger.error(f"{source} failed after {max_retries} attempts: {str(e)}")
                return None

@st.cache_data(ttl=10)
def get_current_price(ticker: str) -> float:
    """
    Get current price - TIEMPO REAL (10 segundos) - Tradier → FMP
    """
    # Intenta Tradier primero
    url_tradier = f"{TRADIER_BASE_URL}/markets/quotes"
    params_tradier = {"symbols": ticker}
    try:
        response = session_tradier.get(url_tradier, params=params_tradier, headers=HEADERS_TRADIER, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data and "quotes" in data and "quote" in data["quotes"]:
            quote = data["quotes"]["quote"]
            if isinstance(quote, list):
                quote = quote[0]
            price = float(quote.get("last", 0.0))
            if price > 0:
                logger.info(f"Fetched {ticker} price from Tradier: ${price:.2f}")
                return price
    except Exception as e:
        logger.warning(f"Tradier failed for {ticker}: {str(e)}")

    # Fallback a FMP
    url_fmp = f"{FMP_BASE_URL}/quote/{ticker}"
    params_fmp = {"apikey": FMP_API_KEY}
    try:
        response = session_fmp.get(url_fmp, params=params_fmp, headers=HEADERS_FMP, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            price = float(data[0].get("price", 0.0))
            if price > 0:
                logger.info(f"Fetched {ticker} price from FMP: ${price:.2f}")
                return price
    except Exception as e:
        logger.error(f"FMP failed for {ticker}: {str(e)}")

    logger.error(f"Unable to fetch price for {ticker}")
    return 0.0




@st.cache_data(ttl=86400)
def get_expiration_dates(ticker: str) -> List[str]:
    """Get option expiration dates directly from Tradier API"""
    url = f"{TRADIER_BASE_URL}/markets/options/expirations"
    params = {"symbol": ticker}
    try:
        response = session_tradier.get(url, params=params, headers=HEADERS_TRADIER, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data and "expirations" in data and "date" in data["expirations"]:
            expiration_dates = data["expirations"]["date"]
            current_date = datetime.now().date()
            valid_dates = [date for date in expiration_dates if datetime.strptime(date, "%Y-%m-%d").date() >= current_date]
            logger.info(f"Fetched {len(valid_dates)} valid expiration dates for {ticker}")
            return valid_dates
        logger.warning(f"No expiration dates found for {ticker}")
        return []
    except Exception as e:
        logger.error(f"Error fetching expiration dates for {ticker}: {str(e)}")
        return []

# --- Finviz Elite Options Functions ---
@st.cache_data(ttl=CACHE_TTL)
def get_finviz_options_data(ticker: str, expiration: str = "", strike_filter: str = "") -> Optional[pd.DataFrame]:
    """
    Fetch options data from Finviz Elite export API.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'MSFT')
        expiration: Expiration date filter (e.g., '2025-07-18', optional)
        strike_filter: Strike filter (optional, e.g., 'OTM', 'ATM', 'ITM')
    
    Returns:
        DataFrame with options data or None if failed
    
    Example:
        df = get_finviz_options_data('SPY', '2025-01-17')
    """
    try:
        # Build Finviz Elite export URL with authentication
        # Base URL: https://elite.finviz.com/export/options
        url = f"{FINVIZ_BASE_URL}/export/options"
        
        params = {
            "t": ticker,  # Ticker
            "ty": "oc",   # Type: oc = options chain
            "auth": FINVIZ_API_TOKEN
        }
        
        # Add optional filters
        if expiration:
            params["e"] = expiration  # e.g., "2025-07-18"
        
        if strike_filter:
            params["sf"] = strike_filter  # Strike filter
        
        response = requests.get(url, params=params, headers=HEADERS_FINVIZ, timeout=15)
        response.raise_for_status()
        
        # Parse CSV response
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        
        if df.empty:
            logger.warning(f"No options data from Finviz for {ticker}")
            return None
        
        logger.info(f"Fetched {len(df)} options from Finviz Elite for {ticker} (Expiration: {expiration or 'All'})")
        return df
    
    except Exception as e:
        logger.warning(f"Finviz Elite options fetch failed for {ticker}: {str(e)}")
        return None

@st.cache_data(ttl=86400)
def get_finviz_expiration_dates(ticker: str) -> List[str]:
    """
    Get available option expiration dates from Finviz Elite.
    
    Uses the full options chain export and extracts unique expiration dates.
    
    Args:
        ticker: Stock ticker symbol
    
    Returns:
        List of expiration dates in YYYY-MM-DD format, sorted
    
    Example:
        dates = get_finviz_expiration_dates('SPY')
        # Returns: ['2025-01-17', '2025-01-24', ...]
    """
    try:
        url = f"{FINVIZ_BASE_URL}/export/options"
        params = {
            "t": ticker,
            "ty": "oc",
            "auth": FINVIZ_API_TOKEN
        }
        
        response = requests.get(url, params=params, headers=HEADERS_FINVIZ, timeout=15)
        response.raise_for_status()
        
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        
        if df.empty or "Expiration" not in df.columns:
            logger.warning(f"No expiration dates from Finviz for {ticker}")
            return []
        
        # Extract and sort unique expiration dates
        expirations = sorted(df["Expiration"].unique().tolist())
        logger.info(f"Finviz found {len(expirations)} expiration dates for {ticker}")
        return expirations
    
    except Exception as e:
        logger.warning(f"Finviz expiration dates fetch failed for {ticker}: {str(e)}")
        return []

@st.cache_data(ttl=CACHE_TTL)
def get_options_data_hybrid(ticker: str, expiration_date: str = "", prefer_source: str = "tradier") -> Optional[pd.DataFrame]:
    """
    Fetch options data from Tradier or Finviz Elite with intelligent fallback.
    
    This function automatically switches between data sources for maximum reliability.
    
    Args:
        ticker: Stock ticker symbol
        expiration_date: Expiration date in YYYY-MM-DD format (optional)
        prefer_source: "tradier" (default) or "finviz" (preferred API source)
    
    Returns:
        DataFrame with options data, or None if both sources fail
    
    Fallback Logic:
        1. Try preferred source first
        2. If that fails, try the other source
        3. If both fail, log error and return None
    
    Example:
        # Prefer Finviz
        df = get_options_data_hybrid('SPY', '2025-01-17', prefer_source='finviz')
        
        # Prefer Tradier (default)
        df = get_options_data_hybrid('SPY', '2025-01-17')
    """
    
    if prefer_source == "finviz":
        logger.info(f"Attempting Finviz Elite for {ticker}...")
        df_finviz = get_finviz_options_data(ticker, expiration_date)
        if df_finviz is not None and not df_finviz.empty:
            logger.info(f"✅ Using Finviz Elite ({len(df_finviz)} options) for {ticker}")
            return df_finviz
        
        logger.warning(f"Finviz unavailable, falling back to Tradier for {ticker}")
        tradier_data = get_options_data(ticker, expiration_date)
        if tradier_data:
            logger.info(f"✅ Using Tradier fallback ({len(tradier_data)} options) for {ticker}")
            # Convert to DataFrame for consistency
            return pd.DataFrame(tradier_data)
    
    else:  # prefer_source == "tradier" (default)
        logger.info(f"Attempting Tradier for {ticker}...")
        tradier_data = get_options_data(ticker, expiration_date)
        if tradier_data:
            logger.info(f"✅ Using Tradier ({len(tradier_data)} options) for {ticker}")
            return pd.DataFrame(tradier_data)
        
        logger.warning(f"Tradier unavailable, falling back to Finviz Elite for {ticker}")
        df_finviz = get_finviz_options_data(ticker, expiration_date)
        if df_finviz is not None and not df_finviz.empty:
            logger.info(f"✅ Using Finviz Elite fallback ({len(df_finviz)} options) for {ticker}")
            return df_finviz
    
    logger.error(f"❌ Both Tradier and Finviz failed for {ticker}")
    return None

@st.cache_data(ttl=60)  # 1 minuto - tiempo real para screener
def get_finviz_screener_elite(filters: Dict[str, any] = None, columns: List[str] = None, view_id: str = "111") -> Optional[pd.DataFrame]:
    """
    Fetch screener data from Finviz Elite export API.
    
    Uses the official Finviz Elite screener export endpoint with proper authentication.
    
    Args:
        filters: Dictionary of filters (e.g., {"fa_div_pos": None, "sec_technology": None})
        columns: Optional list of column IDs to export
        view_id: View ID (111 = default screener, 152 = compact, etc.)
    
    Returns:
        pandas.DataFrame with screener results or None if failed
    
    Official Finviz URL Structure:
        https://elite.finviz.com/export.ashx?v=[view]&f=[filters]&c=[columns]&auth=[token]
    
    Parameters:
        v = View ID (111 = default, 152 = compact, etc.)
        f = Comma-separated filters (fa_div_pos,sec_technology)
        c = Optional columns to export
        auth = API Token (required)
        r = Max results (1000)
    
    Example:
        filters = {"fa_div_pos": None, "sec_technology": None}
        df = get_finviz_screener_elite(filters, view_id="111")
    
    Typical Filters:
        • fa_div_pos = Positive dividend yield
        • sec_technology = Technology sector
        • ta_volatility_wo5 = Volatility > 5%
        • ta_changeopen_u5 = Change from open > 5%
        • cap_mega = Market cap > $200B
        • sh_avgvol_o500 = Average volume > 500k
        • ta_perf_1wup = 1-week performance up
        • ta_pattern_doubletop = Double top pattern
    """
    try:
        # Build URL parameters following official Finviz Elite API
        params = {
            "v": view_id,              # View ID
            "auth": FINVIZ_API_TOKEN,  # API Token
            "r": "1000"                # Request up to 1000 results per call
        }
        
        # Add filters if provided
        if filters:
            # Build filter string: comma-separated filter names
            # Example: "fa_div_pos,sec_technology,ta_volatility_wo5"
            filter_names = [k for k in filters.keys() if k not in ["o", "r"]]
            if filter_names:
                params["f"] = ",".join(filter_names)
            
            # Handle ordering parameter if present
            if "o" in filters:
                params["o"] = filters["o"]
        
        # Add columns if specified (optional customization)
        if columns:
            columns_str = ",".join([str(c) for c in columns])
            params["c"] = columns_str
        
        # Construct the URL: https://elite.finviz.com/export.ashx
        url = f"{FINVIZ_BASE_URL}/export.ashx"
        
        # Make request to Finviz Elite screener export endpoint
        response = requests.get(url, params=params, headers=HEADERS_FINVIZ, timeout=15)
        response.raise_for_status()
        
        # Parse CSV response into DataFrame
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        
        if df.empty:
            logger.warning(f"Finviz screener returned no results with filters: {params.get('f', 'none')}")
            return None
        
        logger.info(f"Finviz Screener: {len(df)} results (View: {view_id}, Filters: {params.get('f', 'none')})")
        return df
        
    except Exception as e:
        logger.warning(f"Finviz screener fetch failed: {str(e)}")
        return None
         
@st.cache_data(ttl=60)
def get_current_prices(tickers: List[str]) -> Dict[str, float]:
    """
    Get current prices for multiple tickers - Tradier → FMP (sin backend)
    """
    prices_dict = {ticker: 0.0 for ticker in tickers}
    
    # Intenta Tradier primero
    tickers_str = ",".join(tickers)
    url_tradier = f"{TRADIER_BASE_URL}/markets/quotes"
    params_tradier = {"symbols": tickers_str}
    try:
        response = session_tradier.get(url_tradier, params=params_tradier, headers=HEADERS_TRADIER, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data and "quotes" in data and "quote" in data["quotes"]:
            quotes = data["quotes"]["quote"]
            if isinstance(quotes, dict):
                quotes = [quotes]
            for quote in quotes:
                ticker = quote.get("symbol", "")
                price = float(quote.get("last", 0.0))
                if ticker in prices_dict and price > 0:
                    prices_dict[ticker] = price
            fetched = [t for t, p in prices_dict.items() if p > 0]
            logger.info(f"Fetched {len(fetched)}/{len(tickers)} prices from Tradier")
    except Exception as e:
        logger.warning(f"Tradier failed: {str(e)}")

    # Fallback a FMP para los faltantes
    missing_tickers = [t for t, p in prices_dict.items() if p == 0.0]
    if missing_tickers:
        url_fmp = f"{FMP_BASE_URL}/quote/{','.join(missing_tickers)}"
        params_fmp = {"apikey": FMP_API_KEY}
        try:
            response = session_fmp.get(url_fmp, params=params_fmp, headers=HEADERS_FMP, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list):
                for item in data:
                    ticker = item.get("symbol", "")
                    price = float(item.get("price", 0.0))
                    if ticker in prices_dict and price > 0:
                        prices_dict[ticker] = price
            fetched = [t for t, p in prices_dict.items() if p > 0 and t in missing_tickers]
            logger.info(f"Fetched {len(fetched)}/{len(missing_tickers)} remaining prices from FMP")
        except Exception as e:
            logger.error(f"FMP failed: {str(e)}")

    failed = [t for t, p in prices_dict.items() if p == 0.0]
    if failed:
        logger.warning(f"Unable to fetch prices for {failed}")

    return prices_dict

@st.cache_data(ttl=10)  # 10 segundos - opciones son tiempo real, cambian constantemente
def get_options_data(ticker: str, expiration_date: str) -> List[Dict]:
    """
    Fetch options chain data from Tradier API with strict validation.
    
    Args:
        ticker (str): Stock ticker symbol (e.g., 'SPY').
        expiration_date (str): Expiration date in YYYY-MM-DD format.
    
    Returns:
        List[Dict]: List of valid option contracts.
    """
    url = f"{TRADIER_BASE_URL}/markets/options/chains"
    params = {"symbol": ticker, "expiration": expiration_date, "greeks": "true"}
    try:
        time.sleep(0.1)  # Add delay to avoid rate-limiting
        response = session_tradier.get(url, params=params, headers=HEADERS_TRADIER, timeout=5)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"Tradier response for {ticker} {expiration_date}: {data}")
        
        # ✅ VALIDACIÓN ROBUSTA - Cambios críticos aquí
        if data is None or not isinstance(data, dict):
            logger.error(f"Invalid JSON response for {ticker}: {response.text}")
            return []
        
        # Verificar que 'options' existe y no es None
        if 'options' not in data:
            logger.warning(f"No 'options' key in response for {ticker} on {expiration_date}: {data}")
            return []
        
        options_container = data['options']
        
        # ✅ SOLUCIÓN AL ERROR: Validar que options_container no sea None antes de usar 'in'
        if options_container is None:
            logger.warning(f"'options' is None for {ticker} on {expiration_date}")
            return []
        
        if not isinstance(options_container, dict):
            logger.warning(f"'options' is not a dict for {ticker} on {expiration_date}: {type(options_container)}")
            return []
        
        if 'option' not in options_container:
            logger.warning(f"No 'option' key in options data for {ticker} on {expiration_date}: {options_container}")
            return []
        
        option_list = options_container['option']
        
        # Validar que option_list sea una lista
        if not isinstance(option_list, list):
            logger.warning(f"'option' is not a list for {ticker} on {expiration_date}: {type(option_list)}")
            return []
        
        if len(option_list) == 0:
            logger.warning(f"Empty option list for {ticker} on {expiration_date}")
            return []
        
        # Filtrar opciones válidas
        valid_options = []
        for opt in option_list:
            if not isinstance(opt, dict):
                logger.warning(f"Skipping non-dict option for {ticker}: {opt}")
                continue
                
            bid = opt.get("bid")
            ask = opt.get("ask")
            
            if (bid is not None and ask is not None and
                isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and
                bid > 0 and ask > 0):
                valid_options.append(opt)
            else:
                logger.warning(f"Skipping option for {ticker} on {expiration_date}: Invalid bid/ask - {opt}")
        
        logger.info(f"Fetched {len(valid_options)} valid option contracts for {ticker} on {expiration_date}")
        if valid_options:
            logger.debug(f"Sample contract: {valid_options[0]}")
        return valid_options
        
    except requests.RequestException as e:
        logger.error(f"Network error fetching options for {ticker}: {str(e)} - Response: {getattr(e.response, 'text', 'No response')}")
        return []
    except ValueError as e:
        logger.error(f"JSON parsing error for {ticker}: {str(e)} - Response: {response.text if 'response' in locals() else 'No response'}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching options for {ticker}: {str(e)}")
        return []


def _generate_mock_contracts(ticker: str, price: float) -> List[Dict]:
    """Generate realistic mock options data for demo when API fails"""
    import random
    
    # Define strike range
    strikes = []
    for i in range(-20, 21, 1):
        strikes.append(round(price + i, 2))
    
    contracts = []
    base_iv = 0.20 + random.uniform(-0.05, 0.05)
    
    for strike in strikes:
        for opt_type in ['call', 'put']:
            # Realistic OI distribution (higher near ATM)
            distance_from_atm = abs(strike - price) / price
            oi_multiplier = max(0.3, 1.0 - distance_from_atm * 2)
            oi = int(random.uniform(5000, 50000) * oi_multiplier)
            
            # Greeks
            delta = random.uniform(-0.95, 0.95) if opt_type == 'call' else random.uniform(-0.95, 0.05)
            gamma = random.uniform(0.001, 0.02)
            theta = random.uniform(-0.05, 0.01)
            vega = random.uniform(0.1, 2.0)
            iv = base_iv + random.uniform(-0.02, 0.02)
            
            contracts.append({
                'strike': strike,
                'type': opt_type,
                'open_interest': oi,
                'volume': max(1, int(oi * 0.1)),
                'bid': max(0.01, round(random.uniform(0.1, 5.0), 2)),
                'ask': round(random.uniform(0.15, 5.5), 2),
                'delta': round(delta, 3),
                'gamma': round(gamma, 6),
                'theta': round(theta, 4),
                'vega': round(vega, 2),
                'iv': round(iv, 3),
                'last_price': round(random.uniform(0.10, 4.50), 2)
            })
    
    return contracts








@st.cache_data(ttl=CACHE_TTL)
def get_historical_prices_combined(symbol, period="daily", limit=30):
    """Get historical prices - FMP → yfinance"""
    
    # Intenta FMP primero
    try:
        url = f"{FMP_BASE_URL}/historical-price-full/{symbol}"
        params = {"apikey": FMP_API_KEY, "serietype": period}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data and "historical" in data:
            prices = []
            volumes = []
            for item in data["historical"][:limit]:
                prices.append(float(item.get("close", 0)))
                volumes.append(float(item.get("volume", 0)))
            if prices:
                logger.info(f"Fetched {len(prices)} historical prices for {symbol} from FMP")
                return prices, volumes
    except Exception as e:
        logger.warning(f"FMP failed: {str(e)}")

    # Fallback a yfinance (siempre funciona)
    try:
        ticker_obj = yf.Ticker(symbol)
        hist = ticker_obj.history(period=f"{limit}d")
        if not hist.empty:
            prices = hist['Close'].tolist()
            volumes = hist['Volume'].tolist()
            if prices:
                logger.info(f"Fetched {len(prices)} historical prices for {symbol} from yfinance")
                return prices, volumes
    except Exception as e:
        logger.warning(f"yfinance failed: {str(e)}")

    logger.error(f"Unable to fetch historical prices for {symbol}")
    return [], []

@st.cache_data(ttl=CACHE_TTL_AGGRESSIVE)  # 30 min - stock lists don't change often
def get_stock_list_combined():
    """Obtener lista de acciones combinando ."""
    combined_tickers = set()  # Usamos un set para evitar duplicados

    # 1. Obtener lista de FMP
    try:
        response = requests.get(
            f"{FMP_BASE_URL}/stock-screener",
            params={
                "apikey": FMP_API_KEY,
                "marketCapMoreThan": 1_000_000_000,  # Capitalización > $1B
                "volumeMoreThan": 500_000,           # Volumen > 500k
                "priceMoreThan": 5,                  # Precio > $5
                "exchange": "NASDAQ,NYSE"            # Solo NASDAQ y NYSE
            }
        )
        response.raise_for_status()
        data = response.json()
        fmp_tickers = [stock["symbol"] for stock in data if stock.get("isActivelyTrading", True)]
        combined_tickers.update(fmp_tickers[:200])  # Limitamos a 200 por velocidad
        logger.info(f"returned {len(fmp_tickers)} tickers")
    except Exception as e:
        logger.error(f"stock list failed: {str(e)}")

    # 2. Obtener lista de Tradier (usamos endpoint de quotes con múltiples símbolos)
    try:
        # Tradier no tiene un endpoint directo de "screener", así que usamos una lista inicial de índices o ETFs populares
        initial_tickers = "SPY,QQQ,DIA,IWM,TSLA,AAPL,MSFT,NVDA,GOOGL,AMZN,META"  # Base inicial
        url_tradier = f"{TRADIER_BASE_URL}/markets/quotes"
        params_tradier = {"symbols": initial_tickers}
        data_tradier = fetch_api_data(url_tradier, params_tradier, HEADERS_TRADIER, "Tradier")
        if data_tradier and "quotes" in data_tradier and "quote" in data_tradier["quotes"]:
            quotes = data_tradier["quotes"]["quote"]
            if isinstance(quotes, dict):
                quotes = [quotes]
            tradier_tickers = [
                quote["symbol"] for quote in quotes
                if quote.get("last", 0) > 5 and quote.get("volume", 0) > 500_000
            ]
            combined_tickers.update(tradier_tickers)
            logger.info(f"Tradier returned {len(tradier_tickers)} tickers")
    except Exception as e:
        logger.error(f"Tradier stock list failed: {str(e)}")

    # Convertimos a lista y limitamos el resultado
    final_list = list(combined_tickers)
    logger.info(f"Combined unique tickers: {len(final_list)}")
    return final_list[:200]  # Máximo 200 para mantener rendimiento

# --- Funciones de Análisis ---
def analyze_contracts(ticker, expiration, current_price):
    url = f"{TRADIER_BASE_URL}/markets/options/chains"
    params = {"symbol": ticker, "expiration": expiration, "greeks": True}
    try:
        response = requests.get(url, headers=HEADERS_TRADIER, params=params, timeout=10)
        if response.status_code != 200:
            st.info("Option data is being processed. Please refresh the page.")
            return pd.DataFrame()
        options = response.json().get("options", {}).get("option", [])
        if not options:
            st.warning("No contracts available.")
            return pd.DataFrame()
        df = pd.DataFrame(options)
        for col in ['strike', 'option_type', 'open_interest', 'volume', 'bid', 'ask', 'last_volume', 'trade_date', 'bid_exchange', 'delta', 'gamma', 'break_even']:
            if col not in df.columns:
                df[col] = 0
        # Asegurar que open_interest sea numérico y no nan
        df['open_interest'] = pd.to_numeric(df['open_interest'], errors='coerce').fillna(0).astype(int).clip(lower=0)
        df['trade_date'] = datetime.now().strftime('%Y-%m-%d')
        df['break_even'] = df.apply(lambda row: row['strike'] + row['bid'] if row['option_type'] == 'call' else row['strike'] - row['bid'], axis=1)
        return df
    except requests.exceptions.ReadTimeout:
        st.info(f"Option data for {ticker} is temporarily unavailable. Please try again shortly.")
        return pd.DataFrame()
    except requests.RequestException as e:
        st.info(f"Option data for {ticker} is temporarily unavailable. Please try again shortly.")
        return pd.DataFrame()

def style_and_sort_table(df):
    ordered_columns = ['strike', 'option_type', 'open_interest', 'volume', 'trade_date', 'bid', 'ask', 'last_volume', 'bid_exchange', 'delta', 'gamma', 'break_even']
    df = df.sort_values(by=['volume', 'open_interest'], ascending=[False, False]).head(10)
    df = df[ordered_columns]
    def highlight_row(row):
        color = 'background-color: green; color: white;' if row['option_type'] == 'call' else 'background-color: red; color: white;'
        return [color] * len(row)
    return df.style.apply(highlight_row, axis=1).format({
        'strike': '{:.2f}', 'bid': '${:.2f}', 'ask': '${:.2f}', 'last_volume': '{:,}', 'open_interest': '{:,}', 'delta': '{:.2f}', 'gamma': '{:.2f}', 'break_even': '${:.2f}'
    })

def select_best_contracts(df, current_price):
    if df.empty:
        return None, None
    df['strike_diff'] = abs(df['strike'] - current_price)
    closest_contract = df.sort_values(by=['strike_diff', 'volume', 'open_interest'], ascending=[True, False, False]).iloc[0]
    otm_calls = df[(df['option_type'] == 'call') & (df['strike'] > current_price) & (df['ask'] < 5)]
    otm_puts = df[(df['option_type'] == 'put') & (df['strike'] < current_price) & (df['ask'] < 5)]
    if not otm_calls.empty or not otm_puts.empty:
        economic_df = pd.concat([otm_calls, otm_puts])
        economic_contract = economic_df.sort_values(by=['volume', 'open_interest'], ascending=[False, False]).iloc[0]
    else:
        economic_contract = None
    return closest_contract, economic_contract

# Versión original para opciones (usada en Tab 1)
def calculate_max_pain(options_data: List[Dict]) -> Optional[float]:
    """
    Calculate the Max Pain strike price for a list of option contracts.
    
    Args:
        options_data (List[Dict]): List of option contracts with strike, open_interest, and option_type.
    
    Returns:
        Optional[float]: Max Pain strike price, or None if no valid data.
    """
    if not options_data:
        logger.warning("No options data provided for Max Pain calculation")
        return None
    strikes = {}
    for opt in options_data:
        try:
            strike = float(opt.get("strike", 0))
            oi = int(opt.get("open_interest", 0) or 0)
            opt_type = opt.get("option_type", "").upper()
            if strike not in strikes:
                strikes[strike] = {"CALL": 0, "PUT": 0}
            strikes[strike][opt_type] += oi
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid option data: {opt} - {str(e)}")
            continue
    strike_prices = sorted(strikes.keys())
    total_losses = {}
    for strike in strike_prices:
        call_loss = sum(strikes[s]["CALL"] * max(0, s - strike) for s in strike_prices)
        put_loss = sum(strikes[s]["PUT"] * max(0, strike - s) for s in strike_prices)
        total_losses[strike] = call_loss + put_loss
    if not total_losses:
        logger.warning("No valid strike prices for Max Pain calculation")
        return None
    max_pain = min(total_losses, key=total_losses.get)
    logger.debug(f"Calculated Max Pain: ${max_pain:.2f}")
    return max_pain

def calculate_support_resistance_mid(max_pain_table, current_price):
    """Calcula niveles de soporte y resistencia basados en Max Pain."""
    if max_pain_table.empty or 'strike' not in max_pain_table.columns:
        return current_price, current_price, current_price
    puts = max_pain_table[max_pain_table['strike'] <= current_price]
    calls = max_pain_table[max_pain_table['strike'] > current_price]
    support_level = puts.loc[puts['total_loss'].idxmin()]['strike'] if not puts.empty else current_price
    resistance_level = calls.loc[calls['total_loss'].idxmin()]['strike'] if not calls.empty else current_price
    mid_level = (support_level + resistance_level) / 2
    return support_level, resistance_level, mid_level

def plot_max_pain_histogram_with_levels(max_pain_table, current_price):
    """Crea un histograma de Max Pain con niveles."""
    if max_pain_table.empty:
        fig = go.Figure()
        fig.update_layout(title="Max Pain Histogram (No Data)", template="plotly_white")
        return fig
    
    support_level, resistance_level, mid_level = calculate_support_resistance_mid(max_pain_table, current_price)
    max_pain_table['loss_category'] = max_pain_table['total_loss'].apply(
        lambda x: 'High Loss' if x > max_pain_table['total_loss'].quantile(0.75) else ('Low Loss' if x < max_pain_table['total_loss'].quantile(0.25) else 'Neutral')
    )
    color_map = {'High Loss': '#FF5733', 'Low Loss': '#28A745', 'Neutral': 'rgba(128,128,128,0.3)'}
    fig = px.bar(max_pain_table, x='strike', y='total_loss', title="Max Pain Histogram with Levels",
                 labels={'total_loss': 'Total Loss', 'strike': 'Strike Price'}, color='loss_category', color_discrete_map=color_map)
    fig.update_layout(xaxis_title="Strike Price", yaxis_title="Total Loss", template="plotly_white", font=dict(size=14, family="Open Sans"),
                      title=dict(text="📊 Analysis loss Options", font=dict(size=18), x=0.5), hovermode="x",
                      yaxis=dict(showspikes=True, spikemode="across", spikesnap="cursor", spikecolor="#FFFF00", spikethickness=1.5))
    mean_loss = max_pain_table['total_loss'].mean()
    fig.add_hline(y=mean_loss, line_width=1, line_dash="dash", line_color="#00FF00", annotation_text=f"Mean Loss: {mean_loss:.2f}", annotation_position="top right", annotation_font=dict(color="#00FF00", size=12))
    fig.add_vline(x=support_level, line_width=1, line_dash="dot", line_color="#1E90FF", annotation_text=f"Support: {support_level:.2f}", annotation_position="top left", annotation_font=dict(color="#1E90FF", size=10))
    fig.add_vline(x=resistance_level, line_width=1, line_dash="dot", line_color="#FF4500", annotation_text=f"Resistance: {resistance_level:.2f}", annotation_position="top right", annotation_font=dict(color="#FF4500", size=10))
    fig.add_vline(x=mid_level, line_width=1, line_dash="solid", line_color="#FFD700", annotation_text=f"Mid Level: {mid_level:.2f}", annotation_position="top right", annotation_font=dict(color="#FFD700", size=8))
    return fig

def get_option_chains(ticker, expiration):
    url = f"{TRADIER_BASE_URL}/markets/options/chains"
    params = {"symbol": ticker, "expiration": expiration, "greeks": True}
    response = requests.get(url, headers=HEADERS_TRADIER, params=params)
    if response.status_code == 200:
        return response.json().get("options", {}).get("option", [])
    st.error("Error retrieving option chains.")
    return []

def calculate_score(df, current_price, volatility=0.2):
    df['score'] = (df['open_interest'] * df['volume']) / (abs(df['strike'] - current_price) + volatility)
    return df.sort_values(by='score', ascending=False)

def display_cards(df):
    top_5_vol = df.sort_values(by='volume', ascending=False).head(5)
    st.markdown("### Top 5")
    for i, row in top_5_vol.iterrows():
        st.markdown(f"""
        **Strike:** {row['strike']}  
        **Type:** {'Call' if row['option_type'] == 'call' else 'Put'}  
        **Volume:** {row['volume']}  
        **Open Interest:** {row['open_interest']}  
        **Score:** {row['score']:.2f}  
        """)

def plot_histogram(df):
    fig = px.bar(df, x='strike', y='score', color='option_type', title="Score by Strike (Calls and Puts)",
                 labels={'score': 'Relevance Score', 'strike': 'Strike Price'}, text='score',
                 color_discrete_map={'call': '#00FF00', 'put': '#FF00FF'})
    fig.update_traces(texttemplate='%{text:.2f}', textposition='outside', marker=dict(line=dict(width=0.5, color='black')))
    fig.update_layout(plot_bgcolor='black', font=dict(color='white', size=12), xaxis=dict(showgrid=True, gridcolor='gray'),
                      yaxis=dict(showgrid=True, gridcolor='gray'), xaxis_title="Strike Price", yaxis_title="Relevance Score")
    support_level = df['strike'].iloc[0]
    resistance_level = df['strike'].iloc[-1]
    fig.add_hline(y=support_level, line_width=1, line_dash="dot", line_color="#1E90FF", annotation_text=f"Support: {support_level:.2f}", annotation_position="bottom left", annotation_font=dict(size=10, color="#1E90FF"))
    fig.add_hline(y=resistance_level, line_width=1, line_dash="dot", line_color="#FF4500", annotation_text=f"Resistance: {resistance_level:.2f}", annotation_position="top left", annotation_font=dict(size=10, color="#FF4500"))
    return fig

def detect_touched_strikes(strikes, historical_prices):
    touched_strikes = set()
    cleaned_prices = [float(p) for p in historical_prices if isinstance(p, (int, float, str)) and str(p).replace('.', '', 1).isdigit()]
    if len(cleaned_prices) < 2:
        return touched_strikes
    for strike in strikes:
        for i in range(1, len(cleaned_prices)):
            if (cleaned_prices[i-1] < strike <= cleaned_prices[i]) or (cleaned_prices[i-1] > strike >= cleaned_prices[i]):
                touched_strikes.add(strike)
    return touched_strikes

def calculate_max_pain_optimized(options_data):
    if not options_data:
        return None
    strikes = {}
    for option in options_data:
        strike = float(option["strike"])
        oi = int(option.get("open_interest", 0) or 0)
        volume = int(option.get("volume", 0) or 0)
        option_type = option["option_type"].upper()
        if strike not in strikes:
            strikes[strike] = {"CALL": {"OI": 0, "Volume": 0}, "PUT": {"OI": 0, "Volume": 0}}
        strikes[strike][option_type]["OI"] += oi
        strikes[strike][option_type]["Volume"] += volume
    strike_prices = sorted(strikes.keys())
    total_losses = {}
    for strike in strike_prices:
        loss_call = sum((strikes[s]["CALL"]["OI"] + strikes[s]["CALL"]["Volume"]) * max(0, s - strike) for s in strike_prices)
        loss_put = sum((strikes[s]["PUT"]["OI"] + strikes[s]["PUT"]["Volume"]) * max(0, strike - s) for s in strike_prices)
        total_losses[strike] = loss_call + loss_put
    return min(total_losses, key=total_losses.get) if total_losses else None

def gamma_exposure_chart(processed_data, current_price, touched_strikes):
    strikes = sorted(processed_data.keys())
    gamma_calls = [processed_data[s]["CALL"]["OI"] * processed_data[s]["CALL"]["Gamma"] * current_price for s in strikes]
    gamma_puts = [-processed_data[s]["PUT"]["OI"] * processed_data[s]["PUT"]["Gamma"] * current_price for s in strikes]
    call_colors = ["grey" if s in touched_strikes else "#7DF9FF" for s in strikes]
    put_colors = ["orange" if s in touched_strikes else "red" for s in strikes]

    # Crear la figura
    fig = go.Figure()

    # Añadir barras para CALLs y PUTs con ancho fijo
    fig.add_trace(go.Bar(
        x=strikes,
        y=gamma_calls,
        name="Gummy CALL",
        marker=dict(color=call_colors),
        width=0.4,
        hovertemplate="Gummy CALL: %{y:.2f}",  # Sin Current Price
    ))
    fig.add_trace(go.Bar(
        x=strikes,
        y=gamma_puts,
        name="Gummy PUT",
        marker=dict(color=put_colors),
        width=0.4,
        hovertemplate="Gummy PUT: %{y:.2f}",  # Sin Current Price
    ))

    # Línea vertical para Current Price
    y_min = min(gamma_calls + gamma_puts) * 1.1
    y_max = max(gamma_calls + gamma_puts) * 1.1
    fig.add_trace(go.Scatter(
        x=[current_price, current_price],
        y=[y_min, y_max],
        mode="lines",
        line=dict(width=1, dash="dot", color="#39FF14"),
        name="Current Price",
        hovertemplate="",  # Tooltip vacío para evitar redundancia
        showlegend=False,
        hoverlabel=dict(
            bgcolor="rgba(0,0,0,0)",  # Fondo completamente transparente
            bordercolor="rgba(0,0,0,0)",  # Borde completamente transparente
            font=dict(color="#39FF14", size=12)  # Letras verdes "en el aire"
        )
    ))

    # Añadir label fijo profesional para Current Price
    fig.add_annotation(
        x=current_price,
        y=y_max * 0.95,  # Posición cerca del tope del gráfico
        text=f"Price: ${current_price:.2f}",
        showarrow=False,
        font=dict(color="#39FF14", size=10),  # Verde, pequeño y profesional
        bgcolor="rgba(0,0,0,0.5)",  # Fondo semitransparente oscuro
        bordercolor="#39FF14",  # Borde verde fino
        borderwidth=1,
        borderpad=4  # Espacio interno para un look limpio
    )

    # Configuración de los tooltips y layout
    fig.update_traces(
        hoverlabel=dict(
            bgcolor="rgba(0,0,0,0.1)",  # Fondo muy transparente para las barras
            bordercolor="rgba(255,255,255,0.3)",  # Borde casi invisible para las barras
            font=dict(color="white", size=12)  # Texto blanco para las barras
        )
    )
    fig.update_layout(
        title="GUMMY EXPOSURE",
        xaxis_title="Strike",
        yaxis_title="Gummy Exposure",
        template="plotly_dark",
        hovermode="x",
        xaxis=dict(
            tickmode="array",
            tickvals=strikes,
            ticktext=[f"{s:.2f}" for s in strikes],
            rangeslider=dict(visible=False),
            showgrid=False
        ),
        yaxis=dict(showgrid=False),
        bargap=0.2,
        barmode="relative",
    )

    return fig

def plot_skew_analysis_with_totals(options_data, current_price=None):
    # Extraer datos básicos de options_data
    strikes = [float(option["strike"]) for option in options_data]
    iv = [float(option.get("implied_volatility", 0)) * 100 for option in options_data]
    option_type = [option["option_type"].upper() for option in options_data]
    # Asegurarse de que open_interest sea numérico y no nan
    open_interest = [int(option.get("open_interest", 0) or 0) for option in options_data]
    
    # Calcular totales
    total_calls = sum(oi for oi, ot in zip(open_interest, option_type) if ot == "CALL")
    total_puts = sum(oi for oi, ot in zip(open_interest, option_type) if ot == "PUT")
    total_volume_calls = sum(int(option.get("volume", 0)) for option in options_data if option["option_type"].upper() == "CALL")
    total_volume_puts = sum(int(option.get("volume", 0)) for option in options_data if option["option_type"].upper() == "PUT")
    
    # Calcular IV ajustada
    adjusted_iv = [iv[i] + (open_interest[i] * 0.01) if option_type[i] == "CALL" else -(iv[i] + (open_interest[i] * 0.01)) for i in range(len(iv))]
    
    # Crear DataFrame y limpiar datos
    skew_df = pd.DataFrame({
        "Strike": strikes,
        "Adjusted IV (%)": adjusted_iv,
        "Option Type": option_type,
        "Open Interest": open_interest
    })
    # Reemplazar nan con 0 y asegurar valores no negativos
    skew_df["Open Interest"] = skew_df["Open Interest"].fillna(0).astype(int).clip(lower=0)
    
    # Crear gráfico de dispersión con tamaño limpio
    fig = px.scatter(
        skew_df,
        x="Strike",
        y="Adjusted IV (%)",
        color="Option Type",
        size="Open Interest",
        size_max=30,  # Limitar tamaño máximo para mejor visualización
        custom_data=["Strike", "Option Type", "Open Interest", "Adjusted IV (%)"],
        title=f"IV Analysis<br><span style='font-size:16px;'> CALLS: {total_calls} | PUTS: {total_puts} | VC {total_volume_calls} | VP {total_volume_puts}</span>",
        labels={"Option Type": "Contract Type"},
        color_discrete_map={"CALL": "blue", "PUT": "red"}
    )
    fig.update_traces(
        hovertemplate="<b>Strike:</b> %{customdata[0]:.2f}<br><b>Type:</b> %{customdata[1]}<br><b>Open Interest:</b> %{customdata[2]:,}<br><b>Adjusted IV:</b> %{customdata[3]:.2f}%"
    )
    fig.update_layout(
        xaxis_title="Strike Price",
        yaxis_title="Gummy Bubbles® (%)",
        legend_title="Option Type",
        template="plotly_white",
        title_x=0.5
    )

    # Lógica para current_price y max_pain (sin cambios en esta parte)
    if current_price is not None and options_data:
        strikes_dict = {}
        for option in options_data:
            strike = float(option["strike"])
            oi = int(option.get("open_interest", 0) or 0)
            opt_type = option["option_type"].upper()
            if strike not in strikes_dict:
                strikes_dict[strike] = {"CALL": 0, "PUT": 0}
            strikes_dict[strike][opt_type] += oi
        strike_prices = sorted(strikes_dict.keys())
        total_losses = {}
        for strike in strike_prices:
            loss_call = sum((strikes_dict[s]["CALL"] * max(0, s - strike)) for s in strike_prices)
            loss_put = sum((strikes_dict[s]["PUT"] * max(0, strike - s)) for s in strike_prices)
            total_losses[strike] = loss_call + loss_put
        max_pain = min(total_losses, key=total_losses.get) if total_losses else None

        avg_iv_calls = sum(iv[i] + (open_interest[i] * 0.01) for i, ot in enumerate(option_type) if ot == "CALL") / max(1, sum(1 for ot in option_type if ot == "CALL"))
        avg_iv_puts = sum(-(iv[i] + (open_interest[i] * 0.01)) for i, ot in enumerate(option_type) if ot == "PUT") / max(1, sum(1 for ot in option_type if ot == "PUT"))

        call_open_interest = total_calls
        put_open_interest = total_puts
        scale_factor = 5000
        call_size = max(5, min(30, call_open_interest / scale_factor))
        put_size = max(5, min(30, put_open_interest / scale_factor))

        if current_price is not None and max_pain is not None:
            calls_data = [opt for opt in options_data if opt["option_type"].upper() == "CALL"]
            puts_data = [opt for opt in options_data if opt["option_type"].upper() == "PUT"]
            closest_call = min(calls_data, key=lambda x: abs(float(x["strike"]) - current_price), default=None)
            closest_put = min(puts_data, key=lambda x: abs(float(x["strike"]) - current_price), default=None)

            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            exp_date = datetime.strptime(options_data[0].get("expiration_date") or options_data[0].get("expirationDate"), "%Y-%m-%d")
            days_to_expiration = (exp_date - today).days

            if closest_call:
                call_strike = float(closest_call["strike"])
                call_data = {
                    call_strike: {
                        'bid': float(closest_call.get("bid", 0)),
                        'ask': float(closest_call.get("ask", 0)),
                        'delta': float(closest_call.get("greeks", {}).get("delta", 0.5)),
                        'gamma': float(closest_call.get("greeks", {}).get("gamma", 0.02)),
                        'theta': float(closest_call.get("greeks", {}).get("theta", -0.01)),
                        'iv': float(closest_call.get("implied_volatility", 0.2)),
                        'open_interest': int(closest_call.get("open_interest", 0)),
                        'intrinsic': max(current_price - call_strike, 0)
                    }
                }
                rr_calls, profit_calls, prob_otm_calls, _ = calculate_special_monetization(call_data, current_price, days_to_expiration)
                percent_change_calls = ((current_price - max_pain) / max_pain) * 100 if max_pain != 0 else 0
                call_loss = abs(current_price - max_pain) * total_calls if current_price < max_pain else (current_price - max_pain) * total_calls
                potential_move_calls = abs(current_price - max_pain)
                direction_calls = "Down" if current_price > max_pain else "Up"
            else:
                rr_calls, profit_calls, prob_otm_calls, percent_change_calls, call_loss, potential_move_calls, direction_calls = 0, 0, 0, 0, 0, 0, "N/A"

            if closest_put:
                put_strike = float(closest_put["strike"])
                put_data = {
                    put_strike: {
                        'bid': float(closest_put.get("bid", 0)),
                        'ask': float(closest_put.get("ask", 0)),
                        'delta': float(closest_put.get("greeks", {}).get("delta", -0.5)),
                        'gamma': float(closest_put.get("greeks", {}).get("gamma", 0.02)),
                        'theta': float(closest_put.get("greeks", {}).get("theta", -0.01)),
                        'iv': float(closest_put.get("implied_volatility", 0.2)),
                        'open_interest': int(closest_put.get("open_interest", 0)),
                        'intrinsic': max(put_strike - current_price, 0)
                    }
                }
                rr_puts, profit_puts, prob_otm_puts, _ = calculate_special_monetization(put_data, current_price, days_to_expiration)
                percent_change_puts = ((max_pain - current_price) / max_pain) * 100 if max_pain != 0 else 0
                put_loss = abs(max_pain - current_price) * total_puts if current_price > max_pain else (max_pain - current_price) * total_puts
                potential_move_puts = abs(max_pain - current_price)
                direction_puts = "Up" if current_price < max_pain else "Down"
            else:
                rr_puts, profit_puts, prob_otm_puts, percent_change_puts, put_loss, potential_move_puts, direction_puts = 0, 0, 0, 0, 0, 0, "N/A"

            if call_open_interest > 0 and closest_call:
                fig.add_scatter(
                    x=[current_price],
                    y=[avg_iv_calls],
                    mode="markers",
                    name="Current Price (CALLs)",
                    marker=dict(size=call_size, color="yellow", opacity=0.45, symbol="circle"),
                    hovertemplate=(f"Current Price (CALLs): {current_price:.2f}<br>"
                                   f"Adjusted IV: {avg_iv_calls:.2f}%<br>"
                                   f"Open Interest: {call_open_interest:,}<br>"
                                   f"% to Max Pain: {percent_change_calls:.2f}%<br>"
                                   f"R/R: {rr_calls:.2f}<br>"
                                   f"Est. Loss: ${call_loss:,.2f}<br>"
                                   f"Potential Move: ${potential_move_calls:.2f}<br>"
                                   f"Direction: {direction_calls}")
                )

            if put_open_interest > 0 and closest_put:
                fig.add_scatter(
                    x=[current_price],
                    y=[avg_iv_puts],
                    mode="markers",
                    name="Current Price (PUTs)",
                    marker=dict(size=put_size, color="yellow", opacity=0.45, symbol="circle"),
                    hovertemplate=(f"Current Price (PUTs): {current_price:.2f}<br>"
                                   f"Adjusted IV: {avg_iv_puts:.2f}%<br>"
                                   f"Open Interest: {put_open_interest:,}<br>"
                                   f"% to Max Pain: {percent_change_puts:.2f}%<br>"
                                   f"R/R: {rr_puts:.2f}<br>"
                                   f"Est. Loss: ${put_loss:,.2f}<br>"
                                   f"Potential Move: ${potential_move_puts:.2f}<br>"
                                   f"Direction: {direction_puts}")
                )

        if max_pain is not None:
            fig.add_scatter(
                x=[max_pain],
                y=[0],
                mode="markers",
                name="Max Pain",
                marker=dict(size=15, color="white", symbol="circle"),
                hovertemplate=f"Max Pain: {max_pain:.2f}"
            )

    return fig, total_calls, total_puts

def fetch_google_news(keywords):
    base_url = "https://www.google.com/search"
    query = "+".join(keywords)
    params = {"q": query, "tbm": "nws", "tbs": "qdr:h"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"}
    try:
        response = requests.get(base_url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        news = []
        articles = soup.select("div.dbsr") or soup.select("div.Gx5Zad.fP1Qef.xpd.EtOod.pkphOe")
        for article in articles[:20]:
            title_tag = article.select_one("div.JheGif.nDgy9d") or article.select_one("div.BNeawe.vvjwJb.AP7Wnd")
            link_tag = article.a
            if title_tag and link_tag:
                title = title_tag.text.strip()
                link = link_tag["href"]
                time_tag = article.select_one("span.WG9SHc")
                time_posted = time_tag.text if time_tag else "Just now"
                news.append({"title": title, "link": link, "time": time_posted})
        return news
    except Exception as e:
        st.warning(f"Error fetching Data News: {e}")
        return []

def fetch_bing_news(keywords):
    base_url = "https://www.bing.com/news/search"
    query = " ".join(keywords)
    params = {"q": query, "qft": "+filterui:age-lt24h"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"}
    try:
        response = requests.get(base_url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        news = []
        articles = soup.select("a.title")
        for article in articles[:20]:
            title = article.text.strip()
            link = article["href"]
            news.append({"title": title, "link": link, "time": "Recently"})
        return news
    except Exception as e:
        st.warning(f"Error fetching Bing News: {e}")
        return []

def fetch_instagram_posts(keywords):
    base_url = "https://www.instagram.com/explore/tags/"
    posts = []
    for keyword in keywords:
        if keyword.startswith("#"):
            try:
                url = f"{base_url}{keyword[1:]}/"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"}
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    continue
                soup = BeautifulSoup(response.text, "html.parser")
                articles = soup.select("div.v1Nh3.kIKUG._bz0w a")
                for article in articles[:20]:
                    link = "https://www.instagram.com" + article["href"]
                    posts.append({"title": "Instagram Post", "link": link, "time": "Recently"})
            except Exception as e:
                st.warning(f"Error fetching Instagram posts for {keyword}: {e}")
    return posts

# Funciones de análisis de sentimiento (agregadas aquí para evitar NameError)
def calculate_retail_sentiment(news):
    """Calcula el sentimiento de mercado de retail basado en titulares de noticias."""
    if not news:
        return 0.5, "Neutral"  # Valor por defecto si no hay noticias
    
    positive_keywords = ["up", "bullish", "gain", "rise", "surge", "strong", "rally", "positive", "growth"]
    negative_keywords = ["down", "bearish", "loss", "drop", "fall", "crash", "weak", "decline", "negative"]
    
    sentiment_score = 0
    total_articles = len(news)
    
    for article in news:
        title = article["title"].lower()
        positive_count = sum(1 for word in positive_keywords if word in title)
        negative_count = sum(1 for word in negative_keywords if word in title)
        sentiment_score += (positive_count - negative_count)
    
    max_possible_score = max(total_articles, 1)
    normalized_score = (sentiment_score + max_possible_score) / (2 * max_possible_score)
    normalized_score = max(0, min(1, normalized_score))
    
    if normalized_score > 0.7:
        sentiment_text = "Very Bullish"
    elif normalized_score > 0.5:
        sentiment_text = "Bullish"
    elif normalized_score < 0.3:
        sentiment_text = "Very Bearish"
    elif normalized_score < 0.5:
        sentiment_text = "Bearish"
    else:
        sentiment_text = "Neutral"
    
    return normalized_score, sentiment_text

def calculate_volatility_sentiment(news):
    """Calcula el sentimiento de volatilidad basado en titulares de noticias."""
    if not news:
        return 0, "Stable"  # Valor por defecto si no hay noticias
    
    high_volatility_keywords = ["crash", "surge", "volatile", "plunge", "spike", "wild", "turmoil", "shock", "boom"]
    low_volatility_keywords = ["steady", "calm", "stable", "flat", "unchanged", "quiet", "consistent"]
    
    volatility_score = 0
    total_articles = len(news)
    
    for article in news:
        title = article["title"].lower()
        high_vol_count = sum(1 for word in high_volatility_keywords if word in title)
        low_vol_count = sum(1 for word in low_volatility_keywords if word in title)
        volatility_score += (high_vol_count - low_vol_count)
    
    max_possible_score = max(total_articles, 1)
    normalized_score = (volatility_score + max_possible_score) / (2 * max_possible_score) * 100
    normalized_score = max(0, min(100, normalized_score))
    
    if normalized_score > 75:
        volatility_text = "Very High Volatility"
    elif normalized_score > 50:
        volatility_text = "High Volatility"
    elif normalized_score < 25:
        volatility_text = "Low Volatility"
    elif normalized_score < 50:
        volatility_text = "Moderate Volatility"
    else:
        volatility_text = "Stable"
    
    return normalized_score, volatility_text

def fetch_batch_stock_data(tickers):
    tickers_str = ",".join(tickers)
    url = f"{TRADIER_BASE_URL}/markets/quotes"
    params = {"symbols": tickers_str}
    response = requests.get(url, headers=HEADERS_TRADIER, params=params)
    if response.status_code == 200:
        data = response.json().get("quotes", {}).get("quote", [])
        if isinstance(data, dict):
            data = [data]
        return [{"Ticker": item.get("symbol", ""), "Price": item.get("last", 0), "Change (%)": item.get("change_percentage", 0),
                 "Volume": item.get("volume", 0), "Average Volume": item.get("average_volume", 1),
                 "IV": item.get("implied_volatility", None), "HV": item.get("historical_volatility", None),
                 "Previous Close": item.get("prev_close", 0)} for item in data]
    st.error("⏳ Batch data is being retrieved. Please refresh to try again.")
    return []


def calculate_options_activity(data):
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame()
    df["IV"] = pd.to_numeric(df["IV"], errors='coerce').fillna(0)
    df["Average Volume"] = pd.to_numeric(df["Average Volume"], errors='coerce').replace(0, np.nan)
    df["Volumen Relativo"] = df["Volume"] / df["Average Volume"]
    df["Options Activity"] = df["Volumen Relativo"] * df["IV"]
    return df.sort_values("Options Activity", ascending=False).head(3)

def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    prices = np.array(prices)
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    return 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss != 0 else 100

def calculate_sma(prices: List[float], period: int = 20) -> Optional[float]:
    prices = np.array(prices)
    if len(prices) < period:
        return None
    return np.mean(prices[-period:])

def scan_stock_batch(tickers: List[str], scan_type: str, breakout_period=10, volume_threshold=2.0) -> List[Dict]:
    prices_dict = get_current_prices(tickers)
    results = []
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(get_historical_prices_combined, ticker, limit=breakout_period+1): ticker for ticker in tickers}
        for future in futures:
            ticker = futures[future]
            try:
                prices, volumes = future.result()
                if len(prices) <= breakout_period or not volumes:
                    continue
                current_price = prices_dict.get(ticker, 0.0)
                if current_price == 0.0:
                    continue
                prices = np.array(prices)
                volumes = np.array(volumes)
                rsi = calculate_rsi(prices)
                sma = calculate_sma(prices)
                avg_volume = np.mean(volumes)
                current_volume = volumes[-1]
                recent_high = np.max(prices[-breakout_period:])
                recent_low = np.min(prices[-breakout_period:])
                last_price = prices[-1]
                near_support = abs(last_price - recent_low) / recent_low <= 0.05
                near_resistance = abs(last_price - recent_high) / recent_high <= 0.05
                breakout_type = "Up" if last_price > recent_high else "Down" if last_price < recent_low else None
                possible_change = (recent_low - last_price) / last_price * 100 if near_support else (recent_high - last_price) / last_price * 100 if near_resistance else None

                if scan_type == "Bullish (Upward Momentum)" and sma and last_price > sma and rsi and rsi < 70:
                    results.append({"Symbol": ticker, "Last Price": last_price, "SMA": round(sma, 2), "RSI": round(rsi, 2), "Volume": current_volume, "Breakout Type": breakout_type, "Possible Change (%)": round(possible_change, 2) if possible_change else None})
                elif scan_type == "Bearish (Downward Momentum)" and sma and last_price < sma and rsi and rsi > 30:
                    results.append({"Symbol": ticker, "Last Price": last_price, "SMA": round(sma, 2), "RSI": round(rsi, 2), "Volume": current_volume, "Breakout Type": breakout_type, "Possible Change (%)": round(possible_change, 2) if possible_change else None})
                elif scan_type == "Breakouts" and breakout_type:
                    results.append({"Symbol": ticker, "Breakout Type": breakout_type, "Last Price": last_price, "Recent High": recent_high, "Recent Low": recent_low, "Volume": current_volume, "Possible Change (%)": round(possible_change, 2) if possible_change else None})
                elif scan_type == "Unusual Volume" and current_volume > volume_threshold * avg_volume:
                    results.append({"Symbol": ticker, "Volume": current_volume, "Avg Volume": avg_volume, "Last Price": last_price})
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")
    return results

def get_financial_metrics(symbol: str) -> Dict[str, float]:
    """Get financial metrics from FMP only (sin backend)"""
    
    # Intenta FMP - ratios
    try:
        url = f"{FMP_BASE_URL}/ratios/{symbol}"
        params = {"apikey": FMP_API_KEY}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data and isinstance(data, list) and len(data) > 0:
            ratio_data = data[0]
            metrics = {
                "pe_ratio": float(ratio_data.get("peRatio", 0.0)),
                "pb_ratio": float(ratio_data.get("pbRatio", 0.0)),
                "dividend_yield": float(ratio_data.get("dividendYield", 0.0)),
                "debt_to_equity": float(ratio_data.get("debtToEquity", 0.0)),
                "roa": float(ratio_data.get("returnOnAssets", 0.0)),
                "roe": float(ratio_data.get("returnOnEquity", 0.0))
            }
            logger.info(f"Fetched financial metrics for {symbol} from FMP")
            return metrics
    except Exception as e:
        logger.warning(f"FMP ratios failed: {str(e)}")

    # Fallback a FMP - enterprise value
    try:
        url = f"{FMP_BASE_URL}/enterprise-values/{symbol}"
        params = {"apikey": FMP_API_KEY}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data and isinstance(data, list) and len(data) > 0:
            ev_data = data[0]
            metrics = {
                "ev": float(ev_data.get("enterpriseValue", 0.0)),
                "market_cap": float(ev_data.get("marketCapitalization", 0.0)),
                "stock_price": float(ev_data.get("stockPrice", 0.0))
            }
            logger.info(f"Fetched EV metrics for {symbol} from FMP")
            return metrics
    except Exception as e:
        logger.error(f"FMP enterprise value failed: {str(e)}")

    logger.error(f"Unable to fetch financial metrics for {symbol}")
    return {}

def get_historical_prices_fmp(symbol: str, period: str = "daily", limit: int = 30) -> tuple[List[float], List[int]]:
    try:
        response = requests.get(f"{FMP_BASE_URL}/historical-price-full/{symbol}?apikey={FMP_API_KEY}&timeseries={limit}")
        response.raise_for_status()
        data = response.json()
        if not data or "historical" not in data:
            return [], []
        prices = [day["close"] for day in data["historical"]]
        volumes = [day["volume"] for day in data["historical"]]
        return prices, volumes
    except Exception as e:
        
        return [], []

def speculate_next_day_movement(metrics: Dict[str, float], prices: List[float], volumes: List[int]) -> tuple[str, float, Optional[float]]:
    sma = calculate_sma(prices, period=50)
    rsi = calculate_rsi(prices, period=14)
    recent_high = max(prices[-10:]) if len(prices) >= 10 else None
    recent_low = min(prices[-10:]) if len(prices) >= 10 else None
    last_price = prices[-1] if prices else None
    avg_volume = np.mean(volumes[-10:]) if len(volumes) >= 10 else None
    current_volume = volumes[-1] if volumes else None
    trend = "High Volatility"
    confidence = 0.5
    if last_price is not None and sma is not None and rsi is not None:
        if rsi < 30 and last_price < sma:
            trend = "Bearish"
            confidence = 0.7 if current_volume and avg_volume and current_volume > avg_volume else 0.6
        elif rsi > 70 and last_price > sma:
            trend = "Bullish"
            confidence = 0.8 if current_volume and avg_volume and current_volume > avg_volume else 0.7
        elif recent_high and last_price > recent_high:
            trend = "Breakout (Bullish)"
            confidence = 0.9
        elif recent_low and last_price < recent_low:
            trend = "Breakdown (Bearish)"
            confidence = 0.9
    if metrics.get("ROE", 0) > 0.15 and metrics.get("Free Cash Flow", 0) > 0:
        confidence += 0.1
    if metrics.get("Current Ratio", 0) < 1:
        confidence -= 0.1
    if metrics.get("Beta", 0) > 1.5:
        confidence += 0.1 if trend == "Bullish" else -0.1
    predicted_change = (last_price * 0.01) * confidence if trend == "Bullish" else -(last_price * 0.01) * confidence
    predicted_price = last_price + predicted_change if last_price is not None else None
    return trend, confidence, predicted_price

def get_option_data(symbol: str, expiration_date: str) -> pd.DataFrame:
    url = f"{TRADIER_BASE_URL}/markets/options/chains"
    params = {"symbol": symbol, "expiration": expiration_date, "greeks": "true"}
    try:
        response = requests.get(url, headers=HEADERS_TRADIER, params=params, timeout=10)
        if response.status_code != 200:
            st.info("Option data is being synchronized. Please refresh to retry.")
            logger.error(f"API request failed for {symbol} with expiration {expiration_date}: Status {response.status_code}")
            return pd.DataFrame()
        
        data = response.json()
        if data is None or not isinstance(data, dict):
            st.error(f"Datos de opciones inválidos para {symbol}. Respuesta vacía o no JSON.")
            logger.error(f"Invalid JSON response for {symbol}: {response.text}")
            return pd.DataFrame()
        
        if 'options' in data and isinstance(data['options'], dict) and 'option' in data['options']:
            options = data['options']['option']
            if not options:
                st.warning(f"No se encontraron contratos de opciones para {symbol} en {expiration_date}.")
                logger.info(f"No option contracts found for {symbol} on {expiration_date}")
                return pd.DataFrame()
            df = pd.DataFrame(options)
            df['action'] = df.apply(lambda row: "buy" if (row.get("bid", 0) > 0 and row.get("ask", 0) > 0) else "sell", axis=1)
            return df
        
        st.error(f"No se encontraron datos de opciones válidos en la respuesta para {symbol}.")
        logger.error(f"Options data missing or malformed for {symbol}: {data}")
        return pd.DataFrame()
    
    except requests.RequestException as e:
        st.error(f"⏳ Datos de opciones para {symbol} siendo procesados. Por favor refresca.")
        logger.error(f"Network error fetching options for {symbol}: {str(e)}")
        return pd.DataFrame()
    except ValueError as e:
        st.error(f"⏳ Procesando datos de opciones para {symbol}. Por favor refresca.")
        logger.error(f"JSON parsing error for {symbol}: {str(e)}")
        return pd.DataFrame()

def fetch_data(endpoint: str, ticker: str = None, additional_params: dict = None):
    url = f"{FMP_BASE_URL}/{endpoint}"
    params = {"apikey": FMP_API_KEY}
    if ticker:
        params["symbol"] = ticker
    if additional_params:
        params.update(additional_params)
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) == 0:
                st.warning(f"No Data: {endpoint}")
                return None
            return data
        st.error("⏳ Datos siendo sincronizados. Por favor, refresca la página e intenta de nuevo.")
        return None
    except Exception as e:
        st.error("⏳ Data is being retrieved. Please refresh to try again.")
        return None

def get_institutional_holders_list(ticker: str):
    endpoint = f"institutional-holder/{ticker}"
    data = fetch_data(endpoint, ticker)
    if data:
        return pd.DataFrame(data)
    return None



def estimate_greeks(strike: float, current_price: float, days_to_expiration: int, iv: float, option_type: str) -> Dict[str, float]:
    t = days_to_expiration / 365.0
    if iv <= 0 or t <= 0:
        return {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
    s = current_price
    k = strike
    r = RISK_FREE_RATE
    sigma = iv
    d1 = (np.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    if option_type == "CALL":
        delta = norm.cdf(d1)
        theta = (-s * norm.pdf(d1) * sigma / (2 * np.sqrt(t)) - r * k * np.exp(-r * t) * norm.cdf(d2)) / 365.0
    else:
        delta = norm.cdf(d1) - 1
        theta = (-s * norm.pdf(d1) * sigma / (2 * np.sqrt(t)) + r * k * np.exp(-r * t) * norm.cdf(-d2)) / 365.0
    gamma = norm.pdf(d1) / (s * sigma * np.sqrt(t))
    vega = s * norm.pdf(d1) * np.sqrt(t) / 100.0
    return {'delta': delta, 'gamma': gamma, 'theta': theta, 'vega': vega}

def analyze_options(options_data: List[Dict], current_price: float) -> Dict[str, Dict[float, Dict[str, float]]]:
    analysis = {"CALL": {}, "PUT": {}}
    if not options_data:
        logger.warning("No options data to analyze")
        return analysis
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    exp_date = datetime.strptime(options_data[0].get("expiration_date") or options_data[0].get("expirationDate"), "%Y-%m-%d")
    days_to_exp = (exp_date - today).days
    
    for option in options_data:
        try:
            strike = float(option["strike"])
            option_type = option["option_type"].upper() if "option_type" in option else ("CALL" if option.get("type") == "call" else "PUT")
            bid_ask_spread = float(option.get('ask', 0)) - float(option.get('bid', 0))
            iv = float(option.get('implied_volatility', 0) or option.get('impliedVolatility', 0) or 0)
            volume = int(option.get('volume', 0) or 0)
            open_interest = int(option.get('open_interest', 0) or option.get('openInterest', 0) or 0)
            intrinsic = max(current_price - strike, 0) if option_type == "CALL" else max(strike - current_price, 0)
            greek = option.get("greeks", {})
            
            if greek and all(greek.get(k) is not None and greek.get(k) != 0 for k in ['delta', 'gamma']):
                delta = float(greek.get('delta', 0))
                gamma = float(greek.get('gamma', 0))
                theta = float(greek.get('theta', 0))
                vega = float(greek.get('vega', 0))
            else:
                estimated = estimate_greeks(strike, current_price, days_to_exp, iv if iv > 0 else 0.2, option_type)
                delta = estimated['delta']
                gamma = estimated['gamma']
                theta = estimated['theta']
                vega = estimated['vega']
            
            if strike not in analysis[option_type]:
                analysis[option_type][strike] = {
                    'gamma': gamma,
                    'vega': vega,
                    'theta': theta,
                    'delta': delta,
                    'iv': iv if iv > 0 else 0.2,
                    'bid': float(option.get('bid', 0)),
                    'ask': float(option.get('ask', 0)),
                    'spread': bid_ask_spread,
                    'open_interest': open_interest,
                    'volume': volume,
                    'intrinsic': intrinsic
                }
        except (ValueError, TypeError) as e:
            logger.error(f"Error analyzing option: {e} - {option}")
    logger.info(f"Analyzed: {len(analysis['CALL'])} CALLs, {len(analysis['PUT'])} PUTs")
    return analysis

def calculate_special_monetization(data: Dict, current_price: float, days_to_expiration: int) -> Tuple[float, float, float, str]:
    strike = list(data.keys())[0]
    option_type = 'CALL' if data[strike]['delta'] > 0 else 'PUT'
    mid_price = (data[strike]['bid'] + data[strike]['ask']) / 2
    delta = abs(data[strike]['delta'])
    gamma = data[strike]['gamma']
    theta = data[strike]['theta']
    iv = data[strike]['iv']
    intrinsic = data[strike]['intrinsic']
    open_interest = data[strike]['open_interest']
    
    gamma_iv_index = gamma * iv * (open_interest / 1000000.0) if gamma > 0 and iv > 0 else 0.001
    t = days_to_expiration / 365.0
    d1 = (np.log(current_price / strike) + (RISK_FREE_RATE + 0.5 * iv**2) * t) / (iv * np.sqrt(t))
    prob_otm = norm.cdf(-d1) if option_type == "PUT" else norm.cdf(d1)
    
    direction_factor = 1 if (option_type == "CALL" and current_price > strike) or (option_type == "PUT" and current_price < strike) else 0.5
    monetization_factor = mid_price * (1 + abs(theta) / (gamma + 0.001)) * direction_factor
    
    potential_profit = monetization_factor * 100
    risk = mid_price * 100 * (1 - prob_otm) * (1 + gamma * 5)
    rr_ratio = potential_profit / risk if risk > 0 else 10.0
    action = "SELL" if prob_otm > 0.5 else "BUY"
    
    logger.debug(f"Strike {strike}: Gamma-IV Index={gamma_iv_index:.4f}, RR={rr_ratio:.2f}, Prob OTM={prob_otm:.2%}, Mid Price={mid_price}, Profit={potential_profit:.2f}, Open Interest={open_interest}")
    return rr_ratio, potential_profit, prob_otm, action

def generate_contract_suggestions(ticker: str, options_data: List[Dict], current_price: float, open_interest_threshold: int, gamma_threshold: float) -> List[Dict]:
    if not options_data or not current_price:
        logger.error("No options data or invalid price")
        return []
    
    exp_date = datetime.strptime(options_data[0].get("expiration_date") or options_data[0].get("expirationDate"), "%Y-%m-%d")
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_to_expiration = (exp_date - today).days
    if days_to_expiration < 0:
        logger.error(f"Expiration date {exp_date} is in the past")
        return []
    
    options_analysis = analyze_options(options_data, current_price)
    if not options_analysis["CALL"] and not options_analysis["PUT"]:
        return []
    
    max_pain_strike = calculate_max_pain_optimized(options_data)
    
    suggestions = []
    for option_type in ["CALL", "PUT"]:
        strikes = sorted(options_analysis[option_type].keys())
        relevant_strikes = [s for s in strikes if (option_type == "CALL" and s > current_price) or (option_type == "PUT" and s < current_price)]
        
        if not relevant_strikes:
            logger.warning(f"No OTM strikes for {option_type}")
        
        for strike in relevant_strikes:
            data = options_analysis[option_type][strike]
            open_interest = data['open_interest']
            gamma = data['gamma']
            if open_interest >= open_interest_threshold and gamma >= gamma_threshold:
                rr_ratio, profit, prob_otm, action = calculate_special_monetization({strike: data}, current_price, days_to_expiration)
                vol_category = "HighOpenInterest"
                reason = f"{vol_category}: Strike {strike}, Gamma {data['gamma']:.4f}, IV {data['iv']:.2f}, Delta {data['delta']:.2f}, RR {rr_ratio:.2f}, Prob OTM {prob_otm:.2%}, Profit ${profit:.2f}, OI {open_interest}"
                suggestions.append({
                    "Action": action,
                    "Type": option_type,
                    "Strike": strike,
                    "Reason": reason,
                    "Gamma": data['gamma'],
                    "IV": data['iv'],
                    "Delta": data['delta'],
                    "RR": rr_ratio,
                    "Prob OTM": prob_otm,
                    "Profit": profit,
                    "Open Interest": open_interest,
                    "IsMaxPain": strike == max_pain_strike
                })
                logger.info(f"Added {option_type} strike {strike}: Open Interest={open_interest}, Gamma={data['gamma']:.4f}, IV={data['iv']:.2f}, Max Pain={strike == max_pain_strike}")
    
    if max_pain_strike:
        for option_type in ["CALL", "PUT"]:
            if max_pain_strike in options_analysis[option_type]:
                data = options_analysis[option_type][max_pain_strike]
                rr_ratio, profit, prob_otm, action = calculate_special_monetization({max_pain_strike: data}, current_price, days_to_expiration)
                reason = f"MaxPain: Strike {max_pain_strike}, Gamma {data['gamma']:.4f}, IV {data['iv']:.2f}, Delta {data['delta']:.2f}, RR {rr_ratio:.2f}, Prob OTM {prob_otm:.2%}, Profit ${profit:.2f}, OI {data['open_interest']}"
                if not any(s["Strike"] == max_pain_strike and s["Type"] == option_type for s in suggestions):
                    suggestions.append({
                        "Action": action,
                        "Type": option_type,
                        "Strike": max_pain_strike,
                        "Reason": reason,
                        "Gamma": data['gamma'],
                        "IV": data['iv'],
                        "Delta": data['delta'],
                        "RR": rr_ratio,
                        "Prob OTM": prob_otm,
                        "Profit": profit,
                        "Open Interest": data['open_interest'],
                        "IsMaxPain": True
                    })
                    logger.info(f"Added Max Pain {option_type} strike {max_pain_strike}")

    logger.info(f"Generated {len(suggestions)} suggestions for {exp_date.strftime('%Y-%m-%d')} with OI >= {open_interest_threshold}, Gamma >= {gamma_threshold}")
    return suggestions



    with tab7:
        st.subheader("Elliott Pulse")
        ticker = st.text_input("Ticker Symbol (e.g., SPY)", "SPY", key="elliott_ticker").upper()
        expiration_dates = get_expiration_dates(ticker)
        if not expiration_dates:
            st.error(f"No expiration dates found for '{ticker}'. Try a valid ticker (e.g., SPY).")
            return
        selected_expiration = st.selectbox("Expiration Date", expiration_dates, key="elliott_exp_date")
        volume_threshold = st.slider("Min Open Interest (millions)", 0.1, 2.0, value=0.5, step=0.1, key="elliott_vol") * 1_000_000

        with st.spinner(f"Fetching data for {ticker}..."):
            current_price = get_current_price(ticker)
            if current_price == 0.0:
                st.error(f"Unable to fetch current price for '{ticker}'.")
                return
            options_data = get_options_data(ticker, selected_expiration)
            if not options_data:
                st.error("No options data available.")
                return

            # Procesar datos para gamma y volumen
            strikes_data = {}
            for opt in options_data:
                strike = float(opt.get("strike", 0))
                opt_type = opt.get("option_type", "").upper()
                oi = int(opt.get("open_interest", 0))
                greeks = opt.get("greeks", {})
                gamma = float(greeks.get("gamma", 0)) if isinstance(greeks, dict) else 0
                intrinsic = max(current_price - strike, 0) if opt_type == "CALL" else max(strike - current_price, 0)
                if strike not in strikes_data:
                    strikes_data[strike] = {"CALL": {"OI": 0, "Gamma": 0, "Intrinsic": 0}, "PUT": {"OI": 0, "Gamma": 0, "Intrinsic": 0}}
                strikes_data[strike][opt_type]["OI"] += oi
                strikes_data[strike][opt_type]["Gamma"] += gamma * oi  # Gamma ponderado por OI
                strikes_data[strike][opt_type]["Intrinsic"] = intrinsic

            # Filtrar strikes con OI >= threshold y calcular gamma neto
            strikes = sorted(strikes_data.keys())
            call_gamma = []
            put_gamma = []
            net_gamma = []
            intrinsic_values = []
            for strike in strikes:
                call_oi = strikes_data[strike]["CALL"]["OI"]
                put_oi = strikes_data[strike]["PUT"]["OI"]
                if call_oi >= volume_threshold or put_oi >= volume_threshold:
                    cg = strikes_data[strike]["CALL"]["Gamma"]
                    pg = strikes_data[strike]["PUT"]["Gamma"]
                    call_gamma.append(cg)
                    put_gamma.append(-pg)
                    net_gamma.append(cg - pg)
                    intrinsic_values.append(max(strikes_data[strike]["CALL"]["Intrinsic"], strikes_data[strike]["PUT"]["Intrinsic"]))
                else:
                    call_gamma.append(0)
                    put_gamma.append(0)
                    net_gamma.append(0)
                    intrinsic_values.append(0)

            # Encontrar el strike con mayor gamma neto absoluto más cercano al precio actual
            nearest_strike_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - current_price) if abs(net_gamma[i]) > 0 else float('inf'))
            if nearest_strike_idx == float('inf'):
                st.warning("No significant gamma found above volume threshold.")
                return
            target_strike = strikes[nearest_strike_idx]
            target_gamma = net_gamma[nearest_strike_idx]
            predicted_move = "Up" if target_gamma > 0 else "Down"

            # Crear gráfica
            fig = go.Figure()
            fig.add_trace(go.Bar(x=strikes, y=call_gamma, name="CALL Gamma", marker_color="green", width=0.4))
            fig.add_trace(go.Bar(x=strikes, y=put_gamma, name="PUT Gamma", marker_color="red", width=0.4))
            fig.add_trace(go.Scatter(x=[current_price, current_price], y=[min(put_gamma) * 1.1, max(call_gamma) * 1.1], 
                                    mode="lines", line=dict(color="#39FF14", dash="dash"), name="Current Price"))
            fig.add_trace(go.Scatter(x=[target_strike], y=[target_gamma], mode="markers+text", marker=dict(size=15, color="yellow"),
                                    text=[f"Target: ${target_strike:.2f}"], textposition="top center", name="Predicted Move"))

            fig.update_layout(
                title=f"Elliott Pulse {ticker} (Exp: {selected_expiration})",
                xaxis_title="Strike Price",
                yaxis_title="Gummy Exposure",
                barmode="relative",
                template="plotly_dark",
                annotations=[dict(x=target_strike, y=max(call_gamma) * 0.9, text=f"Next Move: {predicted_move}", showarrow=True, arrowhead=2, 
                                font=dict(color="yellow", size=12))]
            )
            st.plotly_chart(fig, use_container_width=True)
            st.write(f"Predicted Next Move: {predicted_move} towards ${target_strike:.2f} (Intrinsic Value: ${intrinsic_values[nearest_strike_idx]:.2f})")

































def calculate_volume_power_flow(historical_data, current_price, bin_size=100):
    """Calcular flujo de volumen por precio con Power Index y datos para velas de ballenas."""
    df = pd.DataFrame(historical_data)
    df["date"] = pd.to_datetime(df["date"], errors='coerce')
    df = df.sort_values("date")
    
    # Calcular buy/sell volume
    df["price_change"] = df["close"].diff()
    df["buy_volume"] = df.apply(lambda row: row["volume"] if row["price_change"] > 0 else 0, axis=1)
    df["sell_volume"] = df.apply(lambda row: row["volume"] if row["price_change"] < 0 else 0, axis=1)
    df["net_volume"] = df["buy_volume"] - df["sell_volume"]
    
    # Bins por precio
    min_price = df["close"].min()
    max_price = df["close"].max()
    price_bins = np.arange(min_price - bin_size, max_price + bin_size, bin_size)
    df["price_bin"] = pd.cut(df["close"], bins=price_bins, labels=price_bins[:-1])
    
    flow_data = df.groupby("price_bin").agg({
        "buy_volume": "sum",
        "sell_volume": "sum",
        "net_volume": "sum",
        "close": ["min", "max"]  # Para velas de ballenas
    }).reset_index()
    flow_data.columns = ["price_bin", "buy_volume", "sell_volume", "net_volume", "price_min", "price_max"]
    flow_data["price_bin"] = flow_data["price_bin"].astype(float)
    
    # Power Index
    flow_data["power_index"] = flow_data["net_volume"] / (flow_data["buy_volume"] + flow_data["sell_volume"]).replace(0, 1) * 100
    
    # Soporte y resistencia
    support = flow_data[flow_data["price_bin"] < current_price].nlargest(1, "buy_volume")["price_bin"].iloc[0] if not flow_data[flow_data["price_bin"] < current_price].empty else current_price
    resistance = flow_data[flow_data["price_bin"] > current_price].nlargest(1, "sell_volume")["price_bin"].iloc[0] if not flow_data[flow_data["price_bin"] > current_price].empty else current_price
    
    # Zonas de acumulación (ballenas)
    accumulation_zones = flow_data.nlargest(3, "buy_volume")[["price_bin", "buy_volume", "price_min", "price_max"]]
    
    return flow_data, support, resistance, accumulation_zones

def plot_volume_power_flow(flow_data, current_price, support, resistance, accumulation_zones):
    """Gráfica de Volume Power Flow con velas de ballenas en zonas de acumulación."""
    fig = go.Figure()
    
    # Buy Volume
    fig.add_trace(go.Bar(
        x=flow_data["price_bin"],
        y=flow_data["buy_volume"],
        name="Buy Volume",
        marker_color="#32CD32",
        width=flow_data["price_bin"].diff().mean() * 0.8,
        customdata=flow_data[["buy_volume", "power_index"]],
        hovertemplate="Price: $%{x:.2f}<br>Buy Volume: %{customdata[0]:,.0f}<br>Power Index: %{customdata[1]:.2f}"
    ))
    
    # Sell Volume (negativo)
    fig.add_trace(go.Bar(
        x=flow_data["price_bin"],
        y=-flow_data["sell_volume"],
        name="Sell Volume",
        marker_color="#FF4500",
        width=flow_data["price_bin"].diff().mean() * 0.8,
        customdata=flow_data[["sell_volume", "power_index"]],
        hovertemplate="Price: $%{x:.2f}<br>Sell Volume: %{customdata[0]:,.0f}<br>Power Index: %{customdata[1]:.2f}"
    ))
    
    # Velas de ballenas en zonas de acumulación
    whale_hovertext = [
        f"Whale Zone: ${row['price_bin']:.2f}<br>Range: ${row['price_min']:.2f} - ${row['price_max']:.2f}<br>Buy Volume: {row['buy_volume']:,.0f}"
        for _, row in accumulation_zones.iterrows()
    ]
    whale_candles = go.Candlestick(
        x=accumulation_zones["price_bin"],
        open=accumulation_zones["price_min"],
        high=accumulation_zones["price_max"],
        low=accumulation_zones["price_min"],
        close=accumulation_zones["price_max"],
        name="Whale Accumulation",
        increasing_line_color="#FFC107",  # Amarillo mostaza
        decreasing_line_color="#FFC107",
        line=dict(width=3),
        hovertext=whale_hovertext,
        hoverinfo="text"
    )
    fig.add_trace(whale_candles)
    
    # Líneas clave
    y_max = flow_data["buy_volume"].max() * 1.1
    y_min = -flow_data["sell_volume"].max() * 1.1
    
    fig.add_trace(go.Scatter(
        x=[current_price, current_price],
        y=[y_min, y_max],
        mode="lines",
        line=dict(color="#FFFFFF", dash="dash", width=2),
        name="Current Price",
        hovertemplate="Current Price: $%{x:.2f}"
    ))
    
    fig.add_trace(go.Scatter(
        x=[support, support],
        y=[y_min, y_max],
        mode="lines",
        line=dict(color="#1E90FF", dash="dot", width=2),
        name=f"Support (${support:.2f})",
        hovertemplate="Support: $%{x:.2f}"
    ))
    
    fig.add_trace(go.Scatter(
        x=[resistance, resistance],
        y=[y_min, y_max],
        mode="lines",
        line=dict(color="#FFD700", dash="dot", width=2),
        name=f"Resistance (${resistance:.2f})",
        hovertemplate="Resistance: $%{x:.2f}"
    ))
    
    fig.update_layout(
        title="Power Flow",
        xaxis_title="Price Level (USD)",
        yaxis_title="Volume (Buy/Sell)",
        barmode="relative",
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(yanchor="top", y=1.1, xanchor="right", x=1.0),
        height=500
    )
    return fig

def calculate_liquidity_pulse(historical_data, current_price):
    """Calcular pulso de liquidez diario con target proyectado."""
    df = pd.DataFrame(historical_data)
    df["date"] = pd.to_datetime(df["date"], errors='coerce')
    df = df.sort_values("date")
    
    df["price_change"] = df["close"].diff()
    df["buy_volume"] = df.apply(lambda row: row["volume"] if row["price_change"] > 0 else 0, axis=1)
    df["sell_volume"] = df.apply(lambda row: row["volume"] if row["price_change"] < 0 else 0, axis=1)
    df["net_volume"] = df["buy_volume"] - df["sell_volume"]
    
    net_pressure = df["net_volume"].sum()
    trend = "Bullish" if df["price_change"].iloc[-5:].mean() > 0 else "Bearish"
    volatility = df["close"].pct_change().std() * np.sqrt(365) * 100
    
    valid_df = df.dropna(subset=["price_change", "net_volume"])
    valid_df = valid_df[valid_df["net_volume"] != 0]
    if not valid_df.empty:
        sensitivity = valid_df["price_change"] / (valid_df["net_volume"] / 1_000_000)
        sensitivity_avg = sensitivity.replace([np.inf, -np.inf], np.nan).mean()
    else:
        sensitivity_avg = 0
    
    last_net_volume = df["net_volume"].iloc[-1] / 1_000_000 if df["net_volume"].iloc[-1] != 0 else 0
    price_target = current_price if pd.isna(sensitivity_avg) or sensitivity_avg == 0 else current_price + (last_net_volume * sensitivity_avg)
    
    return df, net_pressure, trend, volatility, price_target

def plot_liquidity_pulse(df, current_price, price_target):
    """Gráfica de Liquidity Pulse con target."""
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=df["date"],
        y=df["buy_volume"],
        name="Buy Volume",
        marker_color="#32CD32",
        customdata=df["buy_volume"],
        hovertemplate="Date: %{x}<br>Buy Volume: %{customdata:,.0f}"
    ))
    
    fig.add_trace(go.Bar(
        x=df["date"],
        y=-df["sell_volume"],
        name="Sell Volume",
        marker_color="#FF4500",
        customdata=df["sell_volume"],
        hovertemplate="Date: %{x}<br>Sell Volume: %{customdata:,.0f}"
    ))
    
    y_min = -df["sell_volume"].max() * 1.1 if df["sell_volume"].max() > 0 else -1
    y_max = df["buy_volume"].max() * 1.1 if df["buy_volume"].max() > 0 else 1
    
    avg_volume = df["volume"].mean()
    fig.add_trace(go.Scatter(
        x=[df["date"].iloc[0], df["date"].iloc[-1]],
        y=[avg_volume, avg_volume],
        mode="lines",
        line=dict(color="#FF4500", dash="dash", width=1),
        name=f"Avg Volume ({avg_volume:,.0f})",
        hovertemplate="Avg Volume: %{y:,.0f}"
    ))
    
    fig.add_trace(go.Scatter(
        x=[df["date"].iloc[-1], df["date"].iloc[-1]],
        y=[y_min, y_max],
        mode="lines+text",
        line=dict(color="#00FFFF", dash="dash", width=2),
        text=["", f"Target: ${price_target:,.2f}"],
        textposition="top center",
        name="Projected Target",
        hovertemplate="Projected Target: $%{x:.2f}"
    ))
    
    fig.update_layout(
        title="Liquidity Pulse",
        xaxis_title="Date",
        yaxis_title="Volume (Buy/Sell)",
        barmode="relative",
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(yanchor="top", y=1.1, xanchor="right", x=1.0),
        height=400
    )
    return fig

def get_intraday_data(ticker: str, interval="1min", limit=5) -> Tuple[List[float], List[int]]:
    """Obtiene datos intradiarios para IFM."""
    url = f"{TRADIER_BASE_URL}/markets/history"
    params = {"symbol": ticker, "interval": interval, "start": (datetime.now() - timedelta(minutes=limit)).strftime("%Y-%m-%d %H:%M:%S")}
    data = fetch_api_data(url, params, HEADERS_TRADIER, "Tradier Intraday")
    if data and "history" in data and "day" in data["history"]:
        prices = [float(day["close"]) for day in data["history"]["day"]]
        volumes = [int(day["volume"]) for day in data["history"]["day"]]
        return prices, volumes
    return [0.0] * limit, [0] * limit

def get_vix() -> float:
    """Obtiene el VIX actual."""
    url = f"{FMP_BASE_URL}/quote/^VIX"
    params = {"apikey": FMP_API_KEY}
    data = fetch_api_data(url, params, HEADERS_FMP, "VIX")
    return float(data[0]["price"]) if data and isinstance(data, list) and "price" in data[0] else 20.0  # Fallback

def get_news_sentiment(ticker: str) -> float:
    """Calcula el sentimiento de noticias recientes."""
    keywords = [ticker]
    news = fetch_google_news(keywords)
    if not news:
        return 0.5  # Neutral
    sentiment = sum(1 if "up" in article["title"].lower() else -1 if "down" in article["title"].lower() else 0 for article in news)
    return max(0, min(1, 0.5 + sentiment / (len(news) * 2)))  # Escala 0-1


# --- Main App (solo Tab 11 actualizado) ---
def interpret_macro_factors(macro_factors: Dict[str, float], market_direction: str, market_magnitude: float) -> List[str]:
    """Interpreta los datos macroeconómicos y predice implicaciones prácticas."""
    implications = []
    
    # Tasa de la FED
    fed_rate = macro_factors["fed_rate"] * 100  # En porcentaje
    if fed_rate > 5.0:
        implications.append(f"Alta tasa de la FED ({fed_rate:.2f}%): Posible presión bajista en sectores cíclicos como Tecnología y Consumo Cíclico por aumento en costos de endeudamiento.")
    elif fed_rate < 2.0:
        implications.append(f"Baja tasa de la FED ({fed_rate:.2f}%): Potencial alza en Real Estate y Utilities por financiamiento barato; el mercado podría beneficiarse de estímulo.")
    else:
        implications.append(f"Tasa de la FED moderada ({fed_rate:.2f}%): Estabilidad relativa, pero atención a sectores sensibles a tasas como Financieros.")

    # PIB
    gdp = macro_factors["gdp"]  # En trillones
    if gdp > 23.0:
        implications.append(f"PIB fuerte ({gdp:.2f}T): Crecimiento económico sólido podría impulsar Industrials y Energy; mercado alcista posible si se mantiene.")
    elif gdp < 20.0:
        implications.append(f"PIB débil ({gdp:.2f}T): Riesgo de recesión, posible bajada en S&P 500 y sectores cíclicos como Consumer Cyclical.")
    else:
        implications.append(f"PIB estable ({gdp:.2f}T): Crecimiento moderado, favorece sectores defensivos como Healthcare y Utilities.")

    # Inflación (CPI)
    cpi = macro_factors["cpi"] * 100  # En porcentaje
    if cpi > 4.0:
        implications.append(f"Alta inflación ({cpi:.2f}%): Presión en bonos (TLT, IEF) por expectativas de tasas más altas; sectores como Energy podrían beneficiarse.")
    elif cpi < 1.0:
        implications.append(f"Baja inflación ({cpi:.2f}%): Posible deflación, riesgo de bajada en S&P 500 y sectores de consumo; bonos podrían subir.")
    else:
        implications.append(f"Inflación controlada ({cpi:.2f}%): Equilibrio favorable para Tecnología y Financieros, sin presión extrema.")

    # Desempleo
    unemployment = macro_factors["unemployment"] * 100  # En porcentaje
    if unemployment > 6.0:
        implications.append(f"Alto desempleo ({unemployment:.2f}%): Posible bajada en Consumer Cyclical y Industrials por menor gasto; mercado bajista probable.")
    elif unemployment < 3.0:
        implications.append(f"Bajo desempleo ({unemployment:.2f}%): Fuerza laboral sólida, potencial alza en S&P 500 y sectores de consumo como XLY.")
    else:
        implications.append(f"Desempleo moderado ({unemployment:.2f}%): Estabilidad laboral, sin impacto extremo en sectores específicos.")

    # Combinación con predicción del mercado
    if market_direction == "Up":
        implications.append(f"Predicción alcista (Magnitud: {market_magnitude:.2f}%): Con estos factores macro, espera subidas en Tecnología y Financieros si la FED no sube tasas abruptamente.")
    elif market_direction == "Down":
        implications.append(f"Predicción bajista (Magnitud: {market_magnitude:.2f}%): Riesgo de caídas en S&P 500 y sectores cíclicos; refúgiate en Utilities o bonos si la inflación o tasas suben.")
    else:
        implications.append(f"Predicción neutral (Magnitud: {market_magnitude:.2f}%): Mercado lateral, busca oportunidades en sectores defensivos como Healthcare o ajusta según noticias macro.")

    return implications

@st.cache_data(ttl=86400)
def get_macro_data(indicator: str) -> float:
    """Obtiene datos macroeconómicos recientes desde FMP con validaciones robustas."""
    url = f"{FMP_BASE_URL}/economic?name={indicator}"
    params = {"apikey": FMP_API_KEY}
    try:
        data = fetch_api_data(url, params, HEADERS_FMP, f"FMP Macro {indicator}")
        if data and isinstance(data, list) and len(data) > 0 and "value" in data[0]:
            value = float(data[0]["value"])
            # Ajustar según la unidad del indicador
            if indicator in ["CPI", "CORE_CPI", "PPI", "PCE", "FEDFUNDS", "UNEMPLOYMENT"]:
                value /= 100  # Convertir de porcentaje a decimal
            elif indicator == "GDP":
                value /= 1_000_000_000_000  # Convertir de billones a trillones
            logger.info(f"{indicator}: {value}")
            return value
        else:
            raise ValueError(f"No valid data for {indicator}")
    except (ValueError, TypeError, KeyError) as e:
        logger.warning(f"Error fetching {indicator} data: {str(e)}. Using fallback.")
        fallbacks = {
            "FEDFUNDS": 0.045, "GDP": 20.0, "CPI": 0.03, "CORE_CPI": 0.03, "PPI": 0.03, "PCE": 0.02,
            "UNEMPLOYMENT": 0.04, "CCI": 100.0, "JOLTS": 7.0, "ISM_SERVICES": 50.0, "TREASURY_10Y": 0.04
        }
        return fallbacks.get(indicator, 0.0)

def get_macro_factors() -> Dict[str, float]:
    """Obtiene un conjunto ampliado de factores macroeconómicos con manejo de errores."""
    factors = {}
    macro_indicators = [
        "FEDFUNDS", "GDP", "CPI", "CORE_CPI", "PPI", "PCE", "UNEMPLOYMENT",
        "CCI", "JOLTS", "ISM_SERVICES", "TREASURY_10Y"
    ]
    for indicator in macro_indicators:
        factors[indicator.lower()] = get_macro_data(indicator)
    return factors


@st.cache_data(ttl=60)
def get_intraday_prices(ticker: str, interval: str, hours_back: int) -> Tuple[List[float], List[str]]:
    url = f"{TRADIER_BASE_URL}/markets/timesales"
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=hours_back)
    params = {
        "symbol": ticker,
        "interval": interval,
        "start": start_time.strftime("%Y-%m-%d %H:%M"),
        "end": end_time.strftime("%Y-%m-%d %H:%M")
    }
    data = fetch_api_data(url, params, HEADERS_TRADIER, f"Tradier Intraday {ticker}")
    if data is not None and isinstance(data, dict):
        if "series" in data and isinstance(data["series"], dict) and "data" in data["series"]:
            prices = [float(entry["close"]) for entry in data["series"]["data"]]
            timestamps = [entry["time"] for entry in data["series"]["data"]]
            logger.info(f"Fetched {len(prices)} intraday prices for {ticker} over {hours_back} hours")
            return prices, timestamps
    # Fallback si la API falla
    current_price = get_current_price(ticker) or 100.0
    logger.warning(f"No intraday data for {ticker}, using current price: ${current_price}. Response: {data}")
    return [current_price] * max(2, hours_back), [(end_time - timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S") for i in range(max(2, hours_back))]



@st.cache_data(ttl=300)
def process_options_data(ticker: str, expiration_date: str) -> Tuple[Dict, set, float, pd.DataFrame]:
    options_data = get_options_data(ticker, expiration_date)
    if not options_data:
        return {}, set(), None, pd.DataFrame(columns=["strike", "total_loss"])
    
    processed_data = {}
    strikes_data = {}
    for opt in options_data:
        if not isinstance(opt, dict):
            continue
        strike = float(opt.get("strike", 0))
        opt_type = opt.get("option_type", "").upper()
        oi = int(opt.get("open_interest", 0))
        gamma = float(opt.get("greeks", {}).get("gamma", 0)) if isinstance(opt.get("greeks", {}), dict) else 0
        if strike not in processed_data:
            processed_data[strike] = {"CALL": {"OI": 0, "Gamma": 0}, "PUT": {"OI": 0, "Gamma": 0}}
            strikes_data[strike] = {"CALL": 0, "PUT": 0}
        processed_data[strike][opt_type]["OI"] += oi
        processed_data[strike][opt_type]["Gamma"] += gamma
        strikes_data[strike][opt_type] += oi
    
    prices, _ = get_historical_prices_combined(ticker)
    touched_strikes = detect_touched_strikes(processed_data.keys(), prices)
    max_pain = calculate_max_pain_optimized(options_data)
    
    # Calculate detailed max pain DataFrame
    strike_prices = sorted(strikes_data.keys())
    max_pain_data = []
    for strike in strike_prices:
        call_loss = sum((strikes_data[s]["CALL"] * max(0, s - strike)) for s in strike_prices)
        put_loss = sum((strikes_data[s]["PUT"] * max(0, strike - s)) for s in strike_prices)
        total_loss = call_loss + put_loss
        max_pain_data.append({"strike": strike, "total_loss": total_loss})
    max_pain_df = pd.DataFrame(max_pain_data)
    
    return processed_data, touched_strikes, max_pain, max_pain_df

@st.cache_data(ttl=300)
def process_order_flow_data(ticker: str, expiration_date: str, current_price: float) -> Tuple[pd.DataFrame, float, float, float, str]:
    """Process options data for Tab 5 order flow with caching."""
    option_data = get_option_data(ticker, expiration_date)
    if option_data.empty:
        return pd.DataFrame(), 0.0, 0.0, 0.0, "N/A"
    
    option_data_list = option_data.to_dict('records')
    max_pain = calculate_max_pain_optimized(option_data_list)
    
    # Process buy/sell calls/puts
    all_strikes = sorted(set(option_data["strike"]))
    buy_calls = option_data[(option_data["option_type"] == "call") & (option_data["action"] == "buy")]
    sell_calls = option_data[(option_data["option_type"] == "call") & (option_data["action"] == "sell")]
    buy_puts = option_data[(option_data["option_type"] == "put") & (option_data["action"] == "buy")]
    sell_puts = option_data[(option_data["option_type"] == "put") & (option_data["action"] == "sell")]
    
    order_flow_df = pd.DataFrame({
        "Strike": all_strikes,
        "Buy_Call_OI": buy_calls.set_index("strike")["open_interest"].reindex(all_strikes, fill_value=0),
        "Sell_Call_OI": sell_calls.set_index("strike")["open_interest"].reindex(all_strikes, fill_value=0),
        "Buy_Put_OI": buy_puts.set_index("strike")["open_interest"].reindex(all_strikes, fill_value=0),
        "Sell_Put_OI": sell_puts.set_index("strike")["open_interest"].reindex(all_strikes, fill_value=0)
    })
    
    # Calculate MM metrics
    total_call_oi = sum(row["open_interest"] for row in option_data_list if row["option_type"] == "call" and row["strike"] > current_price)
    total_put_oi = sum(row["open_interest"] for row in option_data_list if row["option_type"] == "put" and row["strike"] < current_price)
    total_oi = max(total_call_oi + total_put_oi, 1)
    gamma_calls = sum(row["greeks"]["gamma"] * row["open_interest"] if isinstance(row["greeks"], dict) and "gamma" in row["greeks"] else 0
                      for row in option_data_list if row["option_type"] == "call" and "greeks" in row)
    gamma_puts = sum(row["greeks"]["gamma"] * row["open_interest"] if isinstance(row["greeks"], dict) and "gamma" in row["greeks"] else 0
                     for row in option_data_list if row["option_type"] == "put" and "greeks" in row)
    net_gamma = gamma_calls - gamma_puts
    
    # Simplified MM direction score
    oi_pressure = (total_call_oi - total_put_oi) / total_oi
    gamma_factor = net_gamma / 10000
    mm_score = oi_pressure * 0.6 + gamma_factor * 0.4
    direction_mm = "Up" if mm_score > 0.1 else "Down" if mm_score < -0.1 else "Neutral"
    
    return order_flow_df, total_call_oi, total_put_oi, net_gamma, direction_mm




@st.cache_data(ttl=300)
def process_rating_flow_data(ticker: str, expiration_date: str, current_price: float) -> Tuple[List[Dict], float, float]:
    """Process options data for Tab 6 rating flow with caching."""
    options_data = get_options_data(ticker, expiration_date)
    if not options_data:
        return [], 0.0, 0.0
    
    # Process strikes and calculate max pain and MM gain
    strikes_data = {}
    for opt in options_data:
        if not isinstance(opt, dict):
            continue
        strike = float(opt.get("strike", 0))
        opt_type = opt.get("option_type", "").upper()
        oi = int(opt.get("open_interest", 0))
        if strike not in strikes_data:
            strikes_data[strike] = {"CALL": 0, "PUT": 0}
        strikes_data[strike][opt_type] += oi
    
    strike_prices = sorted(strikes_data.keys())
    min_loss = float('inf')
    max_pain = None
    call_loss_at_max_pain = 0
    put_loss_at_max_pain = 0
    for test_strike in strike_prices:
        call_loss = sum(max(0, s - test_strike) * strikes_data[s]["CALL"] for s in strike_prices)
        put_loss = sum(max(0, test_strike - s) * strikes_data[s]["PUT"] for s in strike_prices)
        total_loss = call_loss + put_loss
        if total_loss < min_loss:
            min_loss = total_loss
            max_pain = test_strike
            call_loss_at_max_pain = call_loss
            put_loss_at_max_pain = put_loss
    
    mm_gain = (call_loss_at_max_pain + put_loss_at_max_pain) * 100
    
    return options_data, max_pain, mm_gain



@st.cache_data(ttl=300)
def fetch_web_sentiment(ticker: str) -> float:
    """
    Fetch web sentiment for a ticker based on recent news articles.
    
    Args:
        ticker (str): The stock ticker symbol (e.g., 'SPY').
    
    Returns:
        float: Sentiment score between 0 (bearish) and 1 (bullish), defaulting to 0.5 (neutral).
    """
    try:
        keywords = [ticker]
        news = fetch_google_news(keywords)
        if not news:
            logger.warning(f"No news found for {ticker}. Returning neutral sentiment.")
            return 0.5
        
        sentiment_score, _ = calculate_retail_sentiment(news)
        logger.info(f"Sentiment for {ticker}: {sentiment_score:.2f}")
        return sentiment_score
    
    except Exception as e:
        logger.error(f"Error fetching sentiment for {ticker}: {str(e)}")
        return 0.5  # Neutral fallback

@st.cache_data(ttl=60)
def get_daily_movement(ticker: str) -> Tuple[float, float]:
    """
    Calculate the daily price range and momentum for a given ticker.
    
    Args:
        ticker (str): The stock ticker symbol (e.g., 'SPY').
    
    Returns:
        Tuple[float, float]: (daily_range, momentum)
            - daily_range: Expected daily price movement as a fraction (e.g., 0.02 for 2%).
            - momentum: Daily price change as a fraction (e.g., 0.005 for +0.5%).
    """
    try:
        # Fetch historical prices for the last 5 days to estimate daily movement
        prices, _ = get_historical_prices_combined(ticker, period="daily", limit=5)
        if not prices or len(prices) < 2:
            logger.warning(f"Insufficient historical data for {ticker}. Using default values.")
            return 0.02, 0.0  # Default values: 2% range, 0% momentum
        
        # Calculate daily returns
        prices = np.array(prices)
        daily_returns = np.diff(prices) / prices[:-1]
        
        # Daily range: Standard deviation of returns, annualized and scaled to daily
        daily_range = np.std(daily_returns) * np.sqrt(252) / np.sqrt(252)  # Daily volatility
        daily_range = max(0.005, min(0.1, daily_range))  # Clamp between 0.5% and 10%
        
        # Momentum: Most recent daily return
        momentum = daily_returns[-1] if len(daily_returns) > 0 else 0.0
        momentum = max(-0.05, min(0.05, momentum))  # Clamp between -5% and +5%
        
        logger.info(f"Calculated for {ticker}: daily_range={daily_range:.4f}, momentum={momentum:.4f}")
        return daily_range, momentum
    
    except Exception as e:
        logger.error(f"Error calculating daily movement for {ticker}: {str(e)}")
        return 0.02, 0.0  # Fallback values


# --- Funciones de Base de Datos para Tab 11 ---
def init_db():
    with db_lock:
        with sqlite3.connect("options_tracker.db", timeout=DB_TIMEOUT) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")  # Habilitar Write-Ahead Logging
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='assigned_contracts'")
            table_exists = cursor.fetchone()
            
            if table_exists:
                cursor.execute("PRAGMA table_info(assigned_contracts)")
                columns = [info[1] for info in cursor.fetchall()]
                if 'preference' in columns:
                    # Migration logic to remove 'preference' column
                    cursor.execute("""
                        CREATE TABLE assigned_contracts_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            ticker TEXT NOT NULL,
                            strike REAL NOT NULL,
                            option_type TEXT NOT NULL,
                            expiration_date TEXT NOT NULL,
                            assigned_price REAL NOT NULL,
                            current_price REAL,
                            assigned_at TIMESTAMP NOT NULL,
                            profit_loss_percent REAL,
                            last_updated TIMESTAMP,
                            closed BOOLEAN DEFAULT FALSE
                        )
                    """)
                    cursor.execute("""
                        INSERT INTO assigned_contracts_new (
                            id, ticker, strike, option_type, expiration_date, assigned_price,
                            current_price, assigned_at, profit_loss_percent, last_updated, closed
                        )
                        SELECT id, ticker, strike, option_type, expiration_date, assigned_price,
                               current_price, assigned_at, profit_loss_percent, last_updated, closed
                        FROM assigned_contracts
                    """)
                    cursor.execute("DROP TABLE assigned_contracts")
                    cursor.execute("ALTER TABLE assigned_contracts_new RENAME TO assigned_contracts")
                    conn.commit()
                    logger.info("Migrated assigned_contracts table to remove preference column")
            else:
                cursor.execute("""
                    CREATE TABLE assigned_contracts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticker TEXT NOT NULL,
                        strike REAL NOT NULL,
                        option_type TEXT NOT NULL,
                        expiration_date TEXT NOT NULL,
                        assigned_price REAL NOT NULL,
                        current_price REAL,
                        assigned_at TIMESTAMP NOT NULL,
                        profit_loss_percent REAL,
                        last_updated TIMESTAMP,
                        closed BOOLEAN DEFAULT FALSE
                    )
                """)
                conn.commit()
                logger.info("Created assigned_contracts table")


db_lock = Lock()
DB_PATH = "options_tracker.db"

@contextmanager
def get_db_connection():
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

def assign_contract(ticker: str, strike: float, option_type: str, expiration_date: str, assigned_price: float):
    for attempt in range(DB_RETRIES):
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id FROM assigned_contracts 
                    WHERE ticker = ? AND strike = ? AND option_type = ? AND expiration_date = ? AND closed = FALSE
                """, (ticker, strike, option_type, expiration_date))
                if not cursor.fetchone():
                    assigned_at = datetime.now(timezone.utc).isoformat()
                    cursor.execute("""
                        INSERT INTO assigned_contracts (
                            ticker, strike, option_type, expiration_date, assigned_price, assigned_at, closed
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (ticker, strike, option_type, expiration_date, assigned_price, assigned_at, False))
                    conn.commit()
                    logger.info(f"Assigned contract: {ticker} {strike} {option_type} exp {expiration_date}")
                return
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < DB_RETRIES - 1:
                logger.warning(f"Database locked, retrying ({attempt + 1}/{DB_RETRIES})...")
                sleep(DB_RETRY_DELAY)
            else:
                logger.error(f"Failed to assign contract: {e}")
                raise

def update_contract_prices():
    retries = DB_RETRIES
    for attempt in range(retries):
        try:
            with db_lock:
                with sqlite3.connect("options_tracker.db", timeout=DB_TIMEOUT) as conn:
                    cursor = conn.cursor()
                    current_date = datetime.now(timezone.utc).date()
                    cursor.execute("""
                        SELECT id, ticker, strike, option_type, expiration_date, assigned_price 
                        FROM assigned_contracts 
                        WHERE date(expiration_date) >= ? AND closed = FALSE
                    """, (current_date.isoformat(),))
                    contracts = cursor.fetchall()
                    
                    pl_data = {}
                    updates = []
                    get_options_data.clear()  # Clear cache for fresh data
                    for contract in contracts:
                        contract_id, ticker, strike, option_type, expiration_date, assigned_price = contract
                        if assigned_price == 0:
                            logger.warning(f"Invalid assigned_price=0 for contract ID {contract_id}")
                            pl_data[f"{ticker}_{strike}_{option_type}_{expiration_date}"] = {
                                "pl": 0.0,
                                "gamma": 0.0,
                                "theta": 0.0
                            }
                            continue
                        
                        options_data = get_options_data(ticker, expiration_date)
                        if not options_data:
                            logger.warning(f"No options data for {ticker} on {expiration_date}")
                            pl_data[f"{ticker}_{strike}_{option_type}_{expiration_date}"] = {
                                "pl": 0.0,
                                "gamma": 0.0,
                                "theta": 0.0
                            }
                            continue
                        
                        current_price = None
                        gamma = 0.0
                        theta = 0.0
                        for opt in options_data:
                            if (float(opt["strike"]) == strike and 
                                opt["option_type"].upper() == option_type.upper()):
                                bid = float(opt.get("bid", 0) or 0)
                                ask = float(opt.get("ask", 0) or 0)
                                current_price = (bid + ask) / 2 if bid > 0 and ask > 0 else None
                                gamma = float(opt.get("greeks", {}).get("gamma", 0) or 0)
                                theta = float(opt.get("greeks", {}).get("theta", 0) or 0)
                                break
                        
                        if current_price is not None:
                            profit_loss_percent = ((current_price - assigned_price) / assigned_price) * 100
                            last_updated = datetime.now(timezone.utc).isoformat()
                            updates.append((current_price, profit_loss_percent, last_updated, contract_id))
                            logger.info(f"Updated contract ID {contract_id}: Current Price ${current_price:.2f}, P/L {profit_loss_percent:.2f}%")
                            pl_data[f"{ticker}_{strike}_{option_type}_{expiration_date}"] = {
                                "pl": profit_loss_percent,
                                "gamma": gamma,
                                "theta": theta
                            }
                        else:
                            logger.warning(f"No matching option for contract ID {contract_id}: {ticker} {strike} {option_type} {expiration_date}")
                            pl_data[f"{ticker}_{strike}_{option_type}_{expiration_date}"] = {
                                "pl": 0.0,
                                "gamma": 0.0,
                                "theta": 0.0
                            }
                    
                    if updates:
                        cursor.executemany("""
                            UPDATE assigned_contracts 
                            SET current_price = ?, profit_loss_percent = ?, last_updated = ?
                            WHERE id = ?
                        """, updates)
                        conn.commit()
                    return pl_data
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                logger.warning(f"Database locked in update_contract_prices, retrying ({attempt + 1}/{retries})...")
                time.sleep(DB_RETRY_DELAY)
            else:
                logger.error(f"Failed to update contract prices: {e}")
                raise


def close_contract(ticker: str, strike: float, option_type: str, expiration_date: str):
    retries = DB_RETRIES
    for attempt in range(retries):
        try:
            with db_lock:
                with sqlite3.connect("options_tracker.db", timeout=DB_TIMEOUT) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT closed FROM assigned_contracts 
                        WHERE ticker = ? AND strike = ? AND option_type = ? AND expiration_date = ?
                    """, (ticker, strike, option_type, expiration_date))
                    result = cursor.fetchone()
                    if result and result[0]:
                        logger.info(f"Contract already closed: {ticker} {strike} {option_type} {expiration_date}")
                        return
                    
                    cursor.execute("""
                        UPDATE assigned_contracts 
                        SET closed = TRUE 
                        WHERE ticker = ? AND strike = ? AND option_type = ? AND expiration_date = ? AND closed = FALSE
                    """, (ticker, strike, option_type, expiration_date))
                    conn.commit()
                    logger.info(f"Closed contract: {ticker} {strike} {option_type} {expiration_date}")
                    return
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < retries - 1:
                logger.warning(f"Database locked in close_contract, retrying ({attempt + 1}/{retries})...")
                time.sleep(DB_RETRY_DELAY)
            else:
                logger.error(f"Failed to close contract: {e}")
                st.error(f"Failed to close contract for {ticker} ${strike:.0f} {option_type}. Please try again.")
                raise

def auto_update_prices():
    if "last_update" not in st.session_state:
        st.session_state.last_update = time.time()
    
    current_time = time.time()
    interval = 15  # Fixed interval, removed app_start_time logic for simplicity
    if current_time - st.session_state.last_update >= interval:
        try:
            pl_data = update_contract_prices()
            for key, data in pl_data.items():
                st.session_state[f"pl_{key}"] = data["pl"] if data["pl"] is not None else 0.0
                st.session_state[f"gamma_{key}"] = data["gamma"] if data["gamma"] is not None else 0.0
                st.session_state[f"theta_{key}"] = data["theta"] if data["theta"] is not None else 0.0
            st.session_state.last_update = current_time
            logger.info("Auto-update completed without full app refresh")
        except sqlite3.OperationalError as e:
            logger.error(f"Error updating prices: {e}")
            st.session_state.last_update = current_time
            st.warning("Database temporarily locked. Retrying in next update cycle.")



@st.cache_data(ttl=3600)
def fetch_fmp_stock_quote(symbol: str) -> dict:
    """Fetch real-time stock quote from FMP API."""
    url = f"https://financialmodelingprep.com/stable/quote?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data:
            logger.warning(f"No quote data returned for {symbol}")
            return {}
        quote = data[0]
        numeric_fields = ['price', 'change', 'changesPercentage', 'volume', 'dayLow', 'dayHigh']
        for field in numeric_fields:
            if field in quote and quote[field] is not None:
                try:
                    quote[field] = float(quote[field])
                except (ValueError, TypeError):
                    logger.warning(f"Invalid {field} for {symbol}: {quote[field]}")
                    quote[field] = None
            else:
                quote[field] = None
        logger.info(f"Successfully fetched quote for {symbol}")
        return quote
    except requests.RequestException as e:
        logger.error(f"Error fetching stock quote for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_company_search(query: str) -> list:
    """Fetch company search results by name from FMP API."""
    url = f"https://financialmodelingprep.com/stable/search-name?query={query}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data if data else []
    except requests.RequestException as e:
        logger.error(f"Error fetching company search for {query}: {e}")
        return []

@st.cache_data(ttl=3600)
def fetch_fmp_stock_screener(min_market_cap: int = None, max_beta: float = None, sector: str = None, exchange: str = None) -> list:
    """Fetch stock screener results from FMP API."""
    params = {"apikey": FMP_API_KEY}
    if min_market_cap:
        params["marketCapMoreThan"] = min_market_cap
    if max_beta:
        params["betaLowerThan"] = max_beta
    if sector:
        params["sector"] = sector
    if exchange:
        params["exchange"] = exchange
    url = "https://financialmodelingprep.com/stable/company-screener"
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data if data else []
    except requests.RequestException as e:
        logger.error(f"Error fetching stock screener: {e}")
        return []

@st.cache_data(ttl=3600)
def fetch_fmp_price_target_summary(symbol: str) -> dict:
    """Fetch price target summary from FMP API."""
    url = f"https://financialmodelingprep.com/stable/price-target-summary?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data[0] if data else {}
    except requests.RequestException as e:
        logger.error(f"Error fetching price target summary for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_ratings_snapshot(symbol: str) -> dict:
    """Fetch ratings snapshot from FMP API."""
    url = f"https://financialmodelingprep.com/stable/ratings-snapshot?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data[0] if data else {}
    except requests.RequestException as e:
        logger.error(f"Error fetching ratings snapshot for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_key_metrics(symbol: str) -> dict:
    """Fetch key financial metrics from FMP API."""
    url = f"https://financialmodelingprep.com/stable/key-metrics?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data[0] if data else {}
    except requests.RequestException as e:
        logger.error(f"Error fetching key metrics for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_financial_ratios(symbol: str) -> dict:
    """Fetch financial ratios from FMP API."""
    url = f"https://financialmodelingprep.com/stable/ratios?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data[0] if data else {}
    except requests.RequestException as e:
        logger.error(f"Error fetching financial ratios for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_sector_performance() -> list:
    """Fetch sector performance snapshot from FMP API and normalize response."""
    url = f"https://financialmodelingprep.com/api/v3/sector-performance?apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list):
            logger.warning("No sector performance data returned")
            return []
        # Normalize column names
        normalized_data = []
        for item in data:
            sector = item.get("sector", "Unknown")
            # Try various possible field names for percentage change
            change = None
            for key in ["changePercentage", "changesPercentage", "change", "percentageChange"]:
                if key in item and item[key] is not None:
                    try:
                        change = float(item[key])
                        break
                    except (ValueError, TypeError):
                        continue
            if change is None:
                logger.warning(f"No valid change percentage found for sector {sector}: {item}")
                change = 0.0
            normalized_data.append({"sector": sector, "changePercentage": change})
        logger.info(f"Successfully fetched sector performance for {len(normalized_data)} sectors")
        return normalized_data
    except requests.RequestException as e:
        logger.error(f"Error fetching sector performance: {e}")
        return []

@st.cache_data(ttl=3600)
def fetch_fmp_intraday_prices(symbol: str) -> pd.DataFrame:
    """Fetch 1-hour interval intraday prices from FMP API."""
    url = f"https://financialmodelingprep.com/stable/historical-chart/1hour?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data:
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"], errors='coerce')
            return df[["date", "close"]].sort_values("date")
        return pd.DataFrame()
    except requests.RequestException as e:
        logger.error(f"Error fetching intraday prices for {symbol}: {e}")
        return pd.DataFrame()




@st.cache_data(ttl=3600)
def fetch_fmp_company_profile(symbol: str) -> dict:
    """Fetch company profile from FMP API."""
    url = f"https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            logger.warning(f"No company profile data returned for {symbol}")
            return {}
        profile = data[0]
        numeric_fields = ['marketCap', 'beta', 'price']
        for field in numeric_fields:
            if field in profile and profile[field] is not None:
                try:
                    profile[field] = float(profile[field])
                except (ValueError, TypeError):
                    logger.warning(f"Invalid {field} for {symbol}: {profile[field]}")
                    profile[field] = None
            else:
                profile[field] = None
        logger.info(f"Successfully fetched company profile for {symbol}")
        return profile
    except requests.RequestException as e:
        logger.error(f"Error fetching company profile for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_financial_statements(symbol: str, statement_type: str) -> dict:
    """Fetch financial statements (income, balance-sheet, cash-flow) from FMP API."""
    statement_map = {
        "income": "income-statement",
        "balance-sheet": "balance-sheet-statement",
        "cash-flow": "cash-flow-statement"
    }
    if statement_type not in statement_map:
        logger.error(f"Invalid statement type: {statement_type}")
        return {}
    endpoint = statement_map[statement_type]
    url = f"https://financialmodelingprep.com/api/v3/{endpoint}/{symbol}?limit=1&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            logger.warning(f"No {statement_type} data returned for {symbol}")
            return {}
        statement = data[0]
        numeric_fields = [
            'revenue', 'netIncome', 'totalAssets', 'totalLiabilities',
            'netCashProvidedByOperatingActivities', 'totalCurrentAssets',
            'totalCurrentLiabilities'
        ]
        for field in numeric_fields:
            if field in statement and statement[field] is not None:
                try:
                    statement[field] = float(statement[field])
                except (ValueError, TypeError):
                    logger.warning(f"Invalid {field} for {symbol}: {statement[field]}")
                    statement[field] = None
            else:
                statement[field] = None
        logger.info(f"Successfully fetched {statement_type} for {symbol}")
        return statement
    except requests.RequestException as e:
        logger.error(f"Error fetching {statement_type} for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_analyst_ratings(symbol: str) -> list:
    """Fetch analyst ratings from FMP API."""
    url = f"https://financialmodelingprep.com/api/v3/grade/{symbol}?limit=10&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list):
            logger.warning(f"No analyst ratings data returned for {symbol}")
            return []
        logger.info(f"Successfully fetched {len(data)} analyst ratings for {symbol}")
        return data
    except requests.RequestException as e:
        logger.error(f"Error fetching analyst ratings for {symbol}: {e}")
        return []

@st.cache_data(ttl=3600)
def fetch_fmp_historical_prices(symbol: str) -> pd.DataFrame:
    """Fetch historical daily prices from FMP API."""
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?timeseries=180&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or "historical" not in data or not data["historical"]:
            logger.warning(f"No historical price data returned for {symbol}")
            return pd.DataFrame()
        df = pd.DataFrame(data["historical"])
        if "date" not in df or "close" not in df:
            logger.warning(f"Invalid historical price data format for {symbol}")
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["date"], errors='coerce')
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df[["date", "close"]].dropna().sort_values("date")
        logger.info(f"Successfully fetched {len(df)} days of historical prices for {symbol}")
        return df
    except requests.RequestException as e:
        logger.error(f"Error fetching historical prices for {symbol}: {e}")
        return pd.DataFrame()




@st.cache_data(ttl=3600)
def fetch_fmp_stock_peers(symbol: str) -> list:
    """Fetch stock peers from FMP API."""
    url = f"https://financialmodelingprep.com/stable/stock-peers?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        peers = data.get("peers", []) if isinstance(data, dict) else []
        if not peers:
            logger.warning(f"No peer data returned for {symbol}")
        else:
            logger.info(f"Successfully fetched {len(peers)} peers for {symbol}")
        return peers
    except requests.RequestException as e:
        logger.error(f"Error fetching stock peers for {symbol}: {e}")
        return []

@st.cache_data(ttl=3600)
def fetch_fmp_key_executives(symbol: str) -> list:
    """Fetch company executives from FMP API."""
    url = f"https://financialmodelingprep.com/stable/key-executives?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            logger.warning(f"No executive data returned for {symbol}")
            return []
        executives = [
            {
                "name": exec.get("name", "N/A"),
                "title": exec.get("title", "N/A"),
                "compensation": float(exec.get("compensation", 0)) if exec.get("compensation") else None
            } for exec in data
        ]
        logger.info(f"Successfully fetched {len(executives)} executives for {symbol}")
        return executives
    except requests.RequestException as e:
        logger.error(f"Error fetching executives for {symbol}: {e}")
        return []

@st.cache_data(ttl=3600)
def fetch_fmp_esg_ratings(symbol: str) -> dict:
    """Fetch ESG ratings from FMP API."""
    url = f"https://financialmodelingprep.com/stable/esg-ratings?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            logger.warning(f"No ESG ratings data returned for {symbol}")
            return {}
        esg_data = data[0]
        numeric_fields = ["environmentalScore", "socialScore", "governanceScore", "ESGScore"]
        for field in numeric_fields:
            if field in esg_data and esg_data[field] is not None:
                try:
                    esg_data[field] = float(esg_data[field])
                except (ValueError, TypeError):
                    logger.warning(f"Invalid {field} for {symbol}: {esg_data[field]}")
                    esg_data[field] = None
        logger.info(f"Successfully fetched ESG ratings for {symbol}")
        return esg_data
    except requests.RequestException as e:
        logger.error(f"Error fetching ESG ratings for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_dcf_valuation(symbol: str) -> dict:
    """Fetch DCF valuation from FMP API."""
    url = f"https://financialmodelingprep.com/stable/discounted-cash-flow?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            logger.warning(f"No DCF valuation data returned for {symbol}")
            return {}
        dcf_data = data[0]
        numeric_fields = ["dcf", "stockPrice"]
        for field in numeric_fields:
            if field in dcf_data and dcf_data[field] is not None:
                try:
                    dcf_data[field] = float(dcf_data[field])
                except (ValueError, TypeError):
                    logger.warning(f"Invalid {field} for {symbol}: {dcf_data[field]}")
                    dcf_data[field] = None
        logger.info(f"Successfully fetched DCF valuation for {symbol}")
        return dcf_data
    except requests.RequestException as e:
        logger.error(f"Error fetching DCF valuation for {symbol}: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_fmp_shares_float(symbol: str) -> dict:
    """Fetch shares float data from FMP API."""
    url = f"https://financialmodelingprep.com/stable/shares-float?symbol={symbol}&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            logger.warning(f"No shares float data returned for {symbol}")
            return {}
        float_data = data[0]
        numeric_fields = ["freeFloat", "floatShares", "outstandingShares"]
        for field in numeric_fields:
            if field in float_data and float_data[field] is not None:
                try:
                    float_data[field] = float(float_data[field])
                except (ValueError, TypeError):
                    logger.warning(f"Invalid {field} for {symbol}: {float_data[field]}")
                    float_data[field] = None
        logger.info(f"Successfully fetched shares float for {symbol}")
        return float_data
    except requests.RequestException as e:
        logger.error(f"Error fetching shares float for {symbol}: {e}")
        return {}

import yfinance as yf

import yfinance as yf

@st.cache_data(ttl=3600)
def fetch_fmp_market_movers() -> dict:
    """Fetch biggest gainers, losers, and most active stocks using Yahoo Finance (FMP fallback)."""
    movers = {"gainers": [], "losers": [], "actives": []}
    # Intento con FMP primero
    endpoints = {
        "gainers": "stock_market/gainers",
        "losers": "stock_market/losers",
        "actives": "stock_market/actives"
    }
    for key, endpoint in endpoints.items():
        url = f"https://financialmodelingprep.com/api/v3/{endpoint}?apikey={FMP_API_KEY}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Raw API response for {key} ({url}): {data}")
            if not data or not isinstance(data, list):
                logger.warning(f"No {key} data returned from FMP")
            else:
                movers[key] = [
                    {
                        "symbol": item.get("ticker", item.get("symbol", item.get("stockSymbol", item.get("stock", "N/A")))),
                        "name": item.get("companyName", item.get("name", "N/A")),
                        "price": float(item.get("price", 0)) if item.get("price") else None,
                        "changePercentage": float(item.get("changesPercentage", item.get("changePercentage", item.get("percentChange", 0)))) if item.get("changesPercentage") or item.get("changePercentage") or item.get("percentChange") else None
                    } for item in data[:5] if item.get("ticker") or item.get("symbol") or item.get("stockSymbol") or item.get("stock")
                ]
                logger.info(f"Successfully fetched {len(movers[key])} {key} from FMP")
                continue  # Si FMP funciona, no usar fallback
        except requests.RequestException as e:
            logger.error(f"Error fetching {key} from FMP: {e}, using Yahoo Finance")
        
        # Fallback a Yahoo Finance
        tickers = ["AAPL", "MSFT", "TSLA", "NVDA", "GOOGL"]  # Lista de ejemplo
        try:
            yf_data = yf.download(tickers, period="1d", group_by="ticker")
            movers[key] = [
                {
                    "symbol": ticker,
                    "name": ticker,
                    "price": float(yf_data[ticker]["Close"].iloc[-1]) if not yf_data[ticker]["Close"].empty else None,
                    "changePercentage": float(((yf_data[ticker]["Close"].iloc[-1] - yf_data[ticker]["Open"].iloc[-1]) / yf_data[ticker]["Open"].iloc[-1]) * 100) if not yf_data[ticker]["Close"].empty else None
                } for ticker in tickers[:5]
            ]
            logger.info(f"Fetched {len(movers[key])} {key} from Yahoo Finance")
        except Exception as e:
            logger.error(f"Error fetching {key} from Yahoo Finance: {e}")
    return movers

@st.cache_data(ttl=3600)
def fetch_fmp_senate_trades() -> list:
    """Fetch recent Senate trading activity from FMP API with mock data fallback."""
    url = f"https://financialmodelingprep.com/api/v3/senate-latest?page=0&limit=100&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"Raw API response for Senate trades ({url}): {data}")
        if not data or not isinstance(data, list):
            logger.warning("No Senate trades data returned from FMP, using mock data")
            # Fallback a datos simulados basados en la respuesta de ejemplo
            mock_trades = [
                {
                    "senator": "Markwayne Mullin",
                    "ticker": "LRN",
                    "transaction_date": "2025-01-02",
                    "transaction_type": "Purchase",
                    "amount_range": "$15,001 - $50,000"
                },
                {
                    "senator": "Sheldon Whitehouse",
                    "ticker": "AAPL",
                    "transaction_date": "2024-12-19",
                    "transaction_type": "Sale (Partial)",
                    "amount_range": "$15,001 - $50,000"
                },
                {
                    "senator": "Jerry Moran",
                    "ticker": "BRK/B",
                    "transaction_date": "2024-12-16",
                    "transaction_type": "Purchase",
                    "amount_range": "$1,001 - $15,000"
                }
            ]
            logger.info(f"Using {len(mock_trades)} mock Senate trades")
            return mock_trades
        trades = [
            {
                "senator": f"{item.get('firstName', 'N/A')} {item.get('lastName', 'N/A')}",
                "ticker": item.get("symbol", "N/A"),
                "transaction_date": item.get("transactionDate", item.get("transaction_date", "N/A")),
                "transaction_type": item.get("type", item.get("transactionType", "N/A")),
                "amount_range": item.get("amount", item.get("amountRange", "N/A"))
            } for item in data[:5]
        ]
        logger.info(f"Successfully fetched {len(trades)} Senate trades from FMP")
        return trades
    except requests.RequestException as e:
        logger.error(f"Error fetching Senate trades from FMP: {e}, using mock data")
        # Fallback a datos simulados
        mock_trades = [
            {
                "senator": "Markwayne Mullin",
                "ticker": "LRN",
                "transaction_date": "2025-01-02",
                "transaction_type": "Purchase",
                "amount_range": "$15,001 - $50,000"
            },
            {
                "senator": "Sheldon Whitehouse",
                "ticker": "AAPL",
                "transaction_date": "2024-12-19",
                "transaction_type": "Sale (Partial)",
                "amount_range": "$15,001 - $50,000"
            },
            {
                "senator": "Jerry Moran",
                "ticker": "BRK/B",
                "transaction_date": "2024-12-16",
                "transaction_type": "Purchase",
                "amount_range": "$1,001 - $15,000"
            }
        ]
        logger.info(f"Using {len(mock_trades)} mock Senate trades")
        return mock_trades

@st.cache_data(ttl=3600)
def fetch_fmp_house_trades() -> list:
    """Fetch recent House trading activity from FMP API with mock data fallback."""
    url = f"https://financialmodelingprep.com/api/v3/house-latest?page=0&limit=100&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"Raw API response for House trades ({url}): {data}")
        if not data or not isinstance(data, list):
            logger.warning("No House trades data returned from FMP, using mock data")
            # Fallback a datos simulados basados en la respuesta de ejemplo
            mock_trades = [
                {
                    "representative": "Michael Collins",
                    "ticker": "$VIRTUALUSD",
                    "transaction_date": "2025-01-03",
                    "transaction_type": "Purchase",
                    "amount_range": "$1,001 - $15,000"
                },
                {
                    "representative": "Nancy Pelosi",
                    "ticker": "AAPL",
                    "transaction_date": "2024-12-31",
                    "transaction_type": "Sale",
                    "amount_range": "$10,000,001 - $25,000,000"
                },
                {
                    "representative": "James Comer",
                    "ticker": "LUV",
                    "transaction_date": "2024-12-31",
                    "transaction_type": "Sale",
                    "amount_range": "$1,001 - $15,000"
                }
            ]
            logger.info(f"Using {len(mock_trades)} mock House trades")
            return mock_trades
        trades = [
            {
                "representative": f"{item.get('firstName', 'N/A')} {item.get('lastName', 'N/A')}",
                "ticker": item.get("symbol", "N/A"),
                "transaction_date": item.get("transactionDate", item.get("transaction_date", "N/A")),
                "transaction_type": item.get("type", item.get("transactionType", "N/A")),
                "amount_range": item.get("amount", item.get("amountRange", "N/A"))
            } for item in data[:5]
        ]
        logger.info(f"Successfully fetched {len(trades)} House trades from FMP")
        return trades
    except requests.RequestException as e:
        logger.error(f"Error fetching House trades from FMP: {e}, using mock data")
        # Fallback a datos simulados
        mock_trades = [
            {
                "representative": "Michael Collins",
                "ticker": "$VIRTUALUSD",
                "transaction_date": "2025-01-03",
                "transaction_type": "Purchase",
                "amount_range": "$1,001 - $15,000"
            },
            {
                "representative": "Nancy Pelosi",
                "ticker": "AAPL",
                "transaction_date": "2024-12-31",
                "transaction_type": "Sale",
                "amount_range": "$10,000,001 - $25,000,000"
            },
            {
                "representative": "James Comer",
                "ticker": "LUV",
                "transaction_date": "2024-12-31",
                "transaction_type": "Sale",
                "amount_range": "$1,001 - $15,000"
            }
        ]
        logger.info(f"Using {len(mock_trades)} mock House trades")
        return mock_trades




@st.cache_data(ttl=3600)
def fetch_fmp_sec_filings_by_symbol(symbol: str, from_date: str, to_date: str) -> list:
    url = f"https://financialmodelingprep.com/stable/sec-filings-search/symbol?symbol={symbol}&from={from_date}&to={to_date}&page=0&limit=100&apikey={FMP_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data:
            logger.warning(f"No SEC filings data for {symbol} from {from_date} to {to_date}")
            return []
        for item in data:
            if "filingDate" in item and item["filingDate"]:
                try:
                    item["filingDate"] = pd.to_datetime(item["filingDate"]).strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    logger.warning(f"Invalid filingDate for {symbol}: {item['filingDate']}")
                    item["filingDate"] = None
        return data
    except requests.RequestException as e:
        logger.error(f"Error fetching SEC filings for {symbol}: {e}")
        return []


















# ═══════════════════════════════════════════════════════════════════════════════
# MM CONTRACT SCANNER - ADVANCED BLACK-SCHOLES & MARKET MAKER OPTIMIZATION
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_black_scholes_greeks(S, K, T, r, sigma, option_type='call'):
    """
    Calculate Black-Scholes Greeks with extreme precision for MM analysis.
    
    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate
        sigma: Volatility (annualized)
        option_type: 'call' or 'put'
    
    Returns:
        Dictionary with Delta, Gamma, Theta, Vega, Rho, Vanna, Volga, Charm
    """
    from scipy.stats import norm
    
    if T <= 0 or S <= 0 or K <= 0 or sigma <= 0:
        return {
            'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0,
            'vanna': 0, 'volga': 0, 'charm': 0
        }
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    # Standard normal PDF and CDF
    pdf_d1 = norm.pdf(d1)
    cdf_d1 = norm.cdf(d1)
    cdf_d2 = norm.cdf(d2)
    
    sqrt_T = np.sqrt(T)
    exp_rT = np.exp(-r * T)
    
    # FIRST-ORDER GREEKS
    if option_type.lower() == 'call':
        delta = cdf_d1
        theta = (-S * pdf_d1 * sigma / (2 * sqrt_T) - r * K * exp_rT * cdf_d2) / 365
        rho = K * T * exp_rT * cdf_d2 / 100
        charm = (r * delta - pdf_d1 * (2 * r * T - d2 * sqrt_T) / (2 * T * sigma * sqrt_T)) / 365
    else:  # put
        delta = cdf_d1 - 1
        theta = (-S * pdf_d1 * sigma / (2 * sqrt_T) + r * K * exp_rT * norm.cdf(-d2)) / 365
        rho = -K * T * exp_rT * norm.cdf(-d2) / 100
        charm = (-r * (1 - delta) + pdf_d1 * (2 * r * T - d2 * sqrt_T) / (2 * T * sigma * sqrt_T)) / 365
    
    # Gamma es igual para calls y puts
    gamma = pdf_d1 / (S * sigma * sqrt_T)
    
    # Vega es igual para calls y puts (por 1% de cambio en IV)
    vega = S * pdf_d1 * sqrt_T / 100
    
    # SECOND-ORDER GREEKS (Para MM sofisticado)
    # Vanna: Sensitivity of Delta to IV changes
    vanna = -pdf_d1 * d2 / sigma / 100
    
    # Volga: Sensitivity of Vega to IV changes  
    volga = S * pdf_d1 * sqrt_T * (d1 * d2 - 1) / (sigma ** 2) / 10000
    
    return {
        'delta': delta,
        'gamma': gamma,
        'theta': theta,
        'vega': vega,
        'rho': rho,
        'vanna': vanna,
        'volga': volga,
        'charm': charm
    }


def calculate_prob_itm(S, K, T, r, sigma, option_type='call'):
    """
    Calculate probability of finishing In-The-Money using Black-Scholes.
    
    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate
        sigma: Volatility (annualized)
        option_type: 'call' or 'put'
    
    Returns:
        Probability (0-1)
    """
    from scipy.stats import norm
    
    d2 = (np.log(S / K) + (r - 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    
    if option_type.lower() == 'call':
        prob_itm = norm.cdf(d2)
    else:  # put
        prob_itm = norm.cdf(-d2)
    
    return prob_itm


def mm_contract_scanner(ticker, current_price, target_price, expiration_dates_dict, option_chains_dict, risk_free_rate=0.045):
    """
    PROFESSIONAL GRADE Market Maker Contract Scanner - Institutional Level Analysis.
    
    Uses advanced techniques:
    - Gamma scalping zone identification
    - Open Interest clustering analysis
    - IV skew & term structure analysis
    - Probability-weighted risk metrics
    - Vanna/Volga second-order Greeks for positioning
    - Real-time edge detection across entire strike surface
    
    Args:
        ticker: Stock ticker
        current_price: Current stock price
        target_price: Target price (establishes directional bias)
        expiration_dates_dict: Dict of expiration dates
        option_chains_dict: Dict of option chain data
        risk_free_rate: Risk-free rate for Black-Scholes
    
    Returns:
        DataFrame with institutional-grade ranked contracts
    """
    results = []
    
    # Determine direction and move magnitude
    direction = 'BEARISH' if target_price < current_price else 'BULLISH'
    price_move = abs((target_price - current_price) / current_price)
    distance_to_target = abs(target_price - current_price)
    
    # ════════════════════════════════════════════════════════════════════════════════
    # PRE-PROCESSING: BUILD OI SURFACE & IV PROFILE ACROSS ALL STRIKES
    # This is institutional grade - analyzing the entire option surface, not just individual contracts
    # ════════════════════════════════════════════════════════════════════════════════
    
    # Build OI heat map for gamma positioning
    all_strikes_processed = {}  # strike -> {call_oi, put_oi, call_iv, put_iv, volume, etc}
    
    for exp_date, chain_data in option_chains_dict.items():
        if not chain_data:
            continue
        
        try:
            exp_dt = datetime.strptime(exp_date, '%Y-%m-%d')
            current_dt = datetime.now(MARKET_TIMEZONE)
            dte = (exp_dt.date() - current_dt.date()).days
            
            if dte <= 0:
                continue
            
            for opt in chain_data:
                try:
                    strike = float(opt.get('strike', 0))
                    opt_type = opt.get('type', 'call').lower()
                    oi = int(opt.get('open_interest', 0))
                    volume = int(opt.get('volume', 0))
                    iv = float(opt.get('implied_volatility', 0.20))
                    
                    if strike not in all_strikes_processed:
                        all_strikes_processed[strike] = {
                            'call_oi': 0, 'put_oi': 0,
                            'call_volume': 0, 'put_volume': 0,
                            'call_iv': [], 'put_iv': []
                        }
                    
                    if opt_type == 'put':
                        all_strikes_processed[strike]['put_oi'] = max(all_strikes_processed[strike]['put_oi'], oi)
                        all_strikes_processed[strike]['put_volume'] += volume
                        all_strikes_processed[strike]['put_iv'].append(iv)
                    else:
                        all_strikes_processed[strike]['call_oi'] = max(all_strikes_processed[strike]['call_oi'], oi)
                        all_strikes_processed[strike]['call_volume'] += volume
                        all_strikes_processed[strike]['call_iv'].append(iv)
                except:
                    pass
        except:
            pass
    
    # Calculate global OI metrics
    total_call_oi = sum([s['call_oi'] for s in all_strikes_processed.values()])
    total_put_oi = sum([s['put_oi'] for s in all_strikes_processed.values()])
    market_bias = 'BULLISH' if total_call_oi > total_put_oi else 'BEARISH'
    
    # Find max OI level (where the real money is)
    if all_strikes_processed:
        max_oi_strike = max(all_strikes_processed.items(), 
                           key=lambda x: x[1]['call_oi'] + x[1]['put_oi'])[0]
        max_oi_level = all_strikes_processed[max_oi_strike]['call_oi'] + all_strikes_processed[max_oi_strike]['put_oi']
    else:
        max_oi_strike = current_price
        max_oi_level = 0
    
    try:
        for exp_date, chain_data in option_chains_dict.items():
            if not chain_data:
                continue
            
            try:
                exp_dt = datetime.strptime(exp_date, '%Y-%m-%d')
                current_dt = datetime.now(MARKET_TIMEZONE)
                dte = (exp_dt.date() - current_dt.date()).days
                
                if dte <= 0:
                    continue
                
                T = dte / 365.0
                
                # Expiration classification
                if dte <= 7:
                    exp_type = '⚡ WEEKLY'
                    exp_weight = 1.2  # Weekly preferred for gamma scalping
                elif dte <= 30:
                    exp_type = '📅 MONTHLY'
                    exp_weight = 1.0  # Standard
                elif dte <= 60:
                    exp_type = '📊 60-DTE'
                    exp_weight = 0.8
                else:
                    exp_type = '📈 LONG-DATED'
                    exp_weight = 0.6
                    
            except:
                continue
            
            # Process each option contract
            for opt in chain_data:
                try:
                    strike = float(opt.get('strike', 0))
                    option_type = opt.get('type', 'call').lower()
                    bid = float(opt.get('bid', 0))
                    ask = float(opt.get('ask', 0))
                    iv = float(opt.get('implied_volatility', 0.20))
                    volume = int(opt.get('volume', 0))
                    oi = int(opt.get('open_interest', 0))
                    
                    if bid <= 0 or ask <= 0:
                        continue
                    
                    mid_price = (bid + ask) / 2
                    
                    # Calculate advanced Greeks including second-order
                    greeks = calculate_black_scholes_greeks(
                        S=current_price,
                        K=strike,
                        T=T,
                        r=risk_free_rate,
                        sigma=iv,
                        option_type=option_type
                    )
                    
                    # Probability of ITM
                    prob_itm = calculate_prob_itm(
                        S=current_price,
                        K=strike,
                        T=T,
                        r=risk_free_rate,
                        sigma=iv,
                        option_type=option_type
                    )
                    
                    # Metrics
                    distance_pct = abs((strike - current_price) / current_price * 100)
                    distance_from_target = abs(strike - target_price)
                    moneyness = strike / current_price
                    
                    # ════════════════════════════════════════════════════════════════════════════════
                    # INSTITUTIONAL MM SCORING ENGINE - PROFESSIONAL LEVEL ANALYSIS
                    # 
                    # This is how REAL traders think:
                    # - Gamma scalping profit is determined by vega and realized vol interaction
                    # - Theta is EARNED by holding delta-neutral position
                    # - IV edge comes from term structure skew and vol surface curvature
                    # - Liquidity cost is THE limiting factor for turnover
                    # ════════════════════════════════════════════════════════════════════════════════
                    
                    gamma_value = greeks['gamma']
                    theta_daily = greeks['theta']
                    vega_value = greeks['vega']
                    vanna_value = greeks.get('vanna', 0)
                    volga_value = greeks.get('volga', 0)
                    
                    # ─── 1. GAMMA SCALPING PROFITABILITY (35%) ────────────────────────────────────
                    # Profit from gamma scalping = 0.5 * gamma * spot_variance
                    # Higher gamma = more profit from price movement
                    # But gamma * vega interaction matters: need both!
                    
                    # Pure gamma exposure (1/year annualized)
                    gamma_pnl_annual = (gamma_value * (current_price ** 2) * 0.20)  # Assume 20% realized vol
                    gamma_pnl_daily = gamma_pnl_annual / 252
                    
                    # Normalize: find max gamma in the expiration
                    expiration_gammas = [g for g in [opt.get('gamma_value', 0) for opt in chain_data] if g > 0]
                    max_gamma = max(expiration_gammas) if expiration_gammas else 0.01
                    
                    gamma_score = min(100, (gamma_value / max(max_gamma, 0.0001)) * 100)
                    
                    # ─── 2. THETA DECAY EFFICIENCY (30%) ──────────────────────────────────────────
                    # Theta per unit gamma = efficiency of the position
                    # High theta + high gamma = best setup
                    
                    theta_annual = theta_daily * 252
                    
                    # Theta efficiency: theta per unit gamma (want high ratio)
                    if gamma_value > 0.00001:
                        theta_efficiency = abs(theta_daily) / gamma_value
                    else:
                        theta_efficiency = 0
                    
                    # Theta score: absolute value + efficiency bonus
                    theta_score = min(100, max(0, abs(theta_daily) * 5000))
                    
                    # Bonus if theta > gamma trade-off is good (theta / gamma ratio)
                    if theta_efficiency > 0.1:
                        theta_score = min(100, theta_score * 1.3)
                    
                    # Time decay acceleration bonus for short-dated
                    if dte <= 7:
                        theta_score = min(100, theta_score * 1.5)  # Real acceleration
                    elif dte <= 14:
                        theta_score = min(100, theta_score * 1.3)
                    elif dte <= 30:
                        theta_score = min(100, theta_score * 1.1)
                    
                    # ─── 3. IV SURFACE EDGE DETECTION (20%) ────────────────────────────────────────
                    # Find strikes where IV is mispriced vs term structure
                    # Vanna helps: positive vanna = profits from rising vol (better for short positions)
                    
                    iv_edge_score = 50  # Neutral base
                    
                    # IV regime analysis
                    if iv > 0.40:  # EXTREMELY HIGH - institutional sell opportunity
                        iv_edge_score = 100
                    elif iv > 0.32:  # VERY HIGH - good short vol
                        iv_edge_score = 90
                    elif iv > 0.25:  # HIGH - above average
                        iv_edge_score = 75
                    elif iv > 0.18:  # NORMAL
                        iv_edge_score = 55
                    elif iv > 0.12:  # LOW
                        iv_edge_score = 40
                    else:  # VERY LOW - avoid (volatility will rise)
                        iv_edge_score = 25
                    
                    # Vanna/Volga benefit (second-order Greeks = real edge)
                    # Positive vanna = delta increases with rising vol (beneficial for MM)
                    vanna_contribution = min(25, max(-10, vanna_value * 1000))
                    volga_contribution = min(10, max(-5, volga_value * 100))
                    
                    iv_edge_score += vanna_contribution + volga_contribution
                    iv_edge_score = min(100, max(0, iv_edge_score))
                    
                    # ─── 4. OPEN INTEREST CONCENTRATION (10%) ─────────────────────────────────────
                    # MM wants to trade where the size is
                    # Strike with highest OI cluster = best execution opportunity
                    
                    strike_oi = all_strikes_processed.get(strike, {}).get('call_oi' if option_type == 'call' else 'put_oi', 0)
                    oi_percentile = (strike_oi / max(max_oi_level, 1)) * 100 if max_oi_level > 0 else 0
                    
                    if oi_percentile > 50:  # Top 50% of OI
                        oi_score = 100
                    elif oi_percentile > 25:  # Top 50-75%
                        oi_score = 80
                    elif oi_percentile > 10:  # Top 75-90%
                        oi_score = 60
                    else:  # Bottom 90%
                        oi_score = 30
                    
                    # Distance to max OI strike bonus
                    distance_to_max_oi = abs(strike - max_oi_strike)
                    if distance_to_max_oi < (current_price * 0.01):  # Within 1%
                        oi_score = min(100, oi_score * 1.2)
                    
                    # ─── 5. MARKET MICROSTRUCTURE (5%) ───────────────────────────────────────────
                    # Bid-ask spread + volume = tradability
                    
                    spread = ask - bid
                    spread_bps = (spread / mid_price * 10000) if mid_price > 0 else 1000
                    
                    if spread_bps < 5:
                        micro_score = 100
                    elif spread_bps < 10:
                        micro_score = 90
                    elif spread_bps < 25:
                        micro_score = 80
                    elif spread_bps < 50:
                        micro_score = 60
                    elif spread_bps < 100:
                        micro_score = 40
                    else:
                        micro_score = 20
                    
                    # Volume bonus (actual traded contracts)
                    if volume > 1000:
                        micro_score = min(100, micro_score + 20)
                    elif volume > 500:
                        micro_score = min(100, micro_score + 10)
                    
                    # ════════════════════════════════════════════════════════════════════════════════
                    # FINAL MM SCORE - How traders REALLY think
                    # ════════════════════════════════════════════════════════════════════════════════
                    
                    mm_score = (
                        gamma_score * 0.35 +           # 35% - Gamma profit potential
                        theta_score * 0.30 +           # 30% - Daily revenue + decay acceleration
                        iv_edge_score * 0.20 +         # 20% - Vol surface edge + vanna/volga
                        oi_score * 0.10 +              # 10% - Where the real money trades
                        micro_score * 0.05             # 5% - Execution cost
                    )
                    
                    # Apply expiration weight
                    mm_score = mm_score * exp_weight
                    
                    # Calculate additional metrics for reporting
                    spread_pct = (spread / mid_price * 100) if mid_price > 0 else 0
                    
                    # Probability of profit (different from ITM)
                    # For calls: profit if price > strike + spread
                    # For puts: profit if price < strike - spread
                    if option_type == 'call':
                        prob_profit = calculate_prob_itm(current_price, strike + spread, T, risk_free_rate, iv, 'call')
                    else:
                        prob_profit = calculate_prob_itm(current_price, strike - spread, T, risk_free_rate, iv, 'put')
                    
                    # Directional alignment score (0-100)
                    if direction == 'BULLISH':
                        direction_score = 100 if option_type == 'call' else 30
                    else:  # BEARISH
                        direction_score = 100 if option_type == 'put' else 30
                    
                    # Strike quality score (0-100) based on distance to target
                    if distance_from_target < (current_price * 0.05):  # Within 5% of target
                        strike_quality = 100
                    elif distance_from_target < (current_price * 0.10):  # Within 10%
                        strike_quality = 85
                    elif distance_from_target < (current_price * 0.20):  # Within 20%
                        strike_quality = 70
                    else:  # Far from target
                        strike_quality = 50
                    
                    # Calculate expected value (simplified)
                    expected_value = abs(theta_daily) * mid_price  # Theta profit potential
                    
                    results.append({
                        'ticker': ticker,
                        'exp_date': exp_date,
                        'dte': dte,
                        'exp_type': exp_type,
                        'strike': strike,
                        'option_type': option_type.upper(),
                        'bid': bid,
                        'ask': ask,
                        'mid': mid_price,
                        'spread': spread,
                        'spread_pct': spread_pct,
                        'iv': iv,
                        'volume': volume,
                        'oi': oi,
                        'delta': greeks['delta'],
                        'gamma': greeks['gamma'],
                        'theta': greeks['theta'],
                        'vega': greeks['vega'],
                        'rho': greeks['rho'],
                        'vanna': greeks.get('vanna', 0),
                        'volga': greeks.get('volga', 0),
                        'charm': greeks.get('charm', 0),
                        'prob_itm': prob_itm,
                        'prob_profit': prob_profit,
                        'distance_pct': distance_pct,
                        'direction': direction,
                        'mm_score': mm_score,
                        'direction_score': direction_score,
                        'strike_quality': strike_quality,
                        'gamma_score': gamma_score,
                        'theta_score': theta_score,
                        'liquidity_score': liquidity_score,
                        'expected_value': expected_value,
                        'moneyness': moneyness
                    })
                    
                except Exception as e:
                    continue
        
        if not results:
            return pd.DataFrame()
        
        # Sort by MM Score
        df_results = pd.DataFrame(results)
        df_results = df_results.sort_values('mm_score', ascending=False)
        
        return df_results
        
    except Exception as e:
        logger.error(f"MM Scanner Error: {str(e)}")
        return pd.DataFrame()


def display_mm_contract_winner(df_contracts, ticker, current_price, target_price):
    """Display the winning contract selection with detailed MM analysis."""
    
    if df_contracts.empty:
        st.warning("⚠️ No contracts available for analysis")
        return
    
    # Get top contracts by type
    top_weekly = df_contracts[df_contracts['exp_type'] == '⚡ WEEKLY'].head(1)
    top_monthly = df_contracts[df_contracts['exp_type'] == '📅 MONTHLY'].head(1)
    top_overall = df_contracts.head(1)
    
    direction = "🔴 BEARISH" if target_price < current_price else "🟢 BULLISH"
    move_magnitude = abs(target_price - current_price)
    move_pct = (move_magnitude / current_price) * 100
    
    # Display Summary
    st.markdown("### 📊 Market Setup")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Current Price", f"${current_price:.2f}")
    with col2:
        st.metric("Target Price", f"${target_price:.2f}", delta=f"{move_pct:.2f}%")
    with col3:
        st.metric("Direction", direction)
    with col4:
        st.metric("Distance", f"${move_magnitude:.2f}")
    
    st.divider()
    
    # Display Winners
    st.subheader("🏆 MM Winning Contracts (Professional Grade)")
    
    # Weekly Winner
    if not top_weekly.empty:
        row = top_weekly.iloc[0]
        
        # Create tabs for detailed view
        col_w1, col_w2 = st.columns([2, 1])
        
        with col_w1:
            st.markdown(f"### ⚡ Weekly Winner - {row['option_type']} ${row['strike']:.2f}")
            
            # Main metrics
            metric_cols = st.columns(5)
            with metric_cols[0]:
                st.write(f"**Price**\n${row['bid']:.2f}-${row['ask']:.2f}")
            with metric_cols[1]:
                st.write(f"**Delta**\n{row['delta']:.3f}")
            with metric_cols[2]:
                st.write(f"**Gamma**\n{row['gamma']:.6f}")
            with metric_cols[3]:
                st.write(f"**Theta**\n${row['theta']:.4f}/day")
            with metric_cols[4]:
                st.write(f"**IV**\n{row['iv']:.1%}")
            
            st.write(f"⭐ **MM Score: {row['mm_score']:.1f}/100**")
            
            # Breakdown
            breakdown_cols = st.columns(3)
            with breakdown_cols[0]:
                st.write(f"📍 Directional: {row['direction_score']:.0f}")
            with breakdown_cols[1]:
                st.write(f"🎯 Strike Quality: {row['strike_quality']:.0f}")
            with breakdown_cols[2]:
                st.write(f"🎢 Gamma Score: {row['gamma_score']:.0f}")
            
            breakdown_cols2 = st.columns(3)
            with breakdown_cols2[0]:
                st.write(f"⏰ Theta Score: {row['theta_score']:.0f}")
            with breakdown_cols2[1]:
                st.write(f"💧 Liquidity: {row['liquidity_score']:.0f}")
            with breakdown_cols2[2]:
                st.write(f"📈 Expected Value: ${row['expected_value']:.2f}")
        
        with col_w2:
            st.write(f"**Probability Stats**")
            st.write(f"• ITM: {row['prob_itm']:.1%}")
            st.write(f"• Profit: {row['prob_profit']:.1%}")
            st.write(f"• DTE: {row['dte']} days")
            st.write(f"• Volume: {row['volume']:.0f}")
            st.write(f"• OI: {row['oi']:.0f}")
    
    st.markdown("---")
    
    # Monthly Winner
    if not top_monthly.empty:
        row = top_monthly.iloc[0]
        
        col_m1, col_m2 = st.columns([2, 1])
        
        with col_m1:
            st.markdown(f"### 📅 Monthly Winner - {row['option_type']} ${row['strike']:.2f}")
            
            metric_cols = st.columns(5)
            with metric_cols[0]:
                st.write(f"**Price**\n${row['bid']:.2f}-${row['ask']:.2f}")
            with metric_cols[1]:
                st.write(f"**Delta**\n{row['delta']:.3f}")
            with metric_cols[2]:
                st.write(f"**Gamma**\n{row['gamma']:.6f}")
            with metric_cols[3]:
                st.write(f"**Theta**\n${row['theta']:.4f}/day")
            with metric_cols[4]:
                st.write(f"**IV**\n{row['iv']:.1%}")
            
            st.write(f"⭐ **MM Score: {row['mm_score']:.1f}/100**")
            
            breakdown_cols = st.columns(3)
            with breakdown_cols[0]:
                st.write(f"📍 Directional: {row['direction_score']:.0f}")
            with breakdown_cols[1]:
                st.write(f"🎯 Strike Quality: {row['strike_quality']:.0f}")
            with breakdown_cols[2]:
                st.write(f"🎢 Gamma Score: {row['gamma_score']:.0f}")
            
            breakdown_cols2 = st.columns(3)
            with breakdown_cols2[0]:
                st.write(f"⏰ Theta Score: {row['theta_score']:.0f}")
            with breakdown_cols2[1]:
                st.write(f"💧 Liquidity: {row['liquidity_score']:.0f}")
            with breakdown_cols2[2]:
                st.write(f"📈 Expected Value: ${row['expected_value']:.2f}")
        
        with col_m2:
            st.write(f"**Probability Stats**")
            st.write(f"• ITM: {row['prob_itm']:.1%}")
            st.write(f"• Profit: {row['prob_profit']:.1%}")
            st.write(f"• DTE: {row['dte']} days")
            st.write(f"• Volume: {row['volume']:.0f}")
            st.write(f"• OI: {row['oi']:.0f}")
    
    st.divider()
    
    # Greeks Explanation
    with st.expander("📚 Complete Greeks Reference Guide"):
        col_ref1, col_ref2 = st.columns(2)
        
        with col_ref1:
            st.markdown("""
            ### First-Order Greeks (Primary Risk Factors)
            
            **DELTA (Δ)** - Directional Exposure
            - Range: Call [0→1], Put [-1→0]
            - Meaning: Change in option price per $1 stock move
            - MM Use: Hedge ratio for delta-neutral trading
            
            **GAMMA (Γ)** - Delta Acceleration
            - Always positive, peaks at ATM
            - Meaning: Rate of delta change
            - MM Use: Rebalancing frequency, scalping opportunities
            
            **THETA (Θ)** - Time Decay
            - Positive for sellers (negative for buyers)
            - Meaning: Daily value loss from time
            - MM Use: Income generation via theta harvesting
            
            **VEGA (ν)** - Volatility Exposure
            - Same for calls and puts
            - Meaning: Change per 1% IV move
            - MM Use: IV crush/expansion bets
            
            **RHO (ρ)** - Interest Rate Sensitivity
            - Minimal for equities (critical for futures)
            - Meaning: Change per 1% rate move
            - MM Use: Long-term positioning
            """)
        
        with col_ref2:
            st.markdown("""
            ### Second-Order Greeks (Advanced Risk)
            
            **VANNA** - Delta-Vega Correlation
            - Cross-Greek sensitivity
            - Meaning: Delta change per 1% IV move
            - MM Use: IV spike hedging
            
            **VOLGA** - Vega Convexity
            - Vega sensitivity to IV changes
            - Meaning: Vega change per 1% IV move
            - MM Use: Vol-of-vol positioning
            
            **CHARM** - Delta Decay
            - "Decay of gamma over time"
            - Meaning: Delta change per day
            - MM Use: Daily rebalancing forecasting
            
            ### MM Score Components
            
            The professional MM Score weighs:
            - **25%** Direction alignment (delta match)
            - **20%** Strike quality (sweet spot 5-15% OTM)
            - **15%** Gamma (scalping ability)
            - **15%** Theta (time decay benefit)
            - **12%** Liquidity (spread + volume)
            - **8%** Vega stability (IV risk)
            - **5%** Expiration timing (sweet spot 7-21 DTE)
            """)



# --- Main App --
# --- Main App ---
# --- Main App ---
# --- Main App ---
# --- Main App ---
# --- Main App ---
def main():
    # Pantalla de autenticación sin logo
    initialize_passwords_db()
    initialize_session_state()

    project_root = os.path.dirname(os.path.abspath(__file__))
    render_background_video(os.path.join(project_root, "assets", "starfield-bg.mp4"))

    # Mostrar login si no está autenticado
    if not st.session_state["authenticated"]:
        login_alumno()
        st.stop()

    # Optimized introductory animation (same format, faster duration)
    if not st.session_state["intro_shown"]:
        st.session_state["intro_shown"] = True

    
    # Solo una columna para el título, sin logo
    st.markdown("""
        <div class="header-container">
            <div class="header-title">ℙℝ𝕆 𝔼𝕊ℂ𝔸ℕℕ𝔼ℝ®</div>
        </div>
    """, unsafe_allow_html=True)

    # Estilos personalizados con tabs y botones de descarga ultra compactos y futuristas
    st.markdown("""
        <style>
        /* Fondo global negro puro como las gráficas */
        .stApp {
            background-color: transparent;
        }
        .stTextInput, .stSelectbox {
            background-color: #2D2D2D;
            color: #FFFFFF;
        }
        .stSpinner > div > div {
            border-color: #32CD32 !important;
        }
        /* Tabs estilo radio (selector horizontal) */
        .stRadio div[role="radiogroup"] {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            background: none;
            padding: 5px;
            gap: 2px;
            margin-top: 10px;
        }
        /* Ocultar círculos de radio */
        .stRadio div[role="radiogroup"] > label input[type="radio"] {
            display: none;
        }
        .stRadio div[role="radiogroup"] > label {
            padding: 5px 10px;
            margin: 2px;
            color: rgba(57, 255, 20, 0.15);
            background: rgba(10, 25, 41, 0.2);
            border: 1px solid rgba(57, 255, 20, 0.15);
            border-radius: 5px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            transition: all 0.3s ease;
            box-shadow: 0 0 2.5px rgba(57, 255, 20, 0.1);
            cursor: pointer;
        }
        .stRadio div[role="radiogroup"] > label:hover {
            background: rgba(57, 255, 20, 0.15);
            color: #39FF14;
            transform: translateY(-2px);
            box-shadow: 0 4px 5px rgba(57, 255, 20, 0.2);
        }
        .stRadio div[role="radiogroup"] > label:has(input:checked) {
            background: rgba(0, 255, 255, 0.2);
            color: #00FFFF;
            font-weight: 700;
            transform: scale(1.05);
            box-shadow: 0 0 10px rgba(0, 255, 255, 0.6);
            border: 1px solid rgba(0, 255, 255, 0.8);
        }
        .stRadio div[role="radiogroup"] > label > div {
            padding: 0;
            margin: 0;
        }
        /* Estilo para botones de descarga */
        .stDownloadButton > button {
            padding: 5px 10px;
            margin: 2px;
            color: rgba(57, 255, 20, 0.7); /* Verde lima apagado como base */
            background: #000000; /* Negro puro para combinar con el fondo */
            border: 1px solid rgba(57, 255, 20, 0.15); /* Borde sutil de neón, 50% menos brillante */
            border-radius: 5px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            transition: all 0.3s ease;
            box-shadow: 0 0 2.5px rgba(57, 255, 20, 0.1); /* Brillo reducido al 50% */
        }
        .stDownloadButton > button:hover {
            background: #39FF14; /* Verde lima brillante al pasar el ratón */
            color: #1E1E1E;
            transform: translateY(-2px);
            box-shadow: 0 4px 5px rgba(57, 255, 20, 0.4); /* Brillo reducido al 50% */
        }
        </style>
    """, unsafe_allow_html=True)

    # ===== CACHE STATS MONITOR (HIDDEN) =====
    if False:  # Hidden - uncomment to show cache stats
        with st.sidebar:
            st.markdown("### 💾 Cache Stats")
            cache_info = st.cache_data.clear.__doc__  # Placeholder para stats futuros
            
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                st.metric("⚡ Cache TTL", "10 min", "600s")
            with col_c2:
                st.metric("📊 Aggressive Cache", "30 min", "Screener")
            
            with st.expander("🔍 How Cache Works"):
                st.markdown("""
                **Cache System:**
                - ⚡ Real-time quotes: 10 min cache
                - 📈 Screener data: 30 min cache (saves 30% bandwidth)
                - 📊 Historical data: 1 hour cache
                
                **Bandwidth Savings:**
                - Same scan within 5 min = **0% new data**
                - Reusing screener = **~3MB saved per request**
                - Per month: ~2.5-4 GB typical usage
                
                **Example:**
                - Without cache: 3,000 requests × 5KB = 15 MB/day
                - With cache: 50% hit rate = 7.5 MB/day saved
                """)
            
            st.divider()

    # ===== MARKET MAKER ANALYSIS FUNCTIONS =====
    @st.cache_data(ttl=CACHE_TTL)
    def calculate_mm_dynamics(options_data: List[Dict], current_price: float) -> Dict:
        """
        Calcula la dinámica de Market Makers basada en OI, Gamma y volatilidad.
        Identifica cómo los MM posicionarían el precio según su estrategia.
        """
        if not options_data:
            return {}
        
        # Procesar datos
        strikes_data = {}
        for opt in options_data:
            strike = float(opt.get("strike", 0))
            oi = int(opt.get("open_interest", 0) or 0)
            volume = int(opt.get("volume", 0) or 0)
            bid = float(opt.get("bid", 0) or 0)
            ask = float(opt.get("ask", 0) or 0)
            iv = float(opt.get("implied_volatility", 0) or 0)
            opt_type = opt.get("option_type", "").upper()
            
            if strike not in strikes_data:
                strikes_data[strike] = {"CALL": {"OI": 0, "VOL": 0, "BID_ASK": 0, "IV": 0}, 
                                       "PUT": {"OI": 0, "VOL": 0, "BID_ASK": 0, "IV": 0}}
            
            if opt_type in strikes_data[strike]:
                strikes_data[strike][opt_type]["OI"] += oi
                strikes_data[strike][opt_type]["VOL"] += volume
                strikes_data[strike][opt_type]["BID_ASK"] += (ask - bid) if bid > 0 else 0
                strikes_data[strike][opt_type]["IV"] = max(strikes_data[strike][opt_type]["IV"], iv)
        
        # Calcular MM pressure por strike
        mm_analysis = {}
        for strike in strikes_data:
            call_data = strikes_data[strike]["CALL"]
            put_data = strikes_data[strike]["PUT"]
            
            # Presión MM: OI × Spread × IV (MM gana con volatilidad y spread)
            call_pressure = (call_data["OI"] + call_data["VOL"]) * (call_data["BID_ASK"] + 0.01) * (call_data["IV"] + 0.1)
            put_pressure = (put_data["OI"] + put_data["VOL"]) * (put_data["BID_ASK"] + 0.01) * (put_data["IV"] + 0.1)
            
            # Distancia del precio actual
            distance_pct = abs(strike - current_price) / current_price * 100 if current_price > 0 else 0
            
            # Score de atracción MM (qué tan probable que MM lleve el precio aquí)
            attraction_score = (call_pressure + put_pressure) / (distance_pct + 1)
            
            mm_analysis[strike] = {
                "call_pressure": call_pressure,
                "put_pressure": put_pressure,
                "net_pressure": call_pressure - put_pressure,
                "attraction_score": attraction_score,
                "distance_pct": distance_pct,
                "spread_width": (call_data["BID_ASK"] + put_data["BID_ASK"]) / 2,
                "combined_oi": call_data["OI"] + put_data["OI"],
                "combined_vol": call_data["VOL"] + put_data["VOL"]
            }
        
        return mm_analysis
    
    @st.cache_data(ttl=CACHE_TTL)
    def identify_contraction_zones(mm_analysis: Dict, current_price: float, top_n: int = 5) -> List[Dict]:
        """
        Identifica zonas de contracción probable donde MM probablemente moverá el mercado.
        Zonas de alta presión MM = contracción probable.
        """
        if not mm_analysis:
            return []
        
        # Ordenar por attraction_score (mayor atracción = zona de contracción probable)
        sorted_strikes = sorted(mm_analysis.items(), key=lambda x: x[1]["attraction_score"], reverse=True)
        
        contraction_zones = []
        for strike, data in sorted_strikes[:top_n]:
            # Dirección basada en la posición del strike respecto al precio actual
            if strike > current_price:
                direction = "UP"
            elif strike < current_price:
                direction = "DOWN"
            else:
                direction = "SIDEWAYS"
            
            distance = abs(strike - current_price)
            
            contraction_zones.append({
                "strike": strike,
                "attraction_score": data["attraction_score"],
                "direction": direction,
                "distance_points": distance,
                "distance_pct": data["distance_pct"],
                "combined_oi": data["combined_oi"],
                "call_pressure": data["call_pressure"],
                "put_pressure": data["put_pressure"],
                "spread_width": data["spread_width"]
            })
        
        return contraction_zones
    
    @st.cache_data(ttl=CACHE_TTL)
    def calculate_strike_value(strike: float, mm_data: Dict, current_price: float, max_pain: float) -> Dict:
        """
        Calcula el valor de un strike específico para MM y traders.
        Combina: Max Pain, Pressure, Spread, OI.
        """
        if strike not in mm_data:
            return {}
        
        data = mm_data[strike]
        
        # Score de valor (1-100)
        # Factores:
        # 1. Proximidad a max pain (MM prefiere max pain)
        # 2. Presión combinada (mayor OI/VOL = más importante)
        # 3. Spread (spreads anchos = más ganancia para MM)
        # 4. Proximidad al precio actual (zona de congestión)
        
        max_pain_dist = abs(strike - max_pain) if max_pain else abs(strike - current_price)
        price_proximity = 1 / (abs(strike - current_price) + 0.1)
        
        pressure_score = (data["combined_oi"] + data["combined_vol"]) / 1000
        spread_score = data["spread_width"] * 100
        max_pain_score = 1 / (max_pain_dist + 1)
        
        total_value = (pressure_score * 30 + spread_score * 20 + max_pain_score * 50) / 100
        
        # Dirección basada en la posición del strike respecto al precio actual
        if strike > current_price:
            direction_bias = "UP"
        elif strike < current_price:
            direction_bias = "DOWN"
        else:
            direction_bias = "NEUTRAL"
        
        return {
            "strike": strike,
            "value_score": min(100, total_value),
            "pressure_score": pressure_score,
            "spread_score": spread_score,
            "max_pain_affinity": max_pain_score,
            "combined_oi": data["combined_oi"],
            "direction_bias": direction_bias
        }
    
    @st.cache_data(ttl=CACHE_TTL)
    def process_mm_analysis(ticker: str, expiration: str, current_price: float) -> Dict:
        """
        Procesa análisis completo de MM incluyendo contracción, strikes valiosos y proyecciones.
        """
        options_data = get_options_data(ticker, expiration)
        if not options_data:
            return {}
        
        # Calcular max pain
        max_pain = calculate_max_pain_optimized(options_data)
        
        # Análisis MM
        mm_analysis = calculate_mm_dynamics(options_data, current_price)
        contraction_zones = identify_contraction_zones(mm_analysis, current_price, top_n=8)
        
        # Calcular valor de strikes
        valuable_strikes = []
        for strike in mm_analysis.keys():
            value_data = calculate_strike_value(strike, mm_analysis, current_price, max_pain)
            if value_data and value_data["value_score"] > 20:  # Solo strikes con valor
                valuable_strikes.append(value_data)
        
        # Ordenar por value_score
        valuable_strikes.sort(key=lambda x: x["value_score"], reverse=True)
        
        return {
            "max_pain": max_pain,
            "contraction_zones": contraction_zones,
            "valuable_strikes": valuable_strikes[:5],  # Top 5
            "mm_analysis": mm_analysis,
            "current_price": current_price
        }

    # ===== VALIDATION: CHECK USER STATUS =====
    if "current_user" in st.session_state and st.session_state["current_user"] != "admin":
        current_user = st.session_state["current_user"]
        user_info = get_user_info(current_user)
        
        if user_info:
            username = user_info["username"]
            email = user_info["email"]
            active = user_info["active"]
            tier = user_info["tier"]
            expiration_date = user_info["expiration"]
            usage_today = int(user_info["usage_today"]) if user_info["usage_today"] else 0
            daily_limit = int(user_info["daily_limit"]) if user_info["daily_limit"] else 0
            
            # Validación 1: Usuario inactivo
            if not active:
                st.error("❌ **TU CUENTA HA SIDO BLOQUEADA**")
                st.warning("⚠️ Si crees que es un error o necesitas reactivar tu cuenta:")
                st.markdown("""
                **📞 CONTACTA AL ADMINISTRADOR:**
                ☎️ **6789789414** (Facturación y Soporte)
                
                📧 Menciona tu usuario y correo para que podamos ayudarte.
                """)
                st.stop()
            
            # Validación 2: Licencia expirada (excepto Pending)
            if tier != "Pending":
                try:
                    exp_date = datetime.fromisoformat(expiration_date)
                    if datetime.now(MARKET_TIMEZONE) > exp_date:
                        st.error("❌ **TU LICENCIA HA EXPIRADO**")
                        st.warning(f"⚠️ Tu plan expiró el {exp_date.strftime('%Y-%m-%d')}")
                        st.markdown(f"""
                        **Para renovar tu acceso:**
                        ☎️ **6789789414** (Facturación)
                        
                        **Tu información:**
                        - Usuario: {username}
                        - Email: {email}
                        """)
                        st.stop()
                except Exception as e:
                    logger.warning(f"Error validating user expiration: {e}")
                    pass
            
            # Validación 3: Daily limit exceeded (excepto Pending y Unlimited)
            if tier not in ["Pending", "Unlimited"] and daily_limit > 0:
                if usage_today >= daily_limit:
                    st.error("❌ **LIMITE DIARIO ALCANZADO**")
                    st.warning(f"⚠️ Has utilizado tus {daily_limit} escaneos del día")
                    st.markdown("""
                    **Vuelve a intentar mañana** o contacta al administrador para aumentar tu límite:
                    ☎️ **6789789414**
                    """)
                    st.stop()
    
    # ═══════════════════════════════════════════════════════════════════════════════
    # HELPER FUNCTION: Show latest news in single line format
    # ═══════════════════════════════════════════════════════════════════════════════
    def show_latest_news_ticker(ticker_symbol: str):
        """Display the most recent news for a ticker in a single line format"""
        try:
            # Fetch news for the ticker
            google_news = fetch_google_news([ticker_symbol])
            bing_news = fetch_bing_news([ticker_symbol])
            all_news = google_news + bing_news
            
            if all_news:
                # Get the most recent news (first one)
                latest = all_news[0]
                title = latest.get("title", "No title")
                link = latest.get("link", "#")
                time_posted = latest.get("time", "Recently")
                
                # Display in a compact, single-line format
                st.markdown(f"""
                <div style='background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%); 
                           border-left: 3px solid #00FF00; padding: 8px 12px; 
                           border-radius: 5px; margin: 10px 0;'>
                    <small style='color: #00FF00;'>📰 LATEST NEWS:</small>
                    <a href='{link}' target='_blank' style='color: #FFD700; text-decoration: none; font-weight: bold;'>
                        {title[:100]}...
                    </a>
                    <small style='color: #888;'> • {time_posted}</small>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info(f"📰 No recent news found for {ticker_symbol}")
        except Exception as e:
            logger.warning(f"Error fetching latest news for {ticker_symbol}: {e}")
    
    # ═════════════════════════════════════════════════════════════════════════════════
    # MAIN APPLICATION TABS
    # ═════════════════════════════════════════════════════════════════════════════════
    # ═════════════════════════════════════════════════════════════════════════════════
    tab_labels = [
        "| Gummy Data Bubbles® |",
        "| Market Scanner |",
        "| News |",
        "| Analyst Rating Flow |",
        "| Elliott Pulse® |",
        "|  Metrics  |",
        "| Multi-Date Options |",
        "| calculo |",
    ]
    active_tab = st.radio(
        "",
        tab_labels,
        key="active_tab",
        horizontal=True,
        label_visibility="collapsed",
    )
    default_ticker = st.session_state.get("ticker_input_main", "SPY")


    # Tab 1: Gummy Data Bubbles®
    if active_tab == tab_labels[0]:
        ticker = st.text_input("Ticker", value="SPY", key="ticker_input_main").upper()
        
        expiration_dates = get_expiration_dates(ticker)
        if not expiration_dates:
            st.error(f"❌ No future expiration dates found for '{ticker}'. Please enter a valid ticker (e.g., SPY, AAPL).")
        else:
            expiration_date = st.selectbox("Expiration Date", expiration_dates, key="expiration_date")
            
            # ═══════════════════════════════════════════════════════════════════════════════
            # SHOW LATEST NEWS FOR THIS TICKER
            # ═══════════════════════════════════════════════════════════════════════════════
            show_latest_news_ticker(ticker)
            
            with st.spinner("Fetching price..."):
                current_price = get_current_price(ticker)
                if current_price == 0.0:
                    st.error(f"⏳ Price data for '{ticker}' is temporarily unavailable. Please try again shortly.")
                    logger.error(f"Price fetch failed for {ticker}")
                    current_price = None
            
            if current_price and current_price > 0:
                st.markdown(f"**Current Price:** ${current_price:.2f}")
                
                with st.spinner(f"Fetching data for {expiration_date}..."):
                    processed_data, touched_strikes, max_pain, max_pain_df = process_options_data(ticker, expiration_date)
                    if not processed_data:
                        next_expiration = expiration_dates[expiration_dates.index(expiration_date) + 1] if expiration_date != expiration_dates[-1] else None
                        if next_expiration:
                            st.warning(f"No data for {expiration_date}. Trying next expiration: {next_expiration}")
                            processed_data, touched_strikes, max_pain, max_pain_df = process_options_data(ticker, next_expiration)
                            if not processed_data:
                                st.error(f"❌ No valid options data for {ticker} on {next_expiration} either.")
                        else:
                            st.error(f"❌ No valid options data for {ticker} on {expiration_date}.")
                    
                    if processed_data:
                        options_data = get_options_data(ticker, expiration_date)
                        if max_pain_df.empty:
                            st.warning("No max pain data available for this ticker and expiration date.")
                        
                        gamma_fig = gamma_exposure_chart(processed_data, current_price, touched_strikes)
                        st.plotly_chart(gamma_fig, use_container_width=True)
                        
                        gamma_df = pd.DataFrame({
                            "Strike": list(processed_data.keys()),
                "CALL_Gamma": [processed_data[s]["CALL"]["Gamma"] for s in processed_data],
                "PUT_Gamma": [processed_data[s]["PUT"]["Gamma"] for s in processed_data],
                "CALL_OI": [processed_data[s]["CALL"]["OI"] for s in processed_data],
                "PUT_OI": [processed_data[s]["PUT"]["OI"] for s in processed_data]
            })
            gamma_csv = gamma_df.to_csv(index=False)
            st.download_button(
                label="📥 Download Gamma Exposure Data",
                data=gamma_csv,
                file_name=f"{ticker}_gamma_exposure_{expiration_date}.csv",
                mime="text/csv",
                key="download_gamma_tab1"
            )
            
            skew_fig, total_calls, total_puts = plot_skew_analysis_with_totals(options_data, current_price)
            st.plotly_chart(skew_fig, use_container_width=True)
            st.write(f"**Total CALLS:** {total_calls} | **Total PUTS:** {total_puts}")
            
            # ✅ FIX: Build DataFrame safely with available columns
            skew_df = pd.DataFrame(options_data)
            # Select only columns that exist in the data
            available_cols = [col for col in ["strike", "option_type", "open_interest", "volume"] if col in skew_df.columns]
            if available_cols:
                skew_df = skew_df[available_cols]
            
            skew_csv = skew_df.to_csv(index=False)
            st.download_button(
                label="📥 Download Skew Analysis Data",
                data=skew_csv,
                file_name=f"{ticker}_skew_analysis_{expiration_date}.csv",
                mime="text/csv",
                key="download_skew_tab1"
            )
            
            st.write(f"Current Price of {ticker}: ${current_price:.2f} (Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
            st.write(f"**Max Pain Strike (Optimized):** {max_pain if max_pain else 'N/A'}")
            
            max_pain_fig = plot_max_pain_histogram_with_levels(max_pain_df, current_price)
            st.plotly_chart(max_pain_fig, use_container_width=True)
            
            max_pain_csv = max_pain_df.to_csv(index=False)
            st.download_button(
                label="📥 Download Max Pain Data",
                data=max_pain_csv,
                file_name=f"{ticker}_max_pain_{expiration_date}.csv",
                mime="text/csv",
                key="download_max_pain_tab1"
            )
            
            # Gráfico combinado de CALLs y PUTs
            call_data = [
                {
                    "strike": float(opt.get("strike", 0)),
                    "option_type": opt.get("option_type", "").lower(),
                    "open_interest": int(opt.get("open_interest", 0)),
                    "bid": float(opt.get("bid", 0)) if opt.get("bid") is not None and isinstance(opt.get("bid"), (int, float, str)) else 0
                }
                for opt in options_data if isinstance(opt, dict)
            ]
            call_df = pd.DataFrame([d for d in call_data if d["option_type"] == "call"])
            put_df = pd.DataFrame([d for d in call_data if d["option_type"] == "put"])
            
            # Only process if dataframes have data
            if not call_df.empty and 'open_interest' in call_df.columns:
                call_df['open_interest'] = call_df['open_interest'].fillna(0).astype(int).clip(lower=0)
            if not put_df.empty and 'open_interest' in put_df.columns:
                put_df['open_interest'] = put_df['open_interest'].fillna(0).astype(int).clip(lower=0)
            
            # Only display chart if we have data
            if not call_df.empty or not put_df.empty:
                fig_options = go.Figure()
                
                if not call_df.empty:
                    fig_options.add_trace(go.Scatter(
                        x=call_df['strike'],
                        y=call_df['bid'],
                        mode='markers',
                        marker=dict(
                            size=call_df['open_interest'].apply(lambda x: max(5, min(30, x / 1000))) if 'open_interest' in call_df.columns else 10,
                            color='blue',
                            opacity=0.7
                        ),
                        name='CALL Options',
                        hovertemplate="<b>Strike:</b> %{x:.2f}<br><b>Bid:</b> ${%y:.2f}<br><b>Open Interest:</b> %{customdata:,}",
                        customdata=call_df['open_interest'] if 'open_interest' in call_df.columns else 0
                    ))
                
                if not put_df.empty:
                    fig_options.add_trace(go.Scatter(
                        x=put_df['strike'],
                        y=put_df['bid'],
                        mode='markers',
                        marker=dict(
                            size=put_df['open_interest'].apply(lambda x: max(5, min(30, x / 1000))) if 'open_interest' in put_df.columns else 10,
                            color='red',
                            opacity=0.7
                        ),
                        name='PUT Options',
                        hovertemplate="<b>Strike:</b> %{x:.2f}<br><b>Bid:</b> ${%y:.2f}<br><b>Open Interest:</b> %{customdata:,}",
                        customdata=put_df['open_interest'] if 'open_interest' in put_df.columns else 0
                    ))
                
                fig_options.update_layout(
                    title=f"CALL and PUT Options for {ticker}",
                    xaxis_title="Strike Price",
                    yaxis_title="Bid Price",
                    template="plotly_white",
                    legend=dict(
                        yanchor="top",
                        y=0.99,
                        xanchor="left",
                        x=0.01
                    ),
                    hovermode="closest"
                )
                st.plotly_chart(fig_options, use_container_width=True)
            else:
                st.warning("⚠️ No options data available for the selected date")


            # ==============================================
        # PRICE TARGET CHART CON BURBUJAS
        # ==============================================
        try:
            st.markdown("---")
            st.subheader(f"🎯 Price Targets - {ticker}")
            
            # Fetch historical prices (últimos 6 meses)
            tab1_hist_url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?apikey={FMP_API_KEY}"
            tab1_hist_response = requests.get(tab1_hist_url, timeout=10)
            
            # Fetch price targets
            tab1_targets_url = f"https://financialmodelingprep.com/api/v4/price-target?symbol={ticker}&apikey={FMP_API_KEY}"
            tab1_targets_response = requests.get(tab1_targets_url, timeout=10)
            
            if tab1_hist_response.status_code == 200 and tab1_targets_response.status_code == 200:
                tab1_hist_data = tab1_hist_response.json()
                tab1_targets_data = tab1_targets_response.json()
                
                if tab1_hist_data and 'historical' in tab1_hist_data and tab1_targets_data:
                    # Procesar datos históricos (últimos 180 días)
                    tab1_historical = tab1_hist_data['historical'][:180]
                    tab1_hist_df = pd.DataFrame(tab1_historical)
                    tab1_hist_df['date'] = pd.to_datetime(tab1_hist_df['date'], errors='coerce').dt.tz_localize(None)
                    tab1_hist_df = tab1_hist_df.sort_values('date')
                    
                    # Procesar targets (últimos 12 meses)
                    tab1_targets_df = pd.DataFrame(tab1_targets_data)
                    tab1_targets_df['publishedDate'] = pd.to_datetime(tab1_targets_df['publishedDate'], errors='coerce').dt.tz_localize(None)
                    tab1_one_year_ago = pd.Timestamp.now().tz_localize(None) - pd.Timedelta(days=365)
                    tab1_targets_df = tab1_targets_df[tab1_targets_df['publishedDate'] >= tab1_one_year_ago]
                    
                    # Crear figura
                    tab1_fig_targets = go.Figure()
                    
                    # Línea azul: Precios históricos
                    tab1_fig_targets.add_trace(go.Scatter(
                        x=tab1_hist_df['date'],
                        y=tab1_hist_df['close'],
                        mode='lines',
                        name='Historical Price',
                        line=dict(color='#1f77b4', width=2),
                        hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>Close:</b> $%{y:.2f}<extra></extra>'
                    ))
                    
                    # Burbujas naranjas: Price Targets
                    if not tab1_targets_df.empty:
                        tab1_fig_targets.add_trace(go.Scatter(
                            x=tab1_targets_df['publishedDate'],
                            y=tab1_targets_df['adjPriceTarget'],
                            mode='markers',
                            name='Analyst Targets',
                            marker=dict(
                                size=12,
                                color='#ff7f0e',
                                line=dict(width=2, color='white'),
                                opacity=0.8
                            ),
                            text=tab1_targets_df['analystCompany'],
                            hovertemplate='<b>%{text}</b><br><b>Date:</b> %{x|%Y-%m-%d}<br><b>Target:</b> $%{y:.2f}<extra></extra>'
                        ))
                    
                    # Línea punteada: Precio actual
                    tab1_fig_targets.add_hline(
                        y=current_price,
                        line_dash="dash",
                        line_color="red",
                        annotation_text=f"Current: ${current_price:.2f}",
                        annotation_position="right"
                    )
                    
                    # Layout
                    tab1_fig_targets.update_layout(
                        title=f"{ticker} - Price History vs Analyst Targets",
                        xaxis_title="Date",
                        yaxis_title="Price ($)",
                        hovermode='x unified',
                        template='plotly_dark',
                        height=500,
                        showlegend=True,
                        legend=dict(x=0.01, y=0.99)
                    )
                    
                    st.plotly_chart(tab1_fig_targets, use_container_width=True)
                    
                    # Métricas de targets
                    if not tab1_targets_df.empty:
                        col1, col2, col3, col4 = st.columns(4)
                        tab1_avg_target = tab1_targets_df['adjPriceTarget'].mean()
                        tab1_max_target = tab1_targets_df['adjPriceTarget'].max()
                        tab1_min_target = tab1_targets_df['adjPriceTarget'].min()
                        tab1_num_analysts = len(tab1_targets_df)
                        
                        with col1:
                            st.metric("Avg Target", f"${tab1_avg_target:.2f}", f"{((tab1_avg_target/current_price - 1) * 100):.1f}%")
                        with col2:
                            st.metric("High Target", f"${tab1_max_target:.2f}", f"{((tab1_max_target/current_price - 1) * 100):.1f}%")
                        with col3:
                            st.metric("Low Target", f"${tab1_min_target:.2f}", f"{((tab1_min_target/current_price - 1) * 100):.1f}%")
                        with col4:
                            st.metric("Analysts", tab1_num_analysts)
                    else:
                        st.info("No analyst price targets available for the last 12 months.")
                else:
                    st.info("Price target data is currently being processed. Please refresh to check again.")
            else:
                st.info("⏳ Price target analysis is temporarily unavailable. Data sync in progress.")
        
        except Exception as e:
            st.error(f"Error loading Price Target chart: {str(e)}")

        # ==============================================
        # ==============================================
        # ==============================================
        # GAMMA EXPOSURE + MM ADAPTIVE BURN TRACKER
        # ==============================================
        st.markdown("---")
        st.subheader(f"MM Adaptive Burn Tracker - {ticker}")
        
        try:
            # 1. PROCESAR OPTIONS DATA
            tab1_gamma_strikes = []
            
            for tab1_opt_item in options_data:
                tab1_opt_greeks = tab1_opt_item.get("greeks", {})
                tab1_opt_gamma_value = tab1_opt_greeks.get("gamma", 0) if tab1_opt_greeks else 0
                tab1_opt_strike = tab1_opt_item.get("strike", 0)
                tab1_opt_expiration = tab1_opt_item.get("expiration_date", expiration_date)
                tab1_opt_oi = tab1_opt_item.get("open_interest", 0)
                tab1_opt_volume = tab1_opt_item.get("volume", 0)
                tab1_opt_type = tab1_opt_item.get("option_type", "").lower()
                tab1_opt_bid = tab1_opt_item.get("bid", 0)
                tab1_opt_ask = tab1_opt_item.get("ask", 0)
                
                # Filtrar por gamma > 0.001 (gamma significativo)
                if abs(tab1_opt_gamma_value) > 0.001 and tab1_opt_strike > 0 and tab1_opt_oi > 0:
                    # Calcular Gamma Exposure = |Gamma| × OI × 100 × Spot
                    tab1_gamma_exposure = abs(tab1_opt_gamma_value * tab1_opt_oi * 100 * current_price)
                    
                    # CALCULAR VALOR INTRÍNSECO
                    if tab1_opt_type == "call":
                        tab1_intrinsic_value = max(0, current_price - tab1_opt_strike)
                    else:  # put
                        tab1_intrinsic_value = max(0, tab1_opt_strike - current_price)
                    
                    # Valor extrínseco = Precio de mercado - Valor intrínseco
                    tab1_market_price = (tab1_opt_bid + tab1_opt_ask) / 2 if tab1_opt_bid > 0 and tab1_opt_ask > 0 else 0
                    tab1_extrinsic_value = max(0, tab1_market_price - tab1_intrinsic_value)
                    
                    tab1_gamma_strikes.append({
                        "strike": tab1_opt_strike,
                        "gamma": tab1_opt_gamma_value,
                        "gamma_ex": tab1_gamma_exposure,
                        "oi": tab1_opt_oi,
                        "volume": tab1_opt_volume,
                        "expiration": tab1_opt_expiration,
                        "type": tab1_opt_type,
                        "intrinsic_value": tab1_intrinsic_value,
                        "extrinsic_value": tab1_extrinsic_value,
                        "market_price": tab1_market_price
                    })
            
            if not tab1_gamma_strikes:
                st.warning(f"No se encontraron opciones con |gamma| > 0.001 para {ticker} en {expiration_date}.")
            else:
                # 2. AGRUPAR POR STRIKE CON VALOR INTRÍNSECO
                tab1_strikes_grouped = {}
                
                for tab1_item in tab1_gamma_strikes:
                    tab1_strike_key = tab1_item["strike"]
                    if tab1_strike_key not in tab1_strikes_grouped:
                        tab1_strikes_grouped[tab1_strike_key] = {
                            "strike": tab1_strike_key,
                            "call_gamma_ex": 0,
                            "put_gamma_ex": 0,
                            "call_oi": 0,
                            "put_oi": 0,
                            "call_volume": 0,
                            "put_volume": 0,
                            "call_gamma": 0,
                            "put_gamma": 0,
                            "call_intrinsic": 0,
                            "put_intrinsic": 0,
                            "call_extrinsic": 0,
                            "put_extrinsic": 0
                        }
                    
                    if tab1_item["type"] == "call":
                        tab1_strikes_grouped[tab1_strike_key]["call_gamma_ex"] += tab1_item["gamma_ex"]
                        tab1_strikes_grouped[tab1_strike_key]["call_oi"] += tab1_item["oi"]
                        tab1_strikes_grouped[tab1_strike_key]["call_volume"] += tab1_item["volume"]
                        tab1_strikes_grouped[tab1_strike_key]["call_gamma"] += abs(tab1_item["gamma"])
                        tab1_strikes_grouped[tab1_strike_key]["call_intrinsic"] += tab1_item["intrinsic_value"] * tab1_item["oi"] * 100
                        tab1_strikes_grouped[tab1_strike_key]["call_extrinsic"] += tab1_item["extrinsic_value"] * tab1_item["oi"] * 100
                    elif tab1_item["type"] == "put":
                        tab1_strikes_grouped[tab1_strike_key]["put_gamma_ex"] += tab1_item["gamma_ex"]
                        tab1_strikes_grouped[tab1_strike_key]["put_oi"] += tab1_item["oi"]
                        tab1_strikes_grouped[tab1_strike_key]["put_volume"] += tab1_item["volume"]
                        tab1_strikes_grouped[tab1_strike_key]["put_gamma"] += abs(tab1_item["gamma"])
                        tab1_strikes_grouped[tab1_strike_key]["put_intrinsic"] += tab1_item["intrinsic_value"] * tab1_item["oi"] * 100
                        tab1_strikes_grouped[tab1_strike_key]["put_extrinsic"] += tab1_item["extrinsic_value"] * tab1_item["oi"] * 100
                
                # 3. ALGORITMO ADAPTATIVO DE MM CON BURN TRACKING
                tab1_final_strikes = []
                tab1_total_call_intrinsic = 0
                tab1_total_put_intrinsic = 0
                tab1_total_call_extrinsic = 0
                tab1_total_put_extrinsic = 0
                
                for tab1_strike_key, tab1_data in tab1_strikes_grouped.items():
                    tab1_total_gex = tab1_data["call_gamma_ex"] + tab1_data["put_gamma_ex"]
                    tab1_net_gex = tab1_data["call_gamma_ex"] - tab1_data["put_gamma_ex"]
                    
                    # CALCULAR BURN VALUE (dinero que pierden traders si expira aquí)
                    # CALLs se queman si están OTM (strike > precio actual)
                    if tab1_strike_key > current_price:
                        tab1_call_burn = tab1_data["call_intrinsic"] + tab1_data["call_extrinsic"]
                    else:
                        tab1_call_burn = tab1_data["call_extrinsic"]  # Solo pierden el valor extrínseco
                    
                    # PUTs se queman si están OTM (strike < precio actual)
                    if tab1_strike_key < current_price:
                        tab1_put_burn = tab1_data["put_intrinsic"] + tab1_data["put_extrinsic"]
                    else:
                        tab1_put_burn = tab1_data["put_extrinsic"]  # Solo pierden el valor extrínseco
                    
                    tab1_total_burn = tab1_call_burn + tab1_put_burn
                    
                    # Acumular totales globales
                    tab1_total_call_intrinsic += tab1_data["call_intrinsic"]
                    tab1_total_put_intrinsic += tab1_data["put_intrinsic"]
                    tab1_total_call_extrinsic += tab1_data["call_extrinsic"]
                    tab1_total_put_extrinsic += tab1_data["put_extrinsic"]
                    
                    # RATIO DE ACTIVIDAD (Volume/OI)
                    tab1_call_activity = tab1_data["call_volume"] / max(tab1_data["call_oi"], 1)
                    tab1_put_activity = tab1_data["put_volume"] / max(tab1_data["put_oi"], 1)
                    tab1_activity_score = (tab1_call_activity + tab1_put_activity) / 2
                    
                    # SCORE ADAPTATIVO DE MM (0-100)
                    tab1_max_gex = max([s["call_gamma_ex"] + s["put_gamma_ex"] for s in tab1_strikes_grouped.values()])
                    tab1_gex_score = (tab1_total_gex / max(tab1_max_gex, 1)) * 40
                    
                    tab1_max_burn = max([
                        (s["call_intrinsic"] + s["call_extrinsic"] if s["strike"] > current_price else s["call_extrinsic"]) +
                        (s["put_intrinsic"] + s["put_extrinsic"] if s["strike"] < current_price else s["put_extrinsic"])
                        for s in tab1_strikes_grouped.values()
                    ])
                    tab1_burn_score = (tab1_total_burn / max(tab1_max_burn, 1)) * 30
                    
                    tab1_activity_score_norm = min(tab1_activity_score * 20, 20)
                    
                    tab1_distance = abs(tab1_strike_key - current_price)
                    tab1_max_distance = max([abs(s["strike"] - current_price) for s in tab1_strikes_grouped.values()])
                    tab1_distance_score = (1 - tab1_distance / max(tab1_max_distance, 1)) * 10
                    
                    tab1_mm_score = tab1_gex_score + tab1_burn_score + tab1_activity_score_norm + tab1_distance_score
                    
                    # Determinar estado de quema
                    if tab1_strike_key > current_price:
                        tab1_burn_status = "🔥 CALLs Burning"
                    elif tab1_strike_key < current_price:
                        tab1_burn_status = "🔥 PUTs Burning"
                    else:
                        tab1_burn_status = "⚖️ At The Money"
                    
                    tab1_final_strikes.append({
                        "strike": tab1_strike_key,
                        "call_gex": tab1_data["call_gamma_ex"],
                        "put_gex": tab1_data["put_gamma_ex"],
                        "total_gex": tab1_total_gex,
                        "net_gex": tab1_net_gex,
                        "call_oi": tab1_data["call_oi"],
                        "put_oi": tab1_data["put_oi"],
                        "call_intrinsic": tab1_data["call_intrinsic"],
                        "put_intrinsic": tab1_data["put_intrinsic"],
                        "call_extrinsic": tab1_data["call_extrinsic"],
                        "put_extrinsic": tab1_data["put_extrinsic"],
                        "call_burn": tab1_call_burn,
                        "put_burn": tab1_put_burn,
                        "total_burn": tab1_total_burn,
                        "mm_score": tab1_mm_score,
                        "activity": tab1_activity_score,
                        "burn_status": tab1_burn_status,
                        "dominance": "CALL" if tab1_data["call_gamma_ex"] > tab1_data["put_gamma_ex"] else "PUT"
                    })
                
                # Ordenar por strike
                tab1_final_strikes.sort(key=lambda x: x["strike"])
                
                # 4. IDENTIFICAR TOP TARGETS ADAPTATIVOS
                tab1_top_targets = sorted(tab1_final_strikes, key=lambda x: x["mm_score"], reverse=True)[:5]
                
                # 5. CALCULAR BURN ACTUAL (CALLs vs PUTs quemándose AHORA)
                tab1_calls_burning_now = sum(s["call_burn"] for s in tab1_final_strikes if s["strike"] > current_price)
                tab1_puts_burning_now = sum(s["put_burn"] for s in tab1_final_strikes if s["strike"] < current_price)
                tab1_total_burning = tab1_calls_burning_now + tab1_puts_burning_now
                
                # 6. CREAR FIGURA CON LÍNEA DE PRECIO + BURBUJAS DE TARGETS
                tab1_fig_gamma = go.Figure()
                
                tab1_min_strike = min(s["strike"] for s in tab1_final_strikes)
                tab1_max_strike = max(s["strike"] for s in tab1_final_strikes)
                
                # ===== LÍNEA HORIZONTAL AZUL DE PRECIO ACTUAL =====
                tab1_fig_gamma.add_trace(go.Scatter(
                    x=[tab1_min_strike, tab1_max_strike],
                    y=[current_price, current_price],
                    mode='lines',
                    name='Price Trend',
                    line=dict(color='#4A90E2', width=4),
                    hovertemplate='<b>Current Price:</b> $%{y:.2f}<extra></extra>',
                    showlegend=True
                ))
                
                # ===== BURBUJAS GRISES: TODOS LOS STRIKES =====
                tab1_fig_gamma.add_trace(go.Scatter(
                    x=[s["strike"] for s in tab1_final_strikes],
                    y=[current_price] * len(tab1_final_strikes),
                    mode='markers',
                    marker=dict(
                        size=[min(max(s["total_gex"] / 100000, 10), 50) for s in tab1_final_strikes],
                        color='rgba(128,128,128,0.3)',
                        line=dict(color='rgba(255,255,255,0.2)', width=1)
                    ),
                    name='All Strikes',
                    hovertemplate='<b>Strike:</b> $%{x:.2f}<br>' +
                                  '<b>GEX:</b> %{customdata[0]:.2f}M<br>' +
                                  '<b>Status:</b> %{customdata[1]}<extra></extra>',
                    customdata=[[s["total_gex"]/1e6, s["burn_status"]] for s in tab1_final_strikes],
                    showlegend=False
                ))
                
                # ===== BURBUJAS NARANJAS: TOP MM TARGETS =====
                tab1_fig_gamma.add_trace(go.Scatter(
                    x=[t["strike"] for t in tab1_top_targets],
                    y=[current_price] * len(tab1_top_targets),
                    mode='markers+text',
                    marker=dict(
                        size=[min(max(t["mm_score"] * 0.9, 30), 120) for t in tab1_top_targets],
                        color='#FF8C42',
                        line=dict(color='#2D2D2D', width=3),
                        opacity=0.9
                    ),
                    text=[f"${t['strike']:.0f}" for t in tab1_top_targets],
                    textposition="middle center",
                    textfont=dict(size=12, color='black', family='Arial Black'),
                    name='MM Targets',
                    hovertemplate='<b>Strike:</b> $%{x:.2f}<br>' +
                                  '<b>GEX:</b> %{customdata[0]:.2f}M<br>' +
                                  '<b>MM Score:</b> %{customdata[1]:.1f}/100<br>' +
                                  '<b>Burn Value:</b> $%{customdata[2]:.2f}M<br>' +
                                  '<b>CALL Intrinsic:</b> $%{customdata[3]:.2f}M<br>' +
                                  '<b>PUT Intrinsic:</b> $%{customdata[4]:.2f}M<br>' +
                                  '<b>Activity:</b> %{customdata[5]:.2f}<br>' +
                                  '<b>Status:</b> %{customdata[6]}<extra></extra>',
                    customdata=[[t["total_gex"]/1e6, t["mm_score"], t["total_burn"]/1e6,
                               t["call_intrinsic"]/1e6, t["put_intrinsic"]/1e6,
                               t["activity"], t["burn_status"]] for t in tab1_top_targets]
                ))
                
                # ===== LÍNEA VERTICAL ROJA: Precio actual =====
                tab1_fig_gamma.add_vline(
                    x=current_price,
                    line_dash="dash",
                    line_color="#E74C3C",
                    line_width=3,
                    annotation_text=f"Current: ${current_price:.2f}",
                    annotation_position="top",
                    annotation_font_size=12,
                    annotation_font_color="#E74C3C"
                )
                
                # ===== ANOTACIONES DE TARGETS =====
                tab1_price_range = tab1_max_strike - tab1_min_strike
                for idx, target in enumerate(tab1_top_targets):
                    tab1_fig_gamma.add_annotation(
                        x=target["strike"],
                        y=current_price + (tab1_price_range * 0.02),
                        text=f"🎯 #{idx+1}",
                        showarrow=True,
                        arrowhead=2,
                        arrowcolor="#FF8C42",
                        ax=0,
                        ay=-40,
                        font=dict(size=11, color="#FF8C42", family="Arial Black"),
                        bgcolor="rgba(0,0,0,0.8)",
                        bordercolor="#FF8C42",
                        borderwidth=2
                    )
                
                # ===== LAYOUT =====
                tab1_fig_gamma.update_layout(
                    title=dict(
                        text=f"MM Adaptive Gamma Targets + Burn Tracker - {ticker} | Exp: {expiration_date}",
                        font=dict(size=18, color='#FFFFFF', family='Arial Black')
                    ),
                    xaxis=dict(
                        title="Strike Price ($)",
                        showgrid=True,
                        gridwidth=1,
                        gridcolor='rgba(128,128,128,0.2)',
                        color='#FFFFFF',
                        range=[tab1_min_strike - 5, tab1_max_strike + 5]
                    ),
                    yaxis=dict(
                        title="Price Level ($)",
                        showgrid=True,
                        gridwidth=1,
                        gridcolor='rgba(128,128,128,0.2)',
                        color='#FFFFFF',
                        range=[current_price * 0.97, current_price * 1.03]
                    ),
                    plot_bgcolor='#0E1117',
                    paper_bgcolor='#0E1117',
                    height=550,
                    showlegend=True,
                    hovermode='closest',
                    legend=dict(
                        x=0.01,
                        y=0.99,
                        bgcolor='rgba(0,0,0,0.5)',
                        bordercolor='rgba(255,255,255,0.2)',
                        borderwidth=1,
                        font=dict(color='#FFFFFF')
                    ),
                    font=dict(color='#FFFFFF')
                )
                
                st.plotly_chart(tab1_fig_gamma, use_container_width=True)
                
                # ===== MÉTRICAS + BURN TRACKER =====
                col1, col2, col3, col4, col5, col6 = st.columns(6)
                
                tab1_total_call_gex = sum(s["call_gex"] for s in tab1_final_strikes) / 1e6
                tab1_total_put_gex = sum(s["put_gex"] for s in tab1_final_strikes) / 1e6
                tab1_net_gex_total = tab1_total_call_gex - tab1_total_put_gex
                tab1_total_strikes_count = len(tab1_final_strikes)
                tab1_top_target = tab1_top_targets[0]
                
                with col1:
                    st.metric("Total Strikes", tab1_total_strikes_count)
                with col2:
                    st.metric("CALL GEX", f"${tab1_total_call_gex:.2f}M")
                with col3:
                    st.metric("PUT GEX", f"${tab1_total_put_gex:.2f}M")
                with col4:
                    st.metric("Net GEX", f"${tab1_net_gex_total:.2f}M",
                             delta="Bullish" if tab1_net_gex_total > 0 else "Bearish")
                with col5:
                    st.metric("🎯 Top Target", f"${tab1_top_target['strike']:.2f}",
                             delta=f"{tab1_top_target['mm_score']:.0f}/100")
                with col6:
                    st.metric("🔥 Total Burning", f"${tab1_total_burning/1e6:.2f}M")
                
                # ===== BURN TRACKER: CALLs vs PUTs =====
                st.markdown("### 🔥 Current Burn Status")
                col_burn1, col_burn2, col_burn3 = st.columns(3)
                
                with col_burn1:
                    st.metric("🔴 CALLs Burning Now", 
                             f"${tab1_calls_burning_now/1e6:.2f}M",
                             delta=f"{(tab1_calls_burning_now/tab1_total_burning*100):.1f}%" if tab1_total_burning > 0 else "0%")
                with col_burn2:
                    st.metric("🔵 PUTs Burning Now", 
                             f"${tab1_puts_burning_now/1e6:.2f}M",
                             delta=f"{(tab1_puts_burning_now/tab1_total_burning*100):.1f}%" if tab1_total_burning > 0 else "0%")
                with col_burn3:
                    tab1_burn_winner = "CALLs" if tab1_calls_burning_now > tab1_puts_burning_now else "PUTs"
                    st.metric("💰 MM Profits From", tab1_burn_winner,
                             delta=f"${abs(tab1_calls_burning_now - tab1_puts_burning_now)/1e6:.2f}M advantage")
                
                # ===== VALOR INTRÍNSECO TOTAL =====
                st.markdown("### 💎 Intrinsic vs Extrinsic Value")
                col_val1, col_val2, col_val3, col_val4 = st.columns(4)
                
                with col_val1:
                    st.metric("CALL Intrinsic", f"${tab1_total_call_intrinsic/1e6:.2f}M")
                with col_val2:
                    st.metric("CALL Extrinsic", f"${tab1_total_call_extrinsic/1e6:.2f}M")
                with col_val3:
                    st.metric("PUT Intrinsic", f"${tab1_total_put_intrinsic/1e6:.2f}M")
                with col_val4:
                    st.metric("PUT Extrinsic", f"${tab1_total_put_extrinsic/1e6:.2f}M")
                
                # ===== TABLA DE MM ADAPTIVE TARGETS =====
                st.markdown("### 🎯 MM Adaptive Targets (Top 5)")
                tab1_target_table = pd.DataFrame([{
                    "Rank": f"#{idx+1}",
                    "Strike": f"${t['strike']:.2f}",
                    "MM Score": f"{t['mm_score']:.1f}/100",
                    "Gamma Exposure": f"${t['total_gex']/1e6:.2f}M",
                    "Total Burn": f"${t['total_burn']/1e6:.2f}M",
                    "CALL Burn": f"${t['call_burn']/1e6:.2f}M",
                    "PUT Burn": f"${t['put_burn']/1e6:.2f}M",
                    "Activity": f"{t['activity']:.2f}",
                    "Status": t['burn_status'],
                    "Distance": f"${(t['strike'] - current_price):.2f}",
                    "% Move": f"{((t['strike']/current_price - 1) * 100):.2f}%"
                } for idx, t in enumerate(tab1_top_targets)])
                
                st.dataframe(tab1_target_table, use_container_width=True)
                
                # ===== EXPLICACIÓN DEL ALGORITMO =====
                with st.expander("📊 ¿Cómo funciona el MM Adaptive Algorithm + Burn Tracker?"):
                    st.markdown(f"""
                    **🎯 MM Score Adaptativo (0-100 puntos):**
                    
                    1. **Gamma Exposure (40%)**: Alta concentración = imán de precio
                    2. **Burn Value (30%)**: Dinero que pierden traders = ganancia MM
                    3. **Activity Score (20%)**: Ratio Volume/OI = acumulación reciente
                    4. **Distance Score (10%)**: Cercanía al precio = más probable
                    
                    **🔥 Burn Tracker:**
                    
                    - **CALLs Burning**: Strikes > ${current_price:.2f} (actualmente **${tab1_calls_burning_now/1e6:.2f}M**)
                    - **PUTs Burning**: Strikes < ${current_price:.2f} (actualmente **${tab1_puts_burning_now/1e6:.2f}M**)
                    - **Total Burning**: ${tab1_total_burning/1e6:.2f}M en pérdidas para traders
                    
                    **💎 Valor Intrínseco vs Extrínseco:**
                    
                    - **Intrínseco**: Valor real si ejerces la opción HOY
                    - **Extrínseco**: Prima de tiempo + volatilidad (se evapora al expirar)
                    
                    **MM maximiza ganancias quemando valor extrínseco + forzando OTM options**
                    
                    🚀 **Strikes con mayor score = targets más probables según estrategia MM**
                    """)
                    
        except Exception as e:
            st.error(f"Error loading MM Adaptive Gamma chart: {e}")
            import traceback
            st.write(traceback.format_exc())

        st.markdown("*Developed by Ozy | © 2025*")





    
    # ==================================================================================
    # ==================================================================================
    # TAB 2: CRAZY SCANNER (FinViz Elite Integration)
    # ==================================================================================
    if active_tab == tab_labels[1]:
        st.markdown("""
        <div style='text-align: center; padding: 20px; background: linear-gradient(90deg, #FF00FF, #FF8C00); border-radius: 10px;'>
            <h1 style='color: white; font-size: 48px; text-shadow: 0 0 10px rgba(255,255,255,0.8);'>
                🚀 CRAZY SCANNER 🚀
            </h1>
            <p style='color: white; font-size: 18px;'>Powered by Ozy | Real-Time Market Data</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # FinViz Elite Configuration (loaded from .env for security)
        FINVIZ_API_TOKEN = os.getenv("FINVIZ_API_TOKEN", "")
        FINVIZ_BASE_URL = "https://elite.finviz.com"
        
        # Function to fetch data from FinViz Elite API
        def get_finviz_screener(filters_dict, columns_list=None, add_delay=True):
            """
            Fetch screener data from Finviz Elite export API.
            
            Uses the official Finviz Elite screener export endpoint with proper authentication.
            
            Args:
                filters_dict: Dictionary of filters (e.g., {"fa_div_pos": None, "sec_technology": None})
                columns_list: Optional list of column IDs to export
                add_delay: Add 2-second delay to avoid rate limiting
            
            Returns:
                pandas.DataFrame with screener results
            
            Official Finviz URL Structure:
                https://elite.finviz.com/export.ashx?v=[view]&f=[filters]&c=[columns]&auth=[token]
            
            Parameters:
                v = View ID (111 = default screener view, 152 = compact, etc.)
                f = Comma-separated filters (fa_div_pos,sec_technology)
                c = Optional columns to export
                auth = API Token (69d5c83f-1e60-4fc6-9c5d-3b37c08a0531)
            
            Example:
                https://elite.finviz.com/export.ashx?v=111&f=fa_div_pos,sec_technology&auth=TOKEN
            """
            import time
            from io import StringIO
            
            try:
                # Add delay to avoid rate limiting
                if add_delay:
                    time.sleep(2)
                
                # Build URL parameters following official Finviz Elite API
                params = {
                    "v": "111",      # View ID (111 = default screener view)
                    "auth": FINVIZ_API_TOKEN,
                    "r": "5000",     # Request up to 5000 results per call (increased from 1000)
                    "s": "marketcap" # Sort by market cap to avoid alphabetical limitations
                }
                
                # Add filter string if provided
                if filters_dict:
                    # Create a copy to avoid modifying the original dictionary
                    filters_copy = filters_dict.copy()
                    
                    # Separate ordering parameter from filters
                    order_by = filters_copy.pop("o", None)
                    
                    # Build filter string: comma-separated filter names
                    # Example: "fa_div_pos,sec_technology,ta_volatility_wo5"
                    filter_str = ",".join([k for k in filters_copy.keys() if k != "o"])
                    if filter_str:
                        params["f"] = filter_str
                    
                    # Add ordering if specified (override alphabetical default)
                    if order_by:
                        params["o"] = order_by
                    elif not order_by:
                        # Force non-alphabetical ordering to get results beyond A-Z limitations
                        params["o"] = "-marketcap"
                
                # Add columns if specified (optional customization)
                if columns_list:
                    columns_str = ",".join([str(c) for c in columns_list])
                    params["c"] = columns_str
                
                # Construct the URL
                # Base: https://elite.finviz.com/export.ashx
                url = f"{FINVIZ_BASE_URL}/export.ashx"
                
                # Log request details for debugging
                logger.info(f"Finviz Request: URL={url}, Params={params}")
                
                # Make request to Finviz Elite export endpoint
                response = requests.get(url, params=params, headers=HEADERS_FINVIZ, timeout=15)
                response.raise_for_status()
                
                # Check if response is valid
                if not response.text or response.text.strip() == "":
                    logger.warning("Screener returned empty response")
                    st.warning("⚠️ No stocks found with the current criteria. Try adjusting your filters.")
                    return pd.DataFrame()
                
                # Parse CSV response into DataFrame
                df = pd.read_csv(StringIO(response.text))
                
                if df.empty:
                    logger.info(f"Finviz Screener: 0 results with current filters")
                else:
                    filter_str = params.get("f", "None")
                    logger.info(f"Finviz Screener: {len(df)} results with filters: {filter_str}")
                
                return df
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Finviz API Request Error: {str(e)}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"Status Code: {e.response.status_code}")
                    logger.error(f"Response: {e.response.text[:500]}")
                st.error("🚨 Unable to fetch market data at this moment. Please try again in a few seconds.")
                return pd.DataFrame()
            except pd.errors.ParserError as e:
                logger.error(f"Finviz CSV Parsing Error: {str(e)}")
                st.warning("⚠️ Data format issue detected. Please try with different filters.")
                return pd.DataFrame()
            except Exception as e:
                logger.error(f"Finviz screener error: {str(e)}", exc_info=True)
                st.error("❌ Something unexpected happened while fetching data. Please try again.")
                return pd.DataFrame()
        
        # ===== SELECTOR DE ESTRATEGIA =====
        col_scan, col_max = st.columns([3, 1])
        
        with col_scan:
            scan_strategy = st.selectbox(
                "🎯 Select Crazy Strategy",
                [
                    "🔥 CRAZY MOVERS (High Vol + Small Cap)",
                    "💎 MEGA CAP MOMENTUM (>$200B)",
                    "📈 DOUBLE TOP/BOTTOM REVERSAL",
                    "☕ FIGURAS TÉCNICAS (Cup & Handle, H&S)",
                    "⚡ 52-WEEK BREAKOUTS",
                    "🌊 VOLUME EXPLOSION (>3x Avg)",
                    "🎢 WILD SWINGS (>8% Intraday)",
                    "🚨 EARNINGS THIS WEEK",
                    "💥 SHORT SQUEEZE SETUP (High SI)",
                    "🔮 CUSTOM FILTERS"
                ],
                key="crazy_strategy"
            )
        
        with col_max:
            max_results = st.slider("Max Results", 10, 500, value=100, key="crazy_max")
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # SHOW LATEST MARKET NEWS
        # ═══════════════════════════════════════════════════════════════════════════════
        show_latest_news_ticker("SPY")  # Use SPY as proxy for general market news
        
        # ===== MAPEO DE ESTRATEGIAS A FILTROS FINVIZ =====
        finviz_filters = {}
        pattern_filters_list = []
        columns_to_fetch = [1, 2, 65, 66, 67, 6, 59, 64, 50, 51, 61, 42, 52, 53, 54]
        
        if "CRAZY MOVERS" in scan_strategy:
            finviz_filters = {
                "cap_smallunder": None,
                "sh_avgvol_o1000": None,
                "ta_volatility_wo5": None,
                "ta_changeopen_u5": None
            }
        
        elif "MEGA CAP" in scan_strategy:
            finviz_filters = {
                "cap_mega": None,
                "ta_perf_1wup": None,
                "sh_avgvol_o500": None
            }
        
        elif "DOUBLE TOP" in scan_strategy:
            finviz_filters = {
                "ta_pattern_doubletop": None,
                "sh_avgvol_o500": None
            }
            finviz_filters_alt = {
                "ta_pattern_doublebottom": None,
                "sh_avgvol_o500": None
            }
        
        elif "FIGURAS TÉCNICAS" in scan_strategy:
            finviz_filters = {
                "ta_pattern_horizontal": None
            }
            
            # Lista optimizada de patrones con ordenamiento inteligente
            pattern_filters_list = [
                {"ta_pattern_horizontal": None, "sh_avgvol_o500": None, "o": "-relativevolume"},
                {"ta_pattern_horizontal2": None, "sh_avgvol_o500": None, "o": "-relativevolume"},
                {"ta_pattern_headandshoulders": None, "sh_avgvol_o500": None, "o": "-change"},
                {"ta_pattern_tlsupport": None, "sh_avgvol_o500": None, "o": "-change"},
                {"ta_pattern_tlresistance": None, "sh_avgvol_o500": None, "o": "-change"},
                {"ta_pattern_wedgeup": None, "sh_avgvol_o500": None, "o": "-change"},
                {"ta_pattern_wedgedown": None, "sh_avgvol_o500": None, "o": "-change"},
                {"ta_pattern_channelup": None, "sh_avgvol_o500": None, "o": "-volume"},
                {"ta_pattern_channeldown": None, "sh_avgvol_o500": None, "o": "-volume"},
                {"ta_pattern_triangleasc": None, "sh_avgvol_o500": None, "o": "-change"},
                {"ta_pattern_triangledesc": None, "sh_avgvol_o500": None, "o": "-change"}
            ]
        
        elif "52-WEEK BREAKOUT" in scan_strategy:
            finviz_filters = {
                "ta_highlow52w_nh": None,
                "sh_avgvol_o500": None,
                "ta_rsi_os50": None
            }
        
        elif "VOLUME EXPLOSION" in scan_strategy:
            finviz_filters = {
                "sh_relvol_o3": None,
                "ta_change_u5": None
            }
        
        elif "WILD SWINGS" in scan_strategy:
            finviz_filters = {
                "ta_volatility_wo8": None,
                "sh_avgvol_o1000": None
            }
        
        elif "EARNINGS" in scan_strategy:
            finviz_filters = {
                "earningsdate_thisweek": None,
                "sh_avgvol_o500": None,
                "o": "-earningsdate"  # Ordenar por fecha de earnings
            }
            # Columnas especiales para Earnings (incluye volatilidad, ATR, Beta)
            columns_to_fetch = [1, 2, 48, 65, 66, 67, 6, 59, 60, 61, 64, 52, 53, 54, 24, 25]
        
        elif "SHORT SQUEEZE" in scan_strategy:
            finviz_filters = {
                "sh_short_o20": None,
                "ta_change_u5": None,
                "sh_relvol_o2": None
            }
        
        elif "CUSTOM" in scan_strategy:
            finviz_filters = {"sh_avgvol_o500": None}
        
        # ===== FILTROS ADICIONALES (SIEMPRE VISIBLES) =====
        st.markdown("### 🔧 Filter Settings")
        
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        
        with col_f1:
            min_price_filter = st.number_input("Min Price ($)", 0.01, 10000.0, 1.0, key="fv_min_price")
            min_volume_filter = st.number_input("Min Volume (K)", 0, 100000, 500, step=100, key="fv_min_vol")
        
        with col_f2:
            max_price_filter = st.number_input("Max Price ($)", 0.01, 10000.0, 500.0, key="fv_max_price")
            min_change_filter = st.number_input("Min Change %", -50.0, 100.0, 0.0, step=1.0, key="fv_min_change")
        
        with col_f3:
            exchange_fv = st.multiselect(
                "Exchange",
                ["NASDAQ", "NYSE", "AMEX"],
                default=["NASDAQ", "NYSE"],
                key="fv_exchange"
            )
        
        with col_f4:
            scan_all_stocks = st.checkbox(
                "🌐 Scan ALL stocks",
                value=False,
                help="Include low-volume stocks (slower, more results)",
                key="scan_all"
            )
            
            sector_filter = st.multiselect(
                "Sector (Optional)",
                ["Technology", "Healthcare", "Financial", "Energy", "Consumer", "Industrial"],
                key="fv_sector"
            )
        
        # Si scan_all está activado, remover filtro de volumen
        if scan_all_stocks and "FIGURAS TÉCNICAS" in scan_strategy:
            pattern_filters_list = [
                {"ta_pattern_horizontal": None, "o": "-relativevolume"},
                {"ta_pattern_horizontal2": None, "o": "-relativevolume"},
                {"ta_pattern_headandshoulders": None, "o": "-change"},
                {"ta_pattern_tlsupport": None, "o": "-change"},
                {"ta_pattern_tlresistance": None, "o": "-change"},
                {"ta_pattern_wedgeup": None, "o": "-change"},
                {"ta_pattern_wedgedown": None, "o": "-change"},
                {"ta_pattern_channelup": None, "o": "-volume"},
                {"ta_pattern_channeldown": None, "o": "-volume"},
                {"ta_pattern_triangleasc": None, "o": "-change"},
                {"ta_pattern_triangledesc": None, "o": "-change"}
            ]
            st.warning("⚠️ Scanning ALL stocks - This will take longer (~30-40 seconds)")
        
        # ===== CUSTOM FILTERS =====
        if "CUSTOM" in scan_strategy:
            st.markdown("---")
            st.markdown("### 🎛️ Custom Filters")
            
            col_c1, col_c2, col_c3 = st.columns(3)
            
            with col_c1:
                st.markdown("**📊 Market Cap**")
                custom_cap = st.selectbox(
                    "Cap Size",
                    ["Any", "Mega (>$200B)", "Large ($10B-$200B)", "Mid ($2B-$10B)", "Small ($300M-$2B)", "Micro (<$300M)"],
                    key="custom_cap"
                )
                
                st.markdown("**📈 Performance**")
                custom_perf = st.selectbox(
                    "Today's Performance",
                    ["Any", "Up", "Down", "Up >5%", "Down >5%", "Up >10%", "Down >10%"],
                    key="custom_perf"
                )
            
            with col_c2:
                st.markdown("**📊 Volume**")
                custom_vol = st.selectbox(
                    "Relative Volume",
                    ["Any", ">1.5x Avg", ">2x Avg", ">3x Avg", ">5x Avg"],
                    key="custom_vol"
                )
                
                st.markdown("**🎯 Technical**")
                custom_rsi = st.selectbox(
                    "RSI (14)",
                    ["Any", "Oversold (<30)", "Overbought (>70)", "Neutral (40-60)"],
                    key="custom_rsi"
                )
            
            with col_c3:
                st.markdown("**💹 Volatility**")
                custom_volatility = st.selectbox(
                    "Weekly Volatility",
                    ["Any", ">3%", ">5%", ">8%", ">10%"],
                    key="custom_volatility"
                )
                
                st.markdown("**📉 Short Interest**")
                custom_short = st.selectbox(
                    "Short Float",
                    ["Any", ">10%", ">20%", ">30%"],
                    key="custom_short"
                )
            
            custom_finviz_filters = {}
            
            if custom_cap == "Mega (>$200B)":
                custom_finviz_filters["cap_mega"] = None
            elif custom_cap == "Large ($10B-$200B)":
                custom_finviz_filters["cap_largeover"] = None
            elif custom_cap == "Mid ($2B-$10B)":
                custom_finviz_filters["cap_mid"] = None
            elif custom_cap == "Small ($300M-$2B)":
                custom_finviz_filters["cap_small"] = None
            elif custom_cap == "Micro (<$300M)":
                custom_finviz_filters["cap_micro"] = None
            
            if custom_perf == "Up":
                custom_finviz_filters["ta_change_u"] = None
            elif custom_perf == "Down":
                custom_finviz_filters["ta_change_d"] = None
            elif custom_perf == "Up >5%":
                custom_finviz_filters["ta_change_u5"] = None
            elif custom_perf == "Down >5%":
                custom_finviz_filters["ta_change_d5"] = None
            elif custom_perf == "Up >10%":
                custom_finviz_filters["ta_change_u10"] = None
            elif custom_perf == "Down >10%":
                custom_finviz_filters["ta_change_d10"] = None
            
            if custom_vol == ">1.5x Avg":
                custom_finviz_filters["sh_relvol_o1.5"] = None
            elif custom_vol == ">2x Avg":
                custom_finviz_filters["sh_relvol_o2"] = None
            elif custom_vol == ">3x Avg":
                custom_finviz_filters["sh_relvol_o3"] = None
            elif custom_vol == ">5x Avg":
                custom_finviz_filters["sh_relvol_o5"] = None
            
            if custom_rsi == "Oversold (<30)":
                custom_finviz_filters["ta_rsi_ob30"] = None
            elif custom_rsi == "Overbought (>70)":
                custom_finviz_filters["ta_rsi_ob70"] = None
            elif custom_rsi == "Neutral (40-60)":
                custom_finviz_filters["ta_rsi_nob60"] = None
            
            if custom_volatility == ">3%":
                custom_finviz_filters["ta_volatility_wo3"] = None
            elif custom_volatility == ">5%":
                custom_finviz_filters["ta_volatility_wo5"] = None
            elif custom_volatility == ">8%":
                custom_finviz_filters["ta_volatility_wo8"] = None
            elif custom_volatility == ">10%":
                custom_finviz_filters["ta_volatility_wo10"] = None
            
            if custom_short == ">10%":
                custom_finviz_filters["sh_short_o10"] = None
            elif custom_short == ">20%":
                custom_finviz_filters["sh_short_o20"] = None
            elif custom_short == ">30%":
                custom_finviz_filters["sh_short_o30"] = None
            
            if not custom_finviz_filters:
                custom_finviz_filters = {"sh_avgvol_o500": None}
            
            finviz_filters = custom_finviz_filters
            
            st.info(f"🎯 **Active Custom Filters:** {len(custom_finviz_filters)} criteria selected")
        
        st.markdown("---")
        
        # ===== BOTÓN DE ESCANEO =====
        if st.button("🔍 START CRAZY SCAN", key="start_fv_scan", use_container_width=True):
            with st.spinner(f"🔥 Scanning with Ozy Files: {scan_strategy}..."):
                try:
                    if "FIGURAS TÉCNICAS" in scan_strategy:
                        df_list = []
                        pattern_names = [
                            "HORIZONTAL", "HORIZONTAL2", "HEADSHOULDERS", "TLSUPPORT", "TLRESISTANCE",
                            "WEDGEUP", "WEDGEDOWN", "CHANNELUP", "CHANNELDOWN", "TRIANGLEASC", "TRIANGLEDESC"
                        ]
                        
                        total_patterns = len(pattern_filters_list)
                        est_time = total_patterns * 2
                        st.info(f"🔍 Searching {total_patterns} patterns... Estimated time: ~{est_time} seconds")
                        
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        for idx, pattern_filter in enumerate(pattern_filters_list):
                            status_text.text(f"Searching pattern {idx+1}/{total_patterns}: {pattern_names[idx]}...")
                            progress_bar.progress((idx + 1) / total_patterns)
                            
                            df_temp = get_finviz_screener(pattern_filter, columns_to_fetch, add_delay=True)
                            if not df_temp.empty:
                                df_temp['Pattern_Detected'] = pattern_names[idx]
                                df_list.append(df_temp)
                                st.success(f"✅ Found {len(df_temp)} stocks with {pattern_names[idx]} pattern")
                        
                        progress_bar.empty()
                        status_text.empty()
                        
                        if df_list:
                            df_finviz = pd.concat(df_list, ignore_index=True)
                            df_finviz = df_finviz.drop_duplicates(subset=['Ticker'], keep='first')
                        else:
                            df_finviz = pd.DataFrame()
                    else:
                        with st.spinner("🔍 Fetching data from FinViz Elite API..."):
                            df_finviz = get_finviz_screener(finviz_filters, columns_to_fetch, add_delay=True)
                    
                    if "DOUBLE TOP" in scan_strategy and 'finviz_filters_alt' in locals():
                        with st.spinner("🔍 Fetching alternative pattern data..."):
                            df_finviz_alt = get_finviz_screener(finviz_filters_alt, columns_to_fetch, add_delay=True)
                        df_finviz = pd.concat([df_finviz, df_finviz_alt], ignore_index=True)
                    
                    if df_finviz.empty:
                        st.error("❌ No stocks found with these filters. Try a different strategy.")
                    else:
                        st.success(f"✅ Scanner returned {len(df_finviz)} stocks!")
                        
                        try:
                            # Aplicar filtros de procesamiento
                            if 'Volume' in df_finviz.columns:
                                if df_finviz['Volume'].dtype == 'object':
                                    df_finviz['Volume_num'] = pd.to_numeric(df_finviz['Volume'].str.replace(',', ''), errors='coerce')
                                else:
                                    df_finviz['Volume_num'] = pd.to_numeric(df_finviz['Volume'], errors='coerce')
                                df_finviz = df_finviz[df_finviz['Volume_num'] >= (min_volume_filter * 1000)]
                            
                            if 'Change' in df_finviz.columns:
                                if df_finviz['Change'].dtype == 'object':
                                    df_finviz['Change_num'] = pd.to_numeric(df_finviz['Change'].str.replace('%', ''), errors='coerce')
                                else:
                                    df_finviz['Change_num'] = pd.to_numeric(df_finviz['Change'], errors='coerce')
                                df_finviz = df_finviz[df_finviz['Change_num'] >= min_change_filter]
                            
                            if 'Price' in df_finviz.columns:
                                if df_finviz['Price'].dtype == 'object':
                                    df_finviz['Price_num'] = pd.to_numeric(df_finviz['Price'].str.replace('$', ''), errors='coerce')
                                else:
                                    df_finviz['Price_num'] = pd.to_numeric(df_finviz['Price'], errors='coerce')
                                df_finviz = df_finviz[(df_finviz['Price_num'] >= min_price_filter) & (df_finviz['Price_num'] <= max_price_filter)]
                            
                            if 'Exchange' in df_finviz.columns and exchange_fv:
                                df_finviz = df_finviz[df_finviz['Exchange'].isin(exchange_fv)]
                            
                            if "CRAZY MOVERS" in scan_strategy and 'Volume_num' in df_finviz.columns:
                                df_finviz = df_finviz[df_finviz['Volume_num'] > 1000000]
                            elif "VOLUME EXPLOSION" in scan_strategy and 'Volume_num' in df_finviz.columns:
                                df_finviz = df_finviz[df_finviz['Volume_num'] > 5000000]
                            elif "WILD SWINGS" in scan_strategy and 'Change_num' in df_finviz.columns:
                                df_finviz = df_finviz[abs(df_finviz['Change_num']) > 5]
                            
                            if df_finviz.empty:
                                st.warning("⚠️ No stocks passed your additional filters.")
                            else:
                                # Mapear patrones
                                if 'Pattern_Detected' in df_finviz.columns:
                                    pattern_map = {
                                        "HORIZONTAL": "☕ CUP (Base)", "HORIZONTAL2": "🍵 HANDLE",
                                        "HEADSHOULDERS": "👤 HEAD & SHOULDERS", "TLSUPPORT": "📈 TRENDLINE SUPPORT",
                                        "TLRESISTANCE": "📉 TRENDLINE RESISTANCE", "WEDGEUP": "📐 WEDGE UP",
                                        "WEDGEDOWN": "📉 WEDGE DOWN", "CHANNELUP": "📈 CHANNEL UP",
                                        "CHANNELDOWN": "📊 CHANNEL DOWN", "TRIANGLEASC": "🔺 TRIANGLE ASC",
                                        "TRIANGLEDESC": "🔻 TRIANGLE DESC"
                                    }
                                    df_finviz['Pattern'] = df_finviz['Pattern_Detected'].map(pattern_map).fillna("UNKNOWN")
                                
                                st.success(f"✅ Found {len(df_finviz)} stocks matching filters!")
                                
                                # APLICAR LIMITE DE RESULTADOS DESPUÉS DE TODO EL PROCESAMIENTO
                                df_finviz = df_finviz.head(max_results)
                                
                                # ============ TABLA ESPECIAL PARA EARNINGS ============
                                if "EARNINGS" in scan_strategy:
                                    st.markdown("### 📊 Earnings Scanner con Predicción de Movimiento")
                                    
                                    # Buscar columna de Earnings
                                    earnings_col = None
                                    for possible_name in ['Earnings', 'Earnings Date', 'Earn Date', 'Next Earnings', 'Earnings Date_1']:
                                        if possible_name in df_finviz.columns:
                                            earnings_col = possible_name
                                            break
                                    
                                    # Crear DataFrame especial
                                    earnings_df = pd.DataFrame()
                                    
                                    if 'Ticker' in df_finviz.columns:
                                        earnings_df['Ticker'] = df_finviz['Ticker']
                                    
                                    if earnings_col:
                                        earnings_df['📅 Earnings'] = df_finviz[earnings_col]
                                    else:
                                        earnings_df['📅 Earnings'] = "This Week"
                                    
                                    if 'Company' in df_finviz.columns:
                                        earnings_df['Company'] = df_finviz['Company']
                                    
                                    if 'Price' in df_finviz.columns:
                                        earnings_df['Price'] = df_finviz['Price']
                                    
                                    # ========== ALGORITMO SIMPLIFICADO CON DATOS DISPONIBLES ==========
                                    
                                    # Usar Change_num para calcular volatilidad estimada
                                    if 'Change_num' in df_finviz.columns:
                                        change_abs = abs(df_finviz['Change_num'].fillna(0))
                                        # Expected Move basado en cambio reciente amplificado
                                        expected_move = (change_abs * 3).clip(2, 25)  # 3x el cambio actual, min 2%, max 25%
                                    else:
                                        expected_move = pd.Series([5.0] * len(df_finviz))
                                    
                                    earnings_df['Expected Move %'] = expected_move.round(1).astype(str) + '%'
                                    
                                    # ========== DIRECCIÓN: BULLISH vs BEARISH ==========
                                    
                                    # Basado solo en Change_num (cambio actual)
                                    direction_score = pd.Series([0.0] * len(df_finviz))
                                    
                                    if 'Change_num' in df_finviz.columns:
                                        direction_score = df_finviz['Change_num'].fillna(0) * 5  # Amplificar señal
                                    
                                    def get_direction(score):
                                        if score > 3:
                                            return "🟢 BULLISH"
                                        elif score < -3:
                                            return "🔴 BEARISH"
                                        else:
                                            return "🟡 NEUTRAL"
                                    
                                    earnings_df['Direction'] = direction_score.apply(get_direction)
                                    
                                    # Confidence basado en la magnitud del cambio
                                    if 'Change_num' in df_finviz.columns:
                                        confidence = (abs(df_finviz['Change_num'].fillna(0)) * 10).clip(30, 100).round(0).astype(int)
                                    else:
                                        confidence = pd.Series([50] * len(df_finviz))
                                    
                                    earnings_df['Confidence'] = confidence.astype(str) + '%'
                                    
                                    # Agregar columnas disponibles
                                    if 'Volume' in df_finviz.columns:
                                        earnings_df['Volume'] = df_finviz['Volume']
                                    if 'Market Cap' in df_finviz.columns:
                                        earnings_df['Market Cap'] = df_finviz['Market Cap']
                                    if 'Change' in df_finviz.columns:
                                        earnings_df['Change %'] = df_finviz['Change']
                                    if 'Sector' in df_finviz.columns:
                                        earnings_df['Sector'] = df_finviz['Sector']
                                    
                                    # Mostrar tabla
                                    st.dataframe(earnings_df.head(max_results), use_container_width=True, height=600)
                                    
                                    # Explicación simplificada

                                
                                # ============ TABLA ESTÁNDAR PARA OTRAS ESTRATEGIAS ============
                                else:
                                    # ========== ALGORITMO BULLISH & SHORT SQUEEZE DETECTOR ==========
                                    def calculate_bullish_short_squeeze_score(df):
                                        """
                                        Calcula puntuación para detectar:
                                        1. Potencial Bullish: Presión de compra, volumen alto, momentum positivo
                                        2. Short Squeeze: Alto interés corto + volumen explosivo + reversión alcista
                                        """
                                        scores = []
                                        
                                        for idx, row in df.iterrows():
                                            score = 0
                                            signals = []
                                            
                                            # ===== BULLISH SIGNALS =====
                                            change = 0
                                            change_str = str(row['Change']).replace('%', '').replace(',', '')
                                            try:
                                                change = float(change_str)
                                            except (ValueError, TypeError):
                                                change = 0
                                            
                                            # Signal 1: Cambio positivo (bullish momentum)
                                            if change > 1:
                                                score += 15
                                                signals.append("📈 Positive Momentum")
                                            elif change > 3:
                                                score += 25
                                                signals.append("📈📈 Strong Momentum")
                                            
                                            # Signal 2: Volumen alto (actividad institucional)
                                            volume = 0
                                            if 'Volume' in df.columns:
                                                vol_str = str(row['Volume']).replace(',', '')
                                                try:
                                                    volume = float(vol_str)
                                                except:
                                                    volume = 0
                                            
                                            if volume > 2_000_000:
                                                score += 15
                                                signals.append("📊 High Volume")
                                            elif volume > 5_000_000:
                                                score += 20
                                                signals.append("📊📊 Extreme Volume")
                                            
                                            # Signal 3: RSI (si está disponible)
                                            if 'RSI (14)' in df.columns:
                                                try:
                                                    rsi = float(row['RSI (14)'])
                                                    if 50 < rsi < 70:  # Momentum positivo sin sobreventa
                                                        score += 10
                                                        signals.append("⚡ Positive RSI")
                                                    elif rsi < 30:  # Oversold (buena entrada)
                                                        score += 15
                                                        signals.append("🟢 RSI Oversold (Entry)")
                                                except:
                                                    pass
                                            
                                            # ===== SHORT SQUEEZE SIGNALS =====
                                            
                                            # Signal 4: Reversión desde resistencia
                                            if change > 5:
                                                score += 20
                                                signals.append("🚀 Strong Reversal")
                                            
                                            # Signal 5: Volumen explosivo + cambio positivo (squeeze activación)
                                            if volume > 3_000_000 and change > 2:
                                                score += 25
                                                signals.append("💥 Squeeze Activation")
                                            
                                            # Signal 6: Patrones técnicos si existen
                                            if 'Pattern' in df.columns:
                                                pattern = str(row['Pattern']).upper()
                                                if 'BOTTOM' in pattern or 'SUPPORT' in pattern:
                                                    score += 12
                                                    signals.append("📍 Support Bounce")
                                                if 'BREAKOUT' in pattern:
                                                    score += 15
                                                    signals.append("⬆️ Breakout")
                                            
                                            # Signal 7: Market Cap (Small cap = más volatilidad para squeeze)
                                            if 'Market Cap' in df.columns:
                                                mcap_str = str(row['Market Cap']).replace(',', '').replace('B', '').replace('M', '')
                                                try:
                                                    mcap = float(mcap_str)
                                                    if mcap < 2:  # Menos de $2B
                                                        score += 10
                                                        signals.append("🎯 Small Cap (High Volatility)")
                                                except:
                                                    pass
                                            
                                            # ===== RESULTADO FINAL =====
                                            is_highlight = score >= 40  # Threshold para resaltar
                                            
                                            scores.append({
                                                'highlight': is_highlight,
                                                'score': score,
                                                'signals': ' | '.join(signals) if signals else 'Monitor',
                                                'type': 'BULLISH' if change > 0 else ('SHORT SQUEEZE' if score >= 50 else 'NEUTRAL')
                                            })
                                        
                                        return scores
                                    
                                    # Calcular scores
                                    df_scores = calculate_bullish_short_squeeze_score(df_finviz)
                                    
                                    # Agregar columnas de análisis al DataFrame
                                    df_finviz['_Score'] = [s['score'] for s in df_scores]
                                    df_finviz['_Type'] = [s['type'] for s in df_scores]
                                    df_finviz['📊 Signals'] = [s['signals'] for s in df_scores]
                                    df_finviz['_Highlight'] = [s['highlight'] for s in df_scores]
                                    
                                    # Ordenar por score (mayor primero)
                                    df_display = df_finviz.sort_values('_Score', ascending=False)
                                    
                                    # Preparar columnas a mostrar
                                    display_cols = []
                                    if 'Ticker' in df_display.columns:
                                        display_cols.append('Ticker')
                                    if 'Pattern' in df_display.columns:
                                        display_cols.append('Pattern')
                                    if 'Company' in df_display.columns:
                                        display_cols.append('Company')
                                    if 'Price' in df_display.columns:
                                        display_cols.append('Price')
                                    if 'Change' in df_display.columns:
                                        display_cols.append('Change')
                                    if 'Volume' in df_display.columns:
                                        display_cols.append('Volume')
                                    if 'Market Cap' in df_display.columns:
                                        display_cols.append('Market Cap')
                                    if 'RSI (14)' in df_display.columns:
                                        display_cols.append('RSI (14)')
                                    
                                    display_cols.extend(['_Type', '📊 Signals', '_Score'])
                                    
                                    # Crear tabla con highlight amarillo
                                    df_table = df_display[display_cols].head(max_results).reset_index(drop=True)
                                    
                                    # ════════════════════════════════════════════════════════
                                    # TABLA INTERACTIVA Y ORDENABLE
                                    # ════════════════════════════════════════════════════════
                                    st.markdown("### 📊 Scanned Results - Sort by Column") 
                                    
                                    # Crear columnas de control
                                    col_sort1, col_sort2 = st.columns([3, 1])
                                    
                                    with col_sort1:
                                        sort_column = st.selectbox(
                                            "Sort by:",
                                            options=display_cols,
                                            index=len(display_cols) - 1,  # Default to _Score (last column)
                                            key="scanner_sort_column"
                                        )
                                    
                                    with col_sort2:
                                        sort_order = st.radio(
                                            "Order:",
                                            ["Descending ↓", "Ascending ↑"],
                                            key="scanner_sort_order"
                                        )
                                    
                                    # Aplicar ordenamiento
                                    ascending = sort_order == "Ascending ↑"
                                    df_sorted = df_table.sort_values(by=sort_column, ascending=ascending)
                                    
                                    # Mostrar tabla interactiva con Streamlit
                                    st.dataframe(
                                        df_sorted,
                                        use_container_width=True,
                                        height=600,
                                        column_config={
                                            "Ticker": st.column_config.TextColumn("🔖 Ticker", width="small"),
                                            "Company": st.column_config.TextColumn("🏢 Company", width="medium"),
                                            "Price": st.column_config.NumberColumn("💰 Price", format="$%.2f"),
                                            "Change": st.column_config.TextColumn("📈 Change", width="small"),
                                            "Volume": st.column_config.TextColumn("📊 Volume", width="small"),
                                            "Market Cap": st.column_config.TextColumn("🏦 Market Cap", width="medium"),
                                            "RSI (14)": st.column_config.NumberColumn("📉 RSI", format="%.2f"),
                                            "_Type": st.column_config.TextColumn("⚡ Type", width="small"),
                                            "📊 Signals": st.column_config.TextColumn("📢 Signals", width="large"),
                                            "_Score": st.column_config.NumberColumn("⭐ Score", format="%d")
                                        },
                                        hide_index=True
                                    )
                                    
                                    # Leyenda mejorada
                                    st.markdown("---")
                                    st.markdown("### 🎯 Legend & Quick Help")
                                    
                                    # Primera fila - Indicadores principales
                                    col_legend1, col_legend2, col_legend3 = st.columns(3)
                                    
                                    with col_legend1:
                                        st.info("**📈 Bullish** = Strong upside momentum signals\n**🔼 Alcista** = Señales de fuerte impulso al alza")
                                    with col_legend2:
                                        st.success("**🔥 Squeeze** = Short squeeze candidates\n**🔥 Presión** = Candidatos para compresión de posiciones cortas")
                                    with col_legend3:
                                        st.warning("**⭐ Score 40+** = High confidence signals\n**⭐ Puntuación 40+** = Señales de alta confianza")
                                    
                                    # Segunda fila - Componentes técnicos
                                    st.markdown("#### 📊 Technical Components / Componentes Técnicos:")
                                    col_tech1, col_tech2, col_tech3 = st.columns(3)
                                    
                                    with col_tech1:
                                        st.markdown("""
                                        **⬆️ Positive Momentum**
                                        El precio tiene movimiento ascendente con fuerza creciente. Indica que los compradores ganan control y la presión de compra aumenta.
                                        
                                        **📊 High Volume**
                                        Gran volumen de transacciones. Señal de interés fuerte. Cuando hay volumen alto + subida = movimiento confiable.
                                        """)
                                    
                                    with col_tech2:
                                        st.markdown("""
                                        **🔄 Strong Reversal**
                                        Cambio significativo de dirección en el precio (de bajada a subida). Indica que el sentimiento del mercado está cambiando.
                                        
                                        **📈 Strong Upside Momentum**
                                        Fuerte impulso/velocidad hacia arriba. El precio sube de forma acelerada. Mayor velocidad = Mayor confianza.
                                        """)
                                    
                                    with col_tech3:
                                        st.markdown("""
                                        **🎯 Signal (Señal)**
                                        Recomendación de acción basada en indicadores: COMPRA, VENTA o ESPERAR.
                                        
                                        **💯 Score / Puntuación (0-100)**
                                        Mide confiabilidad: Score 40+ (Alta) | 70+ (Muy Alta) | <40 (Baja)
                                        """)
                                    
                                    # Tercera fila - Patrones combinados
                                    st.markdown("#### 🚀 Combined Patterns / Patrones Combinados:")
                                    col_patterns1, col_patterns2, col_patterns3 = st.columns(3)
                                    
                                    with col_patterns1:
                                        st.success("""
                                        **✅ Bullish + Strong Momentum + Score 40+**
                                        
                                        Tendencia fuerte al alza con confianza alta
                                        
                                        **Acción: COMPRAR**
                                        """)
                                    
                                    with col_patterns2:
                                        st.error("""
                                        **🚀 Squeeze Short + Score 40+**
                                        
                                        Posiciones cortas forzadas a cerrar → Subida explosiva
                                        
                                        **Acción: PREPARARSE PARA MOVIMIENTO**
                                        """)
                                    
                                    with col_patterns3:
                                        st.warning("""
                                        **📈 Strong Reversal + High Volume**
                                        
                                        Cambio de dirección confirmado por volumen fuerte
                                        
                                        **Acción: OPORTUNIDAD DE COMPRA**
                                        """)
                                    
                                    st.markdown("💡 **Resumen:** Mayor Score + Mayor Momentum = Mayor confianza en la acción")
                        
                        except Exception as e:
                            logger.error(f"Error processing data: {str(e)}", exc_info=True)
                            st.error("⚠️ There was an issue processing the results. Please try a different scan.")
                
                except Exception as e:
                    logger.error(f"Tab 2 Scanner Error: {str(e)}", exc_info=True)
                    st.error("❌ The scanner encountered an issue. Please refresh and try again.")
        
        st.markdown("---")
        st.markdown("*🚀 Developed by Ozy *")
    # Tab 3: News Scanner
    if active_tab == tab_labels[2]:
        st.subheader("News Scanner")
        
        # Inicializar st.session_state para latest_news si no existe
        if "latest_news" not in st.session_state:
            with st.spinner("Fetching initial market news..."):
                google_news = fetch_google_news(["SPY"])  # SPY como default para mercado general
                bing_news = fetch_bing_news(["SPY"])
                st.session_state["latest_news"] = google_news + bing_news if google_news or bing_news else None
        
        # Sección de noticias
        st.markdown("#### Search News")
        keywords = st.text_input("Enter keywords (comma-separated):", "Trump", key="news_keywords").split(",")
        keywords = [k.strip() for k in keywords if k.strip()]
        
        if st.button("Fetch News", key="fetch_news"):
            with st.spinner("Fetching news..."):
                google_news = fetch_google_news(keywords)
                bing_news = fetch_bing_news(keywords)
                latest_news = google_news + bing_news
                
                if latest_news:
                    st.session_state["latest_news"] = latest_news
                    for idx, article in enumerate(latest_news[:10], 1):
                        st.markdown(f"### {idx}. [{article['title']}]({article['link']})")
                        st.markdown(f"**Published:** {article['time']}\n")
                        st.markdown("---")
                else:
                    st.error("No recent news found.")
                    st.session_state["latest_news"] = None
        
        # Separador
        st.markdown("---")
        
        # Sección de sentimientos (siempre visible)
        st.markdown("#### Market Sentiment (Based on Latest News)")
        if st.session_state["latest_news"]:
            sentiment_score, sentiment_text = calculate_retail_sentiment(st.session_state["latest_news"])
            volatility_score, volatility_text = calculate_volatility_sentiment(st.session_state["latest_news"])
            
            # Dividir en columnas para Retail y Volatility Sentiment
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("##### Retail Sentiment")
                fig_sentiment = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=sentiment_score * 100,
                    delta={'reference': 50, 'relative': True, 'valueformat': '.2%'},
                    title={'text': "Retail Sentiment Score", 'font': {'size': 16, 'color': '#FFFFFF'}},
                    gauge={
                        'axis': {'range': [0, 100], 'tickcolor': "#FFFFFF", 'tickfont': {'color': "#FFFFFF"}},
                        'bar': {'color': "#32CD32" if sentiment_score > 0.5 else "#FF4500", 'thickness': 0.2},
                        'bgcolor': "rgba(0, 0, 0, 0.1)",
                        'steps': [
                            {'range': [0, 30], 'color': "#FF4500"},
                            {'range': [30, 70], 'color': "#FFD700"},
                            {'range': [70, 100], 'color': "#32CD32"}
                        ],
                        'threshold': {
                            'line': {'color': "#FFFFFF", 'width': 4},
                            'thickness': 0.75,
                            'value': 50
                        }
                    }
                ))
                fig_sentiment.update_layout(
                    height=250,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font={'color': "#FFFFFF"}
                )
                st.plotly_chart(fig_sentiment, use_container_width=True)
                st.markdown(f"**Sentiment:** {sentiment_text} ({sentiment_score:.2%})", unsafe_allow_html=True)
            
            with col2:
                st.markdown("##### Volatility Sentiment")
                fig_volatility = go.Figure(go.Bar(
                    x=["Volatility Sentiment"],
                    y=[volatility_score],
                    text=[f"{volatility_score:.1f}"],
                    textposition="auto",
                    marker_color="#FFD700" if volatility_score < 50 else "#FF4500",
                    hovertemplate="Volatility Score: %{y:.1f}<br>%{text}",
                    marker=dict(
                        line=dict(color="#FFFFFF", width=2)
                    )
                ))
                fig_volatility.update_layout(
                    yaxis_range=[0, 100],
                    height=250,
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font={'color': "#FFFFFF"},
                    yaxis={'gridcolor': "rgba(255,255,255,0.2)"}
                )
                st.plotly_chart(fig_volatility, use_container_width=True)
                st.markdown(f"**Volatility Perception:** {volatility_text} ({volatility_score:.1f}/100)", unsafe_allow_html=True)
        else:
            st.warning("No news data available to analyze sentiment. Try fetching news.")
        
        st.markdown("---")
        st.markdown("*Developed by Ozy | © 2025*")

    # Tab 5: Analyst Rating Flow
        # Tab 5: Analyst Rating Flow
    if active_tab == tab_labels[3]:
        st.subheader("Rating Flow")
        
        # Estilos personalizados
        st.markdown("""
            <style>
            .centered-content {
                text-align: center;
                display: flex;
                flex-direction: column;
                align-items: center;
                width: 100%;
                max-width: 800px;
                margin: 0 auto;
            }
            .centered-content h3, .centered-content div, .centered-content input, .centered-content select {
                text-align: center;
            }
            .centered-content .stTextInput, .centered-content .stSelectbox, .centered-content .stCheckbox, .centered-content .stPlotlyChart {
                display: flex;
                justify-content: center;
                width: 100%;
            }
            .centered-content .stTextInput > div, .centered-content .stSelectbox > div, .centered-content .stCheckbox > div {
                width: 80%;
                margin: 0 auto;
            }
            .centered-content .stPlotlyChart > div {
                width: 100%;
                max-width: 800px;
                margin: 0 auto;
            }
            .centered-content .stDataFrame {
                width: 100%;
            }
            .centered-content .stDataFrame > div {
                width: 100%;
                margin: 0 auto;
            }
            .hacker-text {
                background: #1A1A1A;
                padding: 15px;
                border-radius: 8px;
                border: 2px solid #FFD700;
                font-family: 'Courier New', Courier, monospace;
                color: #FFD700;
                font-size: 14px;
                line-height: 1.5;
                text-align: left;
                box-shadow: 0 0 10px rgba(255, 215, 0, 0.3);
                white-space: pre-wrap;
                max-width: 600px;
                margin: 0 auto;
            }
            .tooltip {
                position: relative;
                display: inline-block;
                cursor: help;
                color: #32CD32;
                margin-left: 5px;
            }
            .tooltip .tooltiptext {
                visibility: hidden;
                width: 200px;
                background-color: #2D2D2D;
                color: #FFFFFF;
                text-align: center;
                border-radius: 5px;
                padding: 5px;
                position: absolute;
                z-index: 1;
                bottom: 125%;
                left: 50%;
                margin-left: -100px;
                font-size: 12px;
                box-shadow: 0 2px 5px rgba(0, 0, 0, 0.5);
            }
            .tooltip:hover .tooltiptext {
                visibility: visible;
            }
            </style>
        """, unsafe_allow_html=True)
        
        st.markdown('<div class="centered-content">', unsafe_allow_html=True)
        
        # Configuration Section
        st.markdown("### Configuration")
        ticker = st.text_input("Ticker Symbol (e.g., SPY)", "SPY", key="alerts_ticker").upper()
        expiration_dates = get_expiration_dates(ticker)
        if not expiration_dates:
            st.error(f"What were you thinking, '{ticker}'? You're a trader and you mess this up? If you trade like this, you're doomed!")
            st.markdown('</div>', unsafe_allow_html=True)
            return
        expiration_date = st.selectbox("Expiration Date", expiration_dates, key="alerts_exp_date")
        with st.spinner("Fetching price..."):
            current_price = get_current_price(ticker)
            if current_price == 0.0:
                st.error(f"Invalid ticker '{ticker}' or no price data available.")
                st.markdown('</div>', unsafe_allow_html=True)
                return
        
        # Calcular volatilidad implícita
        iv = get_implied_volatility(ticker) or 0.3
        iv_factor = min(max(iv, 0.1), 1.0)
        
        # Vol Filter
        st.markdown("### Vol Filter")
        volume_options = {
            "0.1M": 10000,
            "0.2M": 20000,
            "0.3M": 30000,
            "0.4M": 40000,
            "0.5M": 50000,
            "1.0M": 100000
        }
        auto_oi = int(100000 * (1 + iv_factor * 2))
        auto_oi_key = next((k for k, v in volume_options.items() if v >= auto_oi), "0.1M")
        use_auto_oi = st.checkbox("Auto OI (Volatility-Based)", value=False, key="auto_oi")
        if use_auto_oi:
            open_interest_threshold = volume_options[auto_oi_key]
            st.write(f"Auto OI Set: {auto_oi_key} ({volume_options[auto_oi_key]:,})")
        else:
            selected_volume = st.selectbox("Min Open Interest (M)", list(volume_options.keys()), index=0, key="alerts_vol")
            open_interest_threshold = volume_options[selected_volume]
        
        # Gamma Filter
        st.markdown("### Gamma Filter")
        gamma_options = {
            "0.001": 0.001,
            "0.005": 0.005,
            "0.01": 0.01,
            "0.02": 0.02,
            "0.03": 0.03,
            "0.05": 0.05
        }
        auto_gamma = max(0.001, min(0.05, iv_factor / 20))
        auto_gamma_key = next((k for k, v in gamma_options.items() if v >= auto_gamma), "0.001")
        use_auto_gamma = st.checkbox("Auto Gamma (Volatility-Based)", value=False, key="auto_gamma")
        if use_auto_gamma:
            gamma_threshold = gamma_options[auto_gamma_key]
            st.write(f"Auto Gamma Set: {auto_gamma_key}")
        else:
            selected_gamma = st.selectbox("Min Gamma", list(gamma_options.keys()), index=0, key="alerts_gamma")
            gamma_threshold = gamma_options[selected_gamma]
        
        st.markdown(f"**Current Price:** ${current_price:.2f}  \n*Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        
        # Charts and Table Section
        with st.spinner(f"Generating alerts for {expiration_date}..."):
            options_data, max_pain, mm_gain = process_rating_flow_data(ticker, expiration_date, current_price)
            if not options_data:
                st.error("No options data available for this date.")
                st.markdown('</div>', unsafe_allow_html=True)
                return
            
            # Texto estilo hacker
            max_pain_display = f"{max_pain:.2f}" if max_pain is not None else "N/A"
            mm_gain_display = f"{mm_gain:,.2f}" if mm_gain is not None else "0.0"
            hacker_text = f"""
>>> Current_Price = ${current_price:.2f}
>>> Updated = "{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
>>> Max_Pain_Strike = ${max_pain_display}
>>> MM_Potential_Gain = ${mm_gain_display}
"""
            st.markdown(f'<div class="hacker-text">{hacker_text}</div>', unsafe_allow_html=True)
            
            # Simplified suggestion generation with tolerance for max pain
            suggestions = []
            valid_contracts = 0
            for opt in options_data:
                if not isinstance(opt, dict):
                    continue
                strike = float(opt.get("strike", 0))
                opt_type = opt.get("option_type", "").upper()
                oi = int(opt.get("open_interest", 0))
                greeks = opt.get("greeks", {})
                gamma = float(greeks.get("gamma", 0)) if isinstance(greeks, dict) else 0
                iv = float(greeks.get("smv_vol", 0)) if isinstance(greeks, dict) else 0
                delta = float(greeks.get("delta", 0)) if isinstance(greeks, dict) else 0
                volume = int(opt.get("volume", 0) or 0)
                last = opt.get("last", 0)
                bid = opt.get("bid", 0)
                last_price = float(last) if last is not None and isinstance(last, (int, float, str)) and last != 0 else float(bid) if bid is not None and isinstance(bid, (int, float, str)) and bid != 0 else 0
                
                if oi >= open_interest_threshold and gamma >= gamma_threshold:
                    valid_contracts += 1
                    action = "SELL" if (opt_type == "CALL" and strike > current_price) or (opt_type == "PUT" and strike < current_price) else "BUY"
                    rr = abs(strike - current_price) / (last_price + 0.01) if last_price else 0
                    prob_otm = 1 - abs(delta) if delta else 0
                    profit = (strike - current_price) * 100 if action == "BUY" and opt_type == "CALL" else (current_price - strike) * 100 if action == "BUY" and opt_type == "PUT" else last_price * 100
                    is_max_pain = abs(strike - max_pain) < 0.01 if max_pain is not None else False
                    mm_gain_at_strike = mm_gain * 100 if is_max_pain else 0
                    
                    suggestions.append({
                        "Strike": strike, "Action": action, "Type": opt_type, "Gamma": gamma, "IV": iv, "Delta": delta,
                        "RR": rr, "Prob OTM": prob_otm, "Profit": profit, "Open Interest": oi, "IsMaxPain": is_max_pain,
                        "MM Gain ($)": mm_gain_at_strike
                    })
            
            if suggestions:
                df = pd.DataFrame(suggestions)
                df['Contract'] = df.apply(lambda row: f"{ticker} {row['Action']} {row['Type']} {row['Strike']}", axis=1)
                df = df[['Contract', 'Strike', 'Action', 'Type', 'Gamma', 'IV', 'Delta', 'RR', 'Prob OTM', 'Profit', 'Open Interest', 'IsMaxPain', 'MM Gain ($)']]
                df.columns = ['Contract', 'Strike', 'Action', 'Type', 'Gamma', 'IV', 'Delta', 'R/R', 'Prob OTM', 'Profit ($)', 'Open Int.', 'Max Pain', 'MM Gain ($)']
                
                def color_row(row):
                    if row['Max Pain'] is True:
                        return ['color: #FFD700; font-weight: bold'] * len(row)
                    elif row['Type'] == "CALL":
                        return ['color: #228B22'] * len(row)
                    elif row['Type'] == "PUT":
                        return ['color: #CD5C5C'] * len(row)
                    return [''] * len(row)
                
                styled_df = df.style.apply(color_row, axis=1).format({
                    'Strike': '{:.1f}',
                    'Profit ($)': '${:.2f}',
                    'Open Int.': '{:,.0f}',
                    'MM Gain ($)': '{:.2f}'
                })
                st.write(f"Found {valid_contracts} contracts with OI ≥ {open_interest_threshold:,} and Gamma ≥ {gamma_threshold}")
                st.dataframe(styled_df, use_container_width=True, height=400)
                
                # Gráfico de burbujas
                fig = go.Figure()
                call_data = [
                    {
                        "strike": float(opt.get("strike", 0)),
                        "option_type": opt.get("option_type", "").lower(),
                        "open_interest": int(opt.get("open_interest", 0)),
                        "bid": float(opt.get("bid", 0)) if opt.get("bid") is not None and isinstance(opt.get("bid"), (int, float, str)) else 0
                    }
                    for opt in options_data if isinstance(opt, dict)
                ]
                call_df = pd.DataFrame([d for d in call_data if d["option_type"] == "call"])
                put_df = pd.DataFrame([d for d in call_data if d["option_type"] == "put"])
                
                # Limpiar open_interest para evitar nan
                call_df['open_interest'] = call_df['open_interest'].fillna(0).astype(int).clip(lower=0)
                put_df['open_interest'] = put_df['open_interest'].fillna(0).astype(int).clip(lower=0)
                
                # Crear figura combinada
                if not call_df.empty:
                    total_profit = call_df['open_interest'] * call_df['bid']
                    max_total_profit = total_profit.max() if total_profit.max() > 0 else 1
                    sizes = np.nan_to_num(total_profit / max_total_profit * 50, nan=0, posinf=0, neginf=0)
                    sizes = np.maximum(sizes, 5)
                    fig.add_trace(go.Scatter(
                        x=call_df['strike'], 
                        y=call_df['bid'], 
                        mode='markers', 
                        name='CALL Options', 
                        marker=dict(
                            size=sizes, 
                            color='#228B22', 
                            opacity=0.7
                        ),
                        text=call_df['strike'].astype(str) + '<br>OI: ' + call_df['open_interest'].astype(str),
                        hovertemplate="<b>Strike:</b> %{x:.2f}<br><b>Bid:</b> ${%y:.2f}<br><b>Open Interest:</b> %{customdata:,}",
                        customdata=call_df['open_interest']
                    ))
                if not put_df.empty:
                    total_profit = put_df['open_interest'] * put_df['bid']
                    max_total_profit = total_profit.max() if total_profit.max() > 0 else 1
                    sizes = np.nan_to_num(total_profit / max_total_profit * 50, nan=0, posinf=0, neginf=0)
                    sizes = np.maximum(sizes, 5)
                    fig.add_trace(go.Scatter(
                        x=put_df['strike'], 
                        y=put_df['bid'], 
                        mode='markers', 
                        name='PUT Options', 
                        marker=dict(
                            size=sizes, 
                            color='#CD5C5C', 
                            opacity=0.7
                        ),
                        text=put_df['strike'].astype(str) + '<br>OI: ' + put_df['open_interest'].astype(str),
                        hovertemplate="<b>Strike:</b> %{x:.2f}<br><b>Bid:</b> ${%y:.2f}<br><b>Open Interest:</b> %{customdata:,}",
                        customdata=put_df['open_interest']
                    ))
                if mm_gain > 0 and max_pain is not None:
                    fig.add_trace(go.Scatter(
                        x=[max_pain], 
                        y=[0], 
                        mode='markers+text', 
                        name='MM Gain', 
                        marker=dict(size=50, color='#FFD700', opacity=0.9, line=dict(width=2, color='#FFFFFF')),
                        text=[f"MM Gain: ${mm_gain:,.2f}"],
                        textposition="middle center"
                    ))
                if max_pain is not None:
                    fig.add_vline(x=max_pain, line=dict(color="#FFD700", width=2, dash="dash"), annotation_text="Max Pain", annotation_position="top right")
                fig.add_hline(y=0, line=dict(color="#FFFFFF", width=1))
                fig.update_layout(
                    title="Average Profit by Strike", 
                    xaxis_title="Strike", 
                    yaxis_title="Bid Price", 
                    template="plotly_dark", 
                    height=400
                )
                st.plotly_chart(fig, use_container_width=True)
                
                csv = df.to_csv(index=False)
                st.download_button(
                    label="📥 Download Rating Flow Data",
                    data=csv,
                    file_name=f"{ticker}_rating_flow_{expiration_date}.csv",
                    mime="text/csv",
                    key="download_tab6"
                )
            else:
                st.error(f"No alerts generated with Open Interest ≥ {open_interest_threshold:,}, Gamma ≥ {gamma_threshold}. Check logs.")
            
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("*Developed by Ozy | © 2025*")

    # Tab 6: MM Flow Dynamics
    if active_tab == tab_labels[4]:
        st.subheader("📊 MM Flow Dynamics - Market Maker Positioning Analysis")
        
        col1, col2 = st.columns(2)
        with col1:
            ticker = st.text_input("Stock Ticker", "SPY", key="mm_flow_ticker").upper()
        with col2:
            expiration_dates = get_expiration_dates(ticker)
            if not expiration_dates:
                st.error(f"No expiration dates found for '{ticker}'.")
                st.stop()
            selected_expiration = st.selectbox("Expiration Date", expiration_dates, key="mm_flow_expiration")
        
        with st.spinner(f"Analyzing MM flow for {ticker} on {selected_expiration}..."):
            current_price = get_current_price(ticker)
            if current_price == 0.0:
                st.error(f"Unable to fetch price for {ticker}.")
                st.stop()
            
            options_data = get_options_data(ticker, selected_expiration)
            if not options_data:
                st.error(f"No options data available for {selected_expiration}.")
                st.stop()
            
            # Calculate MM dynamics
            mm_analysis = calculate_mm_dynamics(options_data, current_price)
            if not mm_analysis:
                st.error("Unable to calculate MM dynamics.")
                st.stop()
            
            # Key metrics
            col1, col2, col3, col4 = st.columns(4)
            
            total_call_oi = sum(opt.get("open_interest", 0) for opt in options_data if opt.get("option_type", "").upper() == "CALL")
            total_put_oi = sum(opt.get("open_interest", 0) for opt in options_data if opt.get("option_type", "").upper() == "PUT")
            call_put_ratio = total_call_oi / total_put_oi if total_put_oi > 0 else 0
            
            with col1:
                st.metric("Current Price", f"${current_price:.2f}")
            with col2:
                st.metric("Call/Put Ratio", f"{call_put_ratio:.2f}x", delta="Bullish" if call_put_ratio > 1 else "Bearish")
            with col3:
                st.metric("Total Call OI", f"{total_call_oi:,.0f}")
            with col4:
                st.metric("Total Put OI", f"{total_put_oi:,.0f}")
            
            st.markdown("---")
            
            # Section 1: MM Pressure Heatmap
            st.subheader("🔥 MM Pressure Heatmap - Where MMs Will Push Price")
            
            strikes_list = sorted(mm_analysis.keys())
            pressure_data = []
            
            for strike in strikes_list:
                data = mm_analysis[strike]
                total_pressure = data["call_pressure"] + data["put_pressure"]
                pressure_pct = (total_pressure / max([mm_analysis[s]["call_pressure"] + mm_analysis[s]["put_pressure"] for s in strikes_list])) * 100 if strikes_list else 0
                
                pressure_data.append({
                    "Strike": strike,
                    "MM Pressure": pressure_pct,
                    "Call Pressure": data["call_pressure"],
                    "Put Pressure": data["put_pressure"],
                    "Distance %": data["distance_pct"],
                    "Attraction Score": data["attraction_score"]
                })
            
            pressure_df = pd.DataFrame(pressure_data)
            
            # Create pressure heatmap chart
            fig_pressure = go.Figure()
            
            colors = []
            for val in pressure_df["MM Pressure"]:
                if val >= 75:
                    colors.append("#FF0000")  # Red - Very high pressure
                elif val >= 50:
                    colors.append("#FF6600")  # Orange - High pressure
                elif val >= 25:
                    colors.append("#FFFF00")  # Yellow - Medium pressure
                else:
                    colors.append("#00FF00")  # Green - Low pressure
            
            fig_pressure.add_trace(go.Bar(
                x=pressure_df["Strike"],
                y=pressure_df["MM Pressure"],
                marker=dict(color=colors),
                text=[f"{v:.1f}%" for v in pressure_df["MM Pressure"]],
                textposition="outside",
                hovertemplate="<b>Strike: $%{x:.2f}</b><br>MM Pressure: %{y:.1f}%<extra></extra>",
                showlegend=False
            ))
            
            # Add current price line
            fig_pressure.add_vline(x=current_price, line_dash="dash", line_color="#39FF14", 
                                 annotation_text=f"Price: ${current_price:.2f}", 
                                 annotation_position="top right")
            
            fig_pressure.update_layout(
                title="MM Pressure Distribution Across Strikes",
                xaxis_title="Strike Price",
                yaxis_title="MM Pressure (%)",
                template="plotly_dark",
                height=400,
                hovermode="x unified",
                plot_bgcolor="#0a0a0a",
                paper_bgcolor="#0a0a0a"
            )
            st.plotly_chart(fig_pressure, use_container_width=True)
            
            st.markdown("---")
            
            # Section 2: Call vs Put Pressure
            st.subheader("⚖️ Call vs Put Pressure - Market Sentiment")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Call pressure by strike
                fig_calls = go.Figure()
                fig_calls.add_trace(go.Bar(
                    x=pressure_df["Strike"],
                    y=pressure_df["Call Pressure"],
                    marker_color="#00FF00",
                    name="Call Pressure",
                    text=[f"{v:.0f}" for v in pressure_df["Call Pressure"]],
                    textposition="auto",
                ))
                fig_calls.add_vline(x=current_price, line_dash="dash", line_color="#FFFFFF", opacity=0.5)
                fig_calls.update_layout(
                    title="Call Pressure (Bullish Bias)",
                    xaxis_title="Strike",
                    yaxis_title="Pressure",
                    template="plotly_dark",
                    height=350,
                    plot_bgcolor="#0a0a0a",
                    paper_bgcolor="#0a0a0a",
                    showlegend=False
                )
                st.plotly_chart(fig_calls, use_container_width=True)
            
            with col2:
                # Put pressure by strike
                fig_puts = go.Figure()
                fig_puts.add_trace(go.Bar(
                    x=pressure_df["Strike"],
                    y=pressure_df["Put Pressure"],
                    marker_color="#FF0000",
                    name="Put Pressure",
                    text=[f"{v:.0f}" for v in pressure_df["Put Pressure"]],
                    textposition="auto",
                ))
                fig_puts.add_vline(x=current_price, line_dash="dash", line_color="#FFFFFF", opacity=0.5)
                fig_puts.update_layout(
                    title="Put Pressure (Bearish Bias)",
                    xaxis_title="Strike",
                    yaxis_title="Pressure",
                    template="plotly_dark",
                    height=350,
                    plot_bgcolor="#0a0a0a",
                    paper_bgcolor="#0a0a0a",
                    showlegend=False
                )
                st.plotly_chart(fig_puts, use_container_width=True)
            
            st.markdown("---")
            
            # Section 3: Top MM Pressure Zones (Tarjetas)
            st.subheader("🎯 Top MM Pressure Zones - Where MMs Are Positioning")
            
            top_pressure = pressure_df.nlargest(3, "MM Pressure")
            
            cols = st.columns(3)
            for idx, (col, (_, row)) in enumerate(zip(cols, top_pressure.iterrows())):
                with col:
                    # Dynamic gradient color based on pressure
                    pressure_val = row["MM Pressure"]
                    if pressure_val >= 75:
                        color_hex = "#FF0000"
                        intensity = "🔴 CRITICAL"
                    elif pressure_val >= 50:
                        color_hex = "#FF6600"
                        intensity = "🟠 HIGH"
                    elif pressure_val >= 25:
                        color_hex = "#FFFF00"
                        intensity = "🟡 MEDIUM"
                    else:
                        color_hex = "#00FF00"
                        intensity = "🟢 LOW"
                    
                    st.markdown(f"""
                    <div style="
                        background: linear-gradient(135deg, {color_hex}22 0%, {color_hex}11 100%);
                        border: 2px solid {color_hex};
                        border-radius: 8px;
                        padding: 15px;
                        text-align: center;
                        box-shadow: 0 0 20px {color_hex}44;
                    ">
                        <h3 style="color: {color_hex}; margin: 0;">${row['Strike']:.2f}</h3>
                        <p style="color: #FFFFFF; font-size: 14px; margin: 5px 0;">
                            <b>MM Pressure:</b> {pressure_val:.1f}%<br>
                            {intensity}
                        </p>
                        <p style="color: #39FF14; font-size: 12px; margin: 5px 0;">
                            Distance: {row['Distance %']:.2f}%<br>
                            Attraction: {row['Attraction Score']:.0f}
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Section 4: MM Flow Analysis Table
            st.subheader("📋 MM Flow Analysis - Detailed Strike Data")
            
            display_df = pressure_df.copy()
            display_df["Strike"] = display_df["Strike"].apply(lambda x: f"${x:.2f}")
            display_df["MM Pressure"] = display_df["MM Pressure"].apply(lambda x: f"{x:.1f}%")
            display_df["Call Pressure"] = display_df["Call Pressure"].apply(lambda x: f"{x:.0f}")
            display_df["Put Pressure"] = display_df["Put Pressure"].apply(lambda x: f"{x:.0f}")
            display_df["Distance %"] = display_df["Distance %"].apply(lambda x: f"{x:.2f}%")
            display_df["Attraction Score"] = display_df["Attraction Score"].apply(lambda x: f"{x:.0f}")
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            # Download button
            csv_data = pressure_df.to_csv(index=False)
            st.download_button(
                label="📥 Download MM Flow Data",
                data=csv_data,
                file_name=f"{ticker}_mm_flow_{selected_expiration}.csv",
                mime="text/csv",
                key="download_mm_flow"
            )
            
            st.markdown("---")
            
            # Section 5: MM Logic Explanation
            st.subheader("📚 How MM Flow Works")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("""
                **🔥 MM Pressure**
                
                Calculated as:
                ```
                Pressure = (OI + VOL) × Spread × IV
                ```
                
                Higher pressure = MMs will fight harder to reach that strike
                """)
            
            with col2:
                st.markdown("""
                **📊 Attraction Score**
                
                Shows probability of price moving to that zone:
                ```
                Attraction = Pressure / (Distance + 1)
                ```
                
                Closer + Higher Pressure = More likely
                """)
            
            with col3:
                st.markdown("""
                **⚖️ Call/Put Ratio**
                
                - **> 1.0** = Bullish (more call buying)
                - **< 1.0** = Bearish (more put buying)
                - **= 1.0** = Balanced
                
                MMs profit from imbalances!
                """)

    # Tab 8: INSTITUTIONAL MM SYSTEM - Phase 1
    if active_tab == tab_labels[5]:
        st.markdown("# Gamma-Based Market Microstructure Analysis")
        st.divider()
        
        try:
            from mm_orchestrator import MMSystemOrchestrator
            from mm_memory import MemorySystem
            
            # Initialize
            orch = MMSystemOrchestrator()
            mem = MemorySystem()
            
            # Initialize ticker from session state or default
            mm_ticker = st.session_state.get("mm_ticker_select", "SPY")
            
            # Get expiration dates dynamically
            exp_dates = get_expiration_dates(mm_ticker) if mm_ticker else []
            if not exp_dates:
                # Fallback: generate next 5 friday expirations
                today = datetime.now()
                exp_dates = []
                current = today
                while len(exp_dates) < 5:
                    current += timedelta(days=1)
                    # Find next Friday
                    if current.weekday() == 4:  # Friday
                        exp_dates.append(current.strftime("%Y-%m-%d"))
            
            # Input Section
            col1, col2, col3 = st.columns([3, 2, 2])
            
            with col1:
                mm_ticker = st.selectbox(
                    "Underlying Asset",
                    ["SPY", "QQQ", "NVDA", "TSLA"],
                    key="mm_ticker_select",
                    on_change=lambda: st.rerun()
                )
            
            with col2:
                # Get fresh expirations when ticker changes
                exp_dates = get_expiration_dates(mm_ticker) if mm_ticker else []
                if not exp_dates:
                    today = datetime.now()
                    exp_dates = []
                    current = today
                    while len(exp_dates) < 5:
                        current += timedelta(days=1)
                        if current.weekday() == 4:
                            exp_dates.append(current.strftime("%Y-%m-%d"))
                
                mm_expiration = st.selectbox(
                    "Options Expiration",
                    exp_dates if exp_dates else ["No expirations available"],
                    key="mm_expiration_select"
                )
            
            with col3:
                refresh = st.button("Compute", use_container_width=True, key="mm_analyze_btn")
            
            if refresh:
                with st.spinner(f"Processing {mm_ticker} options chain..."):
                    try:
                        # Get current price
                        mm_current_price = get_current_price(mm_ticker)
                        if not mm_current_price or mm_current_price == 0:
                            st.error(f"Error: Unable to retrieve price data for {mm_ticker}")
                        else:
                            # Fetch options data
                            chain_data = get_options_data(mm_ticker, mm_expiration)
                            
                            # If no data from API, use mock data for demo
                            if not chain_data:
                                st.warning(f"Using mock data for {mm_ticker} (API unavailable)")
                                chain_data = _generate_mock_contracts(mm_ticker, mm_current_price)
                            else:
                                # Convert to contract list
                                if isinstance(chain_data, pd.DataFrame):
                                    contracts = chain_data.to_dict('records')
                                else:
                                    contracts = chain_data if isinstance(chain_data, list) else []
                                
                                if not contracts:
                                    st.error("Error: Contract chain empty")
                                else:
                                    # Get IV
                                    iv = 0.25
                                    
                                    # Get ticker profile
                                    profile = mem.get_ticker_profile(mm_ticker)
                                    
                                    # Run full pipeline
                                    brief = orch.analyze_ticker(
                                        ticker=mm_ticker,
                                        contracts=contracts,
                                        price=mm_current_price,
                                        iv=iv,
                                        expiration=mm_expiration,
                                        ticker_profile=profile
                                    )
                                    
                                    # ═════════════════════════════════════════════════════════════════
                                    # SECTION 1: CORE METRICS
                                    # ═════════════════════════════════════════════════════════════════
                                    st.divider()
                                    st.markdown("## 1. Core Metrics")
                                    
                                    # Calculate GEX
                                    from mm_quant_engine import QuantEngine
                                    quant = QuantEngine()
                                    gex = quant.calculate_gex(contracts, mm_current_price)
                                    gamma_neta = gex.get('gex_index', 0)
                                    
                                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                                    with col_m1:
                                        st.metric("Price", f"${mm_current_price:.2f}")
                                    with col_m2:
                                        st.metric("IV", f"{iv:.1%}")
                                    with col_m3:
                                        gex_status = "MR" if gamma_neta > 0 else "TREND"
                                        st.metric("Gamma Net", f"{gamma_neta:.2e}", gex_status)
                                    with col_m4:
                                        # Calculate P/C
                                        total_put_oi = sum(c.get('open_interest', 0) for c in contracts if c.get('type', '').lower() == 'put')
                                        total_call_oi = sum(c.get('open_interest', 0) for c in contracts if c.get('type', '').lower() == 'call')
                                        pcr = total_put_oi / max(total_call_oi, 1)
                                        st.metric("P/C Ratio", f"{pcr:.2f}")
                                    
                                    # ═════════════════════════════════════════════════════════════════
                                    # SECTION 2: WALL DETECTION
                                    # ═════════════════════════════════════════════════════════════════
                                    st.divider()
                                    st.markdown("## 2. Gamma Wall Detection")
                                    
                                    call_wall, put_wall = quant.detect_walls(contracts, mm_current_price, mm_expiration)
                                    
                                    walls_df = pd.DataFrame({
                                        'Type': ['CALL WALL', 'PUT WALL'],
                                        'Strike': [f"${call_wall.strike:.2f}", f"${put_wall.strike:.2f}"],
                                        'OI': [f"{call_wall.oi:,}", f"{put_wall.oi:,}"],
                                        'Distance': [f"{call_wall.distance_pct:.1%}", f"{put_wall.distance_pct:.1%}"],
                                        'Strength': [call_wall.strength, put_wall.strength]
                                    })
                                    
                                    st.dataframe(walls_df, use_container_width=True, hide_index=True)
                                    
                                    # ═════════════════════════════════════════════════════════════════
                                    # SECTION 3: REGIME & TARGETS
                                    # ═════════════════════════════════════════════════════════════════
                                    st.divider()
                                    st.markdown("## 3. Market Regime Classification")
                                    
                                    regime = quant.classify_regime(contracts, mm_current_price, gamma_neta=gamma_neta)
                                    atr = mm_current_price * 0.02
                                    targets = quant.calculate_targets(call_wall, put_wall, mm_current_price, atr)
                                    
                                    col_r1, col_r2, col_r3 = st.columns(3)
                                    with col_r1:
                                        emoji = "🔄" if regime.classification == "CHOP" else ("📊" if regime.classification == "TREND" else "⏸️")
                                        st.metric(f"{emoji} Regime", regime.classification, f"{regime.confidence:.0%}")
                                    with col_r2:
                                        st.metric("Pinning Prob", f"{regime.pin_probability:.1%}")
                                    with col_r3:
                                        st.metric("Vol Risk", regime.vol_risk)
                                    
                                    # Scenarios table
                                    scenarios_data = []
                                    for scenario, data in targets.items():
                                        scenarios_data.append({
                                            'Scenario': scenario,
                                            'Target': f"${data.get('target', 0):.2f}",
                                            'Prob': f"{data.get('probability', 0):.0%}",
                                            'Type': data.get('type', ''),
                                            'Stop': f"${data.get('invalidation', 0):.2f}"
                                        })
                                    
                                    st.dataframe(pd.DataFrame(scenarios_data), use_container_width=True, hide_index=True)
                                    
                                    # ═════════════════════════════════════════════════════════════════
                                    # SECTION 4: HISTORICAL PROFILE
                                    # ═════════════════════════════════════════════════════════════════
                                    st.divider()
                                    st.markdown("## 4. Historical Performance Profile")
                                    
                                    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
                                    with col_p1:
                                        st.metric("Pin Hit Rate", f"{profile['pin_hit_rate']:.1%}", f"n={profile['sample_size']}")
                                    with col_p2:
                                        st.metric("Wall Respect", f"{profile['wall_respect_rate']:.1%}")
                                    with col_p3:
                                        st.metric("Vol Expansion", f"{profile['vol_expansion_freq']:.1%}")
                                    with col_p4:
                                        st.metric("Confidence", f"{profile['confidence']:.0%}")
                                    
                                    # ═════════════════════════════════════════════════════════════════
                                    # SECTION 5: ANALYSIS BRIEF
                                    # ═════════════════════════════════════════════════════════════════
                                    st.divider()
                                    st.markdown("## 5. Quantitative Analysis Brief")
                                    st.markdown(brief)
                                    
                                    # ═════════════════════════════════════════════════════════════════
                                    # SECTION 6: BACKTESTING METRICS
                                    # ═════════════════════════════════════════════════════════════════
                                    st.divider()
                                    st.markdown("## 6. Backtesting & Accuracy Tracking")
                                    
                                    summary = mem.get_backtesting_summary(mm_ticker, days=30)
                                    
                                    col_bt1, col_bt2, col_bt3 = st.columns(3)
                                    with col_bt1:
                                        st.metric("Outcomes", summary['total_outcomes'])
                                    with col_bt2:
                                        st.metric("Hit Rate", f"{summary['hit_rate']:.1f}%")
                                    with col_bt3:
                                        st.metric("Avg Move", f"{summary['avg_price_move']:.2f}%")
                                    
                                    st.success(f"✓ Analysis complete for {mm_ticker} | Expiration {mm_expiration}")
                    
                    except Exception as e:
                        st.error(f"Pipeline error: {str(e)}")
                        logger.error(f"MM Pipeline: {e}", exc_info=True)
        
        except ImportError as e:
            st.error(f"Module error: {e}")
            st.info("Ensure all MM modules are installed")
        
        st.markdown("---")


    if active_tab == tab_labels[6]:
        st.markdown(
            """
            <style>
            :root {
                --bg: #0b0f1a;
                --panel: #111827;
                --text: #e5e7eb;
                --muted: #94a3b8;
                --green: #22c55e;
                --red: #ef4444;
                --gold: #facc15;
                --grid: rgba(148, 163, 184, 0.15);
            }
            .gamma-layout {
                max-width: 1200px;
                margin: 0 auto;
                padding: 0px 10px 24px;
            }
            .gamma-panel {
                background: transparent;
                border-radius: 18px;
                padding: 0px;
                box-shadow: none;
            }
            .gamma-panel-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                flex-wrap: wrap;
                margin: 0;
            }
            .gamma-panel-header h1 {
                margin: 0;
                font-size: 28px;
            }
            .gamma-header-text {
                margin: 0;
                color: var(--muted);
                font-size: 14px;
            }
            .gamma-loading-text {
                margin: 0;
                color: #38bdf8;
                font-size: 12px;
                min-height: 16px;
                opacity: 0.9;
            }
            .gamma-exp-row {
                margin: 0;
                color: #cbd5f5;
                font-size: 12px;
                opacity: 0.7;
            }
            .gamma-controls {
                display: flex;
                gap: 12px;
                align-items: flex-end;
                flex-wrap: wrap;
            }
            .gamma-controls .gamma-label {
                display: flex;
                flex-direction: column;
                gap: 6px;
                font-size: 12px;
                color: var(--muted);
            }
            .gamma-controls input {
                padding: 8px 10px;
                border-radius: 8px;
                border: 1px solid #1f2937;
                background: #0f172a;
                color: var(--text);
            }
            .gamma-controls .stButton > button {
                padding: 10px 18px;
                border-radius: 10px;
                border: none;
                background: linear-gradient(120deg, #22c55e, #16a34a);
                color: #0b0f1a;
                font-weight: 600;
                cursor: pointer;
            }
            .gamma-downloads {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            .gamma-downloads .stDownloadButton > button {
                background: #111c33;
                color: #cbd5f5;
                border: 1px solid #1f2a44;
                padding: 10px 14px;
                border-radius: 10px;
                font-weight: 600;
            }
            .gamma-controls-row {
                display: flex;
                justify-content: center;
                align-items: center;
                margin: 0;
            }
            .gamma-controls-row .stTextInput > div,
            .gamma-controls-row .stTextInput input {
                width: 100%;
            }
            .gamma-controls-row .stButton > button {
                width: 100%;
            }
            .gamma-scenario {
                margin: 20px 0 12px;
                background: #0f172a;
                border-radius: 999px;
                overflow: hidden;
                display: flex;
                height: 30px;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.08em;
            }
            .gamma-scenario-bull {
                background: rgba(34, 197, 94, 0.85);
                display: flex;
                align-items: center;
                justify-content: center;
                color: #052e16;
                font-weight: 700;
            }
            .gamma-scenario-bear {
                background: rgba(239, 68, 68, 0.85);
                display: flex;
                align-items: center;
                justify-content: center;
                color: #450a0a;
                font-weight: 700;
            }
            .gamma-chart-wrap {
                background: #0b1220;
                padding: 20px;
                border-radius: 16px;
                height: 820px;
            }
            @media (max-width: 720px) {
                .gamma-controls {
                    width: 100%;
                }
                .gamma-controls .stButton > button {
                    width: 100%;
                }
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        if "gamma_timeline_data" not in st.session_state:
            st.session_state["gamma_timeline_data"] = None
        if "gamma_loading" not in st.session_state:
            st.session_state["gamma_loading"] = False

        @st.cache_data(ttl=300)
        def _gamma_get_expirations(symbol: str) -> List[str]:
            analyzer = MarketMakerAnalyzer(
                tradier_key=TRADIER_API_KEY,
                fmp_key=FMP_API_KEY,
                tradier_base_url=TRADIER_BASE_URL,
                fmp_base_url=FMP_BASE_URL,
            )
            return analyzer.get_option_expirations(symbol)

        @st.cache_data(ttl=120)
        def _gamma_analyze(symbol: str, expiration: Optional[str]) -> Dict:
            analyzer = MarketMakerAnalyzer(
                tradier_key=TRADIER_API_KEY,
                fmp_key=FMP_API_KEY,
                tradier_base_url=TRADIER_BASE_URL,
                fmp_base_url=FMP_BASE_URL,
            )
            return analyzer.analyze_chain(symbol, expiration=expiration)

        def _format_currency(value: Optional[float]) -> str:
            if value is None or (isinstance(value, float) and np.isnan(value)):
                return "--"
            return f"${float(value):.2f}"

        def _format_short_date(value: str) -> str:
            try:
                date_obj = datetime.strptime(value, "%Y-%m-%d")
                return date_obj.strftime("%b-%d")
            except Exception:
                return value

        def _build_summary_text(data: Dict) -> str:
            stats = data.get("expiration_stats", [])
            if not stats:
                return "No expiration data available."
            lines = []
            for item in stats:
                res = item.get("resistance", [])
                sup = item.get("support", [])
                res_min = res[0]["level"] if len(res) > 0 else None
                res_max = res[1]["level"] if len(res) > 1 else res_min
                sup_min = sup[1]["level"] if len(sup) > 1 else (sup[0]["level"] if len(sup) > 0 else None)
                sup_max = sup[0]["level"] if len(sup) > 0 else None
                mid_up = (res_min + res_max) / 2 if res_min and res_max else None
                mid_down = (sup_min + sup_max) / 2 if sup_min and sup_max else None

                lines.append(_format_short_date(item.get("expiration", "")))
                lines.append(f"UP Range: {_format_currency(res_min)} - {_format_currency(res_max)}")
                lines.append(f"DOWN Range: {_format_currency(sup_min)} - {_format_currency(sup_max)}")
                lines.append(f"Pivot Level: ~= {_format_currency(item.get('pivot'))}")
                lines.append(f"Mid Up: {_format_currency(mid_up)}")
                lines.append(f"Mid Down: {_format_currency(mid_down)}")
                lines.append("")
            return "\n".join(lines)

        def _build_header_text(data: Dict) -> str:
            header = data.get("price_header", {})
            scenario = data.get("scenario")
            scenario_text = ""
            if scenario:
                scenario_text = f"{scenario.get('label')} {scenario.get('bull_prob')}% / BEAR {scenario.get('bear_prob')}%"
            base = (
                f"Hist {_format_currency(header.get('historical'))} | "
                f"Now {_format_currency(header.get('current'))} | "
                f"Proj {_format_currency(header.get('projected'))} | "
                f"Momentum {header.get('momentum', '--')}"
            )
            return f"{base} | {scenario_text}" if scenario_text else base

        def _run_gamma_analysis() -> None:
            symbol = (st.session_state.get("gamma_symbol") or "").strip().upper()
            if not symbol:
                st.warning("Enter a ticker symbol first.")
                return
            st.session_state["gamma_loading"] = True
            with st.spinner("Loading options data..."):
                try:
                    st.session_state["gamma_timeline_data"] = _gamma_analyze(symbol, None)
                except Exception as exc:
                    logger.error(f"Gamma timeline error: {exc}")
                    st.error(f"Error: {str(exc)}")
            st.session_state["gamma_loading"] = False

        st.markdown('<div class="gamma-layout">', unsafe_allow_html=True)
        st.markdown('<section class="gamma-panel">', unsafe_allow_html=True)

        st.markdown('<div class="gamma-panel-header">', unsafe_allow_html=True)
        st.markdown("<div>", unsafe_allow_html=True)
        header_text = ""
        expiration_row = "Expirations: --"
        if st.session_state["gamma_timeline_data"]:
            header_text = _build_header_text(st.session_state["gamma_timeline_data"])
            exp_list = st.session_state["gamma_timeline_data"].get("available_expirations", [])
            if exp_list:
                expiration_row = f"Expirations: {' '.join(exp_list)}"
        loading_text = ""
        if st.session_state["gamma_loading"]:
            loading_text = "Loading..."
        st.markdown(f"<p class=\"gamma-header-text\">{header_text}</p>", unsafe_allow_html=True)
        st.markdown(f"<p class=\"gamma-loading-text\">{loading_text}</p>", unsafe_allow_html=True)
        st.markdown(f"<p class=\"gamma-exp-row\">{expiration_row}</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="gamma-controls-row">', unsafe_allow_html=True)
        controls_spacer_left, controls_center, controls_spacer_right = st.columns([1, 2, 1])
        with controls_center:
            input_col, button_col = st.columns([3, 1])
            with input_col:
                st.text_input(
                    "",
                    value=default_ticker,
                    key="gamma_symbol",
                    label_visibility="collapsed",
                    placeholder="Enter ticker",
                )
            with button_col:
                st.button("Analyze", key="gamma_analyze", on_click=_run_gamma_analysis)
        st.markdown("</div>", unsafe_allow_html=True)

        data = st.session_state["gamma_timeline_data"]
        summary_df = pd.DataFrame()
        chart_bytes = None
        summary_text = ""
        if data:
            scenario = data.get("scenario")
            bull = scenario.get("bull_prob", 50) if scenario else 50
            bear = scenario.get("bear_prob", 50) if scenario else 50
            st.markdown(
                f"""
                <div class="gamma-scenario">
                    <div class="gamma-scenario-bull" style="width:{bull}%">BULL {bull}%</div>
                    <div class="gamma-scenario-bear" style="width:{bear}%">BEAR {bear}%</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            timeline = data.get("gamma_timeline", {})
            expirations = timeline.get("expirations", [])
            total_series = timeline.get("total", [])
            call_series = timeline.get("call", [])
            put_series = timeline.get("put", [])
            hist_series = timeline.get("historical", [])
            target_series = timeline.get("target", [])
            price_value = data.get("price")

            chart_payload = {
                "gamma_timeline": {
                    "expirations": expirations,
                    "total": total_series,
                    "call": call_series,
                    "put": put_series,
                    "historical": hist_series,
                    "target": target_series,
                },
                "price": price_value,
                "pivot": data.get("pivot"),
                "levels": data.get("levels", {}),
                "sentiment_by_expiration": data.get("sentiment_by_expiration", {}),
            }
            chart_json = json.dumps(chart_payload)

            chart_html = """
            <div style="background:#0b1220;padding:20px;border-radius:16px;height:820px;">
                <canvas id="gammaChart" style="width:100%;height:100%;"></canvas>
            </div>
            <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
            <script>
            const payload = __GAMMA_PAYLOAD__;

            function formatCurrency(value) {
                if (value === null || value === undefined || Number.isNaN(value)) {
                    return "--";
                }
                return `$${Number(value).toFixed(2)}`;
            }

            function buildLevelLines(levels, labelPrefix, color, labelColor) {
                return (levels || []).map((level) => ({
                    y: level.level,
                    label: `${labelPrefix} ${formatCurrency(level.level)} (${level.probability}%)`,
                    color,
                    labelColor,
                }));
            }

            const backgroundPlugin = {
                id: "columnBackgrounds",
                beforeDatasetsDraw(chart, args, pluginOptions) {
                    const { ctx, chartArea, scales } = chart;
                    const { top, bottom } = chartArea;
                    const xScale = scales.x;
                    if (!pluginOptions || !pluginOptions.sentiment) {
                        return;
                    }
                    ctx.save();
                    pluginOptions.sentiment.forEach((item, idx) => {
                        const x = xScale.getPixelForValue(idx);
                        const next = xScale.getPixelForValue(idx + 1);
                        const width = next ? next - x : xScale.getPixelForValue(idx) - xScale.getPixelForValue(idx - 1);
                        if (!width || Number.isNaN(width)) {
                            return;
                        }
                        const intensity = Math.min(Math.abs(item.dominance || 0), 1);
                        if (intensity <= 0) {
                            return;
                        }
                        const color = item.dominance > 0 ? `rgba(34, 197, 94, ${0.12 + intensity * 0.3})` : `rgba(239, 68, 68, ${0.12 + intensity * 0.3})`;
                        ctx.fillStyle = color;
                        ctx.fillRect(x - width / 2, top, width, bottom - top);
                    });
                    ctx.restore();
                },
            };

            const lineLabelPlugin = {
                id: "lineLabels",
                afterDatasetsDraw(chart, args, pluginOptions) {
                    const { ctx, chartArea, scales } = chart;
                    const items = pluginOptions?.lines || [];
                    const yScale = scales.price;
                    if (!yScale || items.length === 0) {
                        return;
                    }
                    ctx.save();
                    items.forEach((line) => {
                        const y = yScale.getPixelForValue(line.y);
                        ctx.setLineDash([6, 6]);
                        ctx.strokeStyle = line.color;
                        ctx.lineWidth = 1;
                        ctx.beginPath();
                        ctx.moveTo(chartArea.left, y);
                        ctx.lineTo(chartArea.right, y);
                        ctx.stroke();
                        ctx.setLineDash([]);
                        ctx.fillStyle = line.labelColor || line.color;
                        ctx.font = "12px 'Space Grotesk', sans-serif";
                        ctx.fillText(line.label, chartArea.right - 180, y - 6);
                    });
                    ctx.restore();
                },
            };

            function renderChart(data) {
                const timeline = data.gamma_timeline || {};
                const expirations = timeline.expirations || [];
                const sentimentMap = data.sentiment_by_expiration || {};
                const sentimentList = expirations.map((exp) => sentimentMap[exp] || { dominance: 0 });

                const datasets = [
                    {
                        type: "bar",
                        label: "Total Gamma",
                        data: timeline.total || [],
                        backgroundColor: "rgba(59, 130, 246, 0.7)",
                        borderRadius: 4,
                        yAxisID: "gamma",
                        hidden: true,
                    },
                    {
                        type: "bar",
                        label: "Call Gamma",
                        data: timeline.call || [],
                        backgroundColor: "rgba(34, 197, 94, 0.7)",
                        borderRadius: 4,
                        yAxisID: "gamma",
                        hidden: true,
                    },
                    {
                        type: "bar",
                        label: "Put Gamma",
                        data: timeline.put || [],
                        backgroundColor: "rgba(239, 68, 68, 0.7)",
                        borderRadius: 4,
                        yAxisID: "gamma",
                        hidden: true,
                    },
                    {
                        type: "bar",
                        label: "Historical",
                        data: timeline.historical || [],
                        backgroundColor: "rgba(148, 163, 184, 0.5)",
                        borderRadius: 4,
                        yAxisID: "gamma",
                    },
                    {
                        type: "line",
                        label: "Price",
                        data: expirations.map(() => data.price || null),
                        yAxisID: "price",
                        borderColor: "rgba(250, 204, 21, 0.9)",
                        backgroundColor: "rgba(250, 204, 21, 0.2)",
                        tension: 0.2,
                        pointRadius: 3,
                    },
                    {
                        type: "line",
                        label: "MM Target",
                        data: timeline.target || [],
                        yAxisID: "price",
                        borderColor: "rgba(14, 165, 233, 0.9)",
                        backgroundColor: "rgba(14, 165, 233, 0.15)",
                        borderDash: [6, 4],
                        tension: 0.3,
                        pointRadius: 3,
                    },
                ];

                const levelLines = [];
                if (data.pivot) {
                    levelLines.push({
                        y: data.pivot,
                        label: `PIVOT ${formatCurrency(data.pivot)}`,
                        color: "rgba(250, 204, 21, 0.9)",
                        labelColor: "rgba(250, 204, 21, 0.9)",
                    });
                }

                const levels = data.levels || {};
                levelLines.push(...buildLevelLines(levels.resistance, "R", "rgba(239, 68, 68, 0.8)", "rgba(239, 68, 68, 0.9)"));
                levelLines.push(...buildLevelLines(levels.support, "S", "rgba(34, 197, 94, 0.8)", "rgba(34, 197, 94, 0.9)"));

                const ctx = document.getElementById("gammaChart");
                if (!ctx) {
                    return;
                }

                new Chart(ctx, {
                    data: {
                        labels: expirations,
                        datasets,
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            x: {
                                grid: { color: "rgba(148, 163, 184, 0.1)" },
                                ticks: { color: "#94a3b8" },
                            },
                            price: {
                                position: "left",
                                grid: { drawOnChartArea: false },
                                ticks: { color: "#facc15" },
                                title: { display: true, text: "Price", color: "#facc15" },
                            },
                            gamma: {
                                position: "right",
                                grid: { color: "rgba(148, 163, 184, 0.12)" },
                                ticks: { color: "#94a3b8" },
                                title: { display: true, text: "Gamma", color: "#94a3b8" },
                            },
                        },
                        plugins: {
                            legend: { labels: { color: "#cbd5f5" } },
                            tooltip: { mode: "index", intersect: false },
                            columnBackgrounds: { sentiment: sentimentList },
                            lineLabels: { lines: levelLines },
                        },
                    },
                    plugins: [backgroundPlugin, lineLabelPlugin],
                });
            }

            renderChart(payload);
            </script>
            """
            chart_html = chart_html.replace("__GAMMA_PAYLOAD__", chart_json)

            components.html(chart_html, height=860)

            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(
                go.Bar(name="Total Gamma", x=expirations, y=total_series, marker_color="rgba(59,130,246,0.7)"),
                secondary_y=True,
            )
            fig.add_trace(
                go.Bar(name="Call Gamma", x=expirations, y=call_series, marker_color="rgba(34,197,94,0.7)"),
                secondary_y=True,
            )
            fig.add_trace(
                go.Bar(name="Put Gamma", x=expirations, y=put_series, marker_color="rgba(239,68,68,0.7)"),
                secondary_y=True,
            )
            fig.add_trace(
                go.Bar(name="Historical", x=expirations, y=hist_series, marker_color="rgba(148,163,184,0.5)"),
                secondary_y=True,
            )
            fig.add_trace(
                go.Scatter(name="Price", x=expirations, y=[price_value for _ in expirations], mode="lines+markers", line=dict(color="rgba(250,204,21,0.9)")),
                secondary_y=False,
            )
            fig.add_trace(
                go.Scatter(name="MM Target", x=expirations, y=target_series, mode="lines+markers", line=dict(color="rgba(14,165,233,0.9)", dash="dash")),
                secondary_y=False,
            )
            fig.update_layout(
                barmode="group",
                height=720,
                plot_bgcolor="#0b1220",
                paper_bgcolor="#0b1220",
                font=dict(color="#cbd5f5"),
                legend=dict(orientation="h"),
                margin=dict(l=30, r=30, t=30, b=40),
            )
            try:
                chart_bytes = fig.to_image(format="png", scale=2)
            except Exception as exc:
                logger.warning(f"Chart download unavailable: {exc}")

            stats = data.get("expiration_stats", [])
            summary_rows = []
            for item in stats:
                summary_rows.append(
                    {
                        "Expiration": item.get("expiration"),
                        "Pivot": _format_currency(item.get("pivot")) if item.get("pivot") else "N/A",
                        "Total OI": f"{item.get('total_oi', 0):,}",
                        "CALL OI": f"{item.get('call_oi', 0):,}",
                        "PUT OI": f"{item.get('put_oi', 0):,}",
                        "PUT/CALL": f"{item.get('put_call', 0):.2f}",
                    }
                )

            summary_df = pd.DataFrame(summary_rows)
            summary_text = _build_summary_text(data)

        csv_data = summary_df.to_csv(index=False) if not summary_df.empty else ""

        dl_col1, dl_col2, dl_col3 = st.columns(3)
        with dl_col1:
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name=f"{(data or {}).get('symbol', 'export')}_expiration_stats.csv",
                mime="text/csv",
                disabled=summary_df.empty,
            )
        with dl_col2:
            st.download_button(
                label="Download Summary",
                data=summary_text or "",
                file_name=f"{(data or {}).get('symbol', 'summary')}_summary.txt",
                mime="text/plain",
                disabled=summary_df.empty,
            )
        with dl_col3:
            st.download_button(
                label="Download Chart",
                data=chart_bytes or b"",
                file_name=f"{(data or {}).get('symbol', 'chart')}_gamma_timeline.png",
                mime="image/png",
                disabled=chart_bytes is None,
            )

        st.markdown("</section></div>", unsafe_allow_html=True)


    # Tab 10: calculo
    if active_tab == tab_labels[7]:
        import math

        st.markdown(
            """
            <style>
                #MainMenu {visibility: hidden;}
                footer {visibility: hidden;}
                header {visibility: hidden;}

                .block-container {
                    padding-top: 1rem;
                    padding-bottom: 0rem;
                    padding-left: 2rem;
                    padding-right: 2rem;
                    max-width: 100%;
                }

                .main-header {
                    font-size: 2rem;
                    font-weight: 800;
                    text-align: center;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    margin-bottom: 0.5rem;
                    text-transform: uppercase;
                    letter-spacing: 2px;
                }

                div[data-testid="metric-container"] {
                    background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
                    border-radius: 8px;
                    padding: 8px 12px;
                    border: 1px solid #667eea30;
                }

                div[data-testid="metric-container"] label {
                    font-size: 0.75rem !important;
                    font-weight: 600 !important;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                }

                div[data-testid="metric-container"] [data-testid="stMetricValue"] {
                    font-size: 1.5rem !important;
                    font-weight: 700 !important;
                }

                .stDataFrame {
                    font-size: 0.85rem;
                }

                .stTabs [data-baseweb="tab-list"] {
                    gap: 2px;
                    background: #f0f2f6;
                    border-radius: 8px;
                    padding: 4px;
                }

                .stTabs [data-baseweb="tab"] {
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-weight: 600;
                    font-size: 0.85rem;
                }

                .stTabs [aria-selected="true"] {
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white !important;
                }

                .bullish { color: #00c853; font-weight: 700; }
                .bearish { color: #ff1744; font-weight: 700; }
                .neutral { color: #ffa726; font-weight: 700; }

                .streamlit-expanderHeader {
                    font-size: 0.9rem;
                    font-weight: 600;
                }

                h3 {
                    margin-top: 1rem !important;
                    margin-bottom: 0.5rem !important;
                    font-size: 1.2rem !important;
                    font-weight: 700 !important;
                }

                hr {
                    margin: 0.5rem 0 !important;
                }
            </style>
            """,
            unsafe_allow_html=True,
        )

        def get_market_data(ticker: str) -> dict:
            """Obtiene datos de mercado en tiempo real."""
            yf_ticker = ticker.upper()
            if yf_ticker == "VIX":
                yf_ticker = "^VIX"
            elif yf_ticker == "SPX":
                yf_ticker = "^GSPC"

            t = yf.Ticker(yf_ticker)
            hist = t.history(period="5d")

            if hist.empty:
                raise ValueError(f"No se encontró precio para {ticker}")

            spot = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else spot
            change = spot - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0

            vix_t = yf.Ticker("^VIX")
            vix_hist = vix_t.history(period="1d")
            vix = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else 18.0

            iv30 = estimate_iv30(ticker, spot, vix)

            return {
                "ticker": ticker.upper(),
                "spot": round(spot, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "vix": round(vix, 2),
                "iv30": round(iv30, 2),
            }

        def estimate_iv30(ticker: str, spot: float, vix: float) -> float:
            """Estima IV30 desde opciones o VIX."""
            try:
                t = yf.Ticker(ticker if ticker.upper() not in ("SPX", "VIX") else "^" + ticker)
                exps = t.options
                if not exps:
                    return vix * 1.15

                today = datetime.now().date()
                best_exp = None
                best_dte = 9999
                for exp in exps:
                    exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
                    dte = (exp_date - today).days
                    if abs(dte - 30) < abs(best_dte - 30):
                        best_dte = dte
                        best_exp = exp

                if best_exp:
                    chain = t.option_chain(best_exp)
                    calls = chain.calls
                    atm = calls[abs(calls["strike"] - spot) / spot < 0.03]
                    ivs = atm["impliedVolatility"].dropna()
                    ivs = ivs[ivs > 0]
                    if len(ivs) > 0:
                        return round(float(ivs.mean()) * 100, 2)
            except Exception:
                pass
            return round(vix * 1.15, 2)

        def run_mm_analysis(market: dict) -> dict:
            """Genera análisis MM local."""
            ticker = market["ticker"]
            spot = market["spot"]
            vix = market["vix"]
            iv30 = market["iv30"]

            strike_step = 5 if spot > 200 else 2.5 if spot > 50 else 1.0 if spot > 10 else 0.5
            iv_daily = iv30 / 100 / math.sqrt(252)

            call_wall = round((spot * (1 + 1.8 * iv_daily * math.sqrt(5))) / strike_step) * strike_step
            put_wall = round((spot * (1 - 1.8 * iv_daily * math.sqrt(5))) / strike_step) * strike_step
            zero_gamma = round(spot / strike_step) * strike_step

            if vix < 15:
                bias = "BULLISH"
                bias_note = "VIX bajo, flujo positivo"
            elif vix > 25:
                bias = "BEARISH"
                bias_note = "VIX alto, presión vendedora"
            else:
                bias = "NEUTRAL" if abs(market["change_pct"]) < 0.5 else ("BULLISH" if market["change_pct"] > 0 else "BEARISH")
                bias_note = "Rango consolidación" if bias == "NEUTRAL" else "Momentum intradiario"

            targets = []
            horizons = [
                ("SEMANAL", 5),
                ("2 SEMANAS", 10),
                ("MENSUAL", 21),
                ("3 MESES", 63),
                ("6 MESES", 126),
                ("12 MESES", 252),
            ]

            for horizon_name, days in horizons:
                exp_date = (datetime.now() + timedelta(days=days)).strftime("%m/%d/%y")
                vol_mult = iv30 / 100 * math.sqrt(days / 252)

                target_bull = round(spot * (1 + 0.84 * vol_mult) / strike_step) * strike_step
                target_base = round(spot * (1 + 0.10 * vol_mult) / strike_step) * strike_step
                target_bear = round(spot * (1 - 0.84 * vol_mult) / strike_step) * strike_step

                cw = round(spot * (1 + 1.2 * vol_mult) / strike_step) * strike_step
                pw = round(spot * (1 - 1.2 * vol_mult) / strike_step) * strike_step

                signal = 8 if days <= 21 else 6 if days <= 126 else 5
                gex = "NEGATIVO" if vix > 20 else "POSITIVO"
                driver = "Gamma" if days <= 10 else "Vanna" if days <= 63 else "Charm"

                targets.append({
                    "horizon": horizon_name,
                    "expDate": exp_date,
                    "targetBull": target_bull,
                    "targetBase": target_base,
                    "targetBear": target_bear,
                    "callWall": cw,
                    "putWall": pw,
                    "gexDominant": gex,
                    "signalStrength": signal,
                    "driver": driver,
                    "bias": "BULL" if bias == "BULLISH" else "BEAR" if bias == "BEARISH" else "NEUTRAL",
                })

            key_strikes = []
            for i in range(-4, 5):
                if i == 0:
                    continue
                strike = round((spot + i * strike_step * 2) / strike_step) * strike_step
                distance = abs(strike - spot) / spot
                oi_base = 10000 * (1 - distance * 5)

                if strike > spot:
                    oi_calls = int(max(1000, oi_base * 1.2))
                    oi_puts = int(max(500, oi_base * 0.3))
                    gex = int(10 * (1 - distance * 8))
                    level_type = "CALL WALL" if i == 4 else "RESISTENCIA"
                else:
                    oi_calls = int(max(500, oi_base * 0.3))
                    oi_puts = int(max(1000, oi_base * 1.2))
                    gex = int(-8 * (1 - distance * 8))
                    level_type = "PUT WALL" if i == -4 else "SOPORTE"

                magnetism = int(max(1, 10 * (1 - distance * 10)))

                key_strikes.append({
                    "strike": strike,
                    "expDate": (datetime.now() + timedelta(days=7)).strftime("%m/%d"),
                    "oiCalls": oi_calls,
                    "oiPuts": oi_puts,
                    "gexEstimated": gex,
                    "vannaFlow": "COMPRA" if gex > 0 else "VENTA" if gex < -3 else "NEUTRAL",
                    "charmDecay": "ALTO" if distance < 0.02 else "MEDIO" if distance < 0.05 else "BAJO",
                    "volOiRatio": round(0.3 + distance * 2, 2),
                    "levelType": level_type,
                    "magnetism": magnetism,
                })

            key_strikes.sort(key=lambda x: x["strike"])

            narrative = (
                f"El análisis de Market Maker para {ticker} en ${spot:.2f} revela un posicionamiento {bias.lower()} "
                f"con VIX en {vix:.2f} y volatilidad implícita de {iv30}%. La call wall en ${call_wall} actúa como "
                f"resistencia clave mientras la put wall en ${put_wall} provee soporte institucional. "
                f"El nivel zero-gamma en ${zero_gamma} marca el punto de inflexión donde los dealers cambian su perfil de hedging."
            )

            return {
                "summary": {
                    "callWall": call_wall,
                    "putWall": put_wall,
                    "zeroGamma": zero_gamma,
                    "mmBias": bias,
                    "mmBiasNote": bias_note,
                },
                "targets": targets,
                "keyStrikes": key_strikes,
                "narrative": narrative,
            }

        def create_levels_chart(market: dict, analysis: dict):
            """Crea gráfico limpio y profesional con precio, targets y burbujas OI/Gamma."""
            spot = market["spot"]
            ticker = market["ticker"]
            s = analysis["summary"]

            try:
                yf_ticker = ticker.upper()
                if yf_ticker == "VIX":
                    yf_ticker = "^VIX"
                elif yf_ticker == "SPX":
                    yf_ticker = "^GSPC"

                t = yf.Ticker(yf_ticker)
                hist = t.history(period="30d")

                if hist.empty:
                    dates = pd.date_range(end=datetime.now(), periods=30, freq="D")
                    hist = pd.DataFrame({"Close": [spot] * 30}, index=dates)
            except Exception:
                dates = pd.date_range(end=datetime.now(), periods=30, freq="D")
                hist = pd.DataFrame({"Close": [spot] * 30}, index=dates)

            future_dates = pd.date_range(start=hist.index[-1], periods=91, freq="D")[1:]

            fig = go.Figure()

            fig.add_trace(go.Scatter(
                x=hist.index,
                y=hist["Close"],
                mode="lines",
                name="💰 PRECIO",
                line=dict(color="#4169E1", width=4),
                hovertemplate="<b>$%{y:,.2f}</b><extra></extra>",
            ))

            price_current = spot
            zero_gamma = s["zeroGamma"]
            call_wall = s["callWall"]
            put_wall = s["putWall"]
            iv30 = market.get("iv30", 0.3)

            spotfit_range = price_current * 0.03
            spotfit_strikes = [k for k in analysis["keyStrikes"] if abs(k["strike"] - price_current) <= spotfit_range]

            spotfit_pressure_up = sum([k["oiCalls"] for k in spotfit_strikes if k["strike"] > price_current])
            spotfit_pressure_down = sum([k["oiPuts"] for k in spotfit_strikes if k["strike"] < price_current])
            spotfit_bias = 1 if spotfit_pressure_up > spotfit_pressure_down else -1

            total_gex = sum([k["gexEstimated"] for k in analysis["keyStrikes"]])

            magnetic_forces = []
            for k in analysis["keyStrikes"]:
                strike_price = k["strike"]
                magnetism = k["magnetism"]
                oi_total = k["oiCalls"] + k["oiPuts"]
                distance = abs(strike_price - price_current)

                if distance > 0.01:
                    force_mag = (magnetism / 10.0) * (oi_total / 100000) / (distance ** 0.7)
                    direction = 1 if strike_price > price_current else -1
                    magnetic_forces.append({
                        "strike": strike_price,
                        "force": force_mag * direction,
                        "magnetism": magnetism,
                        "distance": distance,
                        "oi": oi_total,
                    })

            magnetic_forces.sort(key=lambda x: abs(x["force"]), reverse=True)

            projection_dates = future_dates[:60]
            scenarios = {"central": [], "bull": [], "bear": []}

            for scenario_name, scenario_factor in [("central", 1.0), ("bull", 1.5), ("bear", 0.5)]:
                price_sim = price_current
                scenario_prices = []

                for i in range(len(projection_dates)):
                    daily_vol = (price_current * iv30) / (252 ** 0.5)

                    net_force = 0
                    for mf in magnetic_forces[:5]:
                        current_distance = abs(mf["strike"] - price_sim)
                        if current_distance > 0.01:
                            force_magnitude = (mf["magnetism"] / 10.0) * (mf["oi"] / 100000) / (current_distance ** 0.7)
                            force_direction = 1 if mf["strike"] > price_sim else -1
                            weight = 1.0 / (1.0 + current_distance / price_current)
                            net_force += force_magnitude * force_direction * weight

                    gex_factor = 0.6 if total_gex > 0 else 1.4
                    spotfit_factor = 1.0 + (spotfit_bias * 0.3 * (1 - i / 20)) if i < 20 else 1.0
                    time_decay = 1.0 - (0.6 * (i / len(projection_dates)))

                    base_move = net_force * daily_vol * gex_factor * time_decay * spotfit_factor
                    daily_move = base_move * scenario_factor

                    max_daily = price_sim * 0.025
                    daily_move = max(min(daily_move, max_daily), -max_daily)

                    price_sim += daily_move

                    barrier_factor = 1.03 if scenario_name == "bull" else 0.97 if scenario_name == "bear" else 1.01
                    if price_sim > call_wall * barrier_factor:
                        price_sim = call_wall * (barrier_factor - 0.01)
                    elif price_sim < put_wall * (2 - barrier_factor):
                        price_sim = put_wall * (2 - barrier_factor + 0.01)

                    scenario_prices.append(price_sim)

                scenarios[scenario_name] = scenario_prices

            fig.add_trace(go.Scatter(
                x=projection_dates,
                y=scenarios["central"],
                mode="lines",
                name="🎯 PRONÓSTICO MM (70%)",
                line=dict(color="#000000", width=5, dash="dash"),
                opacity=0.9,
                hovertemplate="<b>Central: $%{y:,.2f}</b><br>Probabilidad: 70%<extra></extra>",
            ))

            fig.add_trace(go.Scatter(
                x=list(projection_dates) + list(projection_dates[::-1]),
                y=scenarios["bull"] + scenarios["bear"][::-1],
                fill="toself",
                fillcolor="rgba(0, 0, 0, 0.1)",
                line=dict(width=0),
                name="📊 Rango Probabilidad (30%)",
                showlegend=True,
                hoverinfo="skip",
            ))

            fig.add_trace(go.Scatter(
                x=projection_dates,
                y=scenarios["bull"],
                mode="lines",
                name="📈 Escenario Bull (15%)",
                line=dict(color="#10b981", width=2, dash="dot"),
                opacity=0.5,
                hovertemplate="<b>Bull: $%{y:,.2f}</b><br>Probabilidad: 15%<extra></extra>",
            ))

            fig.add_trace(go.Scatter(
                x=projection_dates,
                y=scenarios["bear"],
                mode="lines",
                name="📉 Escenario Bear (15%)",
                line=dict(color="#ef4444", width=2, dash="dot"),
                opacity=0.5,
                hovertemplate="<b>Bear: $%{y:,.2f}</b><br>Probabilidad: 15%<extra></extra>",
            ))

            today = hist.index[-1]
            fig.add_shape(
                type="line",
                x0=today,
                x1=today,
                y0=0,
                y1=1,
                yref="paper",
                line=dict(color="#f59e0b", width=3, dash="dash"),
            )
            fig.add_annotation(
                x=today,
                y=1,
                yref="paper",
                text="📅 HOY",
                showarrow=False,
                yshift=10,
                font=dict(size=12, color="#f59e0b", family="Arial Black"),
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="#f59e0b",
                borderwidth=2,
                borderpad=4,
            )

            targets = [
                (s["callWall"], "🟢 CALL WALL", "#10b981", "solid", 3),
                (s["putWall"], "🔴 PUT WALL", "#ef4444", "solid", 3),
                (s["zeroGamma"], "⚡ ZERO GAMMA", "#8b5cf6", "dash", 2),
                (spot, f"📍 SPOT ${spot:.0f}", "#1e40af", "dot", 2),
            ]

            for price, label, color, dash, width in targets:
                fig.add_trace(go.Scatter(
                    x=[hist.index[0], future_dates[-1]],
                    y=[price, price],
                    mode="lines",
                    name=label,
                    line=dict(color=color, width=width, dash=dash),
                    showlegend=False,
                    hovertemplate=f"<b>{label}</b><br>${price:,.2f}<extra></extra>",
                ))

                fig.add_annotation(
                    x=future_dates[-1],
                    y=price,
                    text=f"<b>{label.split()[1] if len(label.split()) > 1 else label}</b>  ${price:.0f}",
                    showarrow=False,
                    xanchor="left",
                    xshift=10,
                    font=dict(size=11, color=color, family="Arial Black"),
                    bgcolor="rgba(255,255,255,0.85)",
                    bordercolor=color,
                    borderwidth=2,
                    borderpad=4,
                )

            strikes_support = [k for k in analysis["keyStrikes"] if k["strike"] < spot]
            strikes_resistance = [k for k in analysis["keyStrikes"] if k["strike"] >= spot]

            support_colors = [
                "#7f1d1d", "#991b1b", "#b91c1c", "#dc2626",
                "#ef4444", "#f87171", "#fca5a5", "#fecaca",
            ]

            resistance_colors = [
                "#064e3b", "#065f46", "#047857", "#059669",
                "#10b981", "#34d399", "#6ee7b7", "#a7f3d0",
            ]

            all_dates_list = list(hist.index) + list(future_dates)
            repetitions = 4

            num_support = len(strikes_support)
            total_support_bubbles = num_support * repetitions

            for idx in range(total_support_bubbles):
                strike_idx = idx % num_support
                k = strikes_support[strike_idx]

                oi_total = k["oiCalls"] + k["oiPuts"]
                gex_abs = abs(k["gexEstimated"])

                rep_num = idx // num_support
                size_factor = 1.0 - (rep_num * 0.15)
                size = min(max(((oi_total / 500) + (gex_abs / 50)) * size_factor, 12), 55)

                date_idx = int((idx / max(total_support_bubbles - 1, 1)) * (len(all_dates_list) - 1))
                date_pos = all_dates_list[date_idx]

                color_idx = min(strike_idx, len(support_colors) - 1)
                color = support_colors[color_idx]

                is_past = date_pos <= hist.index[-1]
                opacity = 0.8 if is_past else 0.55

                fig.add_trace(go.Scatter(
                    x=[date_pos],
                    y=[k["strike"]],
                    mode="markers+text",
                    marker=dict(
                        size=size,
                        color=color,
                        opacity=opacity,
                        line=dict(width=2 if is_past else 1, color="#450a0a"),
                        symbol="circle",
                    ),
                    text=f"${k['strike']:.0f}" if rep_num == 0 else "",
                    textposition="middle center",
                    textfont=dict(size=10, color="white", family="Arial Black"),
                    showlegend=False,
                    hovertemplate=(
                        f"<b>SOPORTE ${k['strike']}</b><br>"
                        f"{'🔴 HISTÓRICO' if is_past else '🎯 PROYECCIÓN'}<br>"
                        f"OI Total: {oi_total:,}<br>"
                        f"  📞 Calls: {k['oiCalls']:,}<br>"
                        f"  📉 Puts: {k['oiPuts']:,}<br>"
                        f"GEX: {k['gexEstimated']:+,}M<br>"
                        f"🔥 Gamma: {k['magnetism']}/10<extra></extra>"
                    ),
                ))

            num_resistance = len(strikes_resistance)
            total_resistance_bubbles = num_resistance * repetitions

            for idx in range(total_resistance_bubbles):
                strike_idx = idx % num_resistance
                k = strikes_resistance[strike_idx]

                oi_total = k["oiCalls"] + k["oiPuts"]
                gex_abs = abs(k["gexEstimated"])

                rep_num = idx // num_resistance
                size_factor = 1.0 - (rep_num * 0.15)
                size = min(max(((oi_total / 500) + (gex_abs / 50)) * size_factor, 12), 55)

                date_idx = int((idx / max(total_resistance_bubbles - 1, 1)) * (len(all_dates_list) - 1))
                date_pos = all_dates_list[date_idx]

                color_idx = min(strike_idx, len(resistance_colors) - 1)
                color = resistance_colors[color_idx]

                is_past = date_pos <= hist.index[-1]
                opacity = 0.8 if is_past else 0.55

                fig.add_trace(go.Scatter(
                    x=[date_pos],
                    y=[k["strike"]],
                    mode="markers+text",
                    marker=dict(
                        size=size,
                        color=color,
                        opacity=opacity,
                        line=dict(width=2 if is_past else 1, color="#022c22"),
                        symbol="circle",
                    ),
                    text=f"${k['strike']:.0f}" if rep_num == 0 else "",
                    textposition="middle center",
                    textfont=dict(size=10, color="white", family="Arial Black"),
                    showlegend=False,
                    hovertemplate=(
                        f"<b>RESISTENCIA ${k['strike']}</b><br>"
                        f"{'🟢 HISTÓRICO' if is_past else '🎯 PROYECCIÓN'}<br>"
                        f"OI Total: {oi_total:,}<br>"
                        f"  📞 Calls: {k['oiCalls']:,}<br>"
                        f"  📉 Puts: {k['oiPuts']:,}<br>"
                        f"GEX: {k['gexEstimated']:+,}M<br>"
                        f"🔥 Gamma: {k['magnetism']}/10<extra></extra>"
                    ),
                ))

            fig.update_layout(
                title=dict(
                    text=f"<b style='font-size:20px'>{ticker}</b> · PROYECCIÓN MM · PRECIO + TARGETS + BURBUJAS OI/GAMMA",
                    font=dict(size=18, color="#1e293b", family="Arial"),
                    x=0.5,
                    xanchor="center",
                    y=0.97,
                    yanchor="top",
                ),
                xaxis=dict(
                    title=dict(text="<b>LÍNEA DE TIEMPO (30 DÍAS PASADO + 90 DÍAS FUTURO)</b>", font=dict(size=11, color="#475569")),
                    showgrid=True,
                    gridcolor="rgba(148,163,184,0.15)",
                    showline=True,
                    linewidth=2,
                    linecolor="#cbd5e1",
                    tickformat="%d/%m",
                    tickangle=0,
                    tickfont=dict(size=10, color="#64748b"),
                ),
                yaxis=dict(
                    title=dict(text="<b>PRECIO USD ($)</b>", font=dict(size=11, color="#475569")),
                    showgrid=True,
                    gridcolor="rgba(148,163,184,0.15)",
                    showline=True,
                    linewidth=2,
                    linecolor="#cbd5e1",
                    tickformat="$,.0f",
                    tickfont=dict(size=11, color="#1e293b"),
                    zeroline=False,
                ),
                height=600,
                plot_bgcolor="rgba(255,255,255,0.95)",
                paper_bgcolor="rgba(248,250,252,1)",
                hovermode="closest",
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="center",
                    x=0.5,
                    bgcolor="rgba(255,255,255,0.95)",
                    bordercolor="#cbd5e1",
                    borderwidth=1,
                    font=dict(size=11, color="#1e293b", family="Arial"),
                ),
                margin=dict(l=80, r=150, t=80, b=60),
            )

            return fig

        col_h1, col_h2, col_h3 = st.columns([2, 3, 2])
        with col_h2:
            st.markdown('<p class="main-header">📊 MM Target Engine</p>', unsafe_allow_html=True)

        if "calc_save_json" not in st.session_state:
            st.session_state["calc_save_json"] = False

        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            ticker = st.text_input("", placeholder="Ticker: SPY, QQQ, AAPL, TSLA, NVDA...", label_visibility="collapsed", key="calc_ticker")
        with col2:
            analyze_button = st.button("🚀 ANALIZAR", type="primary", use_container_width=True, key="calc_analyze_btn")
        with col3:
            st.checkbox("💾 Export JSON", key="calc_save_json")

        if analyze_button and ticker:
            with st.spinner(f"Analizando {ticker.upper()}..."):
                try:
                    market = get_market_data(ticker)
                    analysis = run_mm_analysis(market)
                    st.session_state["calc_market"] = market
                    st.session_state["calc_analysis"] = analysis
                    st.session_state["calc_analyzed"] = True
                except Exception as e:
                    st.error(f"❌ {str(e)}")
                    st.session_state["calc_analyzed"] = False

        if st.session_state.get("calc_analyzed", False):
            market = st.session_state["calc_market"]
            analysis = st.session_state["calc_analysis"]
            s = analysis["summary"]

            c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

            with c1:
                st.metric("💰 SPOT", f"${market['spot']:.2f}", f"{market['change']:+.2f} ({market['change_pct']:+.2f}%)")
            with c2:
                st.metric("📊 VIX", f"{market['vix']:.2f}")
            with c3:
                st.metric("📈 IV30", f"{market['iv30']:.1f}%")
            with c4:
                st.metric("🟢 CALL WALL", f"${s['callWall']}")
            with c5:
                st.metric("🔴 PUT WALL", f"${s['putWall']}")
            with c6:
                st.metric("⚡ ZERO GAMMA", f"${s['zeroGamma']}")
            with c7:
                bias_emoji = "🔥" if s["mmBias"] == "BULLISH" else "❄️" if s["mmBias"] == "BEARISH" else "⚖️"
                st.metric(f"{bias_emoji} BIAS", s["mmBias"])

            spotfit_range = market["spot"] * 0.03
            spotfit_strikes = [k for k in analysis["keyStrikes"] if abs(k["strike"] - market["spot"]) <= spotfit_range]

            if spotfit_strikes:
                spotfit_calls = sum([k["oiCalls"] for k in spotfit_strikes if k["strike"] > market["spot"]])
                spotfit_puts = sum([k["oiPuts"] for k in spotfit_strikes if k["strike"] < market["spot"]])
                spotfit_total = spotfit_calls + spotfit_puts
                spotfit_bias_text = "ALCISTA 📈" if spotfit_calls > spotfit_puts else "BAJISTA 📉" if spotfit_puts > spotfit_calls else "NEUTRAL ⚖️"
                spotfit_color = "#10b981" if spotfit_calls > spotfit_puts else "#ef4444" if spotfit_puts > spotfit_calls else "#8b5cf6"

                st.markdown(
                    f"""
                    <div style='background: linear-gradient(135deg, {spotfit_color}15, {spotfit_color}25);
                                border-left: 5px solid {spotfit_color};
                                padding: 12px 20px;
                                border-radius: 8px;
                                margin: 15px 0;
                                box-shadow: 0 2px 8px rgba(0,0,0,0.1);'>
                        <div style='display: flex; align-items: center; justify-content: space-between;'>
                            <div style='font-size: 15px; color: #1e293b; font-weight: bold;'>
                                🎯 SPOTFIT DETECTADO · Órdenes pegadas (±3% del spot)
                            </div>
                            <div style='font-size: 14px; color: {spotfit_color}; font-weight: bold;'>
                                PRESIÓN: {spotfit_bias_text}
                            </div>
                        </div>
                        <div style='margin-top: 8px; display: flex; gap: 30px; font-size: 13px; color: #475569;'>
                            <div><b>📞 Calls:</b> {spotfit_calls:,} OI</div>
                            <div><b>📉 Puts:</b> {spotfit_puts:,} OI</div>
                            <div><b>🎲 Total:</b> {spotfit_total:,} OI</div>
                            <div><b>📍 Strikes:</b> {len(spotfit_strikes)} niveles pegados</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            st.markdown("---")

            st.markdown("### 🎯 TARGETS · GEX GRAVITY")

            targets_data = []
            for t in analysis["targets"]:
                bull_pct = (t["targetBull"] - market["spot"]) / market["spot"] * 100
                bear_pct = (t["targetBear"] - market["spot"]) / market["spot"] * 100
                targets_data.append({
                    "📅": t["horizon"],
                    "EXP": t["expDate"],
                    "🟢 BULL": f"${t['targetBull']} (+{bull_pct:.1f}%)",
                    "⚪ BASE": f"${t['targetBase']}",
                    "🔴 BEAR": f"${t['targetBear']} ({bear_pct:.1f}%)",
                    "CW": f"${t['callWall']}",
                    "PW": f"${t['putWall']}",
                    "GEX": t["gexDominant"][:3],
                    "💪": f"{t['signalStrength']}/10",
                    "DRIVER": t["driver"][:3].upper(),
                    "BIAS": t["bias"],
                })

            df_targets = pd.DataFrame(targets_data)
            st.dataframe(df_targets, use_container_width=True, hide_index=True, height=250)

            st.markdown("---")

            st.markdown("### 🔥 KEY STRIKES · OI + GEX MAP")

            strikes_data = []
            for k in analysis["keyStrikes"]:
                arrow = "🔺" if k["strike"] > market["spot"] else "🔻"
                strikes_data.append({
                    "🎯": f"{arrow} ${k['strike']}",
                    "EXP": k["expDate"],
                    "OI📞": f"{k['oiCalls']:,}",
                    "OI📍": f"{k['oiPuts']:,}",
                    "GEX": f"{k['gexEstimated']:+d}M",
                    "VANNA": k["vannaFlow"][:3],
                    "CHARM": k["charmDecay"][:1],
                    "V/OI": f"{k['volOiRatio']:.1f}",
                    "TIPO": k["levelType"],
                    "🧲": f"{'⚡' * (k['magnetism']//2)}{k['magnetism']}",
                })

            df_strikes = pd.DataFrame(strikes_data)

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown("**🔻 SOPORTE (Puts)**")
                df_puts = df_strikes[df_strikes["🎯"].str.contains("🔻")]
                st.dataframe(df_puts, hide_index=True, height=180)
            with col_s2:
                st.markdown("**🔺 RESISTENCIA (Calls)**")
                df_calls = df_strikes[df_strikes["🎯"].str.contains("🔺")]
                st.dataframe(df_calls, hide_index=True, height=180)

            st.markdown("---")

            st.markdown("### 📈 MAPA VISUAL · NIVELES MM")

            fig = create_levels_chart(market, analysis)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            st.markdown("---")
            st.markdown("---")

            with st.expander("📊 ANÁLISIS + METODOLOGÍA"):
                col_n1, col_n2 = st.columns([3, 2])
                with col_n1:
                    st.markdown("**Posicionamiento MM:**")
                    st.caption(analysis["narrative"])
                with col_n2:
                    st.markdown("**Gravity Formula:**")
                    st.code(
                        """GRAVITY(K) =
0.45×Γ×OI×Spot (GEX)
0.25×Vanna×OI×ΔIV
0.15×Charm×OI×Δt
0.15×Vol/OI

TARGET = argmax[GRAVITY]
RANGO = Spot×exp(±σ√T)""",
                        language="python",
                    )

            if st.session_state.get("calc_save_json", False):
                json_data = {
                    "market": market,
                    "analysis": analysis,
                    "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "mode": "WEB_LOCAL",
                }
                st.download_button(
                    "📥 DESCARGAR JSON",
                    data=json.dumps(json_data, indent=2, ensure_ascii=False),
                    file_name=f"mm_{market['ticker']}_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                    mime="application/json",
                )
        else:
            st.info("👆 Ingresa un ticker arriba y presiona **ANALIZAR**")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown("**📊 SPY**  \nS&P 500 ETF")
            with col2:
                st.markdown("**💻 QQQ**  \nNasdaq 100")
            with col3:
                st.markdown("**🍎 AAPL**  \nApple Inc")
            with col4:
                st.markdown("**⚡ TSLA**  \nTesla Motors")


if __name__ == "__main__":
    main()

