#!/usr/bin/env python3
"""
Construction de la table de collecte AIadoption dans Grist.

À lancer UNE FOIS, localement. Crée toutes les colonnes :
types, listes de choix, formules, contrôle qualité, colonnes de publication.

    pip install requests
    export GRIST_API_KEY="votre_cle"
    python grist_setup_aiadoption.py --doc <DOC_ID> --table Table1

Options utiles :
    --dry-run        affiche ce qui serait fait, sans rien modifier
    --keep-defaults  ne supprime pas les colonnes A/B/C créées par Grist
    --update-gpu-fields met à jour les choix GPU/VRAM déjà présents

Pour appliquer les questions GPU à une table existante :
    python grist_setup_aiadoption.py --doc <DOC_ID> --update-gpu-fields --update-formulas

Où trouver les valeurs :
  - GRIST_API_KEY : Profil (en haut à droite) > Profile Settings > API Key
  - DOC_ID        : Paramètres du document > "Document ID", ou dans l'URL
  - TABLE         : identifiant de la table, "Table1" par défaut

NOTE DE SÉCURITÉ. Cette clé a tous vos droits Grist. Elle reste sur votre
machine, dans une variable d'environnement, pour ce script d'administration
lancé par vous. Elle ne doit JAMAIS se retrouver dans la sonde distribuée
aux participants, ni dans un dépôt public. Ce sont deux usages sans rapport.
"""

import argparse
import json
import os
import sys

import requests

BASE_URL = "https://grist.numerique.gouv.fr/api"


# --------------------------------------------------------------------------
# Listes de choix
# --------------------------------------------------------------------------

CHOIX = {
    "cohorte": [
        "M2-AIOMICS-2026",
        "SEMINAIRE-2026-11",
        "ECOLE-ETE-2026",
    ],
    "source": ["sonde", "declaratif"],
    "d_machine_type": [
        "Portable personnel",
        "Portable fourni par l'établissement ou le laboratoire",
        "Fixe personnel",
        "Fixe de l'établissement (salle de TP)",
        "Machine virtuelle ou serveur distant",
        "Tablette ou Chromebook",
        "Je ne sais pas",
    ],
    "d_os": [
        "Windows 11",
        "Windows 10",
        "Windows, version antérieure",
        "macOS 26 (Tahoe)",
        "macOS 15 (Sequoia)",
        "macOS 14 (Sonoma)",
        "macOS 13 ou antérieur",
        "Linux — Ubuntu",
        "Linux — Debian",
        "Linux — Fedora",
        "Linux — Arch / Manjaro",
        "Linux — autre distribution",
        "ChromeOS",
        "Je ne sais pas",
    ],
    "d_cpu_family": [
        "Apple Silicon (M1 à M4 ou plus récent)",
        "Intel Core (i3 / i5 / i7 / i9)",
        "Intel Core Ultra",
        "AMD Ryzen",
        "Autre",
        "Je ne sais pas",
    ],
    "d_cores": ["2 ou moins", "3-4", "5-8", "9-16", "Plus de 16", "Je ne sais pas"],
    "d_ram": [
        "4 Go ou moins", "8 Go", "16 Go", "24 Go", "32 Go", "48 Go",
        "64 Go ou plus", "Je ne sais pas",
    ],
    "d_gpu": [
        "NVIDIA (GeForce RTX, GTX, etc.)",
        "AMD Radeon",
        "GPU intégré Apple Silicon",
        "GPU Intel intégré",
        "Pas de GPU dédié",
        "Je ne sais pas",
        "Sans réponse",
    ],
    "d_vram": [
        "4 Go ou moins",
        "6-8 Go",
        "10-12 Go",
        "16 Go ou plus",
        "Je ne sais pas / Sans objet",
        "Sans réponse",
    ],
    "d_disk": [
        "Moins de 10 Go", "10-25 Go", "25-50 Go", "50-100 Go",
        "Plus de 100 Go", "Je ne sais pas",
    ],
    "d_python": [
        "Aucune installation", "3.10", "3.11", "3.12", "3.13",
        "Autre version", "Je ne sais pas",
    ],
    "d_envmgr": [
        "Aucun", "conda / miniconda / Anaconda", "mamba / micromamba",
        "venv / virtualenv", "uv", "poetry", "Docker", "Je ne sais pas",
    ],
    "d_reseau": [
        "Wifi de l'établissement",
        "Connexion personnelle à domicile",
        "Partage de connexion mobile",
        "Variable selon les séances",
        "Je ne sais pas",
    ],
}

CLES_SONDE = (
    '{"schema","os","os_release","arch","python","cpu_model",'
    '"cpu_logical","ram_gb","gpu","vram_gb","disk_free_gb"}'
)


# --------------------------------------------------------------------------
# Constructeurs de définitions de colonnes
# --------------------------------------------------------------------------

def texte(col_id, label, description=""):
    return {"id": col_id, "fields": {
        "label": label, "type": "Text", "description": description}}


def entier(col_id, label, description=""):
    return {"id": col_id, "fields": {
        "label": label, "type": "Int", "description": description}}


def bascule(col_id, label, description=""):
    return {"id": col_id, "fields": {
        "label": label, "type": "Bool", "description": description,
        "widgetOptions": json.dumps({"widget": "Switch"})}}


def choix(col_id, label, description=""):
    return {"id": col_id, "fields": {
        "label": label, "type": "Choice", "description": description,
        "widgetOptions": json.dumps({"choices": CHOIX[col_id], "choiceOptions": {}})}}


def formule(col_id, label, code, type_="Any", description=""):
    return {"id": col_id, "fields": {
        "label": label, "type": type_, "description": description,
        "isFormula": True, "formula": code.strip()}}


def declencheur(col_id, label, code, type_="Any", description=""):
    """Formule de déclenchement : calculée à la création de la ligne."""
    return {"id": col_id, "fields": {
        "label": label, "type": type_, "description": description,
        "isFormula": False, "formula": code.strip(),
        "recalcWhen": 0, "recalcDeps": None}}


# --------------------------------------------------------------------------
# Schéma complet, en ordre de dépendance
# --------------------------------------------------------------------------

def schema():
    cols = []

    # --- Bloc 1 : réception -------------------------------------------------
    cols += [
        bascule("consentement", "Consentement",
                "Doit être vrai. Sans quoi la ligne est écartée."),
        choix("cohorte", "Cohorte", "Jeton de session, jamais individuel."),
        choix("source", "Source", "sonde = JSON collé ; declaratif = menus."),
        texte("raw", "Charge utile",
              "JSON de la sonde. Champ de transport, purgé après gel des c_*."),
        declencheur("recu_le", "Reçu le", "NOW()", "DateTime:Europe/Paris",
                    "Usage interne. Ne jamais publier : horodatage quasi-identifiant."),
    ]

    # --- Bloc 2 : déclaratif ------------------------------------------------
    libelles = {
        "d_machine_type": "Type de machine",
        "d_os": "Système d'exploitation",
        "d_cpu_family": "Famille de processeur",
        "d_cores": "Nombre de cœurs logiques",
        "d_ram": "Mémoire vive (RAM)",
        "d_gpu": "Type de carte graphique (GPU)",
        "d_vram": "Mémoire GPU (VRAM)",
        "d_disk": "Espace disque libre",
        "d_python": "Version de Python installée",
        "d_envmgr": "Gestionnaire d'environnement",
        "d_reseau": "Connexion pendant les séances",
    }
    for cid, lab in libelles.items():
        cols.append(choix(cid, lab, "Voie déclarative. Vide si source = sonde."))
    cols.append(texte(
        "d_gpu_model",
        "Modèle du GPU (NVIDIA / AMD)",
        "À renseigner si le GPU est NVIDIA ou AMD (ex. GeForce RTX 4060, Radeon RX 7800 XT).",
    ))

    # --- Bloc 3 : canonique -------------------------------------------------
    cols.append(formule("c_json", "JSON analysé", """
import json
try:
    return json.loads($raw) if $raw else {}
except Exception:
    return {}
""", "Any", "Parsing unique. Toutes les colonnes c_* le relisent."))

    canon = [
        ("c_schema", "Schéma", "schema", "Text"),
        ("c_os", "OS (sonde)", "os", "Text"),
        ("c_os_release", "Version OS (sonde)", "os_release", "Text"),
        ("c_arch", "Architecture (sonde)", "arch", "Text"),
        ("c_python", "Python (sonde)", "python", "Text"),
        ("c_cpu_model", "Modèle CPU (sonde)", "cpu_model", "Text"),
        ("c_cores", "Cœurs (sonde)", "cpu_logical", "Int"),
        ("c_ram_gb", "RAM Go (sonde)", "ram_gb", "Int"),
        ("c_gpu", "GPU (sonde)", "gpu", "Text"),
        ("c_vram_gb", "VRAM Go (sonde)", "vram_gb", "Int"),
        ("c_disk_free_gb", "Disque libre Go (sonde)", "disk_free_gb", "Int"),
    ]
    for cid, lab, cle, typ in canon:
        cols.append(formule(
            cid, lab, f'return $c_json.get("{cle}")', typ,
            "À GELER (Convert formula to data column) avant de purger raw."))

    # --- Bloc 4 : contrôle qualité -----------------------------------------
    cols.append(formule("qa_valide", "Valide", f"""
ATTENDU = {CLES_SONDE}
if not $consentement:
    return False
if $source == "declaratif":
    return bool($d_os)
return (set($c_json) == ATTENDU
        and $c_json.get("schema") == "aiadoption-v1"
        and len($raw or "") < 600)
""", "Bool", "Faux = à examiner à la main avant traitement."))

    cols += [
        texte("qa_note", "Note de contrôle",
              "Saisie manuelle : anomalie, doublon suspect, ligne écartée."),
        bascule("qa_purge", "raw purgé",
                "Saisie manuelle : cocher une fois c_* gelées et raw vidé."),
    ]

    # --- Bloc 5 : publication ----------------------------------------------
    cols.append(formule("p_os_famille", "OS (publié)", """
v = ($c_os or "").lower()
if v:
    if "windows" in v: return "windows"
    if "darwin" in v or "mac" in v: return "macos"
    if "linux" in v: return "linux"
d = $d_os or ""
if d.startswith("Windows"): return "windows"
if d.startswith("macOS"): return "macos"
if d.startswith("Linux"): return "linux"
if d.startswith("ChromeOS"): return "chromeos"
return "nd"
""", "Text"))

    cols.append(formule("p_cpu_famille", "CPU (publié)", """
arch = ($c_arch or "").lower()
cpu = ($c_cpu_model or "").lower()
if ($c_os or "") == "Darwin" and arch in ("arm64", "aarch64"):
    return "apple_silicon"
if "intel" in cpu: return "intel"
if "amd" in cpu or "ryzen" in cpu: return "amd"
d = $d_cpu_family or ""
if d.startswith("Apple"): return "apple_silicon"
if d.startswith("Intel"): return "intel"
if d.startswith("AMD"): return "amd"
if d == "Autre": return "autre"
return "nd"
""", "Text"))

    cols.append(formule("p_cores_bin", "Cœurs (publié)", """
v = $c_cores
if v is not None:
    if v <= 4: return "<=4"
    if v <= 8: return "5-8"
    if v <= 16: return "9-16"
    return ">16"
return {"2 ou moins": "<=4", "3-4": "<=4", "5-8": "5-8",
        "9-16": "9-16", "Plus de 16": ">16"}.get($d_cores, "nd")
""", "Text"))

    cols.append(formule("p_ram_bin", "RAM (publié)", """
v = $c_ram_gb
if v is not None:
    if v <= 8: return "<=8"
    if v <= 16: return "16"
    if v <= 32: return "24-32"
    return ">32"
return {"4 Go ou moins": "<=8", "8 Go": "<=8", "16 Go": "16",
        "24 Go": "24-32", "32 Go": "24-32", "48 Go": ">32",
        "64 Go ou plus": ">32"}.get($d_ram, "nd")
""", "Text"))

    cols.append(formule("p_gpu_classe", "GPU (publié)", """
if $source == "sonde":
    g = ($c_gpu or "").lower()
    # "inconnu" = la sonde n'a pas pu déterminer (ni torch ni nvidia-smi).
    # Ne surtout pas le confondre avec "aucun" = absence constatée.
    if not g or g == "inconnu": return "nd"
    if g == "aucun": return "aucun_dedie"
    if g == "apple-mps": return "integre_apple"
    if any(k in g for k in ("nvidia", "geforce", "rtx", "quadro", "tesla")):
        return "nvidia"
    if any(k in g for k in ("radeon", "amd")): return "amd"
    if "arc" in g: return "intel_arc"
    if "intel" in g: return "integre_intel"
    return "autre"
d = $d_gpu or ""
if d == "Pas de GPU dédié": return "aucun_dedie"
if d == "GPU intégré Apple Silicon": return "integre_apple"
if d == "GPU Intel intégré": return "integre_intel"
if d.startswith("Non"): return "aucun_dedie"
if d.startswith("Intel Arc"): return "intel_arc"
if d.startswith("NVIDIA"): return "nvidia"
if d.startswith("AMD"): return "amd"
return "nd"
""", "Text"))

    cols.append(formule("p_vram_bin", "VRAM (publié)", """
v = $c_vram_gb
if v is not None:
    if v <= 4: return "<=4"
    if v <= 8: return "6-8"
    if v <= 12: return "10-12"
    return ">=16"
if $source == "sonde":
    return "sans_objet" if $p_gpu_classe in (
        "aucun_dedie", "integre_apple", "integre_intel") else "nd"
if $d_vram == "Je ne sais pas / Sans objet":
    return "sans_objet" if $p_gpu_classe in (
        "aucun_dedie", "integre_apple", "integre_intel") else "nd"
return {"4 Go ou moins": "<=4", "6-8 Go": "6-8",
        "10-12 Go": "10-12", "16 Go ou plus": ">=16",
        "Moins de 4 Go": "<=4", "4-6 Go": "6-8", "8 Go": "6-8",
        "12 Go": "10-12", "16 Go": ">=16", "32 Go": ">=16",
        "64 Go": ">=16", "128 Go ou plus": ">=16",
        "Sans objet (pas de GPU dédié)": "sans_objet"}.get(
            $d_vram or "", "nd")
""", "Text"))

    cols.append(formule("p_disk_bin", "Disque (publié)", """
v = $c_disk_free_gb
if v is not None:
    if v < 25: return "<25"
    if v <= 100: return "25-100"
    return ">100"
return {"Moins de 10 Go": "<25", "10-25 Go": "<25", "25-50 Go": "25-100",
        "50-100 Go": "25-100", "Plus de 100 Go": ">100"}.get($d_disk or "", "nd")
""", "Text"))

    cols.append(formule("p_python_majeur", "Python (publié)", """
CONNUES = ("3.10", "3.11", "3.12", "3.13")
v = $c_python or ""
if v:
    p = v.split(".")
    if len(p) >= 2:
        mm = p[0] + "." + p[1]
        return mm if mm in CONNUES else "autre"
d = $d_python or ""
if d in CONNUES: return d
if d == "Aucune installation": return "aucun"
if d == "Autre version": return "autre"
return "nd"
""", "Text"))

    cols.append(formule("p_session_type", "Type de session (publié)", """
c = ($cohorte or "").upper()
if c.startswith("M2"): return "cours_m2"
if c.startswith("SEMINAIRE"): return "seminaire"
if c.startswith("ECOLE"): return "ecole_ete"
return "nd"
""", "Text"))

    cols.append(formule("p_annee", "Année (publié)", """
import re
m = re.search(r"(20\\d\\d)", $cohorte or "")
return int(m.group(1)) if m else None
""", "Int", "Dérivée de cohorte, jamais de recu_le."))

    cols.append(formule("p_source", "Source (publié)",
                        'return $source or "nd"', "Text"))

    return cols


# --------------------------------------------------------------------------
# Appels API
# --------------------------------------------------------------------------

class Grist:
    def __init__(self, cle, doc, base=BASE_URL):
        self.doc = doc
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {cle}"})

    def _url(self, suffixe):
        return f"{self.base}/docs/{self.doc}{suffixe}"

    def colonnes(self, table):
        r = self.s.get(self._url(f"/tables/{table}/columns"))
        r.raise_for_status()
        return [c["id"] for c in r.json().get("columns", [])]

    def ajouter(self, table, cols):
        r = self.s.post(self._url(f"/tables/{table}/columns"),
                        json={"columns": cols})
        if not r.ok:
            raise RuntimeError(f"{r.status_code} — {r.text}")
        return r.json()

    def modifier(self, table, cols):
        r = self.s.patch(self._url(f"/tables/{table}/columns"),
                         json={"columns": cols})
        if not r.ok:
            raise RuntimeError(f"{r.status_code} — {r.text}")

    def supprimer(self, table, col_id):
        r = self.s.delete(self._url(f"/tables/{table}/columns/{col_id}"))
        if not r.ok:
            raise RuntimeError(f"{r.status_code} — {r.text}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", required=True, help="Document ID Grist")
    ap.add_argument("--table", default="Table1", help="Identifiant de la table")
    ap.add_argument("--base", default=BASE_URL, help="URL de l'API")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-defaults", action="store_true",
                    help="Conserver les colonnes A/B/C de Grist")
    ap.add_argument("--update-formulas", action="store_true",
                    help="Réécrire les formules des colonnes DÉJÀ existantes "
                         "(c_*, qa_*, p_*). Ne touche pas aux données saisies.")
    ap.add_argument("--update-gpu-fields", action="store_true",
                    help="Mettre à jour les choix et libellés des colonnes "
                         "d_gpu et d_vram déjà présentes.")
    args = ap.parse_args()

    cle = os.environ.get("GRIST_API_KEY")
    if not cle and not args.dry_run:
        sys.exit("GRIST_API_KEY absente de l'environnement.")

    cols = schema()
    print(f"{len(cols)} colonnes définies.\n")

    if args.dry_run:
        for c in cols:
            f = c["fields"]
            nature = "formule" if f.get("isFormula") else (
                "déclencheur" if f.get("formula") else "saisie")
            print(f"  {c['id']:<18} {f['type']:<22} {nature}")
        print("\n--dry-run : rien n'a été envoyé.")
        return

    g = Grist(cle, args.doc, args.base)

    existantes = g.colonnes(args.table)
    print(f"Table « {args.table} » : {len(existantes)} colonne(s) existante(s).")

    if args.update_gpu_fields:
        maj_gpu = [c for c in cols
                   if c["id"] in ("d_gpu", "d_vram")
                   and c["id"] in existantes]
        print(f"\nMise à jour de {len(maj_gpu)} question(s) GPU existante(s) :")
        for c in maj_gpu:
            try:
                g.modifier(args.table, [c])
                print(f"  ~ {c['id']}")
            except Exception as e:
                print(f"  ! {c['id']} — ÉCHEC : {e}")

    if args.update_formulas:
        maj = [c for c in cols
               if c["id"] in existantes and c["fields"].get("isFormula")]
        print(f"\nMise à jour de {len(maj)} formule(s) existante(s) :")
        for c in maj:
            try:
                g.modifier(args.table, [c])
                print(f"  ~ {c['id']}")
            except Exception as e:
                print(f"  ! {c['id']} — ÉCHEC : {e}")
        print("\nLes colonnes c_* déjà GELÉES ne sont pas concernées : une colonne "
              "convertie en données n'est plus une formule.")

    a_creer = [c for c in cols if c["id"] not in existantes]
    deja = len(cols) - len(a_creer)
    if deja:
        print(f"  {deja} déjà présente(s), ignorée(s).")

    # Création une par une : un message d'erreur exploitable en cas de souci
    # de syntaxe dans une formule, plutôt qu'un rejet global silencieux.
    creees = []
    for c in a_creer:
        try:
            g.ajouter(args.table, [c])
            creees.append(c["id"])
            print(f"  + {c['id']}")
        except Exception as e:
            print(f"  ! {c['id']} — ÉCHEC : {e}")

    print(f"\n{len(creees)} colonne(s) créée(s).")

    if not args.keep_defaults:
        restes = [c for c in g.colonnes(args.table)
                  if c in ("A", "B", "C") and c not in [x["id"] for x in cols]]
        for c in restes:
            try:
                g.supprimer(args.table, c)
                print(f"  - {c} (colonne Grist par défaut)")
            except Exception as e:
                print(f"  ! suppression de {c} impossible : {e}")

    print("""
À VÉRIFIER DANS L'INTERFACE, dans cet ordre :

  1. « Reçu le » — ouvrir le panneau de la colonne et confirmer que la formule
     de déclenchement est bien réglée sur « Apply to new records ». C'est le
     seul réglage que l'API ne pose pas de façon fiable.
  2. Access Rules — Deny All par défaut pour user.Access != OWNER, puis
     permission C seule sur cette table.
  3. Les quatre tests en fenêtre privée : lire / modifier / supprimer doivent
     échouer, ajouter doit réussir.

RAPPEL DE SÉQUENCE, en fin de chaque session :
  geler les colonnes c_* (Convert formula to data column), PUIS vider raw.
  Jamais l'inverse : raw est la source des c_*, et les p_* en dépendent.
""")


if __name__ == "__main__":
    main()
