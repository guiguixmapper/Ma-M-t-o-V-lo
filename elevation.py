"""
elevation.py
============
Correction du profil altimétrique via Open-Elevation API.

L'API Open-Elevation fournit des altitudes issues de données SRTM (90m de résolution),
ce qui est souvent plus fiable que les données GPS brutes des fichiers GPX,
notamment pour les appareils d'entrée de gamme ou les exports Strava/Komoot.

Fonctions publiques :
    - corriger_profil(df)  → DataFrame avec altitudes corrigées (ou original si échec)
"""

import streamlit as st
import requests
import logging
import pandas as pd

logger = logging.getLogger(__name__)

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
BATCH_SIZE         = 100   # points par requête (limite API)
MAX_POINTS         = 2000  # on sous-échantillonne si le GPX est plus dense


def _sous_echantillonner(df, max_points=MAX_POINTS):
    """
    Réduit le DataFrame à max_points lignes régulièrement espacées.
    Retourne aussi le pas d'échantillonnage pour la reconstruction.
    """
    n    = len(df)
    if n <= max_points:
        return df.copy(), 1
    pas  = n // max_points
    return df.iloc[::pas].copy().reset_index(drop=True), pas


def _requete_batch(locations: list) -> list | None:
    """
    Envoie un batch de points à Open-Elevation.

    Args:
        locations : liste de {"latitude": float, "longitude": float}

    Returns:
        Liste d'altitudes (floats) dans le même ordre, ou None si erreur.
    """
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
def corriger_profil(lats_tuple: tuple, lons_tuple: tuple, alts_tuple: tuple) -> tuple:
    """
    Corrige les altitudes d'un profil GPX via Open-Elevation.

    Prend des tuples (hashables pour le cache Streamlit).

    Args:
        lats_tuple : latitudes des points GPX
        lons_tuple : longitudes des points GPX
        alts_tuple : altitudes brutes du GPX (fallback si API échoue)

    Returns:
        Tuple d'altitudes corrigées (même longueur que l'entrée).
        Retourne alts_tuple inchangé en cas d'échec.
    """
    lats = list(lats_tuple)
    lons = list(lons_tuple)
    alts = list(alts_tuple)
    n    = len(lats)

    if n == 0:
        return alts_tuple

    # Sous-échantillonnage si trop de points
    indices_echantillon = list(range(0, n, max(1, n // MAX_POINTS)))
    locations = [
        {"latitude": lats[i], "longitude": lons[i]}
        for i in indices_echantillon
    ]

    # Envoi par batches
    alts_corrigees_echantillon = []
    for start in range(0, len(locations), BATCH_SIZE):
        batch  = locations[start:start + BATCH_SIZE]
        result = _requete_batch(batch)
        if result is None:
            logger.warning("Open-Elevation indisponible — profil GPS conservé.")
            return alts_tuple
        alts_corrigees_echantillon.extend(result)

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
