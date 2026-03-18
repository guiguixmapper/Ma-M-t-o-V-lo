"""
routing.py
==========
Intégration OpenRouteService pour l'estimation du temps de parcours.

ORS fournit un temps de trajet cycliste plus précis que la formule
vitesse_plat / facteur_pente, en tenant compte du profil réel de la route.

Fonctions publiques :
    - estimer_temps_ors(points_gpx, vitesse_kmh, api_key)
        → {"duree_s": int, "distance_m": int, "source": str}
"""

import streamlit as st
import requests
import logging
import math

logger = logging.getLogger(__name__)

ORS_URL      = "https://api.openrouteservice.org/v2/directions/cycling-regular"
MAX_WAYPOINTS = 50    # ORS accepte max 50 waypoints par requête


def _sous_echantillonner_waypoints(points_gpx, max_wp=MAX_WAYPOINTS) -> list:
    """
    Réduit la liste de points GPX à max_wp waypoints régulièrement espacés.
    Conserve toujours le premier et le dernier point.

    Returns:
        Liste de [lon, lat] (format ORS).
    """
    n   = len(points_gpx)
    if n <= max_wp:
        indices = range(n)
    else:
        pas     = (n - 1) / (max_wp - 1)
        indices = [round(i * pas) for i in range(max_wp)]
        indices[-1] = n - 1   # garantit le dernier point

    return [[points_gpx[i].longitude, points_gpx[i].latitude] for i in indices]


@st.cache_data(ttl=3600, show_spinner=False)
def estimer_temps_ors(
    coords_tuple: tuple,   # tuple de (lon, lat) — hashable pour le cache
    api_key: str,
) -> dict:
    """
    Estime la durée et la distance via OpenRouteService (cycling-regular).

    Args:
        coords_tuple : tuple de (lon, lat) sous-échantillonnés
        api_key      : clé API ORS

    Returns:
        {
            "duree_s":    int   — durée en secondes,
            "distance_m": int   — distance en mètres,
            "source":     str   — "ORS" ou "fallback"
        }
    """
    coords = [list(c) for c in coords_tuple]

    if not api_key or len(coords) < 2:
        return {"duree_s": 0, "distance_m": 0, "source": "fallback"}

    try:
        headers = {
            "Authorization": api_key,
            "Content-Type":  "application/json",
        }
        body = {
            "coordinates": coords,
            "preference":  "recommended",
            "units":       "m",
            "language":    "fr",
        }
        r = requests.post(ORS_URL, json=body, headers=headers, timeout=15)
        r.raise_for_status()
        data     = r.json()
        summary  = data["routes"][0]["summary"]
        return {
            "duree_s":    int(summary["duration"]),
            "distance_m": int(summary["distance"]),
            "source":     "ORS",
        }
    except Exception as e:
        logger.warning(f"ORS échoué : {e}")
        return {"duree_s": 0, "distance_m": 0, "source": "fallback"}


def preparer_coords_ors(points_gpx) -> tuple:
    """
    Prépare les waypoints pour ORS sous forme de tuple hashable (pour le cache).
    """
    waypoints = _sous_echantillonner_waypoints(points_gpx)
    return tuple(tuple(wp) for wp in waypoints)
