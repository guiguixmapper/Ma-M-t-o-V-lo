"""
overpass.py — v3
================
Nommage des cols via Nominatim (OpenStreetMap) — bien plus rapide qu'Overpass.

Nominatim utilise un index inversé : on donne des coordonnées, il retourne
le lieu OSM le plus proche. Contrairement à Overpass qui scanne une BBox,
Nominatim répond en < 1s par requête.

Pour accélérer encore, toutes les requêtes (une par col) sont lancées
en parallèle via ThreadPoolExecutor.

Politique d'utilisation Nominatim :
    - Max 1 requête/seconde par IP (géré par semaphore)
    - User-Agent obligatoire identifiant l'application
    - Cache 24h : les interactions UI ne redéclenchent jamais de requête réseau

Fonctions publiques :
    - enrichir_cols(ascensions, points_gpx) → ascensions enrichies avec "Nom" et "Nom OSM alt"
"""

import streamlit as st
import requests
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore

logger = logging.getLogger(__name__)

NOMINATIM_URL     = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {
    "User-Agent":      "VeloMeteoApp/7.0 (cycliste@example.com) Streamlit",
    "Accept-Language": "fr,en",
}

# Types OSM acceptés, par ordre de priorité
TYPES_ACCEPTES = {
    "mountain_pass": 0,
    "saddle":        1,
    "peak":          2,
    "locality":      3,
    "alpine_hut":    4,
}

# zoom=14 couvre environ 1km autour du point — bon compromis précision/couverture
ZOOM_NOMINATIM = 14

# Semaphore pour respecter la limite 1 req/s de Nominatim
_sem = Semaphore(1)


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Distance en mètres entre deux points GPS."""
    R  = 6371000
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a  = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_au_km(points_gpx, km_cible) -> tuple | None:
    """Retourne (lat, lon) du point GPX le plus proche d'une distance cible (km)."""
    if not points_gpx:
        return None
    dist_cum  = 0.0
    best_pt   = points_gpx[0]
    best_diff = abs(dist_cum / 1000 - km_cible)
    for i in range(1, len(points_gpx)):
        p1, p2 = points_gpx[i-1], points_gpx[i]
        dist_cum += p1.distance_2d(p2) or 0.0
        diff = abs(dist_cum / 1000 - km_cible)
        if diff < best_diff:
            best_diff = diff
            best_pt   = p2
    return best_pt.latitude, best_pt.longitude


@st.cache_data(ttl=86400, show_spinner=False)
def _nominatim_reverse(lat: float, lon: float) -> dict | None:
    """
    Appel Nominatim reverse geocoding mis en cache 24h.
    Les interactions UI ne redéclenchent jamais cet appel.
    """
    with _sem:
        try:
            r = requests.get(
                NOMINATIM_URL,
                params={
                    "lat":            lat,
                    "lon":            lon,
                    "format":         "jsonv2",
                    "zoom":           ZOOM_NOMINATIM,
                    "addressdetails": 0,
                    "extratags":      1,
                    "namedetails":    1,
                },
                headers=NOMINATIM_HEADERS,
                timeout=8,
            )
            r.raise_for_status()
            time.sleep(1.1)  # respect limite 1 req/s Nominatim
            return r.json()
        except Exception as e:
            logger.warning(f"Nominatim ({lat:.4f}, {lon:.4f}) : {e}")
            return None


def _extraire_nom_col(data: dict, alt_gpx: int | None) -> tuple:
    """
    Extrait (nom, alt_osm) depuis une réponse Nominatim.
    Retourne ("—", None) si le résultat n'est pas un col/sommet pertinent.
    """
    if not data:
        return "—", None

    osm_type = data.get("type", "")
    category = data.get("category", "")

    # Vérifier que c'est un type montagne accepté
    type_key = osm_type if osm_type in TYPES_ACCEPTES else None
    if type_key is None:
        type_key = category if category in TYPES_ACCEPTES else None
    if type_key is None:
        return "—", None

    # Nom : priorité français
    namedetails = data.get("namedetails", {})
    nom = (namedetails.get("name:fr")
           or namedetails.get("name")
           or data.get("display_name", "").split(",")[0].strip()
           or None)
    if not nom:
        return "—", None

    # Altitude OSM depuis extratags
    alt_osm = None
    ele = data.get("extratags", {}).get("ele")
    if ele:
        try:
            alt_osm = int(float(ele))
        except (ValueError, TypeError):
            pass

    # Filtre cohérence altitude : écarte les homonymes en plaine
    if alt_gpx and alt_osm and abs(alt_osm - alt_gpx) > 300:
        return "—", None

    return nom, alt_osm


def _requete_col(asc: dict, lat: float, lon: float, alt_gpx: int | None) -> dict:
    """Lance la requête Nominatim pour un col et retourne le résultat."""
    data = _nominatim_reverse(round(lat, 5), round(lon, 5))
    nom, alt_osm = _extraire_nom_col(data, alt_gpx)
    return {"asc": asc, "nom": nom, "alt_osm": alt_osm}


def enrichir_cols(ascensions: list, points_gpx: list) -> list:
    """
    Enrichit chaque ascension avec le nom OSM du col via Nominatim.

    Toutes les requêtes sont lancées en parallèle (ThreadPoolExecutor).
    Le cache 24h sur _nominatim_reverse garantit qu'aucune interaction UI
    ne redéclenche d'appel réseau.

    Ajoute "Nom" et "Nom OSM alt" à chaque ascension.
    """
    if not ascensions or not points_gpx:
        return ascensions

    # Préparer les jobs
    jobs = []
    for asc in ascensions:
        coords = _point_au_km(points_gpx, asc["_sommet_km"])
        if not coords:
            asc["Nom"] = "—"; asc["Nom OSM alt"] = None
            continue
        lat, lon = coords
        alt_gpx  = None
        try:
            alt_str = asc.get("Alt. sommet", "").replace(" m", "").strip()
            alt_gpx = int(alt_str) if alt_str else None
        except (ValueError, AttributeError):
            pass
        jobs.append((asc, lat, lon, alt_gpx))

    if not jobs:
        return ascensions

    # Requêtes parallèles — le semaphore garantit max 1 req/s malgré les threads
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_requete_col, asc, lat, lon, alt_gpx): asc
            for asc, lat, lon, alt_gpx in jobs
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                result["asc"]["Nom"]         = result["nom"]
                result["asc"]["Nom OSM alt"] = result["alt_osm"]
            except Exception as e:
                asc = futures[future]
                logger.warning(f"Erreur col km {asc.get('_sommet_km')} : {e}")
                asc["Nom"] = "—"; asc["Nom OSM alt"] = None

    return ascensions
