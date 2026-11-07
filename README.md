# Bouton rouge

- `index.html` : le site avec le bouton rouge et le compteur — https://codtino.github.io/bouton-rouge/
- `bot_clic.pyw` : un bot (Windows, Python sans rien à installer) qui, à l'heure choisie, ouvre un site puis exécute une liste de tâches.

## Utiliser le bot

1. Lance `bot_clic.pyw` (raccourci « Bot clic » sur le Bureau, ou `pyw bot_clic.pyw`).
2. Choisis le site à ouvrir et l'heure.
3. Construis la liste des tâches, exécutées dans l'ordre :
   - **+ Bouton** : clique sur un bouton, lien, onglet ou champ du site ouvert dans Chrome, choisi dans la liste des boutons de la page (il est retrouvé par son nom, même s'il a bougé, et la page défile si besoin) ;
   - **+ Chercher** : scanne l'écran (reconnaissance de texte de Windows), trouve un texte et garde sa position sous un nom, ex. `[position1]` ;
   - **+ Clic** : un clic (ou plusieurs) sur une position trouvée par « Chercher » (avec un décalage possible) ou à une position fixe choisie sur l'écran ;
   - **+ Texte** : écrit un texte là où se trouve le curseur (mets un clic sur la zone de texte avant) ;
   - **+ Touche** : Entrée, Tab, Échap, flèches, Ctrl+A, Ctrl+V…
   - **+ Attente** : patiente quelques secondes (le temps qu'une page charge).
4. **Tester maintenant** pour vérifier, puis **▶ Activer le bot**. Laisse la fenêtre ouverte (réduite si tu veux).

Double-clic sur une tâche pour la modifier ; ▲ / ▼ pour changer l'ordre.
Pour arrêter en cours de route : mets la souris dans un coin de l'écran.
