import streamlit as st
import pandas as pd
import gpxpy
import folium
from streamlit_folium import st_folium

# 1. TITRE ET PARAMÈTRES
st.title("🚴‍♂️ Mon Parcours Vélo & Météo")
st.write("Anticipez la météo, le vent et le dénivelé tout au long de votre sortie !")

st.sidebar.header("Vos paramètres")
vitesse_moyenne = st.sidebar.number_input("Vitesse moyenne sur le plat (km/h)", value=25)
heure_depart = st.sidebar.time_input("Heure de départ")

# 2. IMPORT DU FICHIER
fichier_gpx = st.file_uploader("Importez votre fichier parcours (.gpx)", type=["gpx"])

# 3. TRAITEMENT DU FICHIER ET AFFICHAGE DE LA CARTE
if fichier_gpx is not None:
    st.success("Parcours lu avec succès ! Création de la carte...")
    
    # --- Lecture du fichier GPX ---
    gpx = gpxpy.parse(fichier_gpx)
    
    # Extraction des coordonnées GPS
    points_gps = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points_gps.append([point.latitude, point.longitude])
    
    # --- Création de la carte ---
    if len(points_gps) > 0:
        st.write("### 📍 Votre itinéraire")
        
        # On centre la carte sur le premier point du parcours
        point_depart = points_gps[0]
        carte_parcours = folium.Map(location=point_depart, zoom_start=12)
        
        # On trace la ligne bleue du parcours
        folium.PolyLine(points_gps, color="blue", weight=5, opacity=0.8).add_to(carte_parcours)
        
        # On affiche la carte dans le site web
        st_folium(carte_parcours, width=700, height=500)
    else:
        st.error("Le fichier GPX semble vide ou ne contient pas de tracé valide.")
    
    # 4. LE TABLEAU (En attente du vrai moteur de calcul)
    st.write("### ⏱️ Vos conditions de route (Bientôt !)")
    st.info("La prochaine étape sera d'ajouter le calcul du temps avec le dénivelé et la météo.")
