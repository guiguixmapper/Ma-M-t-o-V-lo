"""
export_pdf.py
=============
Module de génération du Roadbook en PDF.
Génère les tableaux, exporte les graphiques via Kaleido et intègre le brief IA.
"""

from fpdf import FPDF
import tempfile
import os
import plotly.graph_objects as go

def nettoyer_texte(texte):
    """
    Nettoie le texte pour éviter que le PDF ne plante à cause des emojis 
    ou des caractères très spéciaux non supportés par la police standard.
    """
    if not texte: return ""
    return texte.encode('latin-1', 'ignore').decode('latin-1')

def creer_figure_col_pdf(df_profil, asc, nb_segments=None):
    """Recrée le profil du col spécifiquement pour le photographier dans le PDF"""
    d0, d1 = asc["_debut_km"], asc["_sommet_km"]
    dk     = d1 - d0
    mask      = [d0 <= d <= d1 for d in df_profil["Distance (km)"]]
    dists_col = [d for d, m in zip(df_profil["Distance (km)"], mask) if m]
    alts_col  = [a for a, m in zip(df_profil["Altitude (m)"], mask) if m]
    if len(dists_col) < 2: return None
    seg_km = dk / nb_segments if nb_segments else (0.5 if dk < 5 else 1.0 if dk < 15 else 2.0)

    def couleur_pente(p):
        if p < 3: return "#22c55e"
        elif p < 6: return "#84cc16"
        elif p < 8: return "#eab308"
        elif p < 10: return "#f97316"
        elif p < 12: return "#ef4444"
        else: return "#7f1d1d"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dists_col, y=alts_col, fill="tozeroy",
        fillcolor="rgba(203,213,225,0.2)", line=dict(color="#94a3b8", width=1), showlegend=False))
    
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
            fig.add_trace(go.Scatter(x=sx, y=sy, fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.4)",
                line=dict(color=coul, width=3), showlegend=False))
        km_d = km_f

    nom = asc.get("Nom", "")
    titre = f"{nom} ({asc['Catégorie']}) - {asc['Longueur']}, D+ {asc['Dénivelé']}"
    fig.update_layout(
        title=titre,
        height=300, width=700, margin=dict(l=40, r=20, t=40, b=30),
        xaxis_title="Km", yaxis_title="Alt (m)",
        plot_bgcolor="white", paper_bgcolor="white"
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9")
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    return fig

class RoadbookPDF(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 15)
        self.set_text_color(30, 64, 175) # Bleu foncé
        self.cell(0, 10, 'ROADBOOK - CARNET DE ROUTE', border=False, align='C')
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

def generer_roadbook_pdf(score, ascensions, resultats, df_profil, dist_tot, d_plus, d_moins, 
                         temps_s, date_depart, heure_arr, vitesse, calories, briefing_ia):
    pdf = RoadbookPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # --- RESUME ---
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, nettoyer_texte(f"Date de depart : {date_depart.strftime('%d/%m/%Y a %H:%M')}"), new_x="LMARGIN", new_y="NEXT")
    
    dh = int(temps_s // 3600); dm = int((temps_s % 3600) // 60)
    resume_txt = (f"Distance: {round(dist_tot/1000,1)} km | D+: {int(d_plus)} m | D-: {int(d_moins)} m\n"
                  f"Duree: {dh}h{dm:02d}m | Vitesse moy.: {vitesse} km/h | Calories: {calories} kcal\n"
                  f"Difficulte globale: {score['total']}/10 ({nettoyer_texte(score['label'])})")
    
    pdf.set_font('helvetica', '', 11)
    pdf.multi_cell(0, 6, resume_txt)
    pdf.ln(5)

    # --- METEO ---
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 10, "Meteo Detaillee", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font('helvetica', 'B', 9)
    
    col_widths = [15, 15, 30, 20, 20, 30, 40]
    headers = ["Heure", "Km", "Ciel", "Temp", "Pluie", "Vent", "Effet"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1, align='C')
    pdf.ln(8)
    
    pdf.set_font('helvetica', '', 9)
    for cp in resultats:
        t = cp.get('temp_val')
        pdf.cell(col_widths[0], 8, str(cp['Heure']), border=1, align='C')
        pdf.cell(col_widths[1], 8, str(cp['Km']), border=1, align='C')
        pdf.cell(col_widths[2], 8, nettoyer_texte(str(cp.get('Ciel','-'))), border=1, align='C')
        pdf.cell(col_widths[3], 8, f"{t} C" if t else "-", border=1, align='C')
        pdf.cell(col_widths[4], 8, f"{cp.get('pluie_pct', 0)} %", border=1, align='C')
        pdf.cell(col_widths[5], 8, f"{cp.get('vent_val','-')} km/h", border=1, align='C')
        pdf.cell(col_widths[6], 8, nettoyer_texte(str(cp.get('effet','-'))), border=1, align='C')
        pdf.ln(8)
    pdf.ln(10)

    # --- ASCENSIONS ET PROFILS ---
    if ascensions:
        pdf.add_page()
        pdf.set_font('helvetica', 'B', 14)
        pdf.cell(0, 10, "Profils des Ascensions", new_x="LMARGIN", new_y="NEXT")
        
        for asc in ascensions:
            pdf.set_font('helvetica', 'B', 11)
            nom = nettoyer_texte(asc.get("Nom", "Sans nom"))
            pdf.cell(0, 8, f"{nom} ({nettoyer_texte(asc['Catégorie'])}) - Km {asc['Départ (km)']}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font('helvetica', '', 10)
            details = f"Longueur: {asc['Longueur']} | D+: {asc['Dénivelé']} | Pente: {asc['Pente moy.']} moy. / {asc['Pente max']} max"
            pdf.cell(0, 6, nettoyer_texte(details), new_x="LMARGIN", new_y="NEXT")
            
            # Génération Image
            fig = creer_figure_col_pdf(df_profil, asc, nb_segments=None)
            if fig:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
                    fig.write_image(tmpfile.name, engine="kaleido")
                    pdf.image(tmpfile.name, x=10, w=190)
                os.remove(tmpfile.name) # Nettoyage
            pdf.ln(5)

    # --- LE MOT DU COACH (A LA FIN) ---
    if briefing_ia:
        pdf.add_page()
        pdf.set_font('helvetica', 'B', 14)
        pdf.cell(0, 10, "Le Briefing du Coach", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font('helvetica', '', 11)
        
        texte_propre = nettoyer_texte(briefing_ia)
        # On remplace les ** du markdown par des tirets pour que ce soit propre
        texte_propre = texte_propre.replace("**", "")
        pdf.multi_cell(0, 6, texte_propre)

    return pdf.output()
