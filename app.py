import streamlit as st
import pandas as pd
import gpxpy
import folium
from streamlit_folium import st_folium
import requests
from datetime import datetime, timedelta, date
import matplotlib.pyplot as plt
import math

# --- FONCTIONS MATHÉMATIQUES ET TRADUCTEURS ---
def calculer_cap(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    cap_initial = math.atan2(x, y)
    return (math.degrees(cap_initial) + 360) % 360

def direction_vent_relative(cap_velo, dir_vent):
    diff = (dir_vent - cap_velo) % 360
    if diff <= 45 or diff >= 315: return "⬇️ Face"
    elif 135 <= diff <= 225: return "⬆️ Dos"
    elif 45 < diff < 135: return "↘️ Côté (Droit)"
    else: return "↙️ Côté (Gauche)"

def categoriser_ascension(distance_m, d_plus):
    if distance_m < 500 or d_plus < 30: return None
    pente_moyenne = (d_plus / distance_m) * 100
    if pente_moyenne < 3.0: return None
    score = (distance_m / 1000) * (pente_moyenne ** 2)
    if score >= 250: return "🔴 HC (Hors Catégorie)"
    elif score >= 150: return "🟠 1ère Catég."
    elif score >= 80: return "🟡 2ème Catég."
    elif score >= 35: return "🟢 3ème Catég."
    elif score >= 15: return "🔵 4ème Catég."
    else: return "⚪ Non classée"

def obtenir_icone_meteo(code):
    if code == 0: return "☀️ Clair"
    elif code in [1, 2]: return "⛅ Éclaircies"
    elif code == 3: return "☁️ Couvert"
    elif code in [45, 48]: return "🌫️ Brouillard"
    elif code in [51, 53, 55, 56, 57]: return "🌦️ Bruine"
    elif code in [61, 63, 65, 66, 67, 80, 81, 82]: return "🌧️ Pluie"
    elif code in [71, 73, 75, 77, 85, 86]: return "❄️ Neige"
    elif code in [95, 96, 99]: return "⛈️ Orage"
    else: return "❓ Inconnu"

# --- 1. TITRE ET PARAMÈTRES ---
st.title("🚴‍♂️ Mon Parcours Vélo & Météo")
st.write("Anticipez la météo, le vent et analysez vos montées !")

st.sidebar.header("Vos paramètres")
date_depart_choisie = st.sidebar.date_input("Date de départ", value=date.today())
heure_depart = st.sidebar.time_input("Heure de départ")
vitesse_moyenne = st.sidebar.number_input("Vitesse moyenne sur le plat (km/h)", value=25)

intervalle_min = st.sidebar.selectbox(
    "Intervalle des points météo", 
    options=[5, 10, 15], 
    index=1, 
    format_func=lambda x: f"Toutes les {x} min"
)
intervalle_sec = intervalle_min * 60

info_fuseau = st.sidebar.empty()
info_fuseau.info("🌍 Fuseau horaire : En attente du tracé...")

# --- 2. IMPORT DU FICHIER ---
fichier_gpx = st.file_uploader("Importez votre fichier parcours (.gpx)", type=["gpx"])

if fichier_gpx is not None:
    gpx = gpxpy.parse(fichier_gpx)
    points_gpx = []
    
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points_gpx.append(point)
    
    if len(points_gpx) > 0:
        
        # --- PHASE 1 : CALCULS DE BASE ---
        lat_depart = points_gpx[0].latitude
        lon_depart = points_gpx[0].longitude
        url_tz = f"https://api.open-meteo.com/v1/forecast?latitude={lat_depart}&longitude={lon_depart}&current=temperature_2m&timezone=auto"
        try:
            rep_tz = requests.get(url_tz).json()
            fuseau_horaire = rep_tz.get("timezone", "Inconnu")
        except:
            fuseau_horaire = "Erreur"

        info_fuseau.success(f"🌍 Heure et météo calées sur : **{fuseau_horaire}**")

        checkpoints = []
        profil_data = []
        distance_totale_m = 0
        d_plus_total = 0
        d_moins_total = 0
        temps_total_sec = 0
        prochain_checkpoint_sec = 0 
        cap_actuel = 0
        
        date_depart = datetime.combine(date_depart_choisie, heure_depart)

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
                    "Heure": heure_passage.strftime("%d/%m %H:%M"),
                    "Heure_API": heure_passage.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"),
                    "Km": round(distance_totale_m / 1000, 1),
                    "Alt (m)": int(p2.elevation) if p2.elevation else 0
                })
                prochain_checkpoint_sec += intervalle_sec

        heure_arrivee = date_depart + timedelta(seconds=temps_total_sec)
        p_final = points_gpx[-1]
        checkpoints.append({
            "lat": p_final.latitude, "lon": p_final.longitude, "Cap": cap_actuel,
            "Heure": heure_arrivee.strftime("%d/%m %H:%M") + " (Arr.)",
            "Heure_API": heure_arrivee.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"),
            "Km": round(distance_totale_m / 1000, 1),
            "Alt (m)": int(p_final.elevation) if p_final.elevation else 0
        })

        # --- PHASE 2 : ANALYSE DES ASCENSIONS ---
        df_profil = pd.DataFrame(profil_data)
        ascensions = []
        en_montee = False
        debut_idx = 0
        idx_max = 0
        pente_max_locale = 0
        
        if not df_profil.empty:
            alt_min = df_profil.iloc[0]['Altitude (m)']
            alt_max = alt_min
            for i in range(1, len(df_profil)):
                alt = df_profil.iloc[i]['Altitude (m)']
                dist = df_profil.iloc[i]['Distance (km)']
                
                if not en_montee:
                    if alt < alt_min:
                        alt_min = alt
                        debut_idx = i
                    elif alt > alt_min + 15:
                        en_montee = True
                        idx_max = i
                        alt_max = alt
                        pente_max_locale = 0
                else:
                    for j in range(i-1, debut_idx-1, -1):
                        dist_precedente = df_profil.iloc[j]['Distance (km)']
                        dist_diff = dist - dist_precedente
                        if dist_diff >= 0.050: 
                            alt_diff = alt - df_profil.iloc[j]['Altitude (m)']
                            pente_segment = (alt_diff / (dist_diff * 1000)) * 100
                            if 0 < pente_segment <= 40 and pente_segment > pente_max_locale:
                                pente_max_locale = pente_segment
                            break

                    if alt > alt_max:
                        alt_max = alt
                        idx_max = i
                    elif alt <= alt_max - 30:
                        dist_debut = df_profil.iloc[debut_idx]['Distance (km)']
                        alt_debut = df_profil.iloc[debut_idx]['Altitude (m)']
                        dist_sommet = df_profil.iloc[idx_max]['Distance (km)']
                        dist_totale = dist_sommet - dist_debut
                        d_plus = alt_max - alt_debut
                        cat = categoriser_ascension(dist_totale * 1000, d_plus)
                        if cat and "Non classée" not in cat:
                            ascensions.append({"Départ": f"Km {round(dist_debut, 1)}", "Catégorie": cat, "Distance": f"{round(dist_totale, 1)} km", "Pente Moy.": f"{round((d_plus / (dist_totale * 1000)) * 100, 1)} %", "Pente Max": f"{round(pente_max_locale, 1)} %", "Dénivelé": f"{int(d_plus)} m"})
                        en_montee = False
                        alt_min = alt
                        debut_idx = i

            if en_montee:
                dist_debut = df_profil.iloc[debut_idx]['Distance (km)']
                alt_debut = df_profil.iloc[debut_idx]['Altitude (m)']
                dist_sommet = df_profil.iloc[idx_max]['Distance (km)']
                dist_totale = dist_sommet - dist_debut
                d_plus = alt_max - alt_debut
                cat = categoriser_ascension(dist_totale * 1000, d_plus)
                if cat and "Non classée" not in cat:
                    ascensions.append({"Départ": f"Km {round(dist_debut, 1)}", "Catégorie": cat, "Distance": f"{round(dist_totale, 1)} km", "Pente Moy.": f"{round((d_plus / (dist_totale * 1000)) * 100, 1)} %", "Pente Max": f"{round(pente_max_locale, 1)} %", "Dénivelé": f"{int(d_plus)} m"})

        # --- PHASE 3 : INTERROGATION DE LA MÉTÉO ---
        st.write("### 📡 Récupération des données météo en cours...")
        resultats_meteo = []
        barre_progression = st.progress(0)

        for i, cp in enumerate(checkpoints):
            url = f"https://api.open-meteo.com/v1/forecast?latitude={cp['lat']}&longitude={cp['lon']}&hourly=temperature_2m,precipitation_probability,weathercode,wind_speed_10m,wind_direction_10m,wind_gusts_10m&timezone=auto"
            try:
                rep = requests.get(url).json()
                heures_api = rep['hourly']['time']
                if cp['Heure_API'] in heures_api:
                    idx = heures_api.index(cp['Heure_API'])
                    cp["Ciel"] = obtenir_icone_meteo(rep['hourly']['weathercode'][idx])
                    cp["Temp (°C)"] = f"{rep['hourly']['temperature_2m'][idx]}°"
                    cp["Pluie"] = f"{rep['hourly']['precipitation_probability'][idx]}%"
                    cp["Vent (km/h)"] = rep['hourly']['wind_speed_10m'][idx]
                    cp["Rafales"] = rep['hourly']['wind_gusts_10m'][idx]
                    
                    vent_d = rep['hourly']['wind_direction_10m'][idx]
                    directions = ["N", "NE", "E", "SE", "S", "SO", "O", "NO", "N"]
                    cp["Dir."] = directions[round(vent_d / 45) % 8]
                    cp["Effet Vent"] = direction_vent_relative(cp["Cap"], vent_d)
                else:
                    cp["Ciel"], cp["Temp (°C)"], cp["Pluie"], cp["Vent (km/h)"], cp["Rafales"], cp["Dir."], cp["Effet Vent"] = "-", "-", "-", "-", "-", "-", "-"
            except:
                cp["Ciel"], cp["Temp (°C)"], cp["Pluie"], cp["Vent (km/h)"], cp["Rafales"], cp["Dir."], cp["Effet Vent"] = "Err", "Err", "Err", "Err", "Err", "Err", "Err"
            
            resultats_meteo.append(cp)
            barre_progression.progress((i + 1) / len(checkpoints))

        # --- PHASE 4 : AFFICHAGE DE LA CARTE AVEC LES MARQUEURS ---
        st.write("### 📍 Votre itinéraire & Checkpoints Météo")
        carte_parcours = folium.Map(location=[points_gpx[0].latitude, points_gpx[0].longitude], zoom_start=12)
        coordonnees = [[p.latitude, p.longitude] for p in points_gpx]
        folium.PolyLine(coordonnees, color="blue", weight=5, opacity=0.8).add_to(carte_parcours)
        
        # NOUVEAU : Ajout des marqueurs météo sur la carte !
        for cp in resultats_meteo:
            if cp["Temp (°C)"] not in ["-", "Err"]:
                # Le texte qui s'affichera au clic
                popup_html = f"<b>{cp['Heure']} (Km {cp['Km']})</b><br>{cp['Ciel']} {cp['Temp (°C)']}<br>Vent: {cp['Vent (km/h)']} km/h {cp['Effet Vent']}"
                # Le texte qui s'affichera au survol de la souris
                tooltip_text = f"{cp['Heure']} - {cp['Ciel']} {cp['Temp (°C)']}"
                
                folium.Marker(
                    location=[cp['lat'], cp['lon']],
                    popup=folium.Popup(popup_html, max_width=200),
                    tooltip=tooltip_text,
                    icon=folium.Icon(color='blue', icon='info-sign')
                ).add_to(carte_parcours)

        st_folium(carte_parcours, width=700, height=400, returned_objects=[])

        # --- PHASE 5 : AFFICHAGE DES RÉSUMÉS ET TABLEAUX ---
        st.write("### 📊 Résumé du parcours")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Distance", f"{round(distance_totale_m / 1000, 1)} km")
        col2.metric("Dénivelé +", f"{int(d_plus_total)} m")
        col3.metric("Dénivelé -", f"{int(d_moins_total)} m")
        col4.metric("Durée", f"{int(temps_total_sec // 3600)}h {int((temps_total_sec % 3600) // 60):02d}m")

        st.write("### ⛰️ Profil altimétrique & Cols")
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.fill_between(df_profil["Distance (km)"], df_profil["Altitude (m)"], color="#3b82f6", alpha=0.3)
        ax.plot(df_profil["Distance (km)"], df_profil["Altitude (m)"], color="#3b82f6", linewidth=2)
        ax.set_xlabel("Distance (km)", color="gray")
        ax.set_ylabel("Altitude (m)", color="gray")
        ax.grid(True, linestyle='--', alpha=0.5)
        st.pyplot(fig)
        
        if len(ascensions) > 0:
            st.dataframe(pd.DataFrame(ascensions), use_container_width=True)
        else:
            st.success("🚴‍♂️ Parcours plutôt roulant, aucune difficulté catégorisée détectée !")

        st.write("### ⏱️ Détail des conditions de route")
        
        # On nettoie le tableau pour ne pas afficher la latitude/longitude
        df_meteo = pd.DataFrame(resultats_meteo)
        df_meteo = df_meteo.drop(columns=['lat', 'lon', 'Heure_API', 'Cap'])
        st.dataframe(df_meteo, use_container_width=True)

    else:
        st.error("Le fichier GPX semble vide.")
