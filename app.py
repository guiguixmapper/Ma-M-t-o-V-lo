import streamlit as st
import pandas as pd
import gpxpy
import folium
from streamlit_folium import st_folium
import requests
from datetime import datetime, timedelta, date
import matplotlib.pyplot as plt
import math

# --- FONCTIONS MATHÉMATIQUES POUR LE VENT ---
def calculer_cap(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    cap_initial = math.atan2(x, y)
    return (math.degrees(cap_initial) + 360) % 360

def direction_vent_relative(cap_velo, dir_vent):
    diff = (dir_vent - cap_velo) % 360
    if diff <= 45 or diff >= 315:
        return "⬇️ Face"
    elif 135 <= diff <= 225:
        return "⬆️ Dos"
    elif 45 < diff < 135:
        return "↘️ Côté (Droit)"
    else:
        return "↙️ Côté (Gauche)"

# --- 1. TITRE ET PARAMÈTRES ---
st.title("🚴‍♂️ Mon Parcours Vélo & Météo")
st.write("Anticipez la météo, le vent et le dénivelé tout au long de votre sortie !")

st.sidebar.header("Vos paramètres")
vitesse_moyenne = st.sidebar.number_input("Vitesse moyenne sur le plat (km/h)", value=25)
heure_depart = st.sidebar.time_input("Heure de départ")

# --- 2. IMPORT DU FICHIER ---
fichier_gpx = st.file_uploader("Importez votre fichier parcours (.gpx)", type=["gpx"])

if fichier_gpx is not None:
    # --- 3. LECTURE DU FICHIER ---
    gpx = gpxpy.parse(fichier_gpx)
    points_gpx = []
    
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points_gpx.append(point)
    
    if len(points_gpx) > 0:
        
        # --- NOUVEAU : DÉTECTION DU FUSEAU HORAIRE ---
        lat_depart = points_gpx[0].latitude
        lon_depart = points_gpx[0].longitude
        url_tz = f"https://api.open-meteo.com/v1/forecast?latitude={lat_depart}&longitude={lon_depart}&current=temperature_2m&timezone=auto"
        
        try:
            rep_tz = requests.get(url_tz).json()
            fuseau_horaire = rep_tz.get("timezone", "Inconnu")
            # On récupère la vraie date locale du point de départ
            date_str = rep_tz['current']['time'][:10] 
            date_locale = datetime.strptime(date_str, "%Y-%m-%d").date()
        except:
            fuseau_horaire = "Erreur de détection"
            date_locale = date.today()

        st.info(f"🌍 Fuseau horaire détecté pour ce parcours : **{fuseau_horaire}**")

        # --- PRÉ-CALCULS ---
        checkpoints = []
        profil_data = []
        distance_totale_m = 0
        d_plus_total = 0
        d_moins_total = 0
        temps_total_sec = 0
        prochain_checkpoint_sec = 0 
        cap_actuel = 0
        
        # On utilise la vraie date locale plutôt que la date du serveur !
        date_depart = datetime.combine(date_locale, heure_depart)

        for i in range(1, len(points_gpx)):
            p1 = points_gpx[i-1]
            p2 = points_gpx[i]

            dist = p1.distance_2d(p2)
            if dist is None: dist = 0
            
            d_plus_local = 0
            if p2.elevation and p1.elevation:
                diff_alt = p2.elevation - p1.elevation
                if diff_alt > 0:
                    d_plus_local = diff_alt
                    d_plus_total += diff_alt
                elif diff_alt < 0:
                    d_moins_total += abs(diff_alt)

            dist_ajustee = dist + (d_plus_local * 10)
            vitesse_ms = (vitesse_moyenne * 1000) / 3600
            temps_sec = dist_ajustee / vitesse_ms if vitesse_ms > 0 else 0

            distance_totale_m += dist
            temps_total_sec += temps_sec
            
            cap_actuel = calculer_cap(p1.latitude, p1.longitude, p2.latitude, p2.longitude)
            profil_data.append({"Distance (km)": distance_totale_m / 1000, "Altitude (m)": p2.elevation})

            if temps_total_sec >= prochain_checkpoint_sec:
                heure_passage = date_depart + timedelta(seconds=temps_total_sec)
                checkpoints.append({
                    "lat": p2.latitude, "lon": p2.longitude, "Cap": cap_actuel,
                    "Heure": heure_passage.strftime("%H:%M"),
                    "Heure_API": heure_passage.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"),
                    "Km": round(distance_totale_m / 1000, 1),
                    "Alt (m)": int(p2.elevation) if p2.elevation else 0
                })
                prochain_checkpoint_sec += 600

        heure_arrivee = date_depart + timedelta(seconds=temps_total_sec)
        p_final = points_gpx[-1]
        checkpoints.append({
            "lat": p_final.latitude, "lon": p_final.longitude, "Cap": cap_actuel,
            "Heure": heure_arrivee.strftime("%H:%M") + " (Arrivée)",
            "Heure_API": heure_arrivee.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"),
            "Km": round(distance_totale_m / 1000, 1),
            "Alt (m)": int(p_final.elevation) if p_final.elevation else 0
        })

        # --- 4. AFFICHAGE VISUEL ---
        st.write("### 📍 Votre itinéraire")
        point_depart = [points_gpx[0].latitude, points_gpx[0].longitude]
        carte_parcours = folium.Map(location=point_depart, zoom_start=12)
        coordonnees = [[p.latitude, p.longitude] for p in points_gpx]
        folium.PolyLine(coordonnees, color="blue", weight=5, opacity=0.8).add_to(carte_parcours)
        st_folium(carte_parcours, width=700, height=400, returned_objects=[])

        st.write("### 📊 Résumé du parcours")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Distance", f"{round(distance_totale_m / 1000, 1)} km")
        col2.metric("Dénivelé +", f"{int(d_plus_total)} m")
        col3.metric("Dénivelé -", f"{int(d_moins_total)} m")
        heures = int(temps_total_sec // 3600)
        minutes = int((temps_total_sec % 3600) // 60)
        col4.metric("Durée estimée", f"{heures}h {minutes:02d}m")

        st.write("### ⛰️ Profil altimétrique")
        df_profil = pd.DataFrame(profil_data)
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.fill_between(df_profil["Distance (km)"], df_profil["Altitude (m)"], color="#3b82f6", alpha=0.3)
        ax.plot(df_profil["Distance (km)"], df_profil["Altitude (m)"], color="#3b82f6", linewidth=2)
        ax.set_xlabel("Distance (km)", color="gray")
        ax.set_ylabel("Altitude (m)", color="gray")
        ax.grid(True, linestyle='--', alpha=0.5)
        st.pyplot(fig)

        # --- 5. INTERROGATION DE LA MÉTÉO ---
        st.write("### ⏱️ Vos conditions de route")
        resultats_meteo = []
        barre_progression = st.progress(0)

        for i, cp in enumerate(checkpoints):
            url = f"https://api.open-meteo.com/v1/forecast?latitude={cp['lat']}&longitude={cp['lon']}&hourly=temperature_2m,precipitation_probability,wind_speed_10m,wind_direction_10m&timezone=auto"
            
            try:
                rep = requests.get(url).json()
                heures_api = rep['hourly']['time']
                
                if cp['Heure_API'] in heures_api:
                    idx = heures_api.index(cp['Heure_API'])
                    temp = rep['hourly']['temperature_2m'][idx]
                    pluie = rep['hourly']['precipitation_probability'][idx]
                    vent_v = rep['hourly']['wind_speed_10m'][idx]
                    vent_d = rep['hourly']['wind_direction_10m'][idx]
                    
                    sens_vent = direction_vent_relative(cp["Cap"], vent_d)

                    cp["Temp (°C)"] = f"{temp}°"
                    cp["Pluie"] = f"{pluie}%"
                    cp["Vent"] = f"{vent_v} km/h {sens_vent}"
                else:
                    cp["Temp (°C)"], cp["Pluie"], cp["Vent"] = "-", "-", "-"
            except:
                cp["Temp (°C)"], cp["Pluie"], cp["Vent"] = "Err", "Err", "Err"
            
            del cp['lat'], cp['lon'], cp['Heure_API'], cp['Cap']
            resultats_meteo.append(cp)
            barre_progression.progress((i + 1) / len(checkpoints))

        # --- 6. AFFICHAGE DU TABLEAU FINAL ---
        st.dataframe(pd.DataFrame(resultats_meteo), use_container_width=True)

    else:
        st.error("Le fichier GPX semble vide.")
