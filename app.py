import streamlit as st
import pandas as pd

# 1. TITRE DE L'APPLICATION
st.title("🚴‍♂️ Mon Parcours Vélo & Météo")
st.write("Anticipez la météo, le vent et le dénivelé tout au long de votre sortie !")

# 2. LES PARAMÈTRES (Sur le côté de la page)
st.sidebar.header("Vos paramètres")
vitesse_moyenne = st.sidebar.number_input("Vitesse moyenne sur le plat (km/h)", value=25)
heure_depart = st.sidebar.time_input("Heure de départ")

# 3. LE BOUTON D'IMPORT DU PARCOURS
fichier_gpx = st.file_uploader("Importez votre fichier parcours (.gpx)", type=["gpx"])

# 4. SI UN FICHIER EST IMPORTÉ, ON LANCE LA MACHINE
if fichier_gpx is not None:
    st.success("Parcours chargé avec succès ! Calcul en cours...")
    
    # ---------------------------------------------------------
    # C'EST ICI QUE LE "MOTEUR" FERA SON TRAVAIL INVISIBLE :
    # - Lire les points GPS du fichier
    # - Calculer le ralentissement dû au dénivelé positif
    # - Trouver votre position toutes les 10 minutes
    # - Interroger l'API Open-Meteo
    # ---------------------------------------------------------

    # 5. AFFICHAGE DE LA CARTE (Ici, on affichera le tracé réel)
    st.write("### 📍 Votre itinéraire")
    st.info("La carte interactive s'affichera ici.")
    
    # 6. AFFICHAGE DU RÉSULTAT FINAL (Le tableau de bord)
    st.write("### ⏱️ Vos conditions de route (Toutes les 10 min)")
    
    # J'ai mis de fausses données ici pour vous montrer à quoi ressemblera le résultat
    donnees_exemple = {
        "Heure": ["08:00", "08:10", "08:20", "08:30"],
        "Km franchis": [0, 4.1, 7.8, 10.5], # On voit qu'on a moins avancé à cause de la montée !
        "Altitude (m)": [200, 215, 450, 600],
        "Météo": ["☀️ Beau", "⛅ Nuageux", "🌧️ Averses", "🌧️ Pluie"],
        "Vent": ["⬇️ Face (15km/h)", "⬇️ Face (15km/h)", "⬅️ Côté (20km/h)", "⬅️ Côté (25km/h)"]
    }
    
    # On transforme ces données en un beau tableau
    st.dataframe(pd.DataFrame(donnees_exemple), use_container_width=True)
