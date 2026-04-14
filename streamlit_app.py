import streamlit as st
import requests
from bs4 import BeautifulSoup
import json
import time
from pathlib import Path
from requests.exceptions import RequestException

# --- Page Configuration ---
st.set_page_config(
    page_title="CBSE 10th Tracker 2026", 
    page_icon="🎓", 
    layout="centered"
)

# --- Constants ---
MUST_HAVE = ["2026", "class x", "result"]
MUST_NOT = ["xii", "re-evaluation", "compartment", "supplementary"]

# Check both the results portal and the main website
TARGET_URLS = [
    "https://cbseresults.nic.in/",
    "https://cbse.nic.in/"
]

# --- Firebase Cloud Messaging Configuration ---
DEFAULT_FIREBASE_CONFIG = {
    "apiKey": "",
    "authDomain": "",
    "projectId": "",
    "storageBucket": "",
    "messagingSenderId": "",
    "appId": "",
    "measurementId": ""
}

DEFAULT_FCM_VAPID_KEY = ""

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


def load_toml_file(path):
    if not path.exists():
        return None
    if tomllib is None:
        return None
    with path.open('rb') as f:
        return tomllib.load(f)


def load_firebase_config():
    firebase_config = DEFAULT_FIREBASE_CONFIG.copy()
    vapid_key = DEFAULT_FCM_VAPID_KEY

    # 1) Streamlit secrets
    if hasattr(st, 'secrets'):
        firebase_secrets = st.secrets.get('firebase') if isinstance(st.secrets, dict) else st.secrets.get('firebase')
        if firebase_secrets:
            firebase_config.update(firebase_secrets)
        vapid_key = st.secrets.get('fcm_vapid_key', vapid_key)

    # 2) .streamlit/secrets.toml
    if tomllib is not None:
        secrets_path = Path(__file__).resolve().parent / '.streamlit' / 'secrets.toml'
        secrets_toml = load_toml_file(secrets_path)
        if secrets_toml and 'firebase' in secrets_toml:
            firebase_config.update(secrets_toml['firebase'])
        if secrets_toml and 'fcm_vapid_key' in secrets_toml:
            vapid_key = secrets_toml['fcm_vapid_key']

        # 3) config.toml or settings.toml
        config = load_toml_file(Path(__file__).resolve().parent / 'config.toml') or load_toml_file(Path(__file__).resolve().parent / 'settings.toml')
        if config and 'firebase' in config:
            firebase_config.update(config['firebase'])
        if config and 'fcm_vapid_key' in config:
            vapid_key = config['fcm_vapid_key']

    return firebase_config, vapid_key


FIREBASE_CONFIG, FCM_VAPID_KEY = load_firebase_config()

# --- Core Logic ---
def check_cbse_results() -> dict | str | None:
    """
    Scrapes official CBSE portals for Class 10 result links.
    Returns a dictionary with link info, 'error' on total failure, or None.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    
    success_flags = 0
    
    for url in TARGET_URLS:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            success_flags += 1
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all('a')
            for link in links:
                text = link.get_text().strip().lower()
                if all(k in text for k in MUST_HAVE) and not any(x in text for x in MUST_NOT):
                    href = link.get('href', '')
                    # Resolve relative URLs
                    full_url = href if href.startswith('http') else f"{url.rstrip('/')}/{href.lstrip('/')}"
                    return {"text": link.get_text().strip(), "url": full_url}
        
        except RequestException:
            # Silently continue to the next URL if one fails
            continue
            
    # If all URLs resulted in a RequestException, return an error state
    if success_flags == 0:
        return "error"
        
    return None

# --- Firebase Cloud Messaging Helper ---
def render_fcm_registration_widget(firebase_config: dict, vapid_key: str) -> None:
    if not firebase_config or not vapid_key:
        st.error("FCM is not configured yet. Add Firebase settings to Streamlit secrets or update FIREBASE_CONFIG and FCM_VAPID_KEY.")
        return

    firebase_config_json = json.dumps(firebase_config)
    js_template = """
        <div id="fcm-widget">
            <div id="fcm-status">FCM status: not registered.</div>
            <div id="fcm-token" style="word-break: break-all; margin-top: 12px;">Token: none</div>
            <button id="register-fcm" style="margin-top: 12px; width: 100%; padding: 10px;">Register FCM for background notifications</button>
        </div>
        <script src="https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js"></script>
        <script>
        const firebaseConfig = @@FIREBASE_CONFIG@@;
        const vapidKey = @@VAPID_KEY@@;

        const swCode = `importScripts('https://www.gstatic.com/firebasejs/9.22.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.22.1/firebase-messaging-compat.js');

firebase.initializeApp(@@FIREBASE_CONFIG@@);
const messaging = firebase.messaging();

messaging.onBackgroundMessage(function(payload) {{
  const notificationTitle = payload.notification?.title || 'CBSE Alert';
  const notificationOptions = {{
    body: payload.notification?.body || '',
    icon: payload.notification?.icon || ''
  }};
  self.registration.showNotification(notificationTitle, notificationOptions);
}});`;

        const registerServiceWorker = async () => {{
            if (!('serviceWorker' in navigator)) {{
                document.getElementById('fcm-status').innerText = 'FCM status: Service Worker not supported in this browser.';
                return;
            }}
            try {{
                const blob = new Blob([swCode], {{ type: 'application/javascript' }});
                const swUrl = URL.createObjectURL(blob);
                const registration = await navigator.serviceWorker.register(swUrl);
                document.getElementById('fcm-status').innerText = 'FCM status: service worker registered.';
                await initializeFirebaseMessaging(registration);
            }} catch (error) {{
                document.getElementById('fcm-status').innerText = 'FCM status: registration failed.';
                console.error(error);
            }}
        }};

        const initializeFirebaseMessaging = async (registration) => {{
            firebase.initializeApp(firebaseConfig);
            const messaging = firebase.messaging();
            try {{
                await Notification.requestPermission();
                const token = await messaging.getToken({{ vapidKey: vapidKey, serviceWorkerRegistration: registration }});
                document.getElementById('fcm-status').innerText = 'FCM status: registered and token acquired.';
                document.getElementById('fcm-token').innerText = 'Token: ' + token;
            }} catch (error) {{
                document.getElementById('fcm-status').innerText = 'FCM status: token request failed.';
                console.error(error);
            }}
        }};

        document.getElementById('register-fcm').addEventListener('click', registerServiceWorker);
        </script>
    """
    html = js_template.replace('@@FIREBASE_CONFIG@@', firebase_config_json).replace('@@VAPID_KEY@@', json.dumps(vapid_key))
    st.components.v1.html(html, height=260)

# --- User Interface ---
ADMIN_USERNAME = "What@1313867688"
ADMIN_PASSWORD = "MS-AI"

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'show_login' not in st.session_state:
    st.session_state.show_login = False

st.title("🎓 CBSE Class 10 Result Tracker")
st.markdown("Professionally monitoring official CBSE portals for the 2026 result link.")
st.markdown(
    """
    <style>
        button[disabled], input[disabled], div.stSlider > div[class*='css'] {
            opacity: 0.45 !important;
            cursor: not-allowed !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

auth_enabled = st.session_state.authenticated
if 'tracking' not in st.session_state:
    st.session_state.tracking = True

if not auth_enabled and st.session_state.show_login:
    st.warning("Admin login required. Enter your username and password to enable controls.")
    with st.form(key="login_form"):
        username = st.text_input("Username", placeholder="Enter admin username")
        password = st.text_input("Password", type="password", placeholder="Enter admin password")
        submit = st.form_submit_button("🔐 Login")

    if submit:
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.session_state.tracking = True
            st.session_state.show_login = False
            st.rerun()
        else:
            st.error("Invalid credentials. Only admin may use this tracker.")

def prompt_login():
    st.session_state.show_login = True

# Sidebar Controls
with st.sidebar:
    st.header("⚙️ Tracker Settings")
    refresh_rate = st.slider(
        "Refresh Interval (seconds)",
        min_value=60,
        max_value=300,
        value=300,
        step=30,
        disabled=not auth_enabled,
        help="Admin only: adjust this after login.",
    )
    st.caption("⚠️ Refresh interval defaults to 5 minutes and can be adjusted after login.")

    if auth_enabled:
        render_fcm_registration_widget(FIREBASE_CONFIG, FCM_VAPID_KEY)
    else:
        if st.button("Login to enable notifications", use_container_width=True, on_click=prompt_login):
            pass
        st.caption("Click any control to login as admin.")

    st.divider()

    if auth_enabled:
        if st.button("🔓 Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.tracking = True
            st.rerun()
    else:
        if st.button("Login to control tracker", use_container_width=True, on_click=prompt_login):
            pass

    st.divider()

    # Toggle Tracking State
    is_tracking = st.session_state.get('tracking', False)
    button_label = "🛑 Pause Tracker" if is_tracking else "▶️ Start Tracker"
    if auth_enabled:
        if st.button(button_label, use_container_width=True):
            st.session_state.tracking = not is_tracking
            st.rerun()
    else:
        if st.button("Login to start/pause tracker", use_container_width=True, on_click=prompt_login):
            pass

status_placeholder = st.empty()

# --- Execution Loop ---
if st.session_state.tracking:
    result = check_cbse_results()
    
    with status_placeholder.container():
        if result == "error":
            st.error(f"⚠️ Connection error at {time.strftime('%I:%M:%S %p')}. Retrying next cycle...")
        elif result is None:
            st.info(f"🔄 Last checked: **{time.strftime('%I:%M:%S %p')}** - No results found yet.")
            st.progress(0, text=f"Sleeping for {refresh_rate} seconds...")
        else:
            # Result Found!
            st.session_state.tracking = False  # Auto-stop tracker
            st.balloons()
            st.success("🔥 **RESULTS ARE LIVE!**")
            st.markdown(f"**Detected Link Text:** `{result['text']}`")
            st.link_button("👉 CLICK HERE TO OPEN RESULTS", result['url'], type="primary")
            
            # Inject working audio alert (Mixkit Free CDN)
            audio_html = """
                <audio autoplay loop>
                    <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
                </audio>
            """
            st.components.v1.html(audio_html, height=0)
            st.stop()
            
    # Streamlit native wait mechanism
    time.sleep(refresh_rate)
    st.rerun()

else:
    with status_placeholder.container():
        st.warning("Tracker is currently **paused**. Click 'Start Tracker' in the sidebar to begin monitoring.")