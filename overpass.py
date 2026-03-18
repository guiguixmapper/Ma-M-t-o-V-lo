"""
overpass.py
===========
Détection des cols optimisée via une seule requête Bounding Box (BBox).
"""

import streamlit as st
import requests
import logging
import math

logger = logging.getLogger(__name__)

OVERPASS_URL    = "https://overpass-api.de/api/interpreter"
RAYON_SOMMET_M  = 500    # m — rayon de recherche local
TIMEOUT_S       = 25     # Légèrement augmenté pour une grande zone


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Distance en mètres entre deux points GPS."""
    R    = 6371000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ   = math.radians(lat2 - lat1)
    dλ   = math.radians(lon2 - lon1)
    a    = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_au_km(points_gpx, km_cible) -> tuple | None:
    if not points_gpx:
        return None
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


@st.cache_data(ttl=86400, show_spinner=False)
def _requete_cols_bbox(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list:
    """
    Interroge Overpass en UNE SEULE FOIS pour tout le rectangle du parcours.
    (south, west, north, east)
    """
    query = f"""
    [out:json][timeout:{TIMEOUT_S}];
    (
      node["mountain_pass"="yes"]({min_lat},{min_lon},{max_lat},{max_lon});
      node["natural"="saddle"]({min_lat},{min_lon},{max_lat},{max_lon});
      node["natural"="peak"]({min_lat},{min_lon},{max_lat},{max_lon});
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
            nom     = (tags.get("name:fr") or tags.get("name") or tags.get("name:en"))
            alt_tag = tags.get("ele")
            try:    alt = int(float(alt_tag)) if alt_tag else None
            except: alt = None
            results.append({
                "nom": nom,
                "alt": alt,
                "lat": el["lat"],
                "lon": el["lon"],
            })
        return results
    except Exception as e:
        logger.warning(f"Overpass batch échoué : {e}")
        return []


def enrichir_cols(ascensions: list, points_gpx: list) -> list:
    if not ascensions or not points_gpx:
        return ascensions

    # 1. Création de la Bounding Box avec une marge (~1km)
    lats = [p.latitude for p in points_gpx]
    lons = [p.longitude for p in points_gpx]
    min_lat, max_lat = min(lats) - 0.01, max(lats) + 0.01
    min_lon, max_lon = min(lons) - 0.01, max(lons) + 0.01

    # 2. Récupération de TOUS les cols de la région d'un coup
    osm_nodes = _requete_cols_bbox(min_lat, min_lon, max_lat, max_lon)

    # 3. Association locale
    for asc in ascensions:
        coords = _point_au_km(points_gpx, asc["_sommet_km"])
        if coords is None:
            asc["Nom"] = "—"; asc["Nom OSM alt"] = None
            continue

        lat, lon = coords
        meilleur_noeud = None
        meilleure_dist = RAYON_SOMMET_M

        for noeud in osm_nodes:
            if not noeud["nom"]: # On ignore les bosses sans nom
                continue
            dist = _haversine(lat, lon, noeud["lat"], noeud["lon"])
            if dist < meilleure_dist:
                meilleure_dist = dist
                meilleur_noeud = noeud

        if meilleur_noeud:
            asc["Nom"] = meilleur_noeud["nom"]
            asc["Nom OSM alt"] = meilleur_noeud["alt"]
        else:
            asc["Nom"] = "—"
            asc["Nom OSM alt"] = None

    return ascensions
