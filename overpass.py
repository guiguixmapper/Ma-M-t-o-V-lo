"""
elevation.py
============
Correction du profil altimétrique au choix : OpenRouteService (ORS) ou Open-Elevation (SRTM).
"""

import streamlit as st
import requests
import logging

logger = logging.getLogger(__name__)

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
ORS_ELEVATION_URL  = "https://api.openrouteservice.org/elevation/line"
BATCH_SIZE         = 100   # points par requête (Open-Elevation)
MAX_POINTS         = 2000  # limite de points par requête (ORS)


def _requete_ors_line(coords: list, api_key: str) -> list | None:
    """Envoie un lot de points à ORS. coords = [[lon, lat], [lon, lat]...]"""
    try:
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "format_in": "polyline",
            "format_out": "polyline",
            "geometry": coords
        }
        r = requests.post(ORS_ELEVATION_URL, json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json().get("geometry", [])
        return [pt[2] for pt in data if len(pt) >= 3]
    except Exception as e:
        logger.warning(f"ORS Elevation échoué : {e}")
        return None


def _requete_batch(locations: list) -> list | None:
    """Envoie un batch de points à Open-Elevation (SRTM)."""
    try:
        r = requests.post(
            OPEN_ELEVATION_URL,
            json={"locations": locations},
            timeout=20,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        return [pt.get("elevation") for pt in results]
    except Exception as e:
        logger.warning(f"Open-Elevation batch échoué : {e}")
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def corriger_profil(lats_tuple: tuple, lons_tuple: tuple, alts_tuple: tuple, api_key: str = "", methode: str = "srtm") -> tuple:
    lats = list(lats_tuple)
    lons = list(lons_tuple)
    alts = list(alts_tuple)
    n    = len(lats)

    if n == 0:
        return alts_tuple

    # Sous-échantillonnage pour éviter les doublons parfaits qui font planter les API
    indices_echantillon = []
    last_lon, last_lat = None, None
    for i in range(0, n, max(1, n // MAX_POINTS)):
        if lons[i] != last_lon or lats[i] != last_lat:
            indices_echantillon.append(i)
            last_lon, last_lat = lons[i], lats[i]

    alts_corrigees_echantillon = []

    # --- MÉTHODE ORS ---
    if methode == "ors":
        if not api_key:
            logger.warning("Clé ORS manquante pour la correction altimétrique.")
            return alts_tuple
            
        coords_ors = [[lons[i], lats[i]] for i in indices_echantillon]
        res_ors = _requete_ors_line(coords_ors, api_key)
        if res_ors and len(res_ors) == len(indices_echantillon):
            alts_corrigees_echantillon = res_ors
        else:
            logger.warning("Erreur avec ORS Elevation. Conservation des altitudes d'origine.")
            return alts_tuple

    # --- MÉTHODE SRTM ---
    elif methode == "srtm":
        locations = [{"latitude": lats[i], "longitude": lons[i]} for i in indices_echantillon]
        for start in range(0, len(locations), BATCH_SIZE):
            batch  = locations[start:start + BATCH_SIZE]
            result = _requete_batch(batch)
            if result is None:
                logger.warning("Open-Elevation indisponible — profil GPS conservé.")
                return alts_tuple
            alts_corrigees_echantillon.extend(result)

    # Sécurité
    if len(alts_corrigees_echantillon) != len(indices_echantillon):
        return alts_tuple

    # Interpolation linéaire pour reconstruire tous les points
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
