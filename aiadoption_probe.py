#!/usr/bin/env python3
"""
Sonde AIadoption — relevé des caractéristiques techniques de votre machine.

Étude sur l'adéquation du matériel des apprenants aux outils computationnels
enseignés. Université Grenoble Alpes.

    python aiadoption_probe.py              # affiche ce qui serait relevé
    python aiadoption_probe.py --consent    # produit la ligne à coller

CE QUI EST RELEVÉ : uniquement les 11 caractéristiques listées dans KEYS
ci-dessous — système, processeur, mémoire, carte graphique, disque, Python.

CE QUI N'EST JAMAIS RELEVÉ, volontairement :
  - le nom de votre machine (platform.node / socket.gethostname)
  - votre nom d'utilisateur (getpass.getuser, os.getlogin)
  - tout chemin de fichier, y compris votre répertoire personnel
  - toute adresse réseau : IP, MAC, identifiants matériels, UUID
  - numéros de série de la machine ou de ses composants

Aucune de ces valeurs n'est lue par ce programme. La liste KEYS est figée :
rien d'autre ne peut sortir, même par accident.

La sonde n'envoie rien par le réseau. Elle affiche du texte, que vous copiez
vous-même dans le formulaire si vous le décidez.

Code source public, auditable. Licence : CC0 / domaine public.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA = "aiadoption-v1"

# Liste blanche figée. Le relevé est filtré dessus avant affichage.
KEYS = [
    "schema", "os", "os_release", "arch", "python", "cpu_model",
    "cpu_logical", "ram_gb", "gpu", "vram_gb", "disk_free_gb",
]

GO = 2 ** 30


def _run(cmd):
    """Exécute une commande, rend sa sortie ou None. Jamais d'exception."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Relevés
# --------------------------------------------------------------------------

def cpu_model():
    """Libellé commercial du processeur. Ne contient aucune donnée personnelle."""
    sys_ = platform.system()
    if sys_ == "Linux":
        try:
            for ligne in Path("/proc/cpuinfo").read_text().splitlines():
                if "model name" in ligne:
                    return ligne.split(":", 1)[1].strip()
        except Exception:
            pass
    elif sys_ == "Darwin":
        v = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if v:
            return v
    v = platform.processor() or ""
    return v.strip() or None


def ram_gb():
    """Mémoire vive totale. psutil si disponible, sinon repli par plateforme."""
    try:
        import psutil
        return round(psutil.virtual_memory().total / GO)
    except Exception:
        pass

    sys_ = platform.system()
    try:
        if sys_ == "Linux":
            for ligne in Path("/proc/meminfo").read_text().splitlines():
                if ligne.startswith("MemTotal:"):
                    return round(int(ligne.split()[1]) * 1024 / GO)
        elif sys_ == "Darwin":
            v = _run(["sysctl", "-n", "hw.memsize"])
            if v:
                return round(int(v) / GO)
        elif sys_ == "Windows":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / GO)
    except Exception:
        pass
    return None


def gpu():
    """
    Rend (libellé, vram_go).

    Quatre états distincts, et la distinction compte :
      "<nom>"     : GPU dédié identifié
      "apple-mps" : GPU intégré Apple Silicon
      "aucun"     : détection réussie, aucun GPU dédié
      "inconnu"   : détection impossible (ni torch ni nvidia-smi)

    Ne jamais confondre "aucun" et "inconnu" : l'absence de torch ne
    signifie pas l'absence de carte graphique.
    """
    try:
        import torch
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            return torch.cuda.get_device_name(0), round(p.total_memory / GO)
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "apple-mps", None
        return "aucun", None
    except Exception:
        pass

    if shutil.which("nvidia-smi"):
        v = _run(["nvidia-smi",
                  "--query-gpu=name,memory.total",
                  "--format=csv,noheader,nounits"])
        if v:
            premier = v.splitlines()[0]
            parts = [p.strip() for p in premier.split(",")]
            if parts:
                vram = None
                if len(parts) > 1 and parts[1].isdigit():
                    vram = round(int(parts[1]) / 1024)
                return parts[0], vram

    # Apple Silicon : le GPU intégré est déductible de l'architecture seule.
    if platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64"):
        return "apple-mps", None

    return "inconnu", None


def disk_free_gb():
    """Espace libre sur le volume du répertoire personnel. Aucun chemin n'est relevé."""
    try:
        return round(shutil.disk_usage(Path.home()).free / GO)
    except Exception:
        return None


def releve():
    g, vram = gpu()
    brut = {
        "schema": SCHEMA,
        "os": platform.system() or None,
        "os_release": platform.release() or None,
        "arch": platform.machine() or None,
        "python": platform.python_version(),
        "cpu_model": cpu_model(),
        "cpu_logical": os.cpu_count(),
        "ram_gb": ram_gb(),
        "gpu": g,
        "vram_gb": vram,
        "disk_free_gb": disk_free_gb(),
    }
    # Filtrage sur la liste blanche : rien hors KEYS ne peut sortir.
    return {k: brut.get(k) for k in KEYS}


# --------------------------------------------------------------------------
# Garde-fous
# --------------------------------------------------------------------------

INTERDITS = [
    (r"/home/[^/\s]+", "chemin personnel"),
    (r"/Users/[^/\s]+", "chemin personnel"),
    (r"[A-Z]:\\\\Users\\\\", "chemin personnel"),
    (r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b", "adresse MAC"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "adresse IP"),
]


def autocontrole(d):
    """Vérifie la forme et l'absence de motifs identifiants. Rend la liste des alertes."""
    alertes = []
    if set(d) != set(KEYS):
        alertes.append(f"clés inattendues : {set(d) ^ set(KEYS)}")
    if d.get("schema") != SCHEMA:
        alertes.append("schéma incorrect")
    texte = json.dumps(d, ensure_ascii=False)
    if len(texte) >= 600:
        alertes.append(f"sortie trop longue ({len(texte)} car., limite 600)")
    for motif, nom in INTERDITS:
        if re.search(motif, texte):
            alertes.append(f"motif suspect détecté ({nom})")
    return alertes


# --------------------------------------------------------------------------
# Affichage
# --------------------------------------------------------------------------

LIBELLES = {
    "os": "Système", "os_release": "Version du système", "arch": "Architecture",
    "python": "Python", "cpu_model": "Processeur", "cpu_logical": "Cœurs logiques",
    "ram_gb": "Mémoire vive", "gpu": "Carte graphique", "vram_gb": "Mémoire GPU",
    "disk_free_gb": "Disque libre",
}

UNITES = {"ram_gb": " Go", "vram_gb": " Go", "disk_free_gb": " Go"}


def afficher_apercu(d):
    print("\n  Relevé de votre machine\n  " + "-" * 44)
    for k in KEYS:
        if k == "schema":
            continue
        v = d[k]
        if v is None:
            v = "non déterminé"
        elif k in UNITES:
            v = f"{v}{UNITES[k]}"
        elif k == "gpu" and v == "aucun":
            v = "aucune carte dédiée"
        elif k == "gpu" and v == "inconnu":
            v = "non déterminée"
        elif k == "gpu" and v == "apple-mps":
            v = "GPU intégré Apple Silicon"
        print(f"  {LIBELLES[k]:<22} {v}")
    print("  " + "-" * 44)
    print("""
  Ne sont relevés ni le nom de votre machine, ni votre nom d'utilisateur,
  ni aucun chemin, adresse réseau ou numéro de série.

  Rien n'a été transmis. Ce programme n'accède pas au réseau.
""")


def main():
    ap = argparse.ArgumentParser(
        description="Sonde AIadoption — relevé des caractéristiques matérielles.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--consent", action="store_true",
                    help="Produire la ligne à coller dans le formulaire.")
    ap.add_argument("--cohort", default=None,
                    help="Jeton de session indiqué par l'enseignante.")
    args = ap.parse_args()

    d = releve()

    alertes = autocontrole(d)
    if alertes:
        print("\n  ARRÊT — autocontrôle en échec :", file=sys.stderr)
        for a in alertes:
            print(f"    - {a}", file=sys.stderr)
        print("  Rien n'est produit. Signalez ce message à l'enseignante.\n",
              file=sys.stderr)
        sys.exit(1)

    if not args.consent:
        afficher_apercu(d)
        print("  Si vous acceptez de participer, relancez avec --consent :\n")
        print(f"      python {Path(sys.argv[0]).name} --consent"
              + (f" --cohort {args.cohort}" if args.cohort else "") + "\n")
        print("  La participation est volontaire et sans incidence sur votre"
              " évaluation.\n")
        return

    afficher_apercu(d)
    print("  Copiez la ligne ci-dessous et collez-la dans le formulaire :\n")
    print(json.dumps(d, separators=(",", ":"), ensure_ascii=False))
    print()
    if args.cohort:
        print(f"  Cohorte à sélectionner dans le formulaire : {args.cohort}")
    print("  Champ « Source » à sélectionner : sonde\n")


if __name__ == "__main__":
    main()
