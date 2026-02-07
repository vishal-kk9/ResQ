import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import pandas as pd
import time
import json
import os
import random
from streamlit_geolocation import streamlit_geolocation # New Library

# ================== CONFIGURATION ==================
# This reads the key from the secure cloud settings (Fixes the 403 Error)
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    # If running locally without secrets.toml, put your NEW key here temporarily
    API_KEY = "YOUR_NEW_KEY_HERE" 

genai.configure(api_key=API_KEY)

# 🛠️ MODEL SELECTOR
@st.cache_resource
def get_model():
    return genai.GenerativeModel("gemini-pro")

model = get_model()

# ================== 🧠 SHARED REAL-TIME MEMORY ==================
@st.cache_resource
class SharedSystemState:
    def __init__(self):
        # Default: San Francisco (Overwritten if GPS is used)
        self.base_lat = 37.7749
        self.base_lon = -122.4194
        self.gps_locked = False
        
        self.hospitals = {
            "City General Trauma": {"specialty": "Level 1 Trauma", "dist": 5, "icu_beds": 2, "op_beds": 15, "lat": 37.7749, "lon": -122.4194},
            "Metropolitan Heart": {"specialty": "Cardiology Center", "dist": 12, "icu_beds": 8, "op_beds": 5, "lat": 37.7849, "lon": -122.4094},
            "Suburban Clinic": {"specialty": "General Care", "dist": 3, "icu_beds": 0, "op_beds": 20, "lat": 37.7649, "lon": -122.4294}
        }
        self.mission = {
            "status": "IDLE", 
            "target_hospital": None,
            "patient_data": None,
            "ai_analysis": None,
            "live_vitals": {"bp": "120/80", "hr": 80, "spo2": 98},
            "telemetry_alert": "Stable",
            "ambulance_loc": {"lat": 37.7600, "lon": -122.4200} 
        }
        self.declined_hospitals = []

    def update_beds(self, hospital_name, ward_type):
        if ward_type == "ICU":
            self.hospitals[hospital_name]["icu_beds"] -= 1
        else:
            self.hospitals[hospital_name]["op_beds"] -= 1
            
    # Relocate hospitals to be near the user's real GPS
    def relocate_hospitals(self, user_lat, user_lon):
        if not self.gps_locked:
            self.base_lat = user_lat
            self.base_lon = user_lon
            # Move hospitals to random spots around the user (approx 2-5km away)
            offsets = [(0.02, 0.01), (-0.02, -0.02), (0.01, -0.03)]
            keys = list(self.hospitals.keys())
            for i, key in enumerate(keys):
                self.hospitals[key]["lat"] = user_lat + offsets[i][0]
                self.hospitals[key]["lon"] = user_lon + offsets[i][1]
            self.gps_locked = True

system = SharedSystemState()

# ================== LOCAL SESSION STATE ==================
if "analysis_result" not in st.session_state: st.session_state.analysis_result = None

# ================== MOCK EMR DATA ==================
emr_database = {
    "P-101": {"name": "Alex Mercer", "age": 58, "blood": "O+", "history": "Hypertension", "allergies": "Penicillin"},
    "P-102": {"name": "Sarah Connor", "age": 34, "blood": "A+", "history": "Asthma", "allergies": "None"}
}

# ================== APP SETUP ==================
st.set_page_config(page_title="ResQ | Medicare App", page_icon="🚑", layout="wide")

st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 2.2rem; }
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("resq_logo.jpeg"):
        st.image("resq_logo.jpeg", use_container_width=True)
    else:
        st.markdown("## ResQ Medicare")

    st.divider()
    st.header("📡 SYSTEM STATUS")
    
    # --- 🛰️ GPS STATUS ---
    if system.gps_locked:
        st.success("🟢 GPS SIGNAL: LOCKED")
        st.caption(f"Lat: {system.base_lat:.4f}, Lon: {system.base_lon:.4f}")
    else:
        st.warning("🟠 GPS: SEARCHING...")
    
    st.divider()
    page = st.radio("SELECT INTERFACE", ["🚑 EMS UNIT (AMBULANCE)", "🏥 MEDICAL COMMAND (HOSPITAL)"])

# ================== LOGIC ==================
def find_best_hospital(required_ward):
    eligible = []
    for name, data in system.hospitals.items():
        if required_ward == "ICU" and data["icu_beds"] > 0: eligible.append((name, data))
        elif required_ward == "OP" and data["op_beds"] > 0: eligible.append((name, data))
    return sorted(eligible, key=lambda x: x[1]['dist'])

# ================== PAGE 1: AMBULANCE COMMAND ==================
if page == "🚑 EMS UNIT (AMBULANCE)":

    # --- STATE 1: WAITING ---
    if system.mission["status"] == "PENDING":
        st.title("🚑 TRANSFER REQUEST INITIATED")
        st.markdown(f"### ⏳ AWAITING ADMISSION AUTH: {system.mission['target_hospital'].upper()}")
        st.info("Medical Command Center notified. Standby for handshake protocol.")
        
        with st.spinner("Establishing secure telemetry link..."):
            time.sleep(2) 
            st.rerun()

    # --- STATE 2: ACTIVE (EN ROUTE) ---
    elif system.mission["status"] == "ACTIVE":
        dest_name = system.mission['target_hospital']
        dest_data = system.hospitals[dest_name]
        
        st.markdown(f"# 🚑 CODE 3 TRANSPORT: {dest_name.upper()}")
        st.success("✅ ADMISSION AUTHORIZED - UNIT MOBILIZED")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("ETA", "8 Mins")
        c2.metric("RANGE", f"{dest_data['dist']} km")
        c3.metric("STATUS", "EN ROUTE")

        # --- 🗺️ LIVE GPS MAP ---
        st.subheader("📍 LIVE GPS TRACKING")
        map_data = pd.DataFrame([
            {"lat": system.mission["ambulance_loc"]["lat"], "lon": system.mission["ambulance_loc"]["lon"], "type": "🚑 AMBULANCE", "size": 20, "color": "#ff0000"}, 
            {"lat": dest_data['lat'], "lon": dest_data['lon'], "type": "🏥 HOSPITAL", "size": 20, "color": "#00ff00"} 
        ])
        st.map(map_data, latitude="lat", longitude="lon", size="size", color="color", zoom=13)

        st.divider()
        st.subheader("📡 LIVE PATIENT TELEMETRY")
        
        vc1, vc2, vc3, vc4 = st.columns(4)
        with vc1:
            new_bp = st.text_input("BP (mmHg)", value=system.mission["live_vitals"]["bp"])
        with vc2:
            new_hr = st.number_input("Heart Rate (BPM)", value=system.mission["live_vitals"]["hr"])
        with vc3:
            new_spo2 = st.number_input("SpO2 (%)", value=system.mission["live_vitals"]["spo2"])
        with vc4:
            st.write("") 
            st.write("") 
            if st.button("📡 TRANSMIT & RE-EVALUATE"):
                system.mission["live_vitals"] = {"bp": new_bp, "hr": new_hr, "spo2": new_spo2}
                with st.spinner("AI Analyzing New Vitals..."):
                    prompt = f"""
                    Patient Re-evaluation. Previous Status: {system.mission['ai_analysis']['reason']}
                    NEW VITALS: BP {new_bp}, HR {new_hr}, SpO2 {new_spo2}.
                    Task: Provide a 1-sentence status update for the receiving doctor.
                    """
                    try:
                        resp = model.generate_content(prompt)
                        system.mission["telemetry_alert"] = resp.text
                        st.toast("✅ Vitals & Analysis Sent to Hospital", icon="📡")
                        st.rerun()
                    except:
                        st.error("AI Re-evaluation failed.")
        
        if system.mission["telemetry_alert"] != "Stable":
             st.info(f"**AI LIVE MONITOR:** {system.mission['telemetry_alert']}")

        st.divider()
        if st.button("✅ TRANSFER COMPLETE: HANDOVER VERIFIED", type="primary"):
            system.mission["status"] = "IDLE"
            system.declined_hospitals = [] 
            st.session_state.analysis_result = None
            st.rerun()

    # --- STATE 3: DECLINED ---
    elif system.mission["status"] == "DECLINED":
        st.title("❌ ADMISSION DENIED: DIVERSION REQUIRED")
        st.error(f"{system.mission['target_hospital']} reports ZERO CAPACITY. Initiate Diversion Protocol.")
        if st.button("🔄 INITIATE DIVERSION (SELECT ALTERNATE)", type="primary"):
            system.mission["status"] = "IDLE"
            st.rerun()

    # --- STATE 4: TRIAGE ---
    else:
        st.title("🚑 ResQ PRE-HOSPITAL ASSESSMENT")
        
        # --- 🛰️ GEOLOCATION BUTTON ---
        col_gps, col_info = st.columns([1, 2])
        with col_gps:
            st.caption("📍 ACQUIRE SATELLITE FIX")
            location = streamlit_geolocation()
            
            # If GPS found, update system coordinates
            if location and location['latitude'] is not None:
                if not system.gps_locked:
                    system.relocate_hospitals(location['latitude'], location['longitude'])
                    system.mission["ambulance_loc"] = {"lat": location['latitude'], "lon": location['longitude']}
                    st.rerun()
        
        with col_info:
            if system.gps_locked:
                 st.success(f"✅ LOCATION CONFIRMED: {system.base_lat:.4f}, {system.base_lon:.4f}")
            else:
                 st.info("⚠️ Using Default Triangulation (San Francisco). Click above for Real GPS.")

        st.divider()
        c1, c2 = st.columns([1, 2])
        with c1:
            pid = st.text_input("SCAN PATIENT ID / QR (Optional)", placeholder="Enter ID if available")
        with c2:
            if pid:
                patient = emr_database.get(pid, {})
                if patient:
                    st.success(f"**EHR FOUND:** {patient['name']} (Age: {patient['age']})")
                    st.caption(f"Hx: {patient['history']} | Allergies: {patient['allergies']}")
                else:
                    st.warning("Patient ID not found in Local Database.")
                    patient = None
            else:
                patient = None

        st.divider()
        st.subheader("📊 VITAL SIGNS MONITOR")
        v1, v2, v3 = st.columns(3)
        with v1: bp_input = st.text_input("Blood Pressure", placeholder="120/80")
        with v2: hr_input = st.number_input("Heart Rate (BPM)", value=0)
        with v3: spo2_input = st.number_input("SpO2 (%)", value=0)
            
        st.divider()
        notes = st.text_area("🎙️ CLINICAL NOTES / OBSERVATIONS", height=100, placeholder="e.g., Diaphoresis, chest pain radiating to left arm...")
        
        col_act, col_upl = st.columns([1,1])
        with col_upl:
            st.file_uploader("📸 UPLOAD TRAUMA IMAGING", type=["jpg", "png"], label_visibility="collapsed")
        with col_act:
            analyze_btn = st.button("⚡ EXECUTE CLINICAL DIAGNOSTICS", type="primary")

        if analyze_btn:
            if not notes:
                st.toast("⚠️ Input Error: Clinical notes required.")
            else:
                system.declined_hospitals = []
                patient_data_str = str(patient) if patient else "UNIDENTIFIED PATIENT / UNKNOWN HISTORY"
                system.mission["live_vitals"] = {
                    "bp": bp_input if bp_input else "N/A",
                    "hr": hr_input if hr_input > 0 else "N/A",
                    "spo2": spo2_input if spo2_input > 0 else "N/A"
                }

                with st.spinner("🤖 PROCESSING BIOMETRICS..."):
                    prompt = f"""
                    Act as an Expert Trauma Triage AI.
                    Patient Data: {patient_data_str}
                    Vitals: BP {bp_input}, HR {hr_input}, SpO2 {spo2_input}
                    Clinical Notes: {notes}
                    Task: Severity Score (1-10), Ward Need (ICU/OP), Assessment (40 words).
                    Return strict JSON: {{ "severity": int, "ward_need": "str", "reason": "str" }}
                    """
                    try:
                        safe = {HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
                        response = model.generate_content(prompt, safety_settings=safe)
                        clean = response.text.replace("```json", "").replace("```", "").strip()
                        st.session_state.analysis_result = json.loads(clean)
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI ERROR: {e}")

        # --- RESULTS ---
        if st.session_state.analysis_result:
            r = st.session_state.analysis_result
            st.divider()
            st.markdown("### 🤖 CLINICAL ACUITY REPORT")
            c1, c2 = st.columns([1, 2])
            sev = r['severity']
            color = "red" if sev > 7 else "orange" if sev > 4 else "green"
            with c1:
                st.markdown(f"**SEVERITY INDEX**: :{color}[**{sev}/10**]")
                st.metric("REQUIRED UNIT", r['ward_need'])
            with c2:
                st.info(f"**AI ASSESSMENT:**\n\n{r['reason']}", icon="🩺")
            
            st.markdown("### 🏥 AVAILABLE FACILITIES (NEARBY)")
            hospitals = find_best_hospital(r["ward_need"])
            
            # --- 🗺️ SHOW HOSPITALS ON MAP (RELATIVE TO USER) ---
            map_pts = []
            map_pts.append({"lat": system.mission["ambulance_loc"]["lat"], "lon": system.mission["ambulance_loc"]["lon"], "color": "#ff0000", "size": 20})
            for name, data in hospitals:
                 map_pts.append({"lat": data["lat"], "lon": data["lon"], "color": "#0000ff", "size": 15})
            st.map(pd.DataFrame(map_pts), color="color", size="size", zoom=12)

            if not hospitals: st.error("🚨 CRITICAL: NO CAPACITY IN NETWORK")
            
            for name, data in hospitals:
                with st.container():
                    col_det, col_btn = st.columns([3, 1])
                    with col_det:
                        st.markdown(f"**{name}**")
                        st.caption(f"🚗 {data['dist']}km | {r['ward_need']} Capacity: {data['icu_beds'] if r['ward_need']=='ICU' else data['op_beds']}")
                    with col_btn:
                        if name in system.declined_hospitals:
                            st.button(f"⛔ REFUSED", key=name, disabled=True)
                        else:
                            if st.button(f"🚑 REQUEST ADMISSION", key=name):
                                system.mission["status"] = "PENDING"
                                system.mission["target_hospital"] = name
                                system.mission["patient_data"] = patient if patient else {"name": "Unidentified", "age": "Unknown"}
                                system.mission["ai_analysis"] = r
                                st.rerun()
                    st.divider()

# ================== PAGE 2: HOSPITAL OPS ==================
else:
    st.title("🏥 MEDICAL COMMAND CENTER")
    
    if system.mission["status"] == "ACTIVE":
        st.success(f"🚑 ACTIVE INBOUND: {system.mission['patient_data']['name'].upper()}")
        st.subheader("📍 INBOUND UNIT TRACKING")
        target_hosp = system.mission["target_hospital"]
        h_data = system.hospitals[target_hosp]
        map_data = pd.DataFrame([
            {"lat": system.mission["ambulance_loc"]["lat"], "lon": system.mission["ambulance_loc"]["lon"], "type": "🚑 UNIT", "size": 20, "color": "#ff0000"}, 
            {"lat": h_data['lat'], "lon": h_data['lon'], "type": "🏥 HOSPITAL", "size": 20, "color": "#00ff00"} 
        ])
        st.map(map_data, latitude="lat", longitude="lon", size="size", color="color", zoom=13)

        st.subheader("📡 LIVE VITALS")
        if system.mission.get("telemetry_alert") and system.mission["telemetry_alert"] != "Stable":
             st.warning(f"**🔔 UPDATE FROM UNIT:** {system.mission['telemetry_alert']}")

        vitals = system.mission["live_vitals"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("BP", vitals['bp'])
        m2.metric("HR", f"{vitals['hr']} bpm", delta_color="inverse")
        m3.metric("SpO2", f"{vitals['spo2']}%")
        m4.metric("Severity", f"{system.mission['ai_analysis']['severity']}/10")
        st.divider()

    elif system.mission["status"] == "PENDING":
        st.error("🚨 INCOMING PRIORITY TRANSFER REQUEST")
        alert = system.mission
        patient = alert["patient_data"]
        analysis = alert["ai_analysis"]
        target = alert["target_hospital"]
        vitals = alert.get("live_vitals", {"bp": "N/A", "hr": "N/A", "spo2": "N/A"})

        st.markdown(f"### 🚑 Unit Requesting Admission to: **{target}**")
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Patient:** {patient['name']} ({patient['age']})")
            st.info(f"**Clinical Indication:**\n{analysis['reason']}") 
        with c2:
            st.metric("Acuity Score", f"{analysis['severity']}/10")
            st.caption(f"Initial Vitals: BP {vitals['bp']} | HR {vitals['hr']} | SpO2 {vitals['spo2']}")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("✅ AUTHORIZE ADMISSION", type="primary", use_container_width=True):
                system.update_beds(target, analysis["ward_need"])
                system.mission["status"] = "ACTIVE"
                st.rerun()
        with b2:
            if st.button("❌ DIVERT (CAPACITY FULL)", use_container_width=True):
                system.declined_hospitals.append(target)
                system.mission["status"] = "DECLINED"
                st.rerun()
        st.divider()

    st.caption("Live Bed Census & Transport Tracking")
    total_icu = sum(h["icu_beds"] for h in system.hospitals.values())
    total_op = sum(h["op_beds"] for h in system.hospitals.values())
    m1, m2, m3 = st.columns(3)
    m1.metric("ICU Capacity", total_icu)
    m2.metric("General Capacity", total_op)
    m3.metric("Active Inbound", "1" if system.mission["status"] != "IDLE" else "0")

    st.subheader("📊 Network Census Board")
    table = []
    for h, d in system.hospitals.items():
        table.append({"Facility Name": h, "ICU Vacancy": d["icu_beds"], "Gen Ward Vacancy": d["op_beds"], "Specialty": d["specialty"]})
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
