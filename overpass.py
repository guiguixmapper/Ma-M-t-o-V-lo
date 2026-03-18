"""
overpass.py
===========
Détection des cols et points remarquables sur un tracé GPX via l'API Overpass (OpenStreetMap).

On interroge OSM pour trouver les nœuds de type "col" (mountain_pass, saddle)
à proximité du tracé, puis on les associe aux ascensions détectées.

Fonctions publiques :
    - enrichir_cols(ascensions, points_gpx) → ascensions avec champ "Nom" ajouté
"""

import streamlit as st
import requests
import logging
import math

logger = logging.getLogger(__name__)

OVERPASS_URL    = "https://overpass-api.de/api/interpreter"
RAYON_SOMMET_M  = 500    # m — rayon de recherche autour du sommet d'une ascension
TIMEOUT_S       = 15


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Distance en mètres entre deux points GPS."""
    R    = 6371000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ   = math.radians(lat2 - lat1)
    dλ   = math.radians(lon2 - lon1)
    a    = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_au_km(points_gpx, km_cible) -> tuple | None:
    """
    Retourne le point GPX (lat, lon) le plus proche d'une distance donnée (km).
    Nécessite que les points GPX aient une distance cumulée.
    """
    if not points_gpx:
        return None
    # On reconstruit la distance cumulée à la volée
    dist_cum = 0.0
    best_pt  = points_gpx[0]
    best_diff = abs(dist_cum/1000 - km_cible)
    for i in range(1, len(points_gpx)):
        p1, p2 = points_gpx[i-1], points_gpx[i]
        d = p1.distance_2d(p2) or 0.0
        dist_cum += d
        diff = abs(dist_cum/1000 - km_cible)
        if diff < best_diff:
            best_diff = diff
            best_pt   = p2
    return best_pt.latitude, best_pt.longitude


def _requete_cols(lat: float, lon: float, rayon_m: int = RAYON_SOMMET_M) -> list:
    """
    Interroge Overpass pour trouver les cols/sommets dans un rayon autour d'un point.

    Returns:
        Liste de dicts {"nom": str, "alt": int|None, "lat": float, "lon": float, "dist_m": float}
    """
    query = f"""
    [out:json][timeout:{TIMEOUT_S}];
    (
      node["mountain_pass"="yes"](around:{rayon_m},{lat},{lon});
      node["natural"="saddle"](around:{rayon_m},{lat},{lon});
      node["natural"="peak"](around:{rayon_m},{lat},{lon});
    );
    out body;
    """
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=TIMEOUT_S + 5)
        r.raise_for_status()
        elements = r.json().get("elements", [])
        results  = []
        for el in elements:
            tags    = el.get("tags", {})
            nom     = (tags.get("name:fr")
                       or tags.get("name")
                       or tags.get("name:en")
                       or None)
            alt_tag = tags.get("ele")
            try:    alt = int(float(alt_tag)) if alt_tag else None
            except: alt = None
            dist = _haversine(lat, lon, el["lat"], el["lon"])
            results.append({
                "nom":    nom,
                "alt":    alt,
                "lat":    el["lat"],
                "lon":    el["lon"],
                "dist_m": dist,
            })
        # Trier par proximité
        results.sort(key=lambda x: x["dist_m"])
        return results
    except Exception as e:
        logger.warning(f"Overpass échoué pour ({lat:.4f}, {lon:.4f}) : {e}")
        return []


@st.cache_data(ttl=86400, show_spinner=False)
def _requete_cols_cached(lat: float, lon: float) -> list:
    """Version cachée 24h de _requete_cols."""
    return _requete_cols(lat, lon)


def enrichir_cols(ascensions: list, points_gpx: list) -> list:
    """
    Enrichit chaque ascension avec le nom OSM du col au sommet (si trouvé).

    Ajoute les clés :
        "Nom"         → str  — nom du col (ex. "Col du Galibier") ou "—"
        "Nom OSM alt" → int|None — altitude OSM du col (peut différer du GPX)

    Args:
        ascensions  : liste de dicts retournée par detecter_ascensions()
        points_gpx  : liste de points gpxpy

    Returns:
        La même liste enrichie (modifiée in-place ET retournée).
    """
    for asc in ascensions:
        coords = _point_au_km(points_gpx, asc["_sommet_km"])
        if coords is None:
            asc["Nom"]         = "—"
            asc["Nom OSM alt"] = None
            continue

        lat, lon = coords
        candidats = _requete_cols_cached(round(lat, 4), round(lon, 4))

        if candidats and candidats[0]["nom"]:
            meilleur        = candidats[0]
            asc["Nom"]      = meilleur["nom"]
            asc["Nom OSM alt"] = meilleur["alt"]
        else:
            asc["Nom"]         = "—"
            asc["Nom OSM alt"] = None

    return ascensions
