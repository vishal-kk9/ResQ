import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import pandas as pd
import time
import json
import os
import re
import random
from streamlit_geolocation import streamlit_geolocation
import requests
from geopy.distance import geodesic

# ================== CONFIGURATION ==================
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    try:
        API_KEY = st.secrets["GEMINI_API_KEY"]
    except Exception:
        API_KEY = "YOUR_NEW_KEY_HERE"

genai.configure(api_key=API_KEY)

# ================== 🛠️ MODEL SELECTOR ==================
# Priority order: newest free Flash models first, then reliable fallbacks.
FREE_MODEL_PRIORITY = [
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.0-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-flash",
]

@st.cache_resource
def get_model():
    for model_name in FREE_MODEL_PRIORITY:
        try:
            m = genai.GenerativeModel(model_name)
            m.generate_content("ping")
            return m, model_name
        except Exception:
            continue
    fallback = "gemini-1.5-flash"
    return genai.GenerativeModel(fallback), fallback

model, active_model_name = get_model()

# ================== 🧠 SHARED REAL-TIME MEMORY ==================
# FIX: @st.cache_resource must decorate a *function*, not a class directly.
class SharedSystemState:
    def __init__(self):
        self.base_lat = 11.0168
        self.base_lon = 76.9558
        self.gps_locked = False

        # Default Mock Hospitals (Fallback)
        self.hospitals = {
            "City General Trauma": {
                "specialty": "Level 1 Trauma",
                "dist": 5.2,
                "icu_beds": 2,
                "op_beds": 15,
                "lat": 11.0200,
                "lon": 76.9600,
            },
            "Metropolitan Heart": {
                "specialty": "Cardiology Center",
                "dist": 8.5,
                "icu_beds": 8,
                "op_beds": 5,
                "lat": 11.0300,
                "lon": 76.9700,
            },
        }

        self.mission = {
            "status": "IDLE",
            "target_hospital": None,
            "patient_data": None,
            "ai_analysis": None,
            "live_vitals": {"bp": "120/80", "hr": 80, "spo2": 98},
            "telemetry_alert": "Stable",
            "ambulance_loc": {"lat": 11.0168, "lon": 76.9558},
        }
        self.declined_hospitals = []

    def update_beds(self, hospital_name, ward_type):
        if hospital_name not in self.hospitals:
            return
        if ward_type == "ICU":
            self.hospitals[hospital_name]["icu_beds"] = max(
                0, self.hospitals[hospital_name]["icu_beds"] - 1
            )
        else:
            self.hospitals[hospital_name]["op_beds"] = max(
                0, self.hospitals[hospital_name]["op_beds"] - 1
            )

    # 🌍 REAL-WORLD HOSPITAL FETCHING
    def fetch_real_hospitals(self, lat, lon):
        url = "https://overpass-api.de/api/interpreter"
        query = f"""
            [out:json];
            node["amenity"="hospital"](<around:10000, {lat}, {lon}>);
            out 5;
        """
        headers = {
            'User-Agent': 'ResQMedicareApp/1.0 (visha.medical@gmail.com)'
        }
        try:
            response = requests.post(url, data={'data': query}, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                new_hospitals = {}
                for node in data.get("elements", []):
                    name = node.get("tags", {}).get("name", "Unknown Medical Center")
                    h_lat = float(node["lat"])
                    h_lon = float(node["lon"])
                    dist = round(geodesic((lat, lon), (h_lat, h_lon)).km, 1)

                    new_hospitals[name] = {
                        "specialty": "General / Emergency",
                        "dist": dist,
                        "icu_beds": random.randint(0, 5),
                        "op_beds": random.randint(5, 20),
                        "lat": h_lat,
                        "lon": h_lon,
                    }

                if new_hospitals:
                    self.hospitals = new_hospitals
                    self.base_lat = lat
                    self.base_lon = lon
                    self.gps_locked = True
                    return True
        except Exception:
            pass
        return False


@st.cache_resource
def get_system_v2():
    return SharedSystemState()


system = get_system_v2()

# ================== LOCAL SESSION STATE ==================
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "gps_fetch_attempted" not in st.session_state:
    st.session_state.gps_fetch_attempted = False

# ================== MOCK EMR DATA ==================
emr_database = {
    "P-101": {
        "name": "Alex Mercer",
        "age": 58,
        "blood": "O+",
        "history": "Hypertension",
        "allergies": "Penicillin",
    },
    "P-102": {
        "name": "Sarah Connor",
        "age": 34,
        "blood": "A+",
        "history": "Asthma",
        "allergies": "None",
    },
}

# ================== APP SETUP ==================
st.set_page_config(page_title="ResQ | Medicare App", page_icon="🚑", layout="wide")

st.markdown(
    """
<style>
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 2.2rem; }
</style>
""",
    unsafe_allow_html=True,
)

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists("resq_logo.jpeg"):
        st.image("resq_logo.jpeg", use_container_width=True)
    else:
        st.markdown("## ResQ Medicare")

    st.divider()
    st.header("📡 SYSTEM STATUS")

    if system.gps_locked:
        st.success("🌍 REAL-WORLD DATA: ACTIVE")
    else:
        st.warning("⚠️ MODE: SIMULATION")

    st.caption(f"🤖 AI ENGINE: `{active_model_name}`")

    st.divider()
    page = st.radio(
        "SELECT INTERFACE",
        ["🚑 EMS UNIT (AMBULANCE)", "🏥 MEDICAL COMMAND (HOSPITAL)"],
    )


# ================== HELPERS ==================
def safe_int(val):
    try:
        return int(val)
    except Exception:
        return 0


def extract_json(text: str) -> dict:
    """
    Robustly extract a JSON object from an AI response that may contain
    markdown code fences, extra prose, or both.
    """
    # Strip common markdown code fences
    text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    # Try a direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to regex: grab the first {...} block
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract valid JSON from AI response:\n{text}")


def find_best_hospital(required_ward):
    eligible = []
    for name, data in system.hospitals.items():
        if name in system.declined_hospitals:
            continue
        if required_ward == "ICU" and data["icu_beds"] > 0:
            eligible.append((name, data))
        elif required_ward == "OP" and data["op_beds"] > 0:
            eligible.append((name, data))
    return sorted(eligible, key=lambda x: x[1]["dist"])


# ================== PAGE 1: AMBULANCE COMMAND ==================
if page == "🚑 EMS UNIT (AMBULANCE)":

    # 1. ACTIVE — NAVIGATION MODE
    if system.mission["status"] == "ACTIVE":
        dest_name = system.mission["target_hospital"]

        if dest_name and dest_name in system.hospitals:
            dest_data = system.hospitals[dest_name]
        else:
            dest_data = list(system.hospitals.values())[0]
            dest_name = list(system.hospitals.keys())[0]

        st.markdown(f"# 🚑 EN ROUTE TO: {dest_name}")
        st.success("✅ ADMISSION AUTHORIZED - UNIT MOBILIZED")

        c1, c2, c3 = st.columns(3)
        c1.metric("ETA", "8 Mins")
        c2.metric("RANGE", f"{dest_data['dist']} km")
        c3.metric("STATUS", "EN ROUTE")

        st.subheader("📍 LIVE GPS TRACKING")
        map_data = pd.DataFrame(
            [
                {
                    "lat": system.mission["ambulance_loc"]["lat"],
                    "lon": system.mission["ambulance_loc"]["lon"],
                    "type": "🚑 AMBULANCE",
                    "size": 20,
                    "color": "#ff0000",
                },
                {
                    "lat": dest_data["lat"],
                    "lon": dest_data["lon"],
                    "type": "🏥 HOSPITAL",
                    "size": 20,
                    "color": "#00ff00",
                },
            ]
        )
        st.map(
            map_data,
            latitude="lat",
            longitude="lon",
            size="size",
            color="color",
            zoom=13,
        )

        st.divider()
        st.subheader("📡 LIVE PATIENT TELEMETRY")

        vc1, vc2, vc3, vc4 = st.columns(4)
        with vc1:
            new_bp = st.text_input("BP (mmHg)", value=system.mission["live_vitals"]["bp"])
        with vc2:
            new_hr = st.number_input(
                "Heart Rate (BPM)", value=safe_int(system.mission["live_vitals"]["hr"])
            )
        with vc3:
            new_spo2 = st.number_input(
                "SpO2 (%)", value=safe_int(system.mission["live_vitals"]["spo2"])
            )
        with vc4:
            st.write("")
            st.write("")
            if st.button("📡 TRANSMIT & RE-EVALUATE"):
                system.mission["live_vitals"] = {
                    "bp": new_bp,
                    "hr": new_hr,
                    "spo2": new_spo2,
                }
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
                    except Exception as e:
                        st.error(f"AI Re-evaluation failed: {e}")

        if (
            system.mission["telemetry_alert"]
            and system.mission["telemetry_alert"] != "Stable"
        ):
            st.info(f"**AI LIVE MONITOR:** {system.mission['telemetry_alert']}")

        st.divider()
        if st.button(
            "✅ TRANSFER COMPLETE: HANDOVER VERIFIED", type="primary"
        ):
            system.mission["status"] = "IDLE"
            system.declined_hospitals = []
            st.session_state.analysis_result = None
            st.session_state.gps_fetch_attempted = False
            st.rerun()

    # 2. PENDING — WAITING FOR HOSPITAL RESPONSE
    elif system.mission["status"] == "PENDING":
        st.title("🚑 TRANSFER REQUEST INITIATED")
        st.markdown(
            f"### ⏳ AWAITING ADMISSION AUTH: {(system.mission['target_hospital'] or 'UNKNOWN').upper()}"
        )
        st.info("Medical Command Center notified. Standby for handshake protocol.")

        with st.spinner("Establishing secure telemetry link..."):
            time.sleep(2)
            st.rerun()

    # 3. DECLINED — DIVERSION REQUIRED
    elif system.mission["status"] == "DECLINED":
        st.title("❌ ADMISSION DENIED: DIVERSION REQUIRED")
        st.error(
            f"{system.mission['target_hospital']} reports ZERO CAPACITY. Initiate Diversion Protocol."
        )
        if st.button("🔄 INITIATE DIVERSION (SELECT ALTERNATE)", type="primary"):
            system.mission["status"] = "IDLE"
            st.rerun()

    # 4. IDLE — DIAGNOSTICS & HOSPITAL SELECTION
    else:
        st.title("🚑 ResQ PRE-HOSPITAL ASSESSMENT")

        col_gps, col_info = st.columns([1, 2])
        with col_gps:
            st.caption("📍 GET REAL-TIME LOCATION")
            location = streamlit_geolocation()

            # FIX: Only attempt fetch when we have valid coordinates AND haven't locked yet.
            if location and location.get("latitude") is not None:
                user_lat = location["latitude"]
                user_lon = location["longitude"]
                system.mission["ambulance_loc"] = {"lat": user_lat, "lon": user_lon}

                if not system.gps_locked and not st.session_state.gps_fetch_attempted:
                    # Mark attempt so we don't retry in a loop on every rerun
                    st.session_state.gps_fetch_attempted = True
                    with st.spinner("📡 SCANNING SATELLITE & FINDING LOCAL HOSPITALS..."):
                        success = system.fetch_real_hospitals(user_lat, user_lon)
                    if success:
                        st.success("✅ LOCAL HOSPITALS FOUND!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning(
                            "⚠️ Could not reach OpenStreetMap. Using simulation hospitals."
                        )

        with col_info:
            if system.gps_locked:
                st.success(
                    f"✅ GPS LOCKED: {system.base_lat:.4f}, {system.base_lon:.4f}"
                )
            else:
                st.info("⚠️ Click the button to fetch REAL hospitals near you.")

            st.markdown("---")
            with st.expander("📍 Enter Location Manually"):
                m_lat = st.number_input("Latitude", value=system.base_lat, format="%.4f")
                m_lon = st.number_input("Longitude", value=system.base_lon, format="%.4f")
                if st.button("🔍 FETCH HOSPITALS AT COORDINATES", use_container_width=True):
                    system.mission["ambulance_loc"] = {"lat": m_lat, "lon": m_lon}
                    with st.spinner("📡 SCANNING LOCAL HOSPITALS..."):
                        success = system.fetch_real_hospitals(m_lat, m_lon)
                    if success:
                        st.success("✅ LOCAL HOSPITALS FOUND!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning(
                            "⚠️ Could not reach OpenStreetMap. Using simulation hospitals."
                        )

        st.divider()
        c1, c2 = st.columns([1, 2])
        with c1:
            pid = st.text_input(
                "SCAN PATIENT ID / QR (Optional)", placeholder="Enter ID if available"
            )
        with c2:
            if pid:
                patient = emr_database.get(pid, {})
                if patient:
                    st.success(f"**EHR FOUND:** {patient['name']} (Age: {patient['age']})")
                else:
                    st.warning("Patient ID not found in Local Database.")
                    patient = None
            else:
                patient = None

        st.divider()
        st.subheader("📊 VITAL SIGNS MONITOR")
        v1, v2, v3 = st.columns(3)
        with v1:
            bp_input = st.text_input("Blood Pressure", placeholder="120/80")
        with v2:
            hr_input = st.number_input("Heart Rate (BPM)", value=0, min_value=0)
        with v3:
            spo2_input = st.number_input("SpO2 (%)", value=0, min_value=0, max_value=100)

        st.divider()
        notes = st.text_area(
            "🎙️ CLINICAL NOTES / OBSERVATIONS",
            height=100,
            placeholder="e.g., Diaphoresis, chest pain radiating to left arm...",
        )

        col_act, col_upl = st.columns([1, 1])
        with col_upl:
            st.file_uploader(
                "📸 UPLOAD TRAUMA IMAGING",
                type=["jpg", "png"],
                label_visibility="collapsed",
            )
        with col_act:
            analyze_btn = st.button("⚡ EXECUTE CLINICAL DIAGNOSTICS", type="primary")

        if analyze_btn:
            if not notes:
                st.toast("⚠️ Input Error: Clinical notes required.")
            else:
                system.declined_hospitals = []
                patient_data_str = (
                    str(patient) if patient else "UNIDENTIFIED PATIENT / UNKNOWN HISTORY"
                )
                system.mission["live_vitals"] = {
                    "bp": bp_input if bp_input else "N/A",
                    "hr": hr_input if hr_input > 0 else "N/A",
                    "spo2": spo2_input if spo2_input > 0 else "N/A",
                }

                with st.spinner("🤖 PROCESSING BIOMETRICS..."):
                    prompt = f"""You are an Expert Trauma Triage AI assistant.

Patient Data: {patient_data_str}
Vitals: BP {bp_input}, HR {hr_input}, SpO2 {spo2_input}
Clinical Notes: {notes}

Task: Analyze the patient and return ONLY a valid JSON object with exactly these three fields:
- "severity": integer between 1 and 10 (1=minor, 10=critical)
- "ward_need": string, must be exactly "ICU" or "OP"
- "reason": string, max 40 words, clinical assessment

Return ONLY the raw JSON object. No markdown, no explanation, no code fences. Example:
{{"severity": 7, "ward_need": "ICU", "reason": "Patient presents with acute chest pain and low SpO2 consistent with cardiac event requiring intensive monitoring."}}"""

                    try:
                        safe = {
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE
                        }
                        response = model.generate_content(prompt, safety_settings=safe)
                        result = extract_json(response.text)

                        # Validate and normalise fields
                        result["severity"] = max(1, min(10, int(result.get("severity", 5))))
                        ward = str(result.get("ward_need", "OP")).strip().upper()
                        result["ward_need"] = "ICU" if "ICU" in ward else "OP"
                        result["reason"] = str(result.get("reason", "Assessment incomplete."))

                        st.session_state.analysis_result = result
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI ERROR: {e}")
                        st.info(
                            "Tip: Check your API key in st.secrets or the app config."
                        )

        # --- SHOW HOSPITALS ONLY AFTER DIAGNOSIS ---
        if st.session_state.analysis_result:
            r = st.session_state.analysis_result
            st.divider()
            st.markdown("### 🤖 CLINICAL ACUITY REPORT")
            c1, c2 = st.columns([1, 2])
            sev = r["severity"]
            color = "red" if sev > 7 else "orange" if sev > 4 else "green"
            with c1:
                st.markdown(f"**SEVERITY INDEX**: :{color}[**{sev}/10**]")
                st.metric("REQUIRED UNIT", r["ward_need"])
            with c2:
                st.info(f"**AI ASSESSMENT:**\n\n{r['reason']}", icon="🩺")

            st.markdown("### 🏥 SELECT DESTINATION FACILITY")
            hospitals = find_best_hospital(r["ward_need"])

            # Build map with ambulance + all candidate hospitals
            map_pts = [
                {
                    "lat": system.mission["ambulance_loc"]["lat"],
                    "lon": system.mission["ambulance_loc"]["lon"],
                    "color": "#ff0000",
                    "size": 20,
                }
            ]
            for name, data in system.hospitals.items():
                map_pts.append(
                    {
                        "lat": data["lat"],
                        "lon": data["lon"],
                        "color": "#0000ff",
                        "size": 15,
                    }
                )
            st.map(pd.DataFrame(map_pts), color="color", size="size", zoom=12)

            if not hospitals:
                st.error("🚨 CRITICAL: NO HOSPITALS WITH REQUIRED CAPACITY FOUND NEARBY")

            for name, data in hospitals:
                with st.container():
                    col_det, col_btn = st.columns([3, 1])
                    with col_det:
                        st.markdown(f"**{name}**")
                        capacity = (
                            data["icu_beds"]
                            if r["ward_need"] == "ICU"
                            else data["op_beds"]
                        )
                        st.caption(
                            f"🚗 {data['dist']}km | {r['ward_need']} Capacity: {capacity}"
                        )
                    with col_btn:
                        if name in system.declined_hospitals:
                            st.button(f"⛔ REFUSED", key=f"btn_{name}", disabled=True)
                        else:
                            if st.button(f"🚑 REQUEST ADMISSION", key=f"btn_{name}"):
                                system.mission["status"] = "PENDING"
                                system.mission["target_hospital"] = name
                                system.mission["patient_data"] = (
                                    patient
                                    if patient
                                    else {"name": "Unidentified", "age": "Unknown"}
                                )
                                system.mission["ai_analysis"] = r
                                st.rerun()
                    st.divider()

# ================== PAGE 2: HOSPITAL OPS ==================
else:
    st.title("🏥 MEDICAL COMMAND CENTER")

    if system.mission["status"] == "ACTIVE":
        patient_name = (system.mission.get('patient_data') or {}).get('name', 'UNKNOWN')
        st.success(
            f"🚑 ACTIVE INBOUND: {patient_name.upper()}"
        )
        st.subheader("📍 INBOUND UNIT TRACKING")
        target_hosp = system.mission["target_hospital"]

        # Safe lookup for live hospital coordinates
        if target_hosp and target_hosp in system.hospitals:
            h_data = system.hospitals[target_hosp]
        else:
            h_data = list(system.hospitals.values())[0]

        map_data = pd.DataFrame(
            [
                {
                    "lat": system.mission["ambulance_loc"]["lat"],
                    "lon": system.mission["ambulance_loc"]["lon"],
                    "type": "🚑 UNIT",
                    "size": 20,
                    "color": "#ff0000",
                },
                {
                    "lat": h_data["lat"],
                    "lon": h_data["lon"],
                    "type": "🏥 HOSPITAL",
                    "size": 20,
                    "color": "#00ff00",
                },
            ]
        )
        st.map(
            map_data,
            latitude="lat",
            longitude="lon",
            size="size",
            color="color",
            zoom=13,
        )

        st.subheader("📡 LIVE VITALS")
        if (
            system.mission.get("telemetry_alert")
            and system.mission["telemetry_alert"] != "Stable"
        ):
            st.warning(
                f"**🔔 UPDATE FROM UNIT:** {system.mission['telemetry_alert']}"
            )

        vitals = system.mission["live_vitals"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("BP", vitals["bp"])
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
            st.caption(
                f"Initial Vitals: BP {vitals['bp']} | HR {vitals['hr']} | SpO2 {vitals['spo2']}"
            )

        b1, b2 = st.columns(2)
        with b1:
            if st.button(
                "✅ AUTHORIZE ADMISSION", type="primary", use_container_width=True
            ):
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
    m3.metric(
        "Active Inbound", "1" if system.mission["status"] != "IDLE" else "0"
    )

    st.subheader("📊 Network Census Board")
    table = []
    for h, d in system.hospitals.items():
        table.append(
            {
                "Facility Name": h,
                "ICU Vacancy": d["icu_beds"],
                "Gen Ward Vacancy": d["op_beds"],
                "Specialty": d["specialty"],
            }
        )
    st.dataframe(
        pd.DataFrame(table), use_container_width=True, hide_index=True
    )
