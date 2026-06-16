import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import pandas as pd
import time
import json
import os
import random
import re
from streamlit_geolocation import streamlit_geolocation
import overpy
from geopy.distance import geodesic

# ================== CONFIGURATION ==================
st.set_page_config(page_title="ResQ | Medicare App", page_icon="🚑", layout="wide")

st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; font-weight: bold; }
    div[data-testid="stMetricValue"] { font-size: 2.2rem; }
</style>
""", unsafe_allow_html=True)

# ================== GEMINI SETUP ==================
API_KEY = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY"))

if not API_KEY:
    st.error("❌ Gemini API key missing. Add GEMINI_API_KEY in secrets.")
    st.stop()

genai.configure(api_key=API_KEY)

@st.cache_resource
def get_model():
    return genai.GenerativeModel("gemini-1.5-flash")

model = get_model()

# ================== SYSTEM STATE ==================
class SharedSystemState:
    def __init__(self):
        self.base_lat = 11.0168
        self.base_lon = 76.9558
        self.gps_locked = False

        self.hospitals = {
            "City General Trauma": {
                "specialty": "Level 1 Trauma",
                "dist": 5.2,
                "icu_beds": 2,
                "op_beds": 15,
                "lat": 11.0200,
                "lon": 76.9600
            },
            "Metropolitan Heart": {
                "specialty": "Cardiology Center",
                "dist": 8.5,
                "icu_beds": 8,
                "op_beds": 5,
                "lat": 11.0300,
                "lon": 76.9700
            },
        }

        self.mission = {
            "status": "IDLE",
            "target_hospital": None,
            "patient_data": None,
            "ai_analysis": None,
            "live_vitals": {
                "bp": "120/80",
                "hr": 80,
                "spo2": 98
            },
            "telemetry_alert": "Stable",
            "ambulance_loc": {
                "lat": 11.0168,
                "lon": 76.9558
            }
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

    def fetch_real_hospitals(self, lat, lon):
        if self.gps_locked:
            return True

        api = overpy.Overpass()

        query = f"""
        [out:json];
        node["amenity"="hospital"](around:10000,{lat},{lon});
        out 5;
        """

        try:
            result = api.query(query)
            new_hospitals = {}

            for node in result.nodes[:5]:
                name = node.tags.get("name", "Unknown Medical Center")
                h_lat = float(node.lat)
                h_lon = float(node.lon)

                dist = round(
                    geodesic((lat, lon), (h_lat, h_lon)).km, 1
                )

                new_hospitals[name] = {
                    "specialty": "General / Emergency",
                    "dist": dist,
                    "icu_beds": random.randint(0, 5),
                    "op_beds": random.randint(5, 20),
                    "lat": h_lat,
                    "lon": h_lon
                }

            if new_hospitals:
                self.hospitals = new_hospitals
                self.base_lat = lat
                self.base_lon = lon
                self.gps_locked = True
                return True

        except Exception:
            return False

        return False


if "system" not in st.session_state:
    st.session_state.system = SharedSystemState()

system = st.session_state.system

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

# ================== MOCK EMR DATA ==================
emr_database = {
    "P-101": {
        "name": "Alex Mercer",
        "age": 58,
        "blood": "O+",
        "history": "Hypertension",
        "allergies": "Penicillin"
    },
    "P-102": {
        "name": "Sarah Connor",
        "age": 34,
        "blood": "A+",
        "history": "Asthma",
        "allergies": "None"
    }
}

# ================== HELPERS ==================
def safe_int(val):
    try:
        return int(val)
    except:
        return 0

def find_best_hospital(required_ward):
    eligible = []

    for name, data in system.hospitals.items():
        if required_ward == "ICU" and data["icu_beds"] > 0:
            eligible.append((name, data))
        elif required_ward == "OP" and data["op_beds"] > 0:
            eligible.append((name, data))

    return sorted(eligible, key=lambda x: x[1]["dist"])

def parse_gemini_json(text):
    text = text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(text)
    except:
        match = re.search(r'\{.*\}', text, re.S)
        if match:
            return json.loads(match.group())
        raise Exception("Invalid AI JSON response")

# ================== SIDEBAR ==================
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

    st.divider()
    page = st.radio(
        "SELECT INTERFACE",
        ["🚑 EMS UNIT (AMBULANCE)", "🏥 MEDICAL COMMAND (HOSPITAL)"]
    )

# ================== EMS INTERFACE ==================
if page == "🚑 EMS UNIT (AMBULANCE)":

    # ================== ACTIVE MISSION ==================
    if system.mission["status"] == "ACTIVE":
        dest_name = system.mission["target_hospital"]

        if dest_name in system.hospitals:
            dest_data = system.hospitals[dest_name]
        else:
            dest_name = list(system.hospitals.keys())[0]
            dest_data = list(system.hospitals.values())[0]

        st.markdown(f"# 🚑 EN ROUTE TO: {dest_name}")
        st.success("✅ ADMISSION AUTHORIZED - UNIT MOBILIZED")

        c1, c2, c3 = st.columns(3)
        c1.metric("ETA", "8 Mins")
        c2.metric("RANGE", f"{dest_data['dist']} km")
        c3.metric("STATUS", "EN ROUTE")

        st.subheader("📍 LIVE GPS TRACKING")

        map_data = pd.DataFrame([
            {
                "lat": system.mission["ambulance_loc"]["lat"],
                "lon": system.mission["ambulance_loc"]["lon"],
                "type": "🚑 AMBULANCE",
                "size": 20,
                "color": "#ff0000"
            },
            {
                "lat": dest_data["lat"],
                "lon": dest_data["lon"],
                "type": "🏥 HOSPITAL",
                "size": 20,
                "color": "#00ff00"
            }
        ])

        st.map(
            map_data,
            latitude="lat",
            longitude="lon",
            size="size",
            color="color",
            zoom=13
        )

        st.divider()
        st.subheader("📡 LIVE PATIENT TELEMETRY")

        vc1, vc2, vc3, vc4 = st.columns(4)

        with vc1:
            new_bp = st.text_input(
                "BP (mmHg)",
                value=system.mission["live_vitals"]["bp"]
            )

        with vc2:
            new_hr = st.number_input(
                "Heart Rate (BPM)",
                value=safe_int(system.mission["live_vitals"]["hr"])
            )

        with vc3:
            new_spo2 = st.number_input(
                "SpO2 (%)",
                value=safe_int(system.mission["live_vitals"]["spo2"])
            )

        with vc4:
            st.write("")
            st.write("")

            if st.button("📡 TRANSMIT & RE-EVALUATE"):
                system.mission["live_vitals"] = {
                    "bp": new_bp,
                    "hr": new_hr,
                    "spo2": new_spo2
                }

                with st.spinner("AI Analyzing New Vitals..."):
                    previous_reason = (system.mission["ai_analysis"]["reason"]
                                       if system.mission["ai_analysis"]
                                       else "Unknown" )

                    prompt = f"""

                    Patient Re-evaluation.
                    Previous Status: {previous_reason}
                    NEW VITALS:
                    BP {new_bp}
                    HR {new_hr}
                    SpO2 {new_spo2}

                    Provide 1 sentence update for receiving doctor.
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

    # ================== PENDING ==================
    elif system.mission["status"] == "PENDING":
        st.title("🚑 TRANSFER REQUEST INITIATED")
        st.markdown(
            f"### ⏳ AWAITING ADMISSION AUTH: "
            f"{system.mission['target_hospital'].upper()}"
        )

        st.info("Medical Command Center notified. Standby for handshake protocol.")

        with st.spinner("Establishing secure telemetry link..."):
            time.sleep(2)
            st.rerun()

    # ================== DECLINED ==================
    elif system.mission["status"] == "DECLINED":
        st.title("❌ ADMISSION DENIED: DIVERSION REQUIRED")
        st.error(
            f"{system.mission['target_hospital']} reports ZERO CAPACITY. "
            f"Initiate Diversion Protocol."
        )

        if st.button("🔄 INITIATE DIVERSION (SELECT ALTERNATE)", type="primary"):
            system.mission["status"] = "IDLE"
            st.rerun()
    # ================== IDLE / DIAGNOSTICS ==================
    else:
        st.title("🚑 ResQ PRE-HOSPITAL ASSESSMENT")

        col_gps, col_info = st.columns([1, 2])

        with col_gps:
            st.caption("📍 GET REAL-TIME LOCATION")
            location = streamlit_geolocation()

            if location and location["latitude"] is not None:
                if not system.gps_locked:
                    with st.spinner("📡 SCANNING SATELLITE & FINDING LOCAL HOSPITALS..."):
                        success = system.fetch_real_hospitals(
                            location["latitude"],
                            location["longitude"]
                        )

                        system.mission["ambulance_loc"] = {
                            "lat": location["latitude"],
                            "lon": location["longitude"]
                        }

                        if success:
                            st.success("✅ LOCAL HOSPITALS FOUND!")
                            time.sleep(1)
                            st.rerun()

        with col_info:
            if system.gps_locked:
                st.success(
                    f"✅ GPS LOCKED: "
                    f"{system.base_lat:.4f}, {system.base_lon:.4f}"
                )
            else:
                st.info("⚠️ Click the button to fetch REAL hospitals near you.")

        st.divider()

        c1, c2 = st.columns([1, 2])

        with c1:
            pid = st.text_input(
                "SCAN PATIENT ID / QR (Optional)",
                placeholder="Enter ID if available"
            )

        with c2:
            if pid:
                patient = emr_database.get(pid, {})
                if patient:
                    st.success(
                        f"**EHR FOUND:** "
                        f"{patient['name']} (Age: {patient['age']})"
                    )
                else:
                    st.warning("Patient ID not found in Local Database.")
                    patient = None
            else:
                patient = None

        st.divider()
        st.subheader("📊 VITAL SIGNS MONITOR")

        v1, v2, v3 = st.columns(3)

        with v1:
            bp_input = st.text_input(
                "Blood Pressure",
                placeholder="120/80"
            )

        with v2:
            hr_input = st.number_input(
                "Heart Rate (BPM)",
                value=0
            )

        with v3:
            spo2_input = st.number_input(
                "SpO2 (%)",
                value=0
            )

        st.divider()

        notes = st.text_area(
            "🎙️ CLINICAL NOTES / OBSERVATIONS",
            height=100,
            placeholder="e.g., Diaphoresis, chest pain radiating to left arm..."
        )

        col_act, col_upl = st.columns([1, 1])

        with col_upl:
            st.file_uploader(
                "📸 UPLOAD TRAUMA IMAGING",
                type=["jpg", "png"],
                label_visibility="collapsed"
            )

        with col_act:
            analyze_btn = st.button(
                "⚡ EXECUTE CLINICAL DIAGNOSTICS",
                type="primary"
            )

        # ================== AI TRIAGE ==================
        if analyze_btn:
            if not notes:
                st.toast("⚠️ Input Error: Clinical notes required.")
            else:
                system.declined_hospitals = []

                patient_data_str = (
                    str(patient)
                    if patient
                    else "UNIDENTIFIED PATIENT / UNKNOWN HISTORY"
                )

                system.mission["live_vitals"] = {
                    "bp": bp_input if bp_input else "N/A",
                    "hr": hr_input if hr_input > 0 else "N/A",
                    "spo2": spo2_input if spo2_input > 0 else "N/A"
                }

                with st.spinner("🤖 PROCESSING BIOMETRICS..."):
                    prompt = f"""
                    Act as an Expert Trauma Triage AI.

                    Patient Data:
                    {patient_data_str}

                    Vitals:
                    BP {bp_input}
                    HR {hr_input}
                    SpO2 {spo2_input}

                    Clinical Notes:
                    {notes}

                    Task:
                    1. Severity Score (1-10)
                    2. Ward Need (ICU/OP)
                    3. Assessment (max 40 words)

                    Return STRICT JSON only:
                    {{
                        "severity": int,
                        "ward_need": "ICU or OP",
                        "reason": "assessment"
                    }}
                    """

                    try:
                        safe = {
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT:
                            HarmBlockThreshold.BLOCK_NONE
                        }

                        response = model.generate_content(
                            prompt,
                            safety_settings=safe
                        )

                        result = parse_gemini_json(response.text)
                        st.session_state.analysis_result = result
                        st.rerun()

                    except Exception as e:
                        st.error(f"AI ERROR: {e}")

        # ================== TRIAGE RESULT ==================
        if st.session_state.analysis_result:
            r = st.session_state.analysis_result

            st.divider()
            st.markdown("### 🤖 CLINICAL ACUITY REPORT")

            c1, c2 = st.columns([1, 2])

            sev = r["severity"]
            color = "red" if sev > 7 else "orange" if sev > 4 else "green"

            with c1:
                st.markdown(
                    f"**SEVERITY INDEX**: :{color}[**{sev}/10**]"
                )
                st.metric("REQUIRED UNIT", r["ward_need"])

            with c2:
                st.info(
                    f"**AI ASSESSMENT:**\n\n{r['reason']}",
                    icon="🩺"
                )

            st.markdown("### 🏥 SELECT DESTINATION FACILITY")

            hospitals = find_best_hospital(r["ward_need"])

            map_pts = []
            map_pts.append({
                "lat": system.mission["ambulance_loc"]["lat"],
                "lon": system.mission["ambulance_loc"]["lon"],
                "color": "#ff0000",
                "size": 20
            })

            for name, data in hospitals:
                map_pts.append({
                    "lat": data["lat"],
                    "lon": data["lon"],
                    "color": "#0000ff",
                    "size": 15
                })

            st.map(
                pd.DataFrame(map_pts),
                color="color",
                size="size",
                zoom=12
            )

            if not hospitals:
                st.error("🚨 CRITICAL: NO HOSPITALS FOUND NEARBY")

            for name, data in hospitals:
                with st.container():
                    col_det, col_btn = st.columns([3, 1])

                    with col_det:
                        st.markdown(f"**{name}**")
                        st.caption(
                            f"🚗 {data['dist']}km | "
                            f"{r['ward_need']} Capacity: "
                            f"{data['icu_beds'] if r['ward_need']=='ICU' else data['op_beds']}"
                        )

                    with col_btn:
                        if name in system.declined_hospitals:
                            st.button(
                                "⛔ REFUSED",
                                key=name,
                                disabled=True
                            )
                        else:
                            if st.button(
                                "🚑 REQUEST ADMISSION",
                                key=name
                            ):
                                system.mission["status"] = "PENDING"
                                system.mission["target_hospital"] = name
                                system.mission["patient_data"] = (
                                    patient if patient else {
                                        "name": "Unidentified",
                                        "age": "Unknown"
                                    }
                                )
                                system.mission["ai_analysis"] = r
                                st.rerun()

                    st.divider()
# ================== HOSPITAL INTERFACE ==================
else:
    st.title("🏥 MEDICAL COMMAND CENTER")

    # ================== ACTIVE INBOUND ==================
    if system.mission["status"] == "ACTIVE":
        st.success(
            f"🚑 ACTIVE INBOUND: "
            f"{system.mission['patient_data']['name'].upper()}"
        )

        st.subheader("📍 INBOUND UNIT TRACKING")
        target_hosp = system.mission["target_hospital"]

        if target_hosp in system.hospitals:
            h_data = system.hospitals[target_hosp]
        else:
            h_data = list(system.hospitals.values())[0]

        map_data = pd.DataFrame([
            {
                "lat": system.mission["ambulance_loc"]["lat"],
                "lon": system.mission["ambulance_loc"]["lon"],
                "type": "🚑 UNIT",
                "size": 20,
                "color": "#ff0000"
            },
            {
                "lat": h_data["lat"],
                "lon": h_data["lon"],
                "type": "🏥 HOSPITAL",
                "size": 20,
                "color": "#00ff00"
            }
        ])

        st.map(
            map_data,
            latitude="lat",
            longitude="lon",
            size="size",
            color="color",
            zoom=13
        )

        st.subheader("📡 LIVE VITALS")

        if (
            system.mission.get("telemetry_alert")
            and system.mission["telemetry_alert"] != "Stable"
        ):
            st.warning(
                f"**🔔 UPDATE FROM UNIT:** "
                f"{system.mission['telemetry_alert']}"
            )

        vitals = system.mission["live_vitals"]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("BP", vitals["bp"])
        m2.metric("HR", f"{vitals['hr']} bpm", delta_color="inverse")
        m3.metric("SpO2", f"{vitals['spo2']}%")
        m4.metric(
            "Severity",
            f"{system.mission['ai_analysis']['severity']}/10"
        )

        st.divider()

    # ================== PENDING REQUEST ==================
    elif system.mission["status"] == "PENDING":
        st.error("🚨 INCOMING PRIORITY TRANSFER REQUEST")

        alert = system.mission
        patient = alert["patient_data"]
        analysis = alert["ai_analysis"]
        target = alert["target_hospital"]
        vitals = alert.get(
            "live_vitals",
            {"bp": "N/A", "hr": "N/A", "spo2": "N/A"}
        )

        st.markdown(
            f"### 🚑 Unit Requesting Admission to: **{target}**"
        )

        c1, c2 = st.columns(2)

        with c1:
            st.write(
                f"**Patient:** "
                f"{patient['name']} ({patient['age']})"
            )
            st.info(
                f"**Clinical Indication:**\n{analysis['reason']}"
            )

        with c2:
            st.metric(
                "Acuity Score",
                f"{analysis['severity']}/10"
            )
            st.caption(
                f"Initial Vitals: "
                f"BP {vitals['bp']} | "
                f"HR {vitals['hr']} | "
                f"SpO2 {vitals['spo2']}"
            )

        b1, b2 = st.columns(2)

        with b1:
            if st.button(
                "✅ AUTHORIZE ADMISSION",
                type="primary",
                use_container_width=True
            ):
                system.update_beds(target, analysis["ward_need"])
                system.mission["status"] = "ACTIVE"
                st.rerun()

        with b2:
            if st.button(
                "❌ DIVERT (CAPACITY FULL)",
                use_container_width=True
            ):
                system.declined_hospitals.append(target)
                system.mission["status"] = "DECLINED"
                st.rerun()

        st.divider()

    # ================== NETWORK CENSUS ==================
    st.caption("Live Bed Census & Transport Tracking")

    total_icu = sum(
        h["icu_beds"] for h in system.hospitals.values()
    )

    total_op = sum(
        h["op_beds"] for h in system.hospitals.values()
    )

    m1, m2, m3 = st.columns(3)
    m1.metric("ICU Capacity", total_icu)
    m2.metric("General Capacity", total_op)
    m3.metric(
        "Active Inbound",
        "1" if system.mission["status"] != "IDLE" else "0"
    )

    st.subheader("📊 Network Census Board")

    table = []
    for h, d in system.hospitals.items():
        table.append({
            "Facility Name": h,
            "ICU Vacancy": d["icu_beds"],
            "Gen Ward Vacancy": d["op_beds"],
            "Specialty": d["specialty"]
        })

    st.dataframe(
        pd.DataFrame(table),
        use_container_width=True,
        hide_index=True
    )
