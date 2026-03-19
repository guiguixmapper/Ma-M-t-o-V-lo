"""
🚴‍♂️ Vélo & Météo — v9 (Avec Coach IA Ultime)
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
import base64

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


def generer_html_resume(score, ascensions, resultats, dist_tot, d_plus, d_moins,
                        temps_s, heure_depart, heure_arr, vitesse, calories):
    dh = int(temps_s // 3600); dm = int((temps_s % 3600) // 60)
    cols_html = ""
    for a in ascensions:
        nom = a.get("Nom", "—")
        cols_html += (
            f"<tr><td>{a['Catégorie']}</td><td>{nom if nom != '—' else ''}</td>"
            f"<td>{a['Départ (km)']} km</td><td>{a['Longueur']}</td><td>{a['Dénivelé']}</td>"
            f"<td>{a['Pente moy.']}</td><td>{a.get('Temps col','—')}</td>"
            f"<td>{a.get('Arrivée sommet','—')}</td></tr>"
        )
    meteo_html = ""
    for cp in resultats[:10]:
        t = cp.get('temp_val')
        meteo_html += (
            f"<tr><td>{cp['Heure']}</td><td>{cp['Km']} km</td>"
            f"<td>{cp.get('Ciel','—')}</td><td>{f'{t}°C' if t else '—'}</td>"
            f"<td>{cp.get('Pluie','—')}</td><td>{cp.get('vent_val','—')} km/h</td>"
            f"<td>{cp.get('effet','—')}</td></tr>"
        )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  body{{font-family:Arial,sans-serif;padding:32px;color:#1e293b;max-width:900px;margin:auto}}
  h1{{color:#1e40af;border-bottom:3px solid #1e40af;padding-bottom:8px}}
  h2{{color:#1e40af;margin-top:28px}}
  .score{{background:#1e40af;color:white;border-radius:10px;padding:14px 20px;
          font-size:1.1rem;font-weight:700;margin:12px 0;display:inline-block}}
  .grid{{display:flex;gap:14px;flex-wrap:wrap;margin:14px 0}}
  .card{{background:#f1f5f9;border-radius:8px;padding:12px 18px;text-align:center;min-width:110px}}
  .card .v{{font-size:1.4rem;font-weight:700;color:#1e40af}}
  .card .l{{font-size:.72rem;color:#64748b;margin-top:3px}}
  table{{width:100%;border-collapse:collapse;margin-top:10px;font-size:.83rem}}
  th{{background:#1e40af;color:white;padding:8px;text-align:left}}
  td{{padding:6px 8px;border-bottom:1px solid #e2e8f0}}
  tr:nth-child(even) td{{background:#f8fafc}}
</style></head><body>
<h1>🚴‍♂️ Résumé de sortie vélo</h1>
<p>Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} · Départ : {heure_depart.strftime('%d/%m/%Y %H:%M')}</p>
<div class="score">{score['label']} — {score['total']}/10 &nbsp;|&nbsp;
  🌤️ {score['score_meteo']}/6 &nbsp;|&nbsp; 🏔️ {score['score_cols']}/4</div>
<div class="grid">
  <div class="card"><div class="v">{round(dist_tot/1000,1)} km</div><div class="l">📏 Distance</div></div>
  <div class="card"><div class="v">{int(d_plus)} m</div><div class="l">⬆️ D+</div></div>
  <div class="card"><div class="v">{int(d_moins)} m</div><div class="l">⬇️ D−</div></div>
  <div class="card"><div class="v">{dh}h{dm:02d}m</div><div class="l">⏱️ Durée</div></div>
  <div class="card"><div class="v">{heure_arr.strftime('%H:%M')}</div><div class="l">🏁 Arrivée</div></div>
  <div class="card"><div class="v">{vitesse} km/h</div><div class="l">🚴 Vitesse</div></div>
  <div class="card"><div class="v">{calories} kcal</div><div class="l">🔥 Calories</div></div>
</div>
<h2>🏔️ Ascensions</h2>
{"<p>Aucune difficulté catégorisée.</p>" if not ascensions else
 "<table><tr><th>Cat.</th><th>Nom</th><th>Départ</th><th>Long.</th><th>D+</th>"
 "<th>Pente</th><th>Temps</th><th>Arrivée</th></tr>" + cols_html + "</table>"}
<h2>🌤️ Météo</h2>
{"<p>Données météo indisponibles.</p>" if not meteo_html else
 "<table><tr><th>Heure</th><th>Km</th><th>Ciel</th><th>Temp</th>"
 "<th>Pluie</th><th>Vent</th><th>Effet</th></tr>" + meteo_html + "</table>"}
</body></html>""".encode("utf-8")


# ==============================================================================
# SCORE GLOBAL ET ANALYSE
# ==============================================================================

def analyser_meteo_detaillee(resultats, dist_tot):
    """
    Analyse détaillée pluie + vent depuis les checkpoints météo.
    Retourne un dict avec les stats clés.
    """
    valides = [cp for cp in resultats if cp.get("temp_val") is not None]
    if not valides:
        return None

    dist_totale_km = dist_tot / 1000

    # ── Pluie ────────────────────────────────────────────────────────────────
    cps_pluie = [cp for cp in valides if (cp.get("pluie_pct") or 0) >= 50]
    pct_pluie = len(cps_pluie) / len(valides) * 100

    premier_pluie = None
    for cp in valides:
        if (cp.get("pluie_pct") or 0) >= 50:
            premier_pluie = cp
            break

    # ── Vent ─────────────────────────────────────────────────────────────────
    compteur_effet = {"⬇️ Face": 0, "⬆️ Dos": 0,
                      "↙️ Côté (D)": 0, "↘️ Côté (G)": 0, "—": 0}
    for cp in valides:
        effet = cp.get("effet", "—")
        compteur_effet[effet] = compteur_effet.get(effet, 0) + 1

    total_v = len(valides)
    pct_face  = round(compteur_effet["⬇️ Face"]    / total_v * 100)
    pct_dos   = round(compteur_effet["⬆️ Dos"]     / total_v * 100)
    pct_cote  = round((compteur_effet["↙️ Côté (D)"] +
                       compteur_effet["↘️ Côté (G)"]) / total_v * 100)

    # Segments avec vent de face (km consécutifs)
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
    if en_face:
        segments_face.append((debut_face, valides[-1]["Km"]))

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
    """
    Score /10 = Météo (6pts) + Parcours (4pts)
    """
    valides = [cp for cp in resultats if cp.get("temp_val") is not None]

    # ── MÉTÉO (6 pts) ─────────────────────────────────────────────────────────
    if valides:
        # Température (2pts)
        tm = sum(cp["temp_val"] for cp in valides) / len(valides)
        if   15 <= tm <= 22: s_temp = 2.0
        elif 10 <= tm <= 27: s_temp = 1.5
        elif  5 <= tm <= 32: s_temp = 0.8
        elif  0 <= tm:       s_temp = 0.3
        else:                s_temp = 0.0

        # Vent effectif (2pts) — pondéré par direction
        POIDS_EFFET = {
            "⬇️ Face":   1.5,
            "↙️ Côté (D)": 0.7,
            "↘️ Côté (G)": 0.7,
            "⬆️ Dos":    -0.3,
            "—":          0.5,
        }
        ve_moy = sum(
            (cp.get("vent_val") or 0) * POIDS_EFFET.get(cp.get("effet", "—"), 0.5)
            for cp in valides
        ) / len(valides)
        if   ve_moy <= 8:  s_vent = 2.0
        elif ve_moy <= 18: s_vent = 1.5
        elif ve_moy <= 30: s_vent = 0.8
        elif ve_moy <= 45: s_vent = 0.3
        else:              s_vent = 0.0

        # Pluie (2pts)
        pm = sum(cp.get("pluie_pct") or 0 for cp in valides) / len(valides)
        s_pluie = round(max(0.0, 2.0 * (1 - pm / 100)), 2)

        sm = s_temp + s_vent + s_pluie
    else:
        sm = 3.0   # météo inconnue → score neutre

    # ── PARCOURS (4 pts, plancher 2/4) ────────────────────────────────────────

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

    # ── TOTAL ─────────────────────────────────────────────────────────────────
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
    cps = list(resultats)
    
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

    css_legende = """
    <style>
    .leaflet-control-layers {
        border-radius: 10px !important;
        border: none !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15) !important;
        padding: 0 !important;
        overflow: hidden;
        font-family: Arial, sans-serif !important;
    }
    .leaflet-control-layers-expanded {
        padding: 10px 14px !important;
        min-width: 160px !important;
    }
    .leaflet-control-layers-list {
        margin: 0 !important;
    }
    .leaflet-control-layers label {
        display: flex !important;
        align-items: center !important;
        gap: 6px !important;
        font-size: 13px !important;
        color: #1e293b !important;
        margin: 4px 0 !important;
        cursor: pointer !important;
    }
    .leaflet-control-layers-separator {
        display: none !important;
    }
    .leaflet-control-layers-overlays {
        display: flex !important;
        flex-direction: column !important;
        gap: 2px !important;
    }
    .leaflet-control-layers-expanded::before {
        content: "🗺️ Calques";
        display: block;
        font-weight: 700;
        font-size: 11px;
        color: #64748b;
        letter-spacing: .5px;
        text-transform: uppercase;
        margin-bottom: 8px;
        padding-bottom: 6px;
        border-bottom: 1px solid #e2e8f0;
    }
    </style>
    """
    carte.get_root().html.add_child(folium.Element(css_legende))

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
    mode = st.sidebar.radio("📊 Mode d'analyse",
                             ["⚡ Puissance", "🫀 Fréquence Cardiaque"], horizontal=True)
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

        if "sensibilite" not in st.session_state:
            st.session_state.sensibilite = 3
        if "seuil_debut" not in st.session_state:
            st.session_state.seuil_debut = float(climbing_module.SEUIL_DEBUT)
        if "seuil_fin" not in st.session_state:
            st.session_state.seuil_fin = float(climbing_module.SEUIL_FIN)
        if "fusion_m" not in st.session_state:
            st.session_state.fusion_m = int(climbing_module.MAX_DESCENTE_FUSION_M)

        SENSIBILITE_LABELS = {
            1: "🔵 Strict — grands cols seulement",
            2: "🟢 Conservateur",
            3: "🟡 Équilibré (défaut)",
            4: "🟠 Sensible",
            5: "🔴 Maximum — toutes les côtes",
        }
        SENSIBILITE_PARAMS = {
            1: (4.0, 2.0,  20),
            2: (3.0, 1.5,  35),
            3: (2.0, 1.0,  50),
            4: (1.5, 0.5,  70),
            5: (0.5, 0.0, 100),
        }

        st.slider("🎚️ Sensibilité de détection", 1, 5, step=1,
            key="sensibilite",
            help="Bas = seulement les vraies montées. Haut = capte toutes les côtes.")
        niv = st.session_state.sensibilite
        st.caption(SENSIBILITE_LABELS[niv])

        if st.button("↺ Réinitialiser", use_container_width=True):
            st.session_state["_reset_demande"] = True
            st.rerun()

        if st.session_state.pop("_reset_demande", False):
            st.session_state.pop("sensibilite", None)
            st.session_state.pop("seuil_debut", None)
            st.session_state.pop("seuil_fin", None)
            st.session_state.pop("fusion_m", None)
            st.session_state.pop("_last_sensibilite", None)
            st.rerun()

        with st.expander("⚙️ Réglages fins", expanded=False):
            st.caption("Synchronisés avec la sensibilité — modifiez pour affiner.")

            sd_sync, sf_sync, fm_sync = SENSIBILITE_PARAMS[niv]
            if st.session_state.get("_last_sensibilite") != niv:
                st.session_state.seuil_debut = sd_sync
                st.session_state.seuil_fin   = sf_sync
                st.session_state.fusion_m    = fm_sync
                st.session_state["_last_sensibilite"] = niv

            st.slider("Seuil de départ (%)", 0.5, 5.0, step=0.5,
                key="seuil_debut",
                help="Pente minimale pour démarrer une montée.")
            st.slider("Seuil de fin (%)", 0.0, 3.0, step=0.5,
                key="seuil_fin",
                help="Pente en dessous de laquelle la montée est terminée.")
            st.slider("Fusion (D− max, m)", 10, 200, step=10,
                key="fusion_m",
                help="Descente max pour fusionner deux runs en une seule montée.")

        climbing_module.SEUIL_DEBUT           = st.session_state.seuil_debut
        climbing_module.SEUIL_FIN             = st.session_state.seuil_fin
        climbing_module.MAX_DESCENTE_FUSION_M = st.session_state.fusion_m

    # ── OPTIONS AVANCÉES ──────────────────────────────────────────────────────
    st.sidebar.divider()
    with st.sidebar.expander("🔧 Options avancées", expanded=False):
        noms_osm = st.toggle("🗺️ Nommer les cols (OpenStreetMap)", value=False,
            help="Recherche le nom officiel de chaque col sur OpenStreetMap. "
                 "Peut être lent ou indisponible selon l'hébergement.")
        if noms_osm:
            st.sidebar.warning(
                "⚠️ Les serveurs Overpass sont souvent surchargés ou bloqués "
                "sur Streamlit Cloud. La recherche peut échouer ou être lente."
            )
        gemini_key = st.text_input(
            "🤖 Clé API Gemini",
            value="",
            type="password",
            help="Génère un résumé intelligent de ta sortie. "
                 "Clé gratuite sur aistudio.google.com."
        )

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
    if not points_gpx:
        st.error("❌ Fichier GPX vide ou corrompu."); return

    with etapes.container():
        with st.spinner("🌍 Fuseau horaire…"):
            fuseau = recuperer_fuseau(points_gpx[0].
