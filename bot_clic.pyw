"""Bot clic : à l'heure choisie, ouvre un site puis exécute une liste de tâches
(chercher un texte à l'écran, cliquer, écrire du texte, appuyer sur une touche, attendre).

Lancer : raccourci « Bot clic » du Bureau, ou `pyw bot_clic.pyw`.
Aucune bibliothèque à installer : uniquement Python standard + la reconnaissance
de texte (OCR) intégrée à Windows.
"""
import base64
import ctypes
import datetime as dt
import json
import os
import queue
import struct
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unicodedata
import webbrowser
from ctypes import wintypes
from tkinter import ttk, messagebox

# Coordonnées en vrais pixels de l'écran (sinon décalage avec le zoom Windows 125 %, 150 %...)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

DOSSIER = os.path.dirname(os.path.abspath(__file__))
FICHIER_CONFIG = os.path.join(DOSSIER, "config.json")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

DEFAUT = {
    "url": "https://codtino.github.io/bouton-rouge/",
    "heure": 22,
    "minute": 25,
    "attente": 5,
    "tous_les_jours": True,
    "etapes": [{"type": "clic", "x": 189, "y": 78, "nombre": 10, "pause": 0.2}],
}

# ---------------------------------------------------------------- souris / clavier

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]


KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
TOUCHES_ETENDUES = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}

TOUCHES = {
    "Entrée": [0x0D],
    "Tab": [0x09],
    "Maj+Tab": [0x10, 0x09],
    "Échap": [0x1B],
    "Espace": [0x20],
    "Retour arrière": [0x08],
    "Suppr": [0x2E],
    "Flèche haut": [0x26],
    "Flèche bas": [0x28],
    "Flèche gauche": [0x25],
    "Flèche droite": [0x27],
    "Page bas": [0x22],
    "Page haut": [0x21],
    "Ctrl+A (tout sélectionner)": [0x11, 0x41],
    "Ctrl+C (copier)": [0x11, 0x43],
    "Ctrl+V (coller)": [0x11, 0x56],
    "F5 (recharger)": [0x74],
}


def _clavier(vk=0, scan=0, flags=0):
    i = INPUT(type=1)
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def _envoyer(*entrees):
    tableau = (INPUT * len(entrees))(*entrees)
    user32.SendInput(len(entrees), tableau, ctypes.sizeof(INPUT))


def position_souris():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def souris_dans_coin():
    x, y = position_souris()
    l, h = user32.GetSystemMetrics(0) - 1, user32.GetSystemMetrics(1) - 1
    return (x in (0, l)) and (y in (0, h))


def cliquer(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.02)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def appuyer(vks):
    for vk in vks:
        _envoyer(_clavier(vk=vk, flags=KEYEVENTF_EXTENDEDKEY if vk in TOUCHES_ETENDUES else 0))
    for vk in reversed(vks):
        _envoyer(_clavier(vk=vk, flags=KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if vk in TOUCHES_ETENDUES else 0)))


def taper(texte):
    """Tape le texte caractère par caractère (accents et emojis compris)."""
    for ch in texte:
        if ch == "\r":
            continue
        if ch == "\n":
            appuyer([0x0D])
        else:
            data = ch.encode("utf-16-le")
            for k in range(0, len(data), 2):
                code = int.from_bytes(data[k:k + 2], "little")
                _envoyer(_clavier(scan=code, flags=KEYEVENTF_UNICODE),
                         _clavier(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        time.sleep(0.015)


def ouvrir_navigateur(url):
    if os.path.exists(CHROME):
        subprocess.Popen([CHROME, "--new-window", "--start-maximized", url])
    else:
        webbrowser.open(url, new=1)

# ---------------------------------------------------------------- scanner de texte (OCR Windows)

for _f in ("GetDC", "CreateCompatibleDC", "CreateCompatibleBitmap", "SelectObject"):
    getattr(user32 if _f == "GetDC" else gdi32, _f).restype = ctypes.c_void_p
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


IMAGE_ECRAN = os.path.join(tempfile.gettempdir(), "bot_clic_ecran.bmp")


def capturer_ecran(chemin=IMAGE_ECRAN):
    """Capture de l'écran principal en BMP (vrais pixels)."""
    l, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    ecran = user32.GetDC(None)
    memoire = gdi32.CreateCompatibleDC(ecran)
    image = gdi32.CreateCompatibleBitmap(ecran, l, h)
    ancien = gdi32.SelectObject(memoire, image)
    gdi32.BitBlt(memoire, 0, 0, l, h, ecran, 0, 0, 0x00CC0020)  # SRCCOPY
    info = BITMAPINFOHEADER(40, l, h, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = ctypes.create_string_buffer(l * h * 4)
    gdi32.GetDIBits(memoire, image, 0, h, pixels, ctypes.byref(info), 0)
    gdi32.SelectObject(memoire, ancien)
    gdi32.DeleteObject(image)
    gdi32.DeleteDC(memoire)
    user32.ReleaseDC(None, ecran)
    with open(chemin, "wb") as f:
        f.write(b"BM" + struct.pack("<IHHI", 54 + len(pixels.raw), 0, 0, 54))
        f.write(bytes(info))
        f.write(pixels.raw)
    return chemin


OCR_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$m = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $m.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime] | Out-Null
$f = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:BOT_CLIC_IMAGE)) ([Windows.Storage.StorageFile])
$s = Await ($f.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$d = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($s)) ([Windows.Graphics.Imaging.BitmapDecoder])
$b = Await ($d.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$e = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$r = Await ($e.RecognizeAsync($b)) ([Windows.Media.Ocr.OcrResult])
$i = 0
foreach ($l in $r.Lines) { foreach ($w in $l.Words) { $q = $w.BoundingRect; "$i`t$([int]$q.X)`t$([int]$q.Y)`t$([int]$q.Width)`t$([int]$q.Height)`t$($w.Text)" }; $i++ }
$s.Dispose()
"""


def lire_ecran():
    """Capture l'écran et renvoie les mots lus : [(ligne, x, y, largeur, hauteur, texte), ...]."""
    capturer_ecran()
    env = dict(os.environ, BOT_CLIC_IMAGE=IMAGE_ECRAN)
    commande = base64.b64encode(OCR_PS.encode("utf-16-le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", commande],
                       capture_output=True, env=env, timeout=60, creationflags=0x08000000)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[:300] or "la reconnaissance de texte a échoué")
    mots = []
    for ligne in r.stdout.decode("utf-8", "replace").splitlines():
        champs = ligne.split("\t", 5)
        if len(champs) == 6:
            mots.append((int(champs[0]), *map(int, champs[1:5]), champs[5]))
    return mots


def normaliser(s):
    """minuscules, sans accents : « Réserver » == « reserver »."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def lettres(s):
    """Seulement lettres et chiffres, sans accents ni majuscules : « Ven. 13 nov. » -> « ven13nov »."""
    return "".join(c for c in normaliser(s) if c.isalnum())


def trouver_texte(recherche, mots):
    """Toutes les positions (centre x, centre y) où le texte apparaît, de haut en bas.
    Les espaces, la ponctuation, les accents et les majuscules sont ignorés."""
    cible = lettres(recherche)
    if not cible:
        return []
    lignes = {}
    for m in mots:
        lignes.setdefault(m[0], []).append(m)
    trouves = []
    for ligne in lignes.values():
        texte, mot_de = "", []  # mot_de[k] = numéro du mot d'où vient la lettre k
        for j, m in enumerate(ligne):
            l = lettres(m[5])
            texte += l
            mot_de += [j] * len(l)
        k = texte.find(cible)
        while k != -1:
            premier, dernier = mot_de[k], mot_de[k + len(cible) - 1]
            boites = ligne[premier:dernier + 1]
            x1 = min(b[1] for b in boites)
            y1 = min(b[2] for b in boites)
            x2 = max(b[1] + b[3] for b in boites)
            y2 = max(b[2] + b[4] for b in boites)
            trouves.append(((x1 + x2) // 2, (y1 + y2) // 2))
            k = texte.find(cible, k + 1)
    return sorted(trouves, key=lambda p: (p[1], p[0]))


TEXTE_LU = os.path.join(tempfile.gettempdir(), "bot_clic_texte_lu.txt")


def scanner(recherche):
    mots = lire_ecran()
    # Garde ce qui a été lu, pour pouvoir le montrer si le texte n'est pas trouvé
    lignes = {}
    for m in mots:
        lignes.setdefault(m[0], []).append(m)
    with open(TEXTE_LU, "w", encoding="utf-8") as f:
        f.write(f"Texte lu à l'écran le {dt.datetime.now():%d/%m à %H:%M:%S}  (position x, y : texte)\n\n")
        for l in lignes.values():
            f.write(f"({l[0][1]}, {l[0][2]})  " + " ".join(m[5] for m in l) + "\n")
    return trouver_texte(recherche, mots)

# ---------------------------------------------------------------- réglages

def charger_config():
    cfg = json.loads(json.dumps(DEFAUT))
    fichier = {}
    try:
        with open(FICHIER_CONFIG, encoding="utf-8") as f:
            fichier = json.load(f)
    except Exception:
        pass
    cfg.update(fichier)
    # Ancienne version du bot (un seul clic) -> devient la première tâche de la liste
    if "etapes" not in fichier and fichier.get("x") is not None:
        cfg["etapes"] = [{"type": "clic", "x": fichier["x"], "y": fichier["y"],
                          "nombre": fichier.get("clics", 1), "pause": fichier.get("intervalle", 0.2)}]
    for k in ("x", "y", "clics", "intervalle"):
        cfg.pop(k, None)
    return cfg


def decalage(e):
    dx, dy = e.get("dx", 0), e.get("dy", 0)
    return f" {dx:+d},{dy:+d}" if dx or dy else ""


def decrire(e):
    t = e["type"]
    if t == "clic":
        fois = f" ×{e['nombre']}" if e["nombre"] > 1 else ""
        if e.get("variable"):
            return f"🖱  Clic{fois} sur [{e['variable']}]{decalage(e)}"
        return f"🖱  Clic{fois} à ({e['x']}, {e['y']})"
    if t == "texte":
        apercu = e["texte"].replace("\n", " ⏎ ")
        return f"⌨  Écrire « {apercu[:45]}{'…' if len(apercu) > 45 else ''} »"
    if t == "touche":
        return f"⏎  Touche {e['touche']}"
    if t == "attente":
        return f"⏱  Attendre {e['secondes']:g} s"
    if t == "chercher":
        n = f" (n°{e['occurrence']})" if e["occurrence"] > 1 else ""
        return f"🔍  Chercher « {e['texte']} »{n} → [{e['variable']}]"
    return t

# ---------------------------------------------------------------- fenêtre d'une tâche

class DialogueEtape(tk.Toplevel):
    TITRES = {"clic": "Clic", "texte": "Écrire du texte", "touche": "Appuyer sur une touche",
              "attente": "Attendre", "chercher": "Chercher un texte à l'écran"}
    FIXE = "la position fixe ci-dessous"

    def __init__(self, app, etape):
        super().__init__(app.root)
        self.app = app
        self.e = dict(etape)
        self.resultat = None
        self.title(self.TITRES[self.e["type"]])
        self.transient(app.root)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=14)
        f.grid()
        t = self.e["type"]
        gris = {"foreground": "#888", "justify": "left"}

        if t == "clic":
            variables = app.noms_variables()
            ttk.Label(f, text="Cliquer sur :").grid(row=0, column=0, sticky="w")
            self.v_cible = tk.StringVar(value=f"[{self.e['variable']}]" if self.e.get("variable") else self.FIXE)
            ttk.Combobox(f, textvariable=self.v_cible, values=[self.FIXE] + [f"[{v}]" for v in variables],
                         state="readonly", width=30).grid(row=0, column=1, columnspan=3, sticky="w", pady=3)
            ttk.Label(f, text="Position X :").grid(row=1, column=0, sticky="w")
            self.v_x = tk.StringVar(value="" if self.e.get("x") is None else str(self.e["x"]))
            ttk.Entry(f, textvariable=self.v_x, width=7).grid(row=1, column=1, sticky="w", pady=3)
            ttk.Label(f, text="Y :").grid(row=1, column=2, sticky="e")
            self.v_y = tk.StringVar(value="" if self.e.get("y") is None else str(self.e["y"]))
            ttk.Entry(f, textvariable=self.v_y, width=7).grid(row=1, column=3, sticky="w", padx=(4, 0))
            ttk.Button(f, text="Choisir sur l'écran…", command=self.choisir).grid(
                row=2, column=1, columnspan=3, sticky="we", pady=(2, 6))
            ttk.Label(f, text="Décalage X / Y :").grid(row=3, column=0, sticky="w")
            self.v_dx = tk.StringVar(value=str(self.e.get("dx", 0)))
            self.v_dy = tk.StringVar(value=str(self.e.get("dy", 0)))
            ttk.Spinbox(f, from_=-2000, to=2000, textvariable=self.v_dx, width=6).grid(row=3, column=1, sticky="w", pady=3)
            ttk.Spinbox(f, from_=-2000, to=2000, textvariable=self.v_dy, width=6).grid(row=3, column=3, sticky="w", padx=(4, 0))
            ttk.Label(f, text="Nombre de clics :").grid(row=4, column=0, sticky="w")
            self.v_n = tk.StringVar(value=str(self.e.get("nombre", 1)))
            ttk.Spinbox(f, from_=1, to=10000, textvariable=self.v_n, width=7).grid(row=4, column=1, columnspan=3, sticky="w", pady=3)
            ttk.Label(f, text="Pause entre clics (s) :").grid(row=5, column=0, sticky="w")
            self.v_p = tk.StringVar(value=str(self.e.get("pause", 0.2)))
            ttk.Spinbox(f, from_=0.05, to=10, increment=0.05, textvariable=self.v_p, width=7).grid(row=5, column=1, columnspan=3, sticky="w", pady=3)
            ttk.Label(f, text="[nom] = position trouvée par une tâche « Chercher » placée avant.\n"
                              "Décalage : pour cliquer à côté du texte (ex. X +200 = 200 px à droite).",
                      **gris).grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))
        elif t == "texte":
            ttk.Label(f, text="Texte à écrire (les retours à la ligne = touche Entrée) :").grid(row=0, column=0, sticky="w")
            self.zone = tk.Text(f, width=46, height=6, wrap="word", font=("Segoe UI", 10))
            self.zone.grid(row=1, column=0, pady=4)
            self.zone.insert("1.0", self.e.get("texte", ""))
            self.zone.focus_set()
            ttk.Label(f, text="Le texte est écrit là où se trouve le curseur :\n"
                              "mets d'abord une tâche « Clic » sur la zone de texte.", **gris).grid(row=2, column=0, sticky="w")
        elif t == "touche":
            ttk.Label(f, text="Touche :").grid(row=0, column=0, sticky="w")
            self.v_t = tk.StringVar(value=self.e.get("touche", "Entrée"))
            ttk.Combobox(f, textvariable=self.v_t, values=list(TOUCHES), state="readonly", width=28).grid(row=0, column=1, pady=3, padx=(6, 0))
        elif t == "attente":
            ttk.Label(f, text="Attendre (secondes) :").grid(row=0, column=0, sticky="w")
            self.v_s = tk.StringVar(value=str(self.e.get("secondes", 2)))
            ttk.Spinbox(f, from_=0.1, to=3600, increment=0.5, textvariable=self.v_s, width=8).grid(row=0, column=1, pady=3, padx=(6, 0))
        elif t == "chercher":
            ttk.Label(f, text="Texte à chercher :").grid(row=0, column=0, sticky="w")
            self.v_txt = tk.StringVar(value=self.e.get("texte", ""))
            champ = ttk.Entry(f, textvariable=self.v_txt, width=30)
            champ.grid(row=0, column=1, columnspan=2, sticky="we", pady=3)
            champ.focus_set()
            ttk.Label(f, text="Garder la position sous le nom :").grid(row=1, column=0, sticky="w")
            self.v_var = tk.StringVar(value=self.e.get("variable") or app.nouveau_nom())
            ttk.Entry(f, textvariable=self.v_var, width=18).grid(row=1, column=1, columnspan=2, sticky="w", pady=3)
            ttk.Label(f, text="S'il apparaît plusieurs fois, prendre le n° :").grid(row=2, column=0, sticky="w")
            self.v_occ = tk.StringVar(value=str(self.e.get("occurrence", 1)))
            ttk.Spinbox(f, from_=1, to=50, textvariable=self.v_occ, width=5).grid(row=2, column=1, sticky="w", pady=3)
            ttk.Label(f, text="Chercher pendant au plus (s) :").grid(row=3, column=0, sticky="w")
            self.v_del = tk.StringVar(value=str(self.e.get("delai", 10)))
            ttk.Spinbox(f, from_=0, to=600, textvariable=self.v_del, width=5).grid(row=3, column=1, sticky="w", pady=3)
            ttk.Label(f, text="S'il n'est pas trouvé :").grid(row=4, column=0, sticky="w")
            self.v_abs = tk.StringVar(value="Passer à la suite" if self.e.get("si_absent") == "continuer" else "Arrêter le bot")
            ttk.Combobox(f, textvariable=self.v_abs, values=["Arrêter le bot", "Passer à la suite"],
                         state="readonly", width=18).grid(row=4, column=1, columnspan=2, sticky="w", pady=3)
            ttk.Button(f, text="🔍 Tester le scanner…", command=self.tester_scanner).grid(
                row=5, column=0, columnspan=2, sticky="we", pady=(8, 2))
            ttk.Button(f, text="📄 Voir le texte lu", command=self.voir_texte_lu).grid(
                row=5, column=2, sticky="we", pady=(8, 2), padx=(4, 0))
            self.v_res = tk.StringVar()
            ttk.Label(f, textvariable=self.v_res, foreground="#0a6", justify="left").grid(row=6, column=0, columnspan=3, sticky="w")
            ttk.Label(f, text="Les ordres « n° » vont de haut en bas, puis de gauche à droite.\n"
                              "Majuscules, accents, espaces et ponctuation ne comptent pas.", **gris).grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 0))

        b = ttk.Frame(f)
        b.grid(row=10, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Annuler", command=self.destroy).pack(side="right")
        ttk.Button(b, text="OK", command=self.valider).pack(side="right", padx=(0, 6))
        self.bind("<Escape>", lambda _: self.destroy())

        self.grab_set()
        self.wait_window()

    def choisir(self):
        def recu(pos):
            self.grab_set()
            if pos:
                self.v_x.set(str(pos[0]))
                self.v_y.set(str(pos[1]))
                self.v_cible.set(self.FIXE)
        self.grab_release()
        self.app.compte_a_rebours(lambda: self.app.voile_position(recu, (self,)), (self,))

    def tester_scanner(self):
        texte = self.v_txt.get().strip()
        if not texte:
            self.v_res.set("Écris d'abord le texte à chercher.")
            return

        def scanner_puis_montrer():
            try:
                trouves = scanner(texte)
                erreur = None
            except Exception as ex:
                trouves, erreur = [], str(ex)
            self.app.root.deiconify()
            self.deiconify()
            self.lift()
            self.grab_set()
            if erreur:
                self.v_res.set(f"Erreur : {erreur}")
            elif not trouves:
                self.v_res.set(f"« {texte} » n'a pas été trouvé à l'écran.\n"
                               "Clique sur « Voir le texte lu » pour voir ce que le scanner a lu.")
            else:
                liste = ", ".join(f"n°{i + 1} ({x}, {y})" for i, (x, y) in enumerate(trouves[:6]))
                self.v_res.set(f"Trouvé {len(trouves)} fois : {liste}\n(les points rouges montrent où)")
                self.app.montrer_reperes(trouves)
        self.grab_release()
        self.v_res.set("")
        self.app.compte_a_rebours(scanner_puis_montrer, (self,))

    def voir_texte_lu(self):
        if os.path.exists(TEXTE_LU):
            os.startfile(TEXTE_LU)
        else:
            self.v_res.set("Lance d'abord « Tester le scanner ».")

    def valider(self):
        t = self.e["type"]
        try:
            if t == "clic":
                cible = self.v_cible.get()
                variable = None if cible == self.FIXE else cible.strip("[]")
                self.e.update(variable=variable, dx=int(self.v_dx.get() or 0), dy=int(self.v_dy.get() or 0),
                              nombre=max(1, int(self.v_n.get())), pause=max(0.0, float(self.v_p.get().replace(",", "."))))
                if variable is None:
                    self.e.update(x=int(self.v_x.get()), y=int(self.v_y.get()))
                else:
                    self.e.update(x=int(self.v_x.get()) if self.v_x.get().strip() else None,
                                  y=int(self.v_y.get()) if self.v_y.get().strip() else None)
            elif t == "texte":
                self.e["texte"] = self.zone.get("1.0", "end-1c")
                if not self.e["texte"]:
                    raise ValueError
            elif t == "touche":
                self.e["touche"] = self.v_t.get()
            elif t == "attente":
                self.e["secondes"] = max(0.1, float(self.v_s.get().replace(",", ".")))
            elif t == "chercher":
                nom = "".join(self.v_var.get().split())
                if not self.v_txt.get().strip() or not nom:
                    raise ValueError
                self.e.update(texte=self.v_txt.get().strip(), variable=nom, occurrence=max(1, int(self.v_occ.get())),
                              delai=max(0.0, float(self.v_del.get().replace(",", "."))),
                              si_absent="continuer" if self.v_abs.get() == "Passer à la suite" else "arreter")
        except ValueError:
            messagebox.showerror("Bot clic", "Un champ est vide ou n'est pas un nombre valide.", parent=self)
            return
        self.resultat = self.e
        self.destroy()

# ---------------------------------------------------------------- fenêtre principale

class App:
    def __init__(self, root):
        self.root = root
        self.cfg = charger_config()
        self.deja_lance = None  # date du dernier lancement automatique
        self.en_cours = False
        self.actif = False
        self.positions = {}  # positions trouvées par les tâches « Chercher »

        root.title("Bot clic")
        root.resizable(False, False)
        f = ttk.Frame(root, padding=16)
        f.grid()

        # -- quand et où
        ttk.Label(f, text="Site à ouvrir :").grid(row=0, column=0, sticky="w")
        self.v_url = tk.StringVar(value=self.cfg["url"])
        ttk.Entry(f, textvariable=self.v_url, width=46).grid(row=0, column=1, columnspan=3, sticky="we", pady=3)
        ttk.Button(f, text="Ouvrir", width=8, command=lambda: self.v_url.get().strip() and ouvrir_navigateur(self.v_url.get().strip())).grid(row=0, column=4, padx=(6, 0))

        ttk.Label(f, text="Heure de lancement :").grid(row=1, column=0, sticky="w")
        self.v_h = tk.StringVar(value=f"{self.cfg['heure']:02d}")
        self.v_m = tk.StringVar(value=f"{self.cfg['minute']:02d}")
        ttk.Combobox(f, textvariable=self.v_h, values=[f"{i:02d}" for i in range(24)], width=4,
                     state="readonly").grid(row=1, column=1, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.v_m, values=[f"{i:02d}" for i in range(60)], width=4,
                     state="readonly").grid(row=1, column=2, sticky="w")
        self.v_jours = tk.BooleanVar(value=self.cfg["tous_les_jours"])
        ttk.Checkbutton(f, text="Tous les jours", variable=self.v_jours).grid(row=1, column=3, sticky="w")

        ttk.Label(f, text="Attente chargement (s) :").grid(row=2, column=0, sticky="w")
        self.v_att = tk.StringVar(value=str(self.cfg["attente"]))
        ttk.Spinbox(f, from_=0, to=60, textvariable=self.v_att, width=5).grid(row=2, column=1, columnspan=2, sticky="w", pady=3)

        # -- liste des tâches
        ttk.Label(f, text="Liste des tâches (exécutées dans l'ordre) :", font=("Segoe UI", 10, "bold")).grid(
            row=3, column=0, columnspan=5, sticky="w", pady=(12, 4))
        self.liste = ttk.Treeview(f, columns=("n", "action"), show="headings", height=11, selectmode="browse")
        self.liste.heading("n", text="#")
        self.liste.heading("action", text="Action")
        self.liste.column("n", width=34, anchor="center", stretch=False)
        self.liste.column("action", width=380)
        self.liste.grid(row=4, column=0, columnspan=4, sticky="nsew")
        self.liste.bind("<Double-1>", lambda _: self.modifier())
        self.liste.bind("<Delete>", lambda _: self.supprimer())

        c = ttk.Frame(f)
        c.grid(row=4, column=4, sticky="n", padx=(6, 0))
        for txt, cmd in (("+ Chercher", lambda: self.ajouter("chercher")),
                         ("+ Clic", lambda: self.ajouter("clic")),
                         ("+ Texte", lambda: self.ajouter("texte")),
                         ("+ Touche", lambda: self.ajouter("touche")),
                         ("+ Attente", lambda: self.ajouter("attente"))):
            ttk.Button(c, text=txt, width=11, command=cmd).pack(fill="x", pady=1)
        ttk.Separator(c).pack(fill="x", pady=5)
        for txt, cmd in (("Modifier", self.modifier), ("Supprimer", self.supprimer),
                         ("▲ Monter", lambda: self.deplacer(-1)), ("▼ Descendre", lambda: self.deplacer(1))):
            ttk.Button(c, text=txt, width=11, command=cmd).pack(fill="x", pady=1)

        # -- lancement
        b = ttk.Frame(f)
        b.grid(row=6, column=0, columnspan=5, pady=(12, 4), sticky="we")
        self.btn_actif = ttk.Button(b, text="▶ Activer le bot", command=self.basculer)
        self.btn_actif.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(b, text="Tester maintenant", command=self.lancer).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.v_statut = tk.StringVar(value="Bot en pause.")
        ttk.Label(f, textvariable=self.v_statut, foreground="#555").grid(row=7, column=0, columnspan=5, sticky="w")
        ttk.Label(f, text="Astuce : la fenêtre doit rester ouverte (tu peux la réduire).\n"
                          "Pendant l'exécution, mets la souris dans un coin de l'écran pour arrêter.",
                  foreground="#888", justify="left").grid(row=8, column=0, columnspan=5, sticky="w", pady=(8, 0))

        self.rafraichir()
        self.tic()

    # ---- réglages
    def lire(self):
        try:
            self.cfg.update(
                url=self.v_url.get().strip(),
                heure=int(self.v_h.get()),
                minute=int(self.v_m.get()),
                attente=max(0.0, float(self.v_att.get().replace(",", "."))),
                tous_les_jours=self.v_jours.get(),
            )
        except ValueError:
            messagebox.showerror("Bot clic", "« Attente chargement » n'est pas un nombre valide.")
            return False
        self.sauver()
        return True

    def sauver(self):
        with open(FICHIER_CONFIG, "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, indent=2, ensure_ascii=False)

    def noms_variables(self):
        noms = []
        for e in self.cfg["etapes"]:
            if e["type"] == "chercher" and e["variable"] not in noms:
                noms.append(e["variable"])
        return noms

    def nouveau_nom(self):
        k = 1
        while f"position{k}" in self.noms_variables():
            k += 1
        return f"position{k}"

    # ---- liste
    def rafraichir(self, choisir=None):
        self.liste.delete(*self.liste.get_children())
        for i, e in enumerate(self.cfg["etapes"]):
            self.liste.insert("", "end", iid=str(i), values=(i + 1, decrire(e)))
        if choisir is not None and 0 <= choisir < len(self.cfg["etapes"]):
            self.liste.selection_set(str(choisir))
            self.liste.see(str(choisir))

    def selection(self):
        s = self.liste.selection()
        return int(s[0]) if s else None

    def ajouter(self, type_):
        modele = {"type": type_}
        if type_ == "clic":
            noms = self.noms_variables()
            if noms:  # par défaut : cliquer sur la dernière position cherchée
                modele["variable"] = noms[-1]
        d = DialogueEtape(self, modele)
        if d.resultat:
            i = self.selection()
            i = len(self.cfg["etapes"]) if i is None else i + 1
            self.cfg["etapes"].insert(i, d.resultat)
            self.sauver()
            self.rafraichir(i)

    def modifier(self):
        i = self.selection()
        if i is None:
            return
        d = DialogueEtape(self, self.cfg["etapes"][i])
        if d.resultat:
            self.cfg["etapes"][i] = d.resultat
            self.sauver()
            self.rafraichir(i)

    def supprimer(self):
        i = self.selection()
        if i is None:
            return
        del self.cfg["etapes"][i]
        self.sauver()
        self.rafraichir(min(i, len(self.cfg["etapes"]) - 1))

    def deplacer(self, sens):
        i = self.selection()
        if i is None or not 0 <= i + sens < len(self.cfg["etapes"]):
            return
        e = self.cfg["etapes"]
        e[i], e[i + sens] = e[i + sens], e[i]
        self.sauver()
        self.rafraichir(i + sens)

    # ---- outils écran
    def compte_a_rebours(self, ensuite, cacher=()):
        """Cache les fenêtres du bot, laisse 3 s pour afficher la bonne fenêtre, puis lance `ensuite`."""
        for w in cacher:
            w.withdraw()
        self.root.withdraw()
        bandeau = tk.Toplevel(self.root)
        bandeau.overrideredirect(True)
        bandeau.attributes("-topmost", True)
        bandeau.geometry(f"+{user32.GetSystemMetrics(0) // 2 - 150}+30")
        lbl = tk.Label(bandeau, bg="#e11d2e", fg="white", font=("Segoe UI", 14, "bold"), padx=20, pady=10)
        lbl.pack()

        def decompte(n):
            if n == 0:
                bandeau.destroy()
                self.root.after(150, ensuite)  # le bandeau a disparu avant la capture
                return
            lbl.config(text=f"Affiche la bonne fenêtre… {n}")
            self.root.after(1000, lambda: decompte(n - 1))
        decompte(3)

    def voile_position(self, callback, cacher=()):
        voile = tk.Toplevel(self.root)
        voile.attributes("-fullscreen", True)
        voile.attributes("-topmost", True)
        voile.attributes("-alpha", 0.35)
        voile.configure(bg="black", cursor="crosshair")
        tk.Label(voile, text="Clique à l'endroit voulu  (Échap pour annuler)",
                 bg="black", fg="white", font=("Segoe UI", 20, "bold")).pack(pady=40)

        def fini(pos):
            voile.destroy()
            self.root.deiconify()
            for w in cacher:
                w.deiconify()
                w.lift()
            callback(pos)

        voile.bind("<Button-1>", lambda _: fini(position_souris()))
        voile.bind("<Escape>", lambda _: fini(None))
        voile.focus_force()

    def montrer_reperes(self, points, duree=2500):
        for n, (x, y) in enumerate(points[:20], 1):
            r = tk.Toplevel(self.root)
            r.overrideredirect(True)
            r.attributes("-topmost", True)
            r.geometry(f"26x26+{x - 13}+{y - 13}")
            tk.Label(r, text=str(n), bg="#e11d2e", fg="white", font=("Segoe UI", 9, "bold")).pack(fill="both", expand=True)
            r.after(duree, r.destroy)

    # ---- exécution
    def basculer(self):
        if not self.actif:
            if not self.lire():
                return
            if not self.cfg["etapes"]:
                messagebox.showwarning("Bot clic", "Ajoute d'abord au moins une tâche.")
                return
        self.actif = not self.actif
        self.btn_actif.config(text="⏸ Mettre en pause" if self.actif else "▶ Activer le bot")
        self.tic()

    def lancer(self):
        if self.en_cours or not self.lire():
            return
        if not self.cfg["etapes"]:
            messagebox.showwarning("Bot clic", "Ajoute d'abord au moins une tâche.")
            return
        self.en_cours = True
        self.positions = {}
        self.root.iconify()
        if self.cfg["url"]:
            self.v_statut.set("Ouverture du navigateur…")
            ouvrir_navigateur(self.cfg["url"])
            delai = int(self.cfg["attente"] * 1000)
        else:
            delai = 1000
        self.root.after(delai, lambda: self.executer(0, 0))

    def executer(self, i, rep):
        etapes = self.cfg["etapes"]
        if (i, rep) != (0, 0) and souris_dans_coin():
            return self.fin("Arrêté (souris dans un coin).")
        if i >= len(etapes):
            return self.fin(f"Terminé : {len(etapes)} tâche(s) à {dt.datetime.now():%H:%M}.")
        e = etapes[i]
        self.v_statut.set(f"Tâche {i + 1}/{len(etapes)} : {decrire(e)}")
        t = e["type"]
        delai = 150
        if t == "clic":
            if e.get("variable"):
                if e["variable"] not in self.positions:
                    return self.fin(f"Tâche {i + 1} : la position [{e['variable']}] n'a pas été trouvée avant.")
                x, y = self.positions[e["variable"]]
            else:
                x, y = e["x"], e["y"]
            cliquer(x + e.get("dx", 0), y + e.get("dy", 0))
            if rep + 1 < e["nombre"]:
                self.root.after(max(10, int(e["pause"] * 1000)), lambda: self.executer(i, rep + 1))
                return
            delai = max(150, int(e["pause"] * 1000))
        elif t == "texte":
            taper(e["texte"])
        elif t == "touche":
            appuyer(TOUCHES[e["touche"]])
        elif t == "attente":
            delai = int(e["secondes"] * 1000)
        elif t == "chercher":
            return self.chercher(i, e, time.time() + e["delai"])
        self.root.after(delai, lambda: self.executer(i + 1, 0))

    def chercher(self, i, e, limite):
        """Scanne l'écran (dans un fil à part pour ne pas figer la fenêtre) jusqu'à trouver le texte."""
        resultat = queue.Queue()

        def travail():
            try:
                resultat.put((scanner(e["texte"]), None))
            except Exception as ex:
                resultat.put(([], str(ex)))
        threading.Thread(target=travail, daemon=True).start()

        def attendre():
            if souris_dans_coin():
                return self.fin("Arrêté (souris dans un coin).")
            try:
                trouves, erreur = resultat.get_nowait()
            except queue.Empty:
                return self.root.after(100, attendre)
            if erreur:
                return self.fin(f"Erreur du scanner : {erreur}")
            if len(trouves) >= e["occurrence"]:
                self.positions[e["variable"]] = trouves[e["occurrence"] - 1]
                x, y = self.positions[e["variable"]]
                self.v_statut.set(f"Tâche {i + 1} : « {e['texte']} » trouvé en ({x}, {y}) → [{e['variable']}]")
                return self.root.after(150, lambda: self.executer(i + 1, 0))
            if time.time() < limite:
                self.v_statut.set(f"Tâche {i + 1} : je cherche « {e['texte']} »…")
                return self.root.after(700, lambda: self.chercher(i, e, limite))
            if e.get("si_absent") == "continuer":
                return self.root.after(150, lambda: self.executer(i + 1, 0))
            self.fin(f"Tâche {i + 1} : « {e['texte']} » introuvable à l'écran.")
        attendre()

    def fin(self, msg):
        self.en_cours = False
        if self.actif and not self.cfg["tous_les_jours"]:
            self.actif = False
            self.btn_actif.config(text="▶ Activer le bot")
        self.v_statut.set(msg)
        self.root.deiconify()

    # ---- horloge
    def tic(self):
        if hasattr(self, "_tic"):
            self.root.after_cancel(self._tic)
        maintenant = dt.datetime.now()
        if self.actif:
            cible = maintenant.replace(hour=self.cfg["heure"], minute=self.cfg["minute"], second=0, microsecond=0)
            if (maintenant.hour, maintenant.minute) == (cible.hour, cible.minute) \
                    and self.deja_lance != maintenant.date() and not self.en_cours:
                self.deja_lance = maintenant.date()
                self.lancer()
            elif not self.en_cours:
                if cible <= maintenant or self.deja_lance == maintenant.date():
                    cible += dt.timedelta(days=1)
                self.v_statut.set(f"Bot actif — prochain lancement : {cible:%d/%m à %H:%M}")
        elif not self.en_cours and not self.v_statut.get().startswith(("Terminé", "Arrêté", "Tâche", "Erreur")):
            self.v_statut.set("Bot en pause.")
        self._tic = self.root.after(1000, self.tic)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
