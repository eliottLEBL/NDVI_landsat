"""
Carte interactive du NDVI Landsat par IRIS (Ile-de-France), 2000-2026.
Lit ndvi_landsat_iris_idf.csv + iris_idf_shp, écrit carte_ndvi_iris.html
(fichier autonome, à ouvrir dans un navigateur).

Lancer :  py carte_ndvi.py
"""

import json
import pathlib

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

# ------------------------------------------------------------------
# PARAMÈTRES
# ------------------------------------------------------------------
DOSSIER = pathlib.Path(__file__).parent
CSV = DOSSIER / "ndvi_landsat_iris_idf.csv"
SHP = DOSSIER / "iris_idf_shp" / "iris_idf.shp"
IRIS_GPKG = r"C:\Users\Leblond\Desktop\data\NDVI_iris\data\contours_iris_2026\CONTOURS-IRIS_3-0__GPKG_LAMB93_FXX_2026-01-01\CONTOURS-IRIS\1_DONNEES_LIVRAISON_2026-07-00042\CONTOURS-IRIS_3-0_GPKG_LAMB93_FXX-ED2026-01-01\iris.gpkg"
SORTIE = DOSSIER / "carte_ndvi_iris.html"
ID_FIELD = "code_iris"
ECHELLE = (0.1, 0.75)          # bornes de la palette (≈ percentiles 2 et 98)


def arrondir(coords, n=5):
    """Arrondit récursivement les coordonnées (5 décimales ≈ 1 m)."""
    if isinstance(coords[0], (float, int)):
        return [round(c, n) for c in coords]
    return [arrondir(c, n) for c in coords]


def main():
    df = pd.read_csv(CSV, sep=";", decimal=",", dtype={ID_FIELD: str})
    annees = sorted(df["annee"].unique().tolist())
    ndvi = df.pivot(index=ID_FIELD, columns="annee", values="ndvi").reindex(columns=annees)
    nobs = df.pivot(index=ID_FIELD, columns="annee", values="n_obs").reindex(columns=annees)

    iris = gpd.read_file(SHP)
    try:   # noms des IRIS et des communes, si le GPKG d'origine est disponible
        noms = gpd.read_file(IRIS_GPKG, columns=[ID_FIELD, "nom_iris", "nom_commune"],
                             ignore_geometry=True)
        iris = iris.merge(noms, on=ID_FIELD, how="left")
    except Exception:
        iris["nom_iris"] = iris["nom_commune"] = ""

    def valeurs(tab, code, n):
        if code not in tab.index:
            return [None] * len(annees)
        return [None if pd.isna(v) else round(float(v), n) for v in tab.loc[code]]

    features = []
    for _, r in iris.iterrows():
        code = r[ID_FIELD]
        g = mapping(r.geometry)
        features.append({
            "type": "Feature",
            "geometry": {"type": g["type"], "coordinates": arrondir(g["coordinates"])},
            "properties": {
                "c": code,
                "i": r["nom_iris"] if isinstance(r["nom_iris"], str) else "",
                "m": r["nom_commune"] if isinstance(r["nom_commune"], str) else "",
                "v": valeurs(ndvi, code, 3),
                "o": valeurs(nobs, code, 1),
            },
        })

    data = {"annees": annees, "echelle": ECHELLE,
            "geo": {"type": "FeatureCollection", "features": features}}
    html = MODELE.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    SORTIE.write_text(html, encoding="utf-8")
    print(f"{len(features)} IRIS, {len(annees)} années -> {SORTIE} "
          f"({SORTIE.stat().st_size / 1e6:.1f} Mo)")


MODELE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NDVI par IRIS</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  :root { --bg:#fff; --fg:#1f2328; --muted:#656d76; --line:#d0d7de; --accent:#1a7f37; }
  html, body { margin:0; height:100%; background:var(--bg); color:var(--fg);
               font:14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
  #carte { position:absolute; inset:0; }
  .panneau { background:rgba(255,255,255,.95); border:1px solid var(--line); border-radius:8px;
             box-shadow:0 2px 8px rgba(0,0,0,.12); padding:10px 12px; }
  #controle { position:absolute; top:12px; left:56px; right:12px; max-width:520px; z-index:1000; }
  #controle h1 { font-size:15px; margin:0 0 6px; }
  .ligne { display:flex; align-items:center; gap:10px; }
  #annee-txt { font-size:22px; font-weight:600; min-width:64px; font-variant-numeric:tabular-nums; }
  #curseur { flex:1; accent-color:var(--accent); }
  button { border:1px solid var(--line); background:#f6f8fa; border-radius:6px; padding:4px 10px;
           cursor:pointer; font:inherit; }
  button[aria-pressed="true"] { background:var(--accent); color:#fff; border-color:var(--accent); }
  #legende { margin-top:8px; }
  #barre { height:10px; border-radius:3px; }
  .graduations { display:flex; justify-content:space-between; color:var(--muted); font-size:12px; }
  #info { position:absolute; bottom:24px; left:12px; z-index:1000; width:300px; max-width:calc(100% - 50px); }
  #info .titre { font-weight:600; }
  #info .sous { color:var(--muted); font-size:12px; }
  #info .valeur { font-size:20px; font-weight:600; margin-top:4px; font-variant-numeric:tabular-nums; }
  #info svg { width:100%; height:90px; margin-top:6px; }
  .aide { color:var(--muted); font-size:12px; }
</style>
</head>
<body>
<div id="carte"></div>

<div id="controle" class="panneau">
  <h1>NDVI estival Landsat par IRIS — Île-de-France</h1>
  <div class="ligne">
    <button id="lecture" title="Lecture / pause">▶</button>
    <span id="annee-txt"></span>
    <input id="curseur" type="range" step="1" aria-label="Année">
    <button id="moyenne" aria-pressed="false" title="NDVI moyen sur toute la période">Moyenne</button>
  </div>
  <div id="legende">
    <div id="barre"></div>
    <div class="graduations" id="grad"></div>
  </div>
</div>

<div id="info" class="panneau">
  <div class="aide">Survolez un IRIS pour voir sa valeur, cliquez pour fixer la sélection.</div>
</div>

<script>
const D = __DATA__;
const A = D.annees, [LO, HI] = D.echelle;

// Palette séquentielle sol nu -> végétation dense
const STOPS = ["#8c510a", "#d8b365", "#f6e8c3", "#c7e9b4", "#5ab45a", "#1b7837", "#00441b"];
function hex(h) { return [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); }
const RGB = STOPS.map(hex);
function couleur(v) {
  if (v == null) return "#bbb";
  let t = Math.min(1, Math.max(0, (v - LO) / (HI - LO))) * (RGB.length - 1);
  const i = Math.min(RGB.length - 2, Math.floor(t)), f = t - i;
  const c = RGB[i].map((x, k) => Math.round(x + (RGB[i + 1][k] - x) * f));
  return `rgb(${c})`;
}
document.getElementById("barre").style.background = `linear-gradient(to right, ${STOPS.join(",")})`;
document.getElementById("grad").innerHTML =
  [0, .25, .5, .75, 1].map(t => `<span>${(LO + t * (HI - LO)).toFixed(2)}</span>`).join("");

// Moyenne par IRIS sur toute la période
for (const f of D.geo.features) {
  const v = f.properties.v.filter(x => x != null);
  f.properties.moy = v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

const carte = L.map("carte", { preferCanvas: true, zoomControl: true }).setView([48.71, 2.5], 9);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap, &copy; CARTO | NDVI Landsat (USGS) via Google Earth Engine',
  maxZoom: 18,
}).addTo(carte);

let idx = A.length - 1, modeMoy = false, fixe = null;
const val = p => modeMoy ? p.moy : p.v[idx];
const style = f => ({ fillColor: couleur(val(f.properties)), fillOpacity: .85,
                      color: "#fff", weight: .4 });

const couche = L.geoJSON(D.geo, {
  style,
  onEachFeature: (f, l) => {
    l.on("mouseover", () => { if (!fixe) { afficher(f.properties); l.setStyle({ weight: 2, color: "#222" }); } });
    l.on("mouseout",  () => { if (!fixe) couche.resetStyle(l); });
    l.on("click", e => {
      if (fixe) couche.resetStyle(fixe);
      fixe = fixe === l ? null : l;
      if (fixe) { l.setStyle({ weight: 2.5, color: "#000" }); l.bringToFront(); afficher(f.properties); }
      L.DomEvent.stopPropagation(e);
    });
  },
}).addTo(carte);
carte.on("click", () => { if (fixe) { couche.resetStyle(fixe); fixe = null; } });

function fmt(v) { return v == null ? "—" : v.toFixed(3).replace(".", ","); }

function courbe(p) {
  const W = 276, H = 90, m = { l: 30, r: 6, t: 6, b: 16 };
  const x = i => m.l + i * (W - m.l - m.r) / (A.length - 1);
  const y = v => m.t + (1 - (v - LO) / (HI - LO)) * (H - m.t - m.b);
  let d = "", enCours = false;
  p.v.forEach((v, i) => {
    if (v == null) { enCours = false; return; }
    d += `${enCours ? "L" : "M"}${x(i).toFixed(1)},${y(Math.min(HI, Math.max(LO, v))).toFixed(1)}`;
    enCours = true;
  });
  const cur = modeMoy ? "" : (p.v[idx] == null ? "" :
    `<circle cx="${x(idx)}" cy="${y(Math.min(HI, Math.max(LO, p.v[idx])))}" r="3.5" fill="#1a7f37"/>`);
  const axes = [LO, (LO + HI) / 2, HI].map(v =>
    `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="#eaeef2"/>` +
    `<text x="${m.l - 4}" y="${y(v) + 3}" text-anchor="end" font-size="10" fill="#656d76">${v.toFixed(2)}</text>`).join("");
  const ann = [0, A.length - 1].map(i =>
    `<text x="${x(i)}" y="${H - 3}" text-anchor="${i ? "end" : "start"}" font-size="10" fill="#656d76">${A[i]}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Évolution du NDVI">${axes}${ann}
    <path d="${d}" fill="none" stroke="#1b7837" stroke-width="1.8"/>${cur}</svg>`;
}

let dernier = null;
function afficher(p) {
  dernier = p;
  const titre = p.i ? `${p.i}` : `IRIS ${p.c}`;
  const sous = [p.m, p.c].filter(Boolean).join(" · ");
  const lib = modeMoy ? `Moyenne ${A[0]}–${A[A.length - 1]}` : `${A[idx]}`;
  const obs = modeMoy ? "" : ` <span class="sous">(${p.o[idx] == null ? "—" : p.o[idx].toFixed(1).replace(".", ",")} obs. sans nuage)</span>`;
  document.getElementById("info").innerHTML =
    `<div class="titre">${titre}</div><div class="sous">${sous}</div>
     <div class="valeur">NDVI ${lib} : ${fmt(val(p))}${obs}</div>${courbe(p)}`;
}

const curseur = document.getElementById("curseur");
curseur.min = 0; curseur.max = A.length - 1; curseur.value = idx;
function maj() {
  document.getElementById("annee-txt").textContent = modeMoy ? "Moy." : A[idx];
  couche.setStyle(style);
  if (fixe) fixe.setStyle({ weight: 2.5, color: "#000" });
  if (dernier) afficher(dernier);
}
curseur.addEventListener("input", () => {
  idx = +curseur.value;
  if (modeMoy) { modeMoy = false; btnMoy.setAttribute("aria-pressed", "false"); }
  maj();
});

const btnMoy = document.getElementById("moyenne");
btnMoy.addEventListener("click", () => {
  modeMoy = !modeMoy; btnMoy.setAttribute("aria-pressed", String(modeMoy)); maj();
});

let minuteur = null;
const btnLec = document.getElementById("lecture");
btnLec.addEventListener("click", () => {
  if (minuteur) { clearInterval(minuteur); minuteur = null; btnLec.textContent = "▶"; return; }
  if (modeMoy) { modeMoy = false; btnMoy.setAttribute("aria-pressed", "false"); }
  if (idx === A.length - 1) idx = -1;
  btnLec.textContent = "❚❚";
  minuteur = setInterval(() => {
    idx++; curseur.value = idx; maj();
    if (idx >= A.length - 1) { clearInterval(minuteur); minuteur = null; btnLec.textContent = "▶"; }
  }, 700);
});

maj();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
