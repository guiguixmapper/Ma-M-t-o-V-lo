"""
overpass.py
===========
Détection des cols optimisée via une requête ciblée ("Sniper").
Inclut une rotation de serveurs miroirs (Load Balancing) et un backoff exponentiel
pour esquiver les erreurs 504 (Timeout) et 429 (Too Many Requests).
"""

import streamlit as st
import requests
import logging
import math
import time

logger = logging.getLogger(__name__)

# NOUVEAU : Liste des serveurs officiels et miroirs
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",        # Serveur principal
    "https://lz4.overpass-api.de/api/interpreter",    # Serveur miroir 1
    "https://z.overpass-api.de/api/interpreter",      # Serveur miroir 2
    "https://overpass.kumi.systems/api/interpreter"   # Serveur miroir alternatif
]

RAYON_SOMMET_M  = 500    
TIMEOUT_S       = 25     
MAX_RETRIES     = 4      # On a 4 serveurs, on tente 4 fois maximum


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

    query_parts = []
    for _, lat, lon in coords_sommets:
        query_parts.append(f'node["mountain_pass"="yes"](around:{RAYON_SOMMET_M},{lat:.5f},{lon:.5f});')
        query_parts.append(f'node["natural"="saddle"](around:{RAYON_SOMMET_M},{lat:.5f},{lon:.5f});')
        query_parts.append(f'node["natural"="peak"]["name"](around:{RAYON_SOMMET_M},{lat:.5f},{lon:.5f});')

    query_body = "\n".join(query_parts)
    
    query = f"""
    [out:json][timeout:{TIMEOUT_S}];
    (
{query_body}
    );
    out body;
    """

    osm_nodes = []
    succes_api = False
    
    # NOUVEAU : La boucle magique de rotation des serveurs
    for tentative in range(MAX_RETRIES):
        serveur_actuel = OVERPASS_URLS[tentative % len(OVERPASS_URLS)]
        
        try:
            r = requests.post(serveur_actuel, data={"data": query}, timeout=TIMEOUT_S + 5)
            
            # On attrape spécifiquement les erreurs de surcharge
            if r.status_code in [429, 504, 503]:
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
            break  # Victoire ! On sort de la boucle.
            
        except Exception as e:
            logger.warning(f"Tentative {tentative + 1} échouée sur {serveur_actuel} : {e}")
            if tentative < MAX_RETRIES - 1:
                # On attend de plus en plus longtemps pour se faire pardonner (3s, puis 6s, puis 9s)
                attente = (tentative + 1) * 3
                time.sleep(attente)

    if not succes_api:
        st.toast("⚠️ Tous les serveurs OpenStreetMap sont saturés actuellement. Les noms des cols seront absents.")

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
