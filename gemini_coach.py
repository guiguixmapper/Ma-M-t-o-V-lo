"""
gemini_coach.py
===============
Module dédié à l'Intelligence Artificielle (Google Gemini).
Génère un briefing tactique personnalisé en croisant le profil altimétrique et la météo.
"""

import google.generativeai as genai
import logging

logger = logging.getLogger(__name__)

def generer_briefing(api_key: str, dist_tot: float, d_plus: float, 
                     score: dict, ascensions: list, analyse_meteo: dict) -> str | None:
    """
    Envoie les données du parcours à Gemini pour obtenir un briefing du Directeur Sportif.
    """
    if not api_key:
        return None

    try:
        # Configuration de l'API avec la clé
        genai.configure(api_key=api_key)
        # On utilise le modèle Flash 1.5 : hyper rapide et parfait pour l'analyse de texte
        model = genai.GenerativeModel('gemini-1.5-flash')

        # ── PRÉPARATION DES DONNÉES ──
        dist_km = round(dist_tot / 1000, 1)
        d_plus_m = int(d_plus)

        if ascensions:
            cols_str = "\n".join([
                f"- {a.get('Nom', a['Catégorie'])} (Départ: Km {a['Départ (km)']}, Longueur: {a['Longueur']}, Pente: {a['Pente moy.']})" 
                for a in ascensions
            ])
        else:
            cols_str = "Aucune difficulté majeure répertoriée, parcours plutôt roulant."

        meteo_txt = "Données météo non disponibles."
        if analyse_meteo:
            meteo_txt = (
                f"Risque de pluie > 50% sur {analyse_meteo['pct_pluie']}% du parcours. "
                f"Orientation du vent par rapport au cycliste : Face {analyse_meteo['pct_face']}%, "
                f"Dos {analyse_meteo['pct_dos']}%, Côté {analyse_meteo['pct_cote']}%."
            )

        # ── LE PROMPT (La consigne donnée à l'IA) ──
        prompt = f"""
        Tu es un directeur sportif de cyclisme sur route très expérimenté, charismatique et motivant.
        Tu tutoies le cycliste et tu lui fais son briefing tactique juste avant qu'il n'enfourche son vélo.

        Voici les données de sa sortie du jour calculées par son ordinateur de bord :
        - Distance : {dist_km} km
        - Dénivelé positif : {d_plus_m} m
        - Difficulté globale estimée par l'algorithme : {score['label']} ({score['total']}/10)
        - Liste des montées clés :
        {cols_str}
        - Prévisions météo sur le parcours : {meteo_txt}

        Fournis un briefing structuré, punchy et direct contenant obligatoirement :
        1. L'état d'esprit et l'approche globale à avoir vu le profil et la météo.
        2. L'analyse tactique (où il va devoir s'accrocher, où il pourra récupérer, comment gérer le vent).
        3. Des conseils pratiques sur la nutrition/hydratation et le choix des vêtements aujourd'hui.
        4. Une conclusion épique pour le gonfler à bloc.
        """
        
        # Appel à l'IA
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        logger.error(f"Erreur lors de la génération Gemini : {e}")
        raise e # On remonte l'erreur pour l'afficher proprement dans Streamlit
