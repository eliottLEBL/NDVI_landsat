"""
NDVI Landsat moyen par IRIS (Ile-de-France), une valeur par an, de 2000 à 2026.
Calcul fait sur Google Earth Engine (GEE), résultats exportés en CSV sur Google Drive.

AVANT DE LANCER (une seule fois)
1. Créer un compte GEE (gratuit pour la recherche) : https://earthengine.google.com
   et un projet Google Cloud associé (son identifiant va dans PROJECT ci-dessous).
2. Installer :           py -m pip install earthengine-api geopandas
3. S'authentifier :      py -c "import ee; ee.Authenticate()"
4. Importer les contours IRIS dans GEE :
   - lancer ce script avec ETAPE = "preparer"  -> crée iris_idf_shp.zip
   - sur https://code.earthengine.google.com : onglet Assets > NEW > Shape files,
     déposer les fichiers du zip, nommer l'asset "iris_idf"
   - mettre ETAPE = "calculer" et relancer le script

Les exports apparaissent dans l'onglet Tasks de GEE, puis dans le dossier
Google Drive "ndvi_landsat" (un CSV par année). ETAPE = "fusionner" les regroupe.
"""

import ee

# ------------------------------------------------------------------
# PARAMÈTRES
# ------------------------------------------------------------------
ETAPE = "fusionner"            # "preparer", "calculer" ou "fusionner"
PROJECT = "ndvi-idf"  # identifiant du projet Google Cloud
IRIS_GPKG = r"C:\Users\Leblond\Desktop\data\NDVI_iris\data\contours_iris_2026\CONTOURS-IRIS_3-0__GPKG_LAMB93_FXX_2026-01-01\CONTOURS-IRIS\1_DONNEES_LIVRAISON_2026-07-00042\CONTOURS-IRIS_3-0_GPKG_LAMB93_FXX-ED2026-01-01\iris.gpkg"
IRIS_ASSET = f"projects/{PROJECT}/assets/iris_idf"
ID_FIELD = "code_iris"
YEARS = range(2000, 2027)          # 2000 à 2026 inclus
SEASON = ("06-01", "08-31")        # été : végétation en feuilles, moins de nuages
HARMONISE = True                   # aligne Landsat 8/9 sur Landsat 5/7 (Roy et al., 2016)
DOSSIER_CSV = r"C:\Users\Leblond\Desktop\data\ndvi_landsat"   # pour l'étape "fusionner"

# Codes des départements d'Ile-de-France
IDF = ("75", "77", "78", "91", "92", "93", "94", "95")


# ------------------------------------------------------------------
# ÉTAPE 1 : préparer les contours IRIS pour GEE (shapefile zippé)
# ------------------------------------------------------------------
def preparer():
    import zipfile, pathlib
    import geopandas as gpd

    iris = gpd.read_file(IRIS_GPKG)
    iris = iris[iris[ID_FIELD].str[:2].isin(IDF)][[ID_FIELD, "geometry"]]
    iris = iris.to_crs(4326)
    iris["geometry"] = iris.geometry.simplify(0.00005)   # ~5 m, allège l'import
    out = pathlib.Path("iris_idf_shp")
    out.mkdir(exist_ok=True)
    iris.to_file(out / "iris_idf.shp")
    with zipfile.ZipFile("iris_idf_shp.zip", "w") as z:
        for f in out.iterdir():
            z.write(f, f.name)
    print(f"{len(iris)} IRIS -> iris_idf_shp.zip (à importer dans GEE)")


# ------------------------------------------------------------------
# ÉTAPE 2 : calcul du NDVI sur GEE
# ------------------------------------------------------------------
def ndvi_landsat(img, red, nir, oli):
    """Masque nuages/ombres/neige, réflectance de surface, NDVI."""
    qa = img.select("QA_PIXEL")
    propre = (qa.bitwiseAnd(1 << 1).eq(0)        # nuage dilaté
              .And(qa.bitwiseAnd(1 << 3).eq(0))  # nuage
              .And(qa.bitwiseAnd(1 << 4).eq(0))  # ombre de nuage
              .And(qa.bitwiseAnd(1 << 5).eq(0)))  # neige
    sr = img.select([red, nir], ["red", "nir"]).multiply(0.0000275).add(-0.2)
    if oli and HARMONISE:
        # Conversion OLI (Landsat 8/9) -> ETM+ (Landsat 7), Roy et al. (2016)
        sr = sr.multiply([0.9047, 0.8462]).add([0.0061, 0.0412])
    ndvi = sr.normalizedDifference(["nir", "red"]).rename("ndvi")
    return ee.Image(ndvi.updateMask(propre).copyProperties(img, ["system:time_start"]))


def collection(annee, zone):
    debut, fin = f"{annee}-{SEASON[0]}", f"{annee}-{SEASON[1]}"

    def col(cid, red, nir, oli):
        return (ee.ImageCollection(cid).filterBounds(zone).filterDate(debut, fin)
                .map(lambda im: ndvi_landsat(im, red, nir, oli)))

    return (col("LANDSAT/LT05/C02/T1_L2", "SR_B3", "SR_B4", False)     # 1984-2011
            .merge(col("LANDSAT/LE07/C02/T1_L2", "SR_B3", "SR_B4", False))  # 1999-2022
            .merge(col("LANDSAT/LC08/C02/T1_L2", "SR_B4", "SR_B5", True))   # 2013-
            .merge(col("LANDSAT/LC09/C02/T1_L2", "SR_B4", "SR_B5", True)))  # 2021-


def calculer():
    ee.Initialize(project=PROJECT)
    iris = ee.FeatureCollection(IRIS_ASSET).select([ID_FIELD])
    zone = iris.geometry().bounds()

    for annee in YEARS:
        col = collection(annee, zone)
        image = (col.median().rename("ndvi")                  # NDVI médian de l'été
                 .addBands(col.count().rename("n_obs")))      # nb d'observations sans nuage
        stats = image.reduceRegions(collection=iris, reducer=ee.Reducer.mean(),
                                    scale=30, tileScale=4)
        stats = stats.map(lambda f: f.set("annee", annee).setGeometry(None))
        tache = ee.batch.Export.table.toDrive(
            collection=stats, description=f"ndvi_landsat_{annee}",
            folder="ndvi_landsat", fileFormat="CSV",
            selectors=[ID_FIELD, "annee", "ndvi", "n_obs"])
        tache.start()
        print(f"Export lancé : {annee}")
    print("Suivre l'avancement dans l'onglet Tasks de https://code.earthengine.google.com")


# ------------------------------------------------------------------
# ÉTAPE 3 : regrouper les CSV téléchargés depuis Google Drive
# ------------------------------------------------------------------
def fusionner():
    import glob
    import pandas as pd
    fichiers = sorted(glob.glob(DOSSIER_CSV + r"\ndvi_landsat_*.csv"))
    df = pd.concat([pd.read_csv(f, dtype={ID_FIELD: str}) for f in fichiers])
    df = df.sort_values([ID_FIELD, "annee"])
    sortie = DOSSIER_CSV + r"\ndvi_landsat_iris_idf.csv"
    df.to_csv(sortie, index=False)
    print(f"{len(fichiers)} années, {df[ID_FIELD].nunique()} IRIS -> {sortie}")


if __name__ == "__main__":
    {"preparer": preparer, "calculer": calculer, "fusionner": fusionner}[ETAPE]()
