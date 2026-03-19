"""
🚴‍♂️ Vélo & Météo — v11 (Export PDF Kaleido, Fix Calendrier, Tableau Détail Restauré)
================================
Analyse de tracé GPX : météo en temps réel, cols UCI, profil interactif,
zones d'entraînement, score de conditions et Coach IA complet.
"""

import streamlit as st
import pandas as pd
import gpxpy
import folium
from streamlit_folium import st_folium
import requests
from datetime import datetime, timedelta, date
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import math
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==============================================================================
# STYLE GLOBAL
# ==============================================================================

CSS = """
<style>
  :root {
    --bleu: #2563eb; --bleu-l: #dbeafe;
    --gris: #6b7280; --border: #e2e8f0; --radius: 12px;
  }
  .app-header {
    background: linear-gradient(135deg, #1e40af 0%, #2563eb 55%, #0ea5e9 100%);
    border-radius: var(--radius); padding: 24px 32px 20px;
    margin-bottom: 20px; color: white;
  }
  .app-header h1 { font-size: 1.9rem; font-weight: 800; margin: 0; letter-spacing: -.5px; }
  .app-header p  { font-size: .9rem; margin: 5px 0 0; opacity: .85; }
  .soleil-row {
    display: flex; gap: 14px; flex-wrap: wrap;
    background: linear-gradient(90deg, #fef3c7, #fde68a);
    border-radius: var(--radius); padding: 12px 18px; margin: 10px 0; align-items: center;
  }
  .soleil-item .s-val { font-size: 1.05rem; font-weight: 700; color: #92400e; }
  .soleil-item .s-lbl { font-size: .7rem; color: #b45309; }
  @media (max-width: 640px) { .app-header h1 { font-size: 1.35rem; } }
</style>
"""

# ==============================================================================
# IMPORTS MODULES
# ==============================================================================

import climbing as climbing_module
from climbing import (
    detecter_ascensions, categoriser_uci, estimer_watts, estimer_fc,
    estimer_temps_col, calculer_calories, get_zone, zones_actives,
    COULEURS_CAT, LEGENDE_UCI,
)
from weather import (
    recuperer_fuseau, recuperer_meteo_batch, recuperer_soleil,
    extraire_meteo, direction_vent_relative, wind_chill,
    label_wind_chill, obtenir_icone_meteo,
)
from overpass import enrichir_cols
from gemini_coach import generer_briefing
from export_pdf import generer_roadbook_pdf


# ==============================================================================
# UTILITAIRES GPS
# ==============================================================================

def calculer_cap(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

@st.cache_data(show_spinner=False)
def parser_gpx(data):
    try:
        gpx = gpxpy.parse(data)
        return [p for t in gpx.tracks for s in t.segments for p in s.points]
    except Exception as e:
        logger.error(f"GPX : {e}"); return []


# ==============================================================================
# SCORE GLOBAL ET ANALYSE
# ==============================================================================

def analyser_meteo_detaillee(resultats, dist_tot):
    valides = [cp for cp in resultats if cp.get("temp_val") is not None]
    if not valides: return None

    cps_pluie = [cp for cp in valides if (cp.get("pluie_pct") or 0) >= 50]
    pct_pluie = len(cps_pluie) / len(valides) * 100

    premier_pluie = None
    for cp in valides:
        if (cp.get("pluie_pct") or 0) >= 50:
            premier_pluie = cp
            break

    compteur_effet = {"⬇️ Face": 0, "⬆️ Dos": 0, "↙️ Côté (D)": 0, "↘️ Côté (G)": 0, "—": 0}
    for cp in valides:
        effet = cp.get("effet", "—")
        compteur_effet[effet] = compteur_effet.get(effet, 0) + 1

    total_v = len(valides)
    pct_face  = round(compteur_effet["⬇️ Face"]    / total_v * 100)
    pct_dos   = round(compteur_effet["⬆️ Dos"]     / total_v * 100)
    pct_cote  = round((compteur_effet["↙️ Côté (D)"] + compteur_effet["↘️ Côté (G)"]) / total_v * 100)

    segments_face = []
    en_face = False
    debut_face = None
    for cp in valides:
        if cp.get("effet") == "⬇️ Face":
            if not en_face:
                en_face    = True
                debut_face = cp["Km"]
        else:
            if en_face:
                segments_face.append((debut_face, cp["Km"]))
                en_face = False
    if en_face: segments_face.append((debut_face, valides[-1]["Km"]))

    return {
        "pct_pluie":       round(pct_pluie),
        "premier_pluie":   premier_pluie,
        "pct_face":        pct_face,
        "pct_dos":         pct_dos,
        "pct_cote":        pct_cote,
        "segments_face":   segments_face,
        "n_valides":       total_v,
    }

def calculer_score(resultats, ascensions, d_plus, vitesse, ref_val, mode, poids):
    valides = [cp for cp in resultats if cp.get("temp_val") is not None]

    if valides:
        tm = sum(cp["temp_val"] for cp in valides) / len(valides)
        if   15 <= tm <= 22: s_temp = 2.0
        elif 10 <= tm <= 27: s_temp = 1.5
        elif  5 <= tm <= 32: s_temp = 0.8
        elif  0 <= tm:       s_temp = 0.3
        else:                s_temp = 0.0

        POIDS_EFFET = {"⬇️ Face": 1.5, "↙️ Côté (D)": 0.7, "↘️ Côté (G)": 0.7, "⬆️ Dos": -0.3, "—": 0.5}
        ve_moy = sum((cp.get("vent_val") or 0) * POIDS_EFFET.get(cp.get("effet", "—"), 0.5) for cp in valides) / len(valides)
        if   ve_moy <= 8:  s_vent = 2.0
        elif ve_moy <= 18: s_vent = 1.5
        elif ve_moy <= 30: s_vent = 0.8
        elif ve_moy <= 45: s_vent = 0.3
        else:              s_vent = 0.0

        pm = sum(cp.get("pluie_pct") or 0 for cp in valides) / len(valides)
        s_pluie = round(max(0.0, 2.0 * (1 - pm / 100)), 2)
        sm = s_temp + s_vent + s_pluie
    else:
        sm = 3.0   

    dist_km = sum(cp.get("Km", 0) for cp in resultats[-1:])
    if   dist_km < 30:  s_dist = 0.5
    elif dist_km < 80:  s_dist = 0.7
    elif dist_km < 150: s_dist = 0.9
    else:               s_dist = 1.0

    if   d_plus < 300:  s_dplus = 0.5
    elif d_plus < 1000: s_dplus = 0.7
    elif d_plus < 2500: s_dplus = 0.9
    else:               s_dplus = 1.0

    s_parcours = s_dist + s_dplus

    if ascensions and ref_val > 0:
        wm  = sum(estimer_watts(a["_pente_moy"], vitesse, poids) for a in ascensions) / len(ascensions)
        pct = wm / ref_val if mode == "⚡ Puissance" else 0.85
        if   pct <= 0.50: s_effort = 0.8
        elif pct <= 0.70: s_effort = 1.2
        elif pct <= 0.90: s_effort = 2.0
        elif pct <= 1.05: s_effort = 1.5
        else:             s_effort = 0.8
    else:
        s_effort = 1.0

    sc = max(2.0, s_parcours + s_effort)
    total = round(min(10.0, max(0.0, sm + sc)), 1)
    lbl   = ("🔴 Déconseillé"       if total < 3.5 else
             "🟠 Conditions difficiles" if total < 5.0 else
             "🟡 Conditions correctes"  if total < 6.5 else
             "🟢 Bonne sortie"          if total < 8.0 else
             "⭐ Conditions idéales")

    return {
        "total":        total,
        "label":        lbl,
        "score_meteo":  round(max(0.0, sm), 1),
        "score_cols":   round(sc, 1),
        "score_effort": round(s_effort, 1),
    }


# ==============================================================================
# GRAPHIQUES
# ==============================================================================

def creer_figure_profil(df, ascensions, vitesse, ref_val, mode, poids, idx_survol=None):
    fig   = go.Figure()
    dists = df["Distance (km)"].tolist()
    alts  = df["Altitude (m)"].tolist()
    zones = zones_actives(mode)
    fig.add_trace(go.Scatter(
        x=dists, y=alts, fill="tozeroy", fillcolor="rgba(59,130,246,0.12)",
        line=dict(color="#3b82f6", width=2),
        hovertemplate="<b>Km %{x:.1f}</b><br>Altitude : %{y:.0f} m<extra></extra>",
        name="Profil"))
    for i, asc in enumerate(ascensions):
        d0, d1 = asc["_debut_km"], asc["_sommet_km"]
        cat    = asc["Catégorie"]
        nom    = asc.get("Nom", "—")
        coul   = COULEURS_CAT.get(cat, "#94a3b8")
        op     = 1.0 if idx_survol is None or idx_survol == i else 0.2
        sx     = [d for d in dists if d0 <= d <= d1]
        sy     = [alts[j] for j, d in enumerate(dists) if d0 <= d <= d1]
        if not sx: continue
        w = estimer_watts(asc["_pente_moy"], vitesse, poids)
        _, zlbl, zcoul = get_zone(w, ref_val, zones)
        r, g, b = int(zcoul[1:3],16), int(zcoul[3:5],16), int(zcoul[5:7],16)
        hover_extra = (f"FC est. : {estimer_fc(w, ref_val, ref_val)}bpm"
                       if mode == "🫀 Fréquence Cardiaque"
                       else f"Puissance est. : {w} W ({round(w/ref_val*100) if ref_val>0 else '?'}% FTP)")
        fig.add_trace(go.Scatter(
            x=sx, y=sy, fill="tozeroy",
            fillcolor=f"rgba({r},{g},{b},{round(op*0.35,2)})",
            line=dict(color=coul, width=3 if idx_survol==i else 2), opacity=op,
            hovertemplate=(f"<b>{cat}{' — '+nom if nom!='—' else ''}</b>"
                           f"<br>Km %{{x:.1f}}<br>Alt : %{{y:.0f}} m<br>{hover_extra}<extra></extra>"),
            name=nom if nom != "—" else cat, showlegend=True, legendgroup=cat))
        fig.add_annotation(
            x=d1, y=sy[-1] if sy else 0,
            text=f"▲ {nom if nom != '—' else cat.split()[0]}",
            showarrow=True, arrowhead=2, arrowsize=.8,
            arrowcolor=coul, font=dict(size=10, color=coul),
            bgcolor="white", bordercolor=coul, borderwidth=1, opacity=op)
    fig.update_layout(
        height=500, margin=dict(l=50,r=20,t=30,b=40),
        xaxis=dict(title="Distance (km)", showgrid=True, gridcolor="#e2e8f0",
                   title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b")),
        yaxis=dict(title="Altitude (m)", showgrid=True, gridcolor="#e2e8f0",
                   title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b")),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color="#1e293b"), bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="#e2e8f0", borderwidth=1),
        hovermode="x unified", plot_bgcolor="white", paper_bgcolor="white",
        font=dict(color="#1e293b"))
    return fig

def creer_figure_col(df_profil, asc, nb_segments=None):
    d0, d1 = asc["_debut_km"], asc["_sommet_km"]
    dk     = d1 - d0
    mask      = [d0 <= d <= d1 for d in df_profil["Distance (km)"]]
    dists_col = [d for d, m in zip(df_profil["Distance (km)"], mask) if m]
    alts_col  = [a for a, m in zip(df_profil["Altitude (m)"], mask) if m]
    if len(dists_col) < 2: return None
    seg_km = dk / nb_segments if nb_segments else (0.5 if dk < 5 else 1.0 if dk < 15 else 2.0)

    def couleur_pente(p):
        if p < 3:    return "#22c55e"
        elif p < 6:  return "#84cc16"
        elif p < 8:  return "#eab308"
        elif p < 10: return "#f97316"
        elif p < 12: return "#ef4444"
        else:        return "#7f1d1d"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dists_col, y=alts_col, fill="tozeroy",
        fillcolor="rgba(203,213,225,0.2)", line=dict(color="#94a3b8", width=1),
        hoverinfo="skip", showlegend=False))
    km_d = dists_col[0]
    while km_d < dists_col[-1] - 0.05:
        km_f = min(km_d + seg_km, dists_col[-1])
        sx = [d for d in dists_col if km_d <= d <= km_f]
        sy = [alts_col[j] for j, d in enumerate(dists_col) if km_d <= d <= km_f]
        if len(sx) >= 2:
            dist_m = (sx[-1] - sx[0]) * 1000
            pente  = (max(0, sy[-1]-sy[0]) / dist_m * 100) if dist_m > 0 else 0
            coul   = couleur_pente(pente)
            r, g, b = int(coul[1:3],16), int(coul[3:5],16), int(coul[5:7],16)
            fig.add_trace(go.Scatter(
                x=sx, y=sy, fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.4)",
                line=dict(color=coul, width=3),
                hovertemplate=f"<b>{round(pente,1)}%</b><br>Km %{{x:.1f}}<br>Alt : %{{y:.0f}} m<extra></extra>",
                showlegend=False))
            if dist_m > 300:
                fig.add_annotation(
                    x=(sx[0]+sx[-1])/2, y=sy[len(sy)//2],
                    text=f"<b>{round(pente,1)}%</b>", showarrow=False,
                    font=dict(size=10, color=coul), bgcolor="rgba(255,255,255,0.8)",
                    bordercolor=coul, borderwidth=1, yshift=12)
        km_d = km_f
    fig.add_trace(go.Scatter(x=dists_col, y=alts_col, mode="lines",
        line=dict(color="#1e293b", width=2),
        hovertemplate="Km %{x:.1f} — Alt : %{y:.0f} m<extra></extra>",
        showlegend=False))
    nom   = asc.get("Nom", "—")
    titre = (f"{nom+' — ' if nom != '—' else ''}{asc['Catégorie']} — "
             f"{asc['Longueur']} · {asc['Dénivelé']} · {asc['Pente moy.']} moy. · {asc['Pente max']} max")
    fig.update_layout(
        height=380, margin=dict(l=50,r=20,t=40,b=40),
        xaxis=dict(title="Distance (km)", showgrid=True, gridcolor="#f1f5f9",
                   title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b")),
        yaxis=dict(title="Altitude (m)", showgrid=True, gridcolor="#f1f5f9",
                   title_font=dict(color="#1e293b"), tickfont=dict(color="#1e293b")),
        plot_bgcolor="white", paper_bgcolor="white", font=dict(color="#1e293b"),
        hovermode="x unified",
        title=dict(text=titre, font=dict(size=13, color="#1e293b"), x=0))
    return fig

def creer_figure_meteo(resultats):
    kms, temps, vents, rafales, pluies, cv, cp_ = [], [], [], [], [], [], []
    for r in resultats:
        t = r.get("temp_val"); v = r.get("vent_val")
        if t is None or v is None: continue
        kms.append(r["Km"]); temps.append(t); vents.append(v)
        rafales.append(r.get("rafales_val") or v); pluies.append(r.get("pluie_pct") or 0)
        cv.append("#ef4444" if v>=40 else "#f97316" if v>=25 else "#eab308" if v>=10 else "#22c55e")
        p = r.get("pluie_pct") or 0
        cp_.append("#1d4ed8" if p>=70 else "#2563eb" if p>=40 else "#60a5fa" if p>=20 else "#bfdbfe")
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.40, 0.33, 0.27], vertical_spacing=0.06,
        subplot_titles=["🌡️ Température (°C)", "💨 Vent moyen & Rafales (km/h)", "🌧️ Probabilité de pluie (%)"])
    if kms:
        ct = ["#8b5cf6" if t<5 else "#3b82f6" if t<15 else "#22c55e" if t<22
              else "#f97316" if t<30 else "#ef4444" for t in temps]
        fig.add_trace(go.Scatter(x=kms, y=temps, mode="lines+markers",
            line=dict(color="#f97316", width=2.5),
            marker=dict(color=ct, size=9, line=dict(color="white", width=1.5)),
            hovertemplate="<b>Km %{x}</b><br>Temp : %{y}°C<extra></extra>",
            name="Température"), row=1, col=1)
        fig.add_hrect(y0=15, y1=22, row=1, col=1, fillcolor="rgba(34,197,94,0.10)", line_width=0,
            annotation_text="Zone idéale (15–22°C)", annotation_font_size=9,
            annotation_font_color="#16a34a", annotation_position="top left")
        fig.add_trace(go.Bar(x=kms, y=vents, marker_color=cv, name="Vent moyen",
            hovertemplate="<b>Km %{x}</b><br>Vent : %{y} km/h<extra></extra>"), row=2, col=1)
        fig.add_trace(go.Scatter(x=kms, y=rafales, mode="lines+markers",
            line=dict(color="#475569", width=1.8, dash="dot"),
            marker=dict(size=5, color="#475569"), name="Rafales",
            hovertemplate="<b>Km %{x}</b><br>Rafales : %{y} km/h<extra></extra>"), row=2, col=1)
        fig.add_trace(go.Bar(x=kms, y=pluies, marker_color=cp_, name="Pluie",
            hovertemplate="<b>Km %{x}</b><br>Pluie : %{y}%<extra></extra>"), row=3, col=1)
        fig.add_hline(y=50, row=3, col=1, line_dash="dot", line_color="#64748b", line_width=1.5,
            annotation_text="Seuil 50%", annotation_font_size=9,
            annotation_font_color="#64748b", annotation_position="top right")
    fig.update_layout(height=620, margin=dict(l=55,r=20,t=45,b=40),
        hovermode="x unified", plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False, dragmode=False, font=dict(color="#1e293b"),
        annotationdefaults=dict(font=dict(color="#1e293b")))
    for ann in fig.layout.annotations:
        ann.font.color = "#1e293b"; ann.font.size = 13
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9", row=1, col=1, title_text="°C")
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9", row=2, col=1, title_text="km/h", rangemode="tozero")
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9", row=3, col=1, title_text="%", range=[0,105])
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9", row=1, col=1)
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9", row=2, col=1)
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9", title_text="Distance (km)", row=3, col=1)
    return fig


# ==============================================================================
# CARTE
# ==============================================================================

def creer_carte(points_gpx, resultats, ascensions, tiles="CartoDB positron", attr=None):
    kwargs = dict(location=[points_gpx[0].latitude, points_gpx[0].longitude],
                  zoom_start=11, tiles=tiles, scrollWheelZoom=True)
    if attr: kwargs["attr"] = attr
    carte = folium.Map(**kwargs)
    
    fg_meteo = folium.FeatureGroup(name="🌤️ Météo",      show=True)
    fg_cols  = folium.FeatureGroup(name="🏔️ Ascensions", show=True)
    fg_trace = folium.FeatureGroup(name="📍 Parcours",   show=True)
    
    folium.PolyLine([[p.latitude, p.longitude] for p in points_gpx],
                    color="#2563eb", weight=5, opacity=0.9).add_to(fg_trace)
    folium.Marker([points_gpx[0].latitude, points_gpx[0].longitude], tooltip="🚦 Départ",
                  icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(fg_trace)
    folium.Marker([points_gpx[-1].latitude, points_gpx[-1].longitude], tooltip="🏁 Arrivée",
                  icon=folium.Icon(color="red", icon="flag", prefix="fa")).add_to(fg_trace)
    
    COULEUR_COL = {"🔴 HC":"red","🟠 1ère Cat.":"orange",
                   "🟡 2ème Cat.":"beige","🟢 3ème Cat.":"green","🔵 4ème Cat.":"blue"}
    
    for asc in ascensions:
        lat_s = asc.get("_lat_sommet")
        lon_s = asc.get("_lon_sommet")
        if lat_s is None or lon_s is None:
            continue
        nom     = asc.get("Nom", "—")
        coul    = COULEUR_COL.get(asc["Catégorie"], "blue")
        alt_osm = asc.get("Nom OSM alt")
        alt_line = (f'<div>⛰️ Sommet GPX : {asc["Alt. sommet"]}'
                    + (f' &nbsp;·&nbsp; OSM : {alt_osm} m' if alt_osm else '') + '</div>')
        popup_col = (
            '<div style="font-family:sans-serif;font-size:12px;min-width:180px">'
            f'<div style="font-weight:700;font-size:14px;margin-bottom:6px">'
            f'{nom+" — " if nom != "—" else ""}{asc["Catégorie"]}</div>'
            f'<div>📏 {asc["Longueur"]} &nbsp;·&nbsp; D+ {asc["Dénivelé"]}</div>'
            f'<div>📐 {asc["Pente moy."]} moy. &nbsp;·&nbsp; {asc["Pente max"]} max</div>'
            + alt_line
            + (f'<div style="margin-top:5px">⏱️ {asc.get("Temps col","—")} &nbsp;·&nbsp; arr. {asc.get("Arrivée sommet","—")}</div>'
               if asc.get("Temps col") else "")
            + '</div>')
        folium.Marker([lat_s, lon_s],
            popup=folium.Popup(popup_col, max_width=260),
            tooltip=folium.Tooltip(f'▲ {nom if nom != "—" else asc["Catégorie"]} — {asc["Alt. sommet"]}', sticky=True),
            icon=folium.Icon(color=coul, icon="chevron-up", prefix="fa")).add_to(fg_cols)
            
    for cp in resultats:
        t = cp.get("temp_val")
        if t is None: continue
        dd = cp.get("dir_deg"); vv = cp.get("vent_val", 0) or 0
        fc  = "#ef4444" if vv>=40 else "#f97316" if vv>=25 else "#eab308" if vv>=10 else "#22c55e"
        rot = (dd + 180) % 360 if dd is not None else 0
        svg = (f'<svg width="16" height="16" viewBox="0 0 28 28" style="vertical-align:middle">'
               f'<g transform="rotate({rot},14,14)"><polygon points="14,2 20,22 14,18 8,22" fill="{fc}"/>'
               f'</g></svg>') if dd is not None else "💨"
        pp = cp.get("pluie_pct")
        if pp is not None:
            pc    = "#1d4ed8" if pp>=70 else "#2563eb" if pp>=40 else "#60a5fa"
            barre = (f'<div style="margin:4px 0 2px;font-size:11px">&#127783; Pluie : <b>{pp}%</b></div>'
                     '<div style="background:#e2e8f0;border-radius:4px;height:6px;width:100%">'
                     f'<div style="background:{pc};width:{pp}%;height:6px;border-radius:4px"></div></div>')
        else:
            barre = '<div style="font-size:11px">&#127783; Pluie : —</div>'
        res    = cp.get("ressenti")
        popup  = (
            '<div style="font-family:sans-serif;font-size:12px;min-width:200px">'
            f'<div style="font-weight:700;font-size:13px;border-bottom:1px solid #e2e8f0;'
            f'padding-bottom:4px;margin-bottom:6px">{cp["Heure"]} — Km {cp["Km"]}</div>'
            f'<div style="color:#6b7280;margin-bottom:5px">⛰️ Alt : {cp["Alt (m)"]} m</div>'
            f'<div style="font-size:15px;margin-bottom:3px">{cp["Ciel"]} <b>{t}°C</b>'
            + (f' <span style="color:#6b7280;font-size:11px">(ressenti {res}°C)</span>' if res else "")
            + f'</div>{barre}'
            f'<div style="margin-top:7px;padding-top:5px;border-top:1px solid #f1f5f9">'
            f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:2px">'
            f'{svg} <b>{vv} km/h</b> <span style="color:#6b7280">du {cp["Dir"]}</span></div>'
            f'<div style="color:#6b7280;font-size:11px">Rafales : {cp.get("rafales_val","—")} km/h</div>'
            f'<div style="margin-top:3px;font-size:11px">🚴 <b>{cp.get("effet","—")}</b></div>'
            '</div></div>')
        folium.Marker([cp["lat"], cp["lon"]],
            popup=folium.Popup(popup, max_width=280),
            tooltip=folium.Tooltip(
                f"{cp['Heure']} | {cp['Ciel']} {t}°C | "
                f'<svg width="12" height="12" viewBox="0 0 28 28" style="vertical-align:middle">'
                f'<g transform="rotate({rot},14,14)"><polygon points="14,2 20,22 14,18 8,22" fill="{fc}"/></g></svg>'
                f" {vv} km/h", sticky=True),
            icon=folium.Icon(color="blue", icon="info-sign")).add_to(fg_meteo)

    fg_meteo.add_to(carte)
    fg_cols.add_to(carte)
    fg_trace.add_to(carte)
    folium.LayerControl(collapsed=False, position="topright").add_to(carte)
    return carte


# ==============================================================================
# APPLICATION PRINCIPALE
# ==============================================================================

def main():
    st.set_page_config(page_title="Vélo & Météo", page_icon="🚴‍♂️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("""
    <div class="app-header">
      <h1>🚴‍♂️ Vélo &amp; Météo</h1>
      <p>Analysez votre tracé GPX : météo en temps réel, cols UCI, profil interactif et zones d'entraînement.</p>
    </div>""", unsafe_allow_html=True)

    # ── SIDEBAR ───────────────────────────────────────────────────────────────
    st.sidebar.header("⚙️ Paramètres")
    fichier   = st.sidebar.file_uploader("📂 Fichier GPX", type=["gpx"])
    st.sidebar.divider()
    date_dep  = st.sidebar.date_input("📅 Date de départ", value=date.today())
    heure_dep = st.sidebar.time_input("🕐 Heure de départ")
    vitesse   = st.sidebar.number_input("🚴 Vitesse moy. plat (km/h)", 5, 60, 25)
    st.sidebar.divider()
    mode = st.sidebar.radio("📊 Mode d'analyse", ["⚡ Puissance", "🫀 Fréquence Cardiaque"], horizontal=True)
    if mode == "⚡ Puissance":
        ref_val = st.sidebar.number_input("⚡ FTP (W)", 50, 500, 220)
        fc_max  = None; ftp_fc = ref_val
        poids   = st.sidebar.number_input("⚖️ Poids cycliste + vélo (kg)", 40, 150, 75)
    else:
        ref_val = st.sidebar.number_input("❤️ FC max (bpm)", 100, 220, 185)
        fc_max  = ref_val
        ftp_fc  = st.sidebar.number_input("⚡ FTP estimé (W)", 50, 500, 220)
        poids   = st.sidebar.number_input("⚖️ Poids cycliste + vélo (kg)", 40, 150, 75)
    st.sidebar.divider()
    intervalle = st.sidebar.selectbox("⏱️ Intervalle checkpoints météo",
                    options=[5,10,15], index=1, format_func=lambda x: f"Toutes les {x} min")
    intervalle_sec = intervalle * 60

    # ── DÉTECTION DES MONTÉES ─────────────────────────────────────────────────
    st.sidebar.divider()
    with st.sidebar.expander("🏔️ Détection des montées", expanded=False):

        if "sensibilite" not in st.session_state: st.session_state.sensibilite = 3
        if "seuil_debut" not in st.session_state: st.session_state.seuil_debut = float(climbing_module.SEUIL_DEBUT)
        if "seuil_fin" not in st.session_state: st.session_state.seuil_fin = float(climbing_module.SEUIL_FIN)
        if "fusion_m" not in st.session_state: st.session_state.fusion_m = int(climbing_module.MAX_DESCENTE_FUSION_M)

        SENSIBILITE_PARAMS = {
            1: (4.0, 2.0,  20), 2: (3.0, 1.5,  35), 3: (2.0, 1.0,  50),
            4: (1.5, 0.5,  70), 5: (0.5, 0.0, 100),
        }

        niv = st.slider("🎚️ Sensibilité de détection", 1, 5, step=1, key="sensibilite")

        if st.button("↺ Réinitialiser", use_container_width=True):
            st.session_state["_reset_demande"] = True
            st.rerun()

        if st.session_state.pop("_reset_demande", False):
            for k in ["sensibilite", "seuil_debut", "seuil_fin", "fusion_m", "_last_sensibilite"]:
                st.session_state.pop(k, None)
            st.rerun()

        with st.expander("⚙️ Réglages fins", expanded=False):
            sd_sync, sf_sync, fm_sync = SENSIBILITE_PARAMS[niv]
            if st.session_state.get("_last_sensibilite") != niv:
                st.session_state.seuil_debut = sd_sync
                st.session_state.seuil_fin   = sf_sync
                st.session_state.fusion_m    = fm_sync
                st.session_state["_last_sensibilite"] = niv

            st.slider("Seuil de départ (%)", 0.5, 5.0, step=0.5, key="seuil_debut")
            st.slider("Seuil de fin (%)", 0.0, 3.0, step=0.5, key="seuil_fin")
            st.slider("Fusion (D− max, m)", 10, 200, step=10, key="fusion_m")

        climbing_module.SEUIL_DEBUT           = st.session_state.seuil_debut
        climbing_module.SEUIL_FIN             = st.session_state.seuil_fin
        climbing_module.MAX_DESCENTE_FUSION_M = st.session_state.fusion_m

    # ── OPTIONS AVANCÉES ──────────────────────────────────────────────────────
    st.sidebar.divider()
    with st.sidebar.expander("🔧 Options avancées", expanded=False):
        noms_osm = st.toggle("🗺️ Nommer les cols (OSM)", value=False)
        gemini_key = st.text_input("🤖 Clé API Gemini", value="", type="password")

    ph_fuseau = st.sidebar.empty()
    ph_fuseau.info("🌍 Fuseau : en attente…")

    if fichier is None:
        st.info("👈 Importez un fichier GPX dans la barre latérale pour commencer l'analyse.")
        return

    # ── CHARGEMENT ────────────────────────────────────────────────────────────
    etapes = st.empty()
    with etapes.container():
        with st.spinner("📍 Lecture du fichier GPX…"):
            points_gpx = parser_gpx(fichier.read())
    if not points_gpx: st.error("❌ Fichier GPX vide."); return

    with etapes.container():
        with st.spinner("🌍 Fuseau horaire…"):
            fuseau = recuperer_fuseau(points_gpx[0].latitude, points_gpx[0].longitude)
    ph_fuseau.success(f"🌍 **{fuseau}**")
    date_depart = datetime.combine(date_dep, heure_dep)

    with etapes.container():
        with st.spinner("🌅 Lever/coucher du soleil…"):
            infos_soleil = recuperer_soleil(points_gpx[0].latitude, points_gpx[0].longitude, date_dep.strftime("%Y-%m-%d"))

    # ── CALCULS PARCOURS ─────────────────────────────────────────────────────
    with etapes.container():
        with st.spinner("📐 Calcul du parcours…"):
            checkpoints = []; profil_data = []
            dist_tot = d_plus = d_moins = temps_s = prochain = cap = 0.0
            vms = (vitesse * 1000) / 3600
            for i in range(1, len(points_gpx)):
                p1, p2 = points_gpx[i-1], points_gpx[i]
                d  = p1.distance_2d(p2) or 0.0; dp = 0.0
                if p1.elevation is not None and p2.elevation is not None:
                    dif = p2.elevation - p1.elevation
                    if dif > 0: dp = dif; d_plus += dif
                    else: d_moins += abs(dif)
                dist_tot += d; temps_s += (d + dp * 10) / vms
                cap = calculer_cap(p1.latitude, p1.longitude, p2.latitude, p2.longitude)
                profil_data.append({"Distance (km)": round(dist_tot/1000, 3), "Altitude (m)": p2.elevation or 0})
                if temps_s >= prochain:
                    hp = date_depart + timedelta(seconds=temps_s)
                    checkpoints.append({
                        "lat": p2.latitude, "lon": p2.longitude, "Cap": cap,
                        "Heure": hp.strftime("%d/%m %H:%M"),
                        "Heure_API": hp.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"),
                        "Km": round(dist_tot/1000, 1), "Alt (m)": int(p2.elevation) if p2.elevation else 0,
                    })
                    prochain += intervalle_sec

    heure_arr = date_depart + timedelta(seconds=temps_s)
    pf = points_gpx[-1]
    checkpoints.append({
        "lat": pf.latitude, "lon": pf.longitude, "Cap": cap,
        "Heure": heure_arr.strftime("%d/%m %H:%M") + " 🏁",
        "Heure_API": heure_arr.replace(minute=0, second=0).strftime("%Y-%m-%dT%H:00"),
        "Km": round(dist_tot/1000, 1), "Alt (m)": int(pf.elevation) if pf.elevation else 0,
    })
    df_profil = pd.DataFrame(profil_data)

    # ── ASCENSIONS ────────────────────────────────────────────────────────────
    with etapes.container():
        with st.spinner("⛰️ Détection des ascensions…"):
            ascensions = detecter_ascensions(df_profil)

    if ascensions:
        dist_cum = 0.0
        pt_par_km = {} 
        for i in range(1, len(points_gpx)):
            p1, p2 = points_gpx[i-1], points_gpx[i]
            dist_cum += p1.distance_2d(p2) or 0.0
            km = round(dist_cum / 1000, 3)
            pt_par_km[km] = p2

        def coords_au_km(km_cible):
            if not pt_par_km: return None, None
            km_proche = min(pt_par_km.keys(), key=lambda k: abs(k - km_cible))
            pt = pt_par_km[km_proche]
            return pt.latitude, pt.longitude

        for asc in ascensions:
            lat_s, lon_s = coords_au_km(asc["_sommet_km"])
            lat_d, lon_d = coords_au_km(asc["_debut_km"])
            asc["_lat_sommet"] = lat_s
            asc["_lon_sommet"] = lon_s

    if noms_osm and ascensions:
        with etapes.container():
            with st.spinner("🗺️ Recherche des noms (OSM)…"):
                ascensions = enrichir_cols(ascensions, points_gpx)

    for asc in ascensions:
        asc.setdefault("Nom", "—")
        asc.setdefault("Nom OSM alt", None)

    # ── MÉTÉO ─────────────────────────────────────────────────────────────────
    with etapes.container():
        with st.spinner("📡 Récupération météo…"):
            frozen   = tuple((cp["lat"], cp["lon"], cp["Heure_API"]) for cp in checkpoints)
            rep_list = recuperer_meteo_batch(frozen)
    etapes.empty()

    resultats = []; err_meteo = rep_list is None
    if err_meteo:
        st.warning("⚠️ Météo indisponible.")
        for cp in checkpoints:
            cp.update(Ciel="—", temp_val=None, Pluie="—", pluie_pct=None, vent_val=None, rafales_val=None, Dir="—", dir_deg=None, effet="—", ressenti=None)
            resultats.append(cp)
    else:
        for i, cp in enumerate(checkpoints):
            m = extraire_meteo(rep_list[i] if i < len(rep_list) else {}, cp["Heure_API"])
            if m["dir_deg"] is not None: m["effet"] = direction_vent_relative(cp["Cap"], m["dir_deg"])
            cp.update(m); resultats.append(cp)

    dh = int(temps_s // 3600); dm = int((temps_s % 3600) // 60)
    score    = calculer_score(resultats, ascensions, d_plus, vitesse, ref_val, mode, poids)
    calories = calculer_calories(max(1, poids - 10), temps_s, dist_tot, d_plus, vitesse)
    analyse_meteo = analyser_meteo_detaillee(resultats, dist_tot)

    for asc in ascensions:
        temps_jusqu_debut = (asc["_debut_km"] / vitesse) * 3600
        mins_col, vit_col = estimer_temps_col(asc["_sommet_km"] - asc["_debut_km"], asc["_pente_moy"], vitesse)
        heure_sommet = date_depart + timedelta(seconds=temps_jusqu_debut) + timedelta(minutes=mins_col)
        asc["Temps col"]      = f"{mins_col} min ({vit_col} km/h)"
        asc["Arrivée sommet"] = heure_sommet.strftime("%H:%M")

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1e3a5f,#1e40af);border-radius:12px;
                padding:16px 24px;color:white;margin:12px 0;
                display:flex;align-items:center;gap:0;flex-wrap:wrap">
      <div style="min-width:160px;padding-right:24px;border-right:1px solid rgba(255,255,255,0.25)">
        <div style="font-size:2.8rem;font-weight:900;line-height:1">{score['total']}<span style="font-size:1.2rem">/10</span></div>
        <div style="font-size:.95rem;font-weight:600;margin-top:2px">{score['label']}</div>
      </div>
      <div style="display:flex;gap:0;flex:1;flex-wrap:wrap;padding-left:8px">
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{round(dist_tot/1000,1)}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">km</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">📏 Distance</div>
        </div>
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{int(d_plus)}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">m</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">⬆️ D+</div>
        </div>
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px;border-right:1px solid rgba(255,255,255,0.2)">
          <div style="font-size:1.9rem;font-weight:800">{dh}h{dm:02d}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">min</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">⏱️ Durée</div>
        </div>
        <div style="flex:1;min-width:90px;text-align:center;padding:6px 12px">
          <div style="font-size:1.9rem;font-weight:800">{len(ascensions)}</div>
          <div style="font-size:.9rem;color:rgba(255,255,255,0.85)">cols</div>
          <div style="font-size:.75rem;color:rgba(255,255,255,0.6)">🏔️ Détectés</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── ONGLETS ───────────────────────────────────────────────────────────────
    tab_carte, tab_profil, tab_meteo, tab_cols, tab_detail, tab_analyse = st.tabs([
        "🗺️ Carte", "⛰️ Profil & Cols", "🌤️ Météo", "🏔️ Ascensions", "📋 Détail", "🤖 Coach IA"
    ])

    with tab_carte:
        fond_choisi = st.selectbox("🖼️ Fond de carte", options=["CartoDB positron", "OpenStreetMap"], index=0)
        carte = creer_carte(points_gpx, resultats, ascensions, fond_choisi)
        st_folium(carte, width="100%", height=700, returned_objects=[])
        
        st.divider()
        if st.button("📥 Télécharger le Roadbook (PDF)", type="primary", use_container_width=True):
            with st.spinner("Génération du PDF en cours (photos des profils...)"):
                try:
                    pdf_bytes = generer_roadbook_pdf(
                        score=score, ascensions=ascensions, resultats=resultats, df_profil=df_profil,
                        dist_tot=dist_tot, d_plus=d_plus, d_moins=d_moins, temps_s=temps_s,
                        date_depart=date_depart, heure_arr=heure_arr, vitesse=vitesse, calories=calories,
                        briefing_ia=st.session_state.get("briefing_ia")
                    )
                    st.download_button(
                        label="✅ PDF Prêt - Cliquez ici pour télécharger",
                        data=pdf_bytes,
                        file_name=f"Roadbook_Velo_{date_dep.strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                except Exception as e:
                    st.error(f"❌ Erreur lors de la création du PDF : {e}")

    with tab_profil:
        idx_survol = None
        if not df_profil.empty:
            st.plotly_chart(creer_figure_profil(df_profil, ascensions, vitesse, ref_val, mode, poids, idx_survol), width='stretch')

    with tab_meteo:
        if err_meteo: st.warning("⚠️ Données météo indisponibles.")
        else: st.plotly_chart(creer_figure_meteo(resultats), width='stretch')

    with tab_cols:
        if ascensions:
            cols_aff = ["Catégorie","Nom","Départ (km)","Sommet (km)","Longueur", "Dénivelé","Pente moy."]
            st.dataframe(pd.DataFrame(ascensions)[cols_aff], width='stretch', hide_index=True)
            col_choix = st.selectbox("Choisir une montée :", [f"{a['Catégorie']} - {a.get('Nom','')}" for a in ascensions])
            idx = [f"{a['Catégorie']} - {a.get('Nom','')}" for a in ascensions].index(col_choix)
            st.plotly_chart(creer_figure_col(df_profil, ascensions[idx]), width='stretch')
        else:
            st.success("🚴‍♂️ Aucune difficulté catégorisée.")

    # ── ONGLET DÉTAIL (CORRIGÉ ET RESTAURÉ) ──────────────────────────────────
    with tab_detail:
        st.caption(f"Un point toutes les **{intervalle} min**.")
        lignes = []
        for cp in resultats:
            t = cp.get("temp_val")
            v = cp.get("vent_val")
            rg = cp.get("rafales_val")
            lignes.append({
                "Heure": cp["Heure"], "Km": cp["Km"], "Alt (m)": cp["Alt (m)"],
                "Ciel": cp.get("Ciel","—"),
                "Temp (°C)": f"{t}°C" if t is not None else "—",
                "Ressenti": label_wind_chill(cp.get("ressenti")),
                "Pluie": cp.get("Pluie","—"),
                "Vent (km/h)": f"{v} km/h" if v is not None else "—",
                "Rafales": f"{rg} km/h" if rg is not None else "—",
                "Direction": cp.get("Dir","—"),
                "Effet vent": cp.get("effet","—"),
            })
        st.dataframe(pd.DataFrame(lignes), width='stretch', hide_index=True,
            column_config={
                "Heure":       st.column_config.TextColumn("🕐 Heure"),
                "Km":          st.column_config.NumberColumn("📏 Km"),
                "Alt (m)":     st.column_config.NumberColumn("⛰️ Alt"),
                "Ciel":        st.column_config.TextColumn("🌤️ Ciel"),
                "Temp (°C)":   st.column_config.TextColumn("🌡️ Temp"),
                "Ressenti":    st.column_config.TextColumn("🥶 Ressenti"),
                "Pluie":       st.column_config.TextColumn("🌧️ Pluie"),
                "Vent (km/h)": st.column_config.TextColumn("💨 Vent"),
                "Rafales":     st.column_config.TextColumn("🌬️ Rafales"),
                "Direction":   st.column_config.TextColumn("🧭 Direction"),
                "Effet vent":  st.column_config.TextColumn("🚴 Effet"),
            })

    # ── ANALYSE IA (AVEC FIX CALENDRIER) ──────────────────────────────────────
    with tab_analyse:
        st.subheader("🎙️ Le Briefing du Pote de Sortie")
        if not gemini_key:
            st.info("👈 **Entrez votre clé API Gemini dans le menu latéral.**")
        else:
            if "briefing_ia" not in st.session_state:
                st.session_state.briefing_ia = None

            if st.button("💬 Générer ou Actualiser le briefing", use_container_width=True):
                with st.spinner("Analyse du parcours..."):
                    try:
                        # ── FIX CALENDRIER ──
                        jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
                        mois_fr = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
                        delta_jours = (date_dep - date.today()).days
                        
                        if delta_jours == 0:
                            contexte_date = "Aujourd'hui"
                        elif delta_jours == 1:
                            contexte_date = "Demain"
                        else:
                            # Python calcule le jour exact de la semaine
                            contexte_date = f"le {jours_fr[date_dep.weekday()]} {date_dep.day} {mois_fr[date_dep.month]} {date_dep.year}"

                        briefing = generer_briefing(
                            api_key=gemini_key, dist_tot=dist_tot, d_plus=d_plus, temps_s=temps_s,
                            calories=calories, score=score, ascensions=ascensions, analyse_meteo=analyse_meteo,
                            resultats=resultats, heure_depart=heure_dep.strftime('%H:%M'),
                            heure_arrivee=heure_arr.strftime('%H:%M'), vitesse_moyenne=vitesse,
                            infos_soleil=infos_soleil, contexte_date=contexte_date
                        )
                        st.session_state.briefing_ia = briefing
                    except Exception as e:
                        st.error(f"❌ Erreur API : {e}")

            if st.session_state.briefing_ia:
                st.success("✅ Briefing prêt ! Vous pouvez maintenant télécharger le Roadbook PDF depuis l'onglet 'Carte'.")
                st.markdown(f"<div style='background-color:#f8fafc; padding:25px; border-radius:12px; border-left:6px solid #22c55e;'>{st.session_state.briefing_ia}</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
