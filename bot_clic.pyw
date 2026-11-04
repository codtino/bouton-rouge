"""Bot clic : ouvre le navigateur à une heure choisie et clique à une position choisie.

Lancer : double-clic sur bot_clic.pyw (ou `py bot_clic.pyw`).
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
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

DOSSIER = os.path.dirname(os.path.abspath(__file__))
FICHIER_CONFIG = os.path.join(DOSSIER, "config.json")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

DEFAUT = {
    "url": "https://codtino.github.io/bouton-rouge/",
    "heure": 9,
    "minute": 0,
    "x": None,
    "y": None,
    "clics": 10,
    "intervalle": 0.2,
    "attente": 5,
    "tous_les_jours": True,
}


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def position_souris():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def cliquer(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.02)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def ouvrir_navigateur(url):
    if os.path.exists(CHROME):
        subprocess.Popen([CHROME, "--new-window", "--start-maximized", url])
    else:
        webbrowser.open(url, new=1)


def charger_config():
    cfg = dict(DEFAUT)
    try:
        with open(FICHIER_CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = charger_config()
        self.deja_lance = None  # date du dernier lancement automatique
        self.en_cours = False

        root.title("Bot clic")
        root.resizable(False, False)
        f = ttk.Frame(root, padding=16)
        f.grid()

        ttk.Label(f, text="Site à ouvrir :").grid(row=0, column=0, sticky="w")
        self.v_url = tk.StringVar(value=self.cfg["url"])
        ttk.Entry(f, textvariable=self.v_url, width=42).grid(row=0, column=1, columnspan=3, sticky="we", pady=3)

        ttk.Label(f, text="Heure de lancement :").grid(row=1, column=0, sticky="w")
        self.v_h = tk.StringVar(value=f"{self.cfg['heure']:02d}")
        self.v_m = tk.StringVar(value=f"{self.cfg['minute']:02d}")
        ttk.Combobox(f, textvariable=self.v_h, values=[f"{i:02d}" for i in range(24)], width=4,
                     state="readonly").grid(row=1, column=1, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.v_m, values=[f"{i:02d}" for i in range(60)], width=4,
                     state="readonly").grid(row=1, column=2, sticky="w")
        self.v_jours = tk.BooleanVar(value=self.cfg["tous_les_jours"])
        ttk.Checkbutton(f, text="Tous les jours", variable=self.v_jours).grid(row=1, column=3, sticky="w")

        ttk.Label(f, text="Position du clic :").grid(row=2, column=0, sticky="w")
        self.v_pos = tk.StringVar()
        ttk.Label(f, textvariable=self.v_pos, width=16).grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Button(f, text="Choisir la position…", command=self.choisir_position).grid(row=2, column=3, sticky="we", pady=3)

        ttk.Label(f, text="Nombre de clics :").grid(row=3, column=0, sticky="w")
        self.v_clics = tk.IntVar(value=self.cfg["clics"])
        ttk.Spinbox(f, from_=1, to=10000, textvariable=self.v_clics, width=8).grid(row=3, column=1, columnspan=2, sticky="w", pady=3)

        ttk.Label(f, text="Pause entre clics (s) :").grid(row=4, column=0, sticky="w")
        self.v_int = tk.DoubleVar(value=self.cfg["intervalle"])
        ttk.Spinbox(f, from_=0.05, to=10, increment=0.05, textvariable=self.v_int, width=8).grid(row=4, column=1, columnspan=2, sticky="w", pady=3)

        ttk.Label(f, text="Attente chargement (s) :").grid(row=5, column=0, sticky="w")
        self.v_att = tk.IntVar(value=self.cfg["attente"])
        ttk.Spinbox(f, from_=1, to=60, textvariable=self.v_att, width=8).grid(row=5, column=1, columnspan=2, sticky="w", pady=3)

        b = ttk.Frame(f)
        b.grid(row=6, column=0, columnspan=4, pady=(12, 4), sticky="we")
        self.btn_actif = ttk.Button(b, text="▶ Activer le bot", command=self.basculer)
        self.btn_actif.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(b, text="Tester maintenant", command=self.lancer).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.v_statut = tk.StringVar(value="Bot en pause.")
        ttk.Label(f, textvariable=self.v_statut, foreground="#555").grid(row=7, column=0, columnspan=4, sticky="w")

        ttk.Label(f, text="Astuce : la fenêtre doit rester ouverte (tu peux la réduire).\n"
                          "Pendant les clics, mets la souris dans un coin de l'écran pour arrêter.",
                  foreground="#888", justify="left").grid(row=8, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self.actif = False
        self.maj_position()
        self.tic()

    # ---- réglages ----
    def lire(self):
        self.cfg.update(
            url=self.v_url.get().strip(),
            heure=int(self.v_h.get()),
            minute=int(self.v_m.get()),
            clics=max(1, int(self.v_clics.get())),
            intervalle=max(0.0, float(self.v_int.get())),
            attente=max(0, int(self.v_att.get())),
            tous_les_jours=self.v_jours.get(),
        )
        with open(FICHIER_CONFIG, "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, indent=2, ensure_ascii=False)

    def maj_position(self):
        if self.cfg["x"] is None:
            self.v_pos.set("pas encore choisie")
        else:
            self.v_pos.set(f"x={self.cfg['x']}  y={self.cfg['y']}")

    # ---- choix de la position ----
    def choisir_position(self):
        try:
            self.lire()
        except (ValueError, tk.TclError):
            messagebox.showerror("Bot clic", "Un réglage n'est pas un nombre valide.")
            return
        self.root.iconify()
        ouvrir_navigateur(self.cfg["url"])
        self.root.after(self.cfg["attente"] * 1000, self.afficher_voile)

    def afficher_voile(self):
        voile = tk.Toplevel(self.root)
        voile.attributes("-fullscreen", True)
        voile.attributes("-topmost", True)
        voile.attributes("-alpha", 0.35)
        voile.configure(bg="black", cursor="crosshair")
        tk.Label(voile, text="Clique à l'endroit où le bot doit cliquer  (Échap pour annuler)",
                 bg="black", fg="white", font=("Segoe UI", 20, "bold")).pack(pady=40)

        def clic(_):
            self.cfg["x"], self.cfg["y"] = position_souris()
            voile.destroy()
            self.lire()
            self.maj_position()
            self.root.deiconify()

        def annuler(_=None):
            voile.destroy()
            self.root.deiconify()

        voile.bind("<Button-1>", clic)
        voile.bind("<Escape>", annuler)
        voile.focus_force()

    # ---- lancement ----
    def basculer(self):
        if not self.actif:
            try:
                self.lire()
            except (ValueError, tk.TclError):
                messagebox.showerror("Bot clic", "Un réglage n'est pas un nombre valide.")
                return
            if self.cfg["x"] is None:
                messagebox.showwarning("Bot clic", "Choisis d'abord la position du clic.")
                return
        self.actif = not self.actif
        self.btn_actif.config(text="⏸ Mettre en pause" if self.actif else "▶ Activer le bot")
        self.tic()

    def lancer(self):
        if self.en_cours:
            return
        try:
            self.lire()
        except (ValueError, tk.TclError):
            messagebox.showerror("Bot clic", "Un réglage n'est pas un nombre valide.")
            return
        if self.cfg["x"] is None:
            messagebox.showwarning("Bot clic", "Choisis d'abord la position du clic.")
            return
        self.en_cours = True
        self.v_statut.set("Ouverture du navigateur…")
        ouvrir_navigateur(self.cfg["url"])
        self.root.after(self.cfg["attente"] * 1000, lambda: self.clic_suivant(self.cfg["clics"]))

    def clic_suivant(self, restant):
        x, y = position_souris()
        largeur, hauteur = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        if restant < self.cfg["clics"] and (x, y) in ((0, 0), (largeur - 1, 0), (0, hauteur - 1), (largeur - 1, hauteur - 1)):
            self.fin("Arrêté (souris dans un coin).")
            return
        if restant <= 0:
            self.fin(f"Terminé : {self.cfg['clics']} clic(s) à {dt.datetime.now():%H:%M}.")
            return
        cliquer(self.cfg["x"], self.cfg["y"])
        self.v_statut.set(f"Clic {self.cfg['clics'] - restant + 1} / {self.cfg['clics']}")
        self.root.after(int(self.cfg["intervalle"] * 1000), lambda: self.clic_suivant(restant - 1))

    def fin(self, msg):
        self.en_cours = False
        if self.actif and not self.cfg["tous_les_jours"]:
            self.actif = False
            self.btn_actif.config(text="▶ Activer le bot")
        self.v_statut.set(msg)

    # ---- horloge ----
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
