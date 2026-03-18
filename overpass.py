"""
overpass.py
===========
Détection des cols (Méthode BBox simplifiée + User-Agent).
On demande tous les points de la zone d'un coup (très léger grâce au filtre ["name"]),
et on calcule les distances de 500m en local via Python (instantané).
"""

import streamlit as st
import requests
import logging
import math
import time

logger = logging.getLogger(__name__)

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter"
]

RAYON_SOMMET_M  = 500    
TIMEOUT_S       = 25     
MAX_RETRIES     = 3      


def _haversine(lat1, lon1, lat2, lon2) -> float:
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


def enrichir_cols(ascensions: list, points_gpx: list) -> list:
    if not ascensions or not points_gpx:
        return ascensions

    coords_sommets = []
    for asc in ascensions:
        coords = _point_au_km(points_gpx, asc["_sommet_km"])
        if coords:
            coords_sommets.append((asc, coords[0], coords[1]))
        else:
            asc["Nom"] = "—"
            asc["Nom OSM alt"] = None

    if not coords_sommets:
        return ascensions

    # 1. Bounding Box large englobant le parcours
    lats = [p.latitude for p in points_gpx]
    lons = [p.longitude for p in points_gpx]
    min_lat, max_lat = min(lats) - 0.05, max(lats) + 0.05
    min_lon, max_lon = min(lons) - 0.05, max(lons) + 0.05

    # 2. Requête ultra-simple : "Donne-moi les cols et pics nommés du rectangle"
    query = f"""
    [out:json][timeout:{TIMEOUT_S}][bbox:{min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f}];
    (
      node["mountain_pass"="yes"];
      node["natural"="saddle"];
      node["natural"="peak"]["name"];
    );
    out body;
    """

    # LE PASSE-DROIT : On se fait passer pour un vrai navigateur / une vraie application
    headers = {
        "User-Agent": "VeloMeteoApp/6.0 (Contact: cycliste@example.com) Streamlit",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    osm_nodes = []
    succes_api = False
    
    # 3. Interrogation d'Overpass
    for tentative in range(MAX_RETRIES):
        serveur_actuel = OVERPASS_URLS[tentative % len(OVERPASS_URLS)]
        try:
            r = requests.post(serveur_actuel, data={"data": query}, headers=headers, timeout=TIMEOUT_S)
            
            if r.status_code in [429, 503, 504]:
                raise Exception(f"Serveur surchargé (Code {r.status_code})")
                
            r.raise_for_status()
            elements = r.json().get("elements", [])
            
            for el in elements:
                tags = el.get("tags", {})
                nom = tags.get("name:fr") or tags.get("name") or tags.get("name:en")
                if not nom:
                    continue
                alt_tag = tags.get("ele")
                try:    alt = int(float(alt_tag)) if alt_tag else None
                except: alt = None
                
                osm_nodes.append({
                    "nom": nom,
                    "alt": alt,
                    "lat": el["lat"],
                    "lon": el["lon"],
                })
            
            succes_api = True
            break  # Succès immédiat, on sort de la boucle
            
        except Exception as e:
            logger.warning(f"Tentative {tentative + 1} échouée sur {serveur_actuel} : {e}")
            if tentative < MAX_RETRIES - 1:
                time.sleep(2)

    if not succes_api:
        st.toast("⚠️ OSM instable : noms des cols potentiellement manquants.")

    # 4. Association mathématique rapide en local (Python)
    for asc, lat, lon in coords_sommets:
        meilleur_noeud = None
        meilleure_dist = RAYON_SOMMET_M

        for noeud in osm_nodes:
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
