"""Bot clic : à l'heure choisie, ouvre un site puis exécute une liste d'étapes
(cliquer, écrire du texte, appuyer sur une touche, attendre).

Lancer : raccourci « Bot clic » du Bureau, ou `pyw bot_clic.pyw`.
Aucune bibliothèque à installer : uniquement Python standard (Windows).
"""
import ctypes
import datetime as dt
import json
import os
import subprocess
import time
import tkinter as tk
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


def decrire(e):
    t = e["type"]
    if t == "clic":
        fois = f" ×{e['nombre']}" if e["nombre"] > 1 else ""
        return f"🖱  Clic{fois} à ({e['x']}, {e['y']})"
    if t == "texte":
        apercu = e["texte"].replace("\n", " ⏎ ")
        return f"⌨  Écrire « {apercu[:45]}{'…' if len(apercu) > 45 else ''} »"
    if t == "touche":
        return f"⏎  Touche {e['touche']}"
    if t == "attente":
        return f"⏱  Attendre {e['secondes']:g} s"
    return t

# ---------------------------------------------------------------- fenêtre d'une étape

class DialogueEtape(tk.Toplevel):
    TITRES = {"clic": "Clic", "texte": "Écrire du texte", "touche": "Appuyer sur une touche", "attente": "Attendre"}

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

        if t == "clic":
            ttk.Label(f, text="Position X :").grid(row=0, column=0, sticky="w")
            self.v_x = tk.StringVar(value="" if self.e.get("x") is None else str(self.e["x"]))
            ttk.Entry(f, textvariable=self.v_x, width=7).grid(row=0, column=1, sticky="w", pady=3)
            ttk.Label(f, text="Y :").grid(row=0, column=2, sticky="e")
            self.v_y = tk.StringVar(value="" if self.e.get("y") is None else str(self.e["y"]))
            ttk.Entry(f, textvariable=self.v_y, width=7).grid(row=0, column=3, sticky="w", padx=(4, 0))
            ttk.Button(f, text="Choisir sur l'écran…", command=self.choisir).grid(
                row=1, column=0, columnspan=4, sticky="we", pady=(2, 8))
            ttk.Label(f, text="Nombre de clics :").grid(row=2, column=0, sticky="w")
            self.v_n = tk.StringVar(value=str(self.e.get("nombre", 1)))
            ttk.Spinbox(f, from_=1, to=10000, textvariable=self.v_n, width=7).grid(row=2, column=1, columnspan=3, sticky="w", pady=3)
            ttk.Label(f, text="Pause entre clics (s) :").grid(row=3, column=0, sticky="w")
            self.v_p = tk.StringVar(value=str(self.e.get("pause", 0.2)))
            ttk.Spinbox(f, from_=0.05, to=10, increment=0.05, textvariable=self.v_p, width=7).grid(row=3, column=1, columnspan=3, sticky="w", pady=3)
            ttk.Label(f, text="« Choisir sur l'écran » : tu as 3 secondes pour afficher\n"
                              "la bonne fenêtre, puis clique à l'endroit voulu.",
                      foreground="#888", justify="left").grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        elif t == "texte":
            ttk.Label(f, text="Texte à écrire (les retours à la ligne = touche Entrée) :").grid(row=0, column=0, sticky="w")
            self.zone = tk.Text(f, width=46, height=6, wrap="word", font=("Segoe UI", 10))
            self.zone.grid(row=1, column=0, pady=4)
            self.zone.insert("1.0", self.e.get("texte", ""))
            self.zone.focus_set()
            ttk.Label(f, text="Le texte est écrit là où se trouve le curseur :\n"
                              "mets d'abord une étape « Clic » sur la zone de texte.",
                      foreground="#888", justify="left").grid(row=2, column=0, sticky="w")
        elif t == "touche":
            ttk.Label(f, text="Touche :").grid(row=0, column=0, sticky="w")
            self.v_t = tk.StringVar(value=self.e.get("touche", "Entrée"))
            ttk.Combobox(f, textvariable=self.v_t, values=list(TOUCHES), state="readonly", width=28).grid(row=0, column=1, pady=3, padx=(6, 0))
        elif t == "attente":
            ttk.Label(f, text="Attendre (secondes) :").grid(row=0, column=0, sticky="w")
            self.v_s = tk.StringVar(value=str(self.e.get("secondes", 2)))
            ttk.Spinbox(f, from_=0.1, to=3600, increment=0.5, textvariable=self.v_s, width=8).grid(row=0, column=1, pady=3, padx=(6, 0))

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
        self.grab_release()
        self.app.choisir_position(recu, cacher=(self,))

    def valider(self):
        t = self.e["type"]
        try:
            if t == "clic":
                self.e.update(x=int(self.v_x.get()), y=int(self.v_y.get()),
                              nombre=max(1, int(self.v_n.get())), pause=max(0.0, float(self.v_p.get().replace(",", "."))))
            elif t == "texte":
                self.e["texte"] = self.zone.get("1.0", "end-1c")
                if not self.e["texte"]:
                    raise ValueError
            elif t == "touche":
                self.e["touche"] = self.v_t.get()
            elif t == "attente":
                self.e["secondes"] = max(0.1, float(self.v_s.get().replace(",", ".")))
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
        self.liste = ttk.Treeview(f, columns=("n", "action"), show="headings", height=9, selectmode="browse")
        self.liste.heading("n", text="#")
        self.liste.heading("action", text="Action")
        self.liste.column("n", width=34, anchor="center", stretch=False)
        self.liste.column("action", width=380)
        self.liste.grid(row=4, column=0, columnspan=4, sticky="nsew")
        self.liste.bind("<Double-1>", lambda _: self.modifier())
        self.liste.bind("<Delete>", lambda _: self.supprimer())

        c = ttk.Frame(f)
        c.grid(row=4, column=4, sticky="n", padx=(6, 0))
        for txt, cmd in (("+ Clic", lambda: self.ajouter("clic")),
                         ("+ Texte", lambda: self.ajouter("texte")),
                         ("+ Touche", lambda: self.ajouter("touche")),
                         ("+ Attente", lambda: self.ajouter("attente"))):
            ttk.Button(c, text=txt, width=10, command=cmd).pack(fill="x", pady=1)
        ttk.Separator(c).pack(fill="x", pady=5)
        for txt, cmd in (("Modifier", self.modifier), ("Supprimer", self.supprimer),
                         ("▲ Monter", lambda: self.deplacer(-1)), ("▼ Descendre", lambda: self.deplacer(1))):
            ttk.Button(c, text=txt, width=10, command=cmd).pack(fill="x", pady=1)

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
        d = DialogueEtape(self, {"type": type_})
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

    # ---- choix d'une position à l'écran
    def choisir_position(self, callback, cacher=()):
        for w in cacher:
            w.withdraw()
        self.root.withdraw()
        compte = tk.Toplevel(self.root)
        compte.overrideredirect(True)
        compte.attributes("-topmost", True)
        compte.geometry(f"+{user32.GetSystemMetrics(0) // 2 - 150}+30")
        lbl = tk.Label(compte, bg="#e11d2e", fg="white", font=("Segoe UI", 14, "bold"), padx=20, pady=10)
        lbl.pack()

        def decompte(n):
            if n == 0:
                compte.destroy()
                self._voile(callback, cacher)
                return
            lbl.config(text=f"Affiche la bonne fenêtre… {n}")
            self.root.after(1000, lambda: decompte(n - 1))
        decompte(3)

    def _voile(self, callback, cacher):
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
            cliquer(e["x"], e["y"])
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
        self.root.after(delai, lambda: self.executer(i + 1, 0))

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
        elif not self.en_cours and not self.v_statut.get().startswith(("Terminé", "Arrêté")):
            self.v_statut.set("Bot en pause.")
        self._tic = self.root.after(1000, self.tic)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
