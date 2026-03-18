"""
elevation.py
============
Correction du profil altimétrique via OpenRouteService (ORS).
ORS fournit un modèle d'élévation lissé et précis, idéal pour le cyclisme.
"""

import streamlit as st
import requests
import logging

logger = logging.getLogger(__name__)

ORS_ELEVATION_URL  = "https://api.openrouteservice.org/elevation/line"
MAX_POINTS         = 2000  # limite de points par requête (ORS)


def _requete_ors_line(coords: list, api_key: str) -> list | None:
    """Envoie un lot de points à ORS en utilisant le format GeoJSON."""
    try:
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "format_in": "geojson",
            "format_out": "geojson",
            "geometry": {
                "type": "LineString",
                "coordinates": coords
            }
        }
        r = requests.post(ORS_ELEVATION_URL, json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        
        data = r.json()
        if "geometry" in data and "coordinates" in data["geometry"]:
            return [pt[2] for pt in data["geometry"]["coordinates"] if len(pt) >= 3]
        return None
    except Exception as e:
        logger.warning(f"ORS Elevation échoué : {e}")
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def corriger_profil(lats_tuple: tuple, lons_tuple: tuple, alts_tuple: tuple, api_key: str) -> tuple:
    lats = list(lats_tuple)
    lons = list(lons_tuple)
    alts = list(alts_tuple)
    n    = len(lats)

    if n == 0 or not api_key:
        return alts_tuple

    # Sous-échantillonnage pour éviter les doublons parfaits qui font planter l'API
    indices_echantillon = []
    last_lon, last_lat = None, None
    for i in range(0, n, max(1, n // MAX_POINTS)):
        if lons[i] != last_lon or lats[i] != last_lat:
            indices_echantillon.append(i)
            last_lon, last_lat = lons[i], lats[i]

    # --- MÉTHODE ORS ---
    coords_ors = [[lons[i], lats[i]] for i in indices_echantillon]
    alts_corrigees_echantillon = _requete_ors_line(coords_ors, api_key)
    
    if not alts_corrigees_echantillon or len(alts_corrigees_echantillon) != len(indices_echantillon):
        logger.warning("Erreur avec ORS Elevation. Conservation des altitudes d'origine.")
        return alts_tuple

    # Interpolation linéaire pour reconstruire tous les points intermédiaires
    alts_out = list(alts)
    for k in range(len(indices_echantillon)):
        i0  = indices_echantillon[k]
        i1  = indices_echantillon[k + 1] if k + 1 < len(indices_echantillon) else n
        a0  = alts_corrigees_echantillon[k]
        a1  = alts_corrigees_echantillon[k + 1] if k + 1 < len(alts_corrigees_echantillon) else a0
        if a0 is None or a1 is None:
            continue
        for j in range(i0, min(i1, n)):
            t = (j - i0) / max(1, i1 - i0)
            alts_out[j] = a0 + t * (a1 - a0)

    return tuple(alts_out)
