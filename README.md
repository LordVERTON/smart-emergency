# MedNote MVP

Application mobile de prise de notes médicales vocales : enregistrement audio, transcription Whisper, extraction structurée heuristique ou IA (LangGraph + LangChain).

## Prérequis

- **Python 3.10+**
- **ffmpeg** (requis par faster-whisper)
- **Node.js 18+**
- **npm** ou **yarn**

## Structure du projet

```
smart-emergency/
├── backend/           # API FastAPI
│   ├── main.py
│   ├── requirements.txt
│   └── data/
│       ├── audio/     # Fichiers .m4a
│       └── notes/     # Fichiers .json
├── mobile/            # App Expo React Native
│   ├── app/           # Écrans (Expo Router)
│   ├── src/
│   │   └── config.ts  # API_BASE (IP du PC)
│   └── package.json
└── README.md
```

---

## Setup Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Lancer le backend

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

L’API sera accessible sur `http://<IP_PC>:8000` (et `http://localhost:8000` sur le PC).

**Variable d’environnement optionnelle :**
- `WHISPER_MODEL` : modèle Whisper (`base` par défaut, ou `small` pour plus de précision)
- `WHISPER_DEVICE` : `cpu` (défaut) ou `cuda` si GPU disponible
- `WHISPER_COMPUTE_TYPE` : `int8` (défaut), `float16` (souvent meilleur sur GPU), etc.
- `AI_PROVIDER` : provider LLM pour la structuration IA (`openai` par défaut)
- `OPENAI_API_KEY` : clé API OpenAI (requise pour `/transcribe-ai`)
- `OPENAI_MODEL` : modèle OpenAI pour extraction structurée (`gpt-4o-mini` par défaut)

```bash
WHISPER_MODEL=small uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Optimisations déjà en place (backend)

- Le modèle Whisper est préchargé au startup FastAPI (réduit le cold start sur la première requête).
- Le modèle Whisper est mis en cache en mémoire process (évite un rechargement coûteux à chaque upload).
- Pipeline upload audio factorisé et validation stricte (taille, ffprobe, conversion).
- Endpoint IA avec fallback heuristique automatique si indisponibilité LLM.

---

## Setup Mobile

```bash
cd mobile
npm install
```

### Lancer l’app

```bash
cd mobile
npm start
```

Puis scanner le QR code avec Expo Go (Android) ou l’app Caméra (iOS).

---

## Test sur téléphone

1. **Trouver l’IP du PC sur le réseau local :**
   - **Linux** : `hostname -I` ou `ip addr` (ex. `192.168.1.100`)
   - **macOS** : Préférences Système > Réseau > Détails
   - **Windows** : `ipconfig` (IPv4)

2. **Configurer l’API dans l’app :**
   - Ouvrir `mobile/src/config.ts`
   - Remplacer `API_BASE` par `http://<IP_PC>:8000` (ex. `http://192.168.1.100:8000`)

3. **Vérifier que :**
   - Le backend tourne sur le PC (`uvicorn ... --host 0.0.0.0`)
   - Le téléphone et le PC sont sur le même réseau Wi‑Fi
   - Le pare-feu du PC autorise les connexions entrantes sur le port 8000

---

## Endpoints API

| Méthode | Endpoint        | Description                                      |
|---------|-----------------|--------------------------------------------------|
| GET     | `/health`       | Vérification que l’API est en ligne              |
| POST    | `/transcribe`   | Upload audio (multipart) → transcription + note |
| POST    | `/transcribe-ai`| Upload audio → transcription + extraction IA (LangGraph + LangChain, fallback heuristique) |
| GET     | `/notes`        | Liste des notes (id, motif, created_at)          |
| GET     | `/notes/{id}`   | Détail d’une note                                |

### Exemple de test API avec curl

Healthcheck:

```bash
curl -X GET "http://127.0.0.1:8000/health"
```

Transcription heuristique:

```bash
curl -X POST "http://127.0.0.1:8000/transcribe" \
  -F "audio=@backend/data/audio/sample.m4a;type=audio/m4a"
```

Transcription IA:

```bash
curl -X POST "http://127.0.0.1:8000/transcribe-ai" \
  -F "audio=@backend/data/audio/sample.m4a;type=audio/m4a"
```

Lister les notes:

```bash
curl -X GET "http://127.0.0.1:8000/notes"
```

### Détails mode IA “production-ready”

`/transcribe-ai` utilise un graphe LangGraph en 2 nodes:
- `llm_extract` : extraction structurée via prompt + parser LangChain/Pydantic
- `clinical_validate` : validation clinique séparée (champs critiques + contrôle qualité)

Métadonnées retournées et stockées dans chaque note (`extraction_meta`) :
- `mode` : `ai`, `fallback` ou `heuristic`
- `confidence_by_field` : score par champ structuré
- `average_confidence` : moyenne globale
- `validation_issues` : liste d’alertes de validation
- `requires_review` : booléen final de revue humaine

---

## Troubleshooting

### Vérification rapide de l’environnement avant tests

- Python: `python --version`
- ffmpeg: `ffmpeg -version`
- Node: `node -v`
- npm: `npm -v`
- API boot: démarrer `uvicorn` puis vérifier `/health`

### L’app mobile ne peut pas joindre l’API

- **localhost** ne fonctionne pas depuis le téléphone : utiliser l’IP LAN du PC.
- Vérifier que `API_BASE` dans `mobile/src/config.ts` pointe vers `http://<IP_PC>:8000`.
- Vérifier que le backend écoute sur `0.0.0.0` (pas seulement `127.0.0.1`).
- Désactiver temporairement le pare-feu ou ouvrir le port 8000.

### Erreur ffmpeg

- Installer ffmpeg : `sudo apt install ffmpeg` (Ubuntu/Debian), `brew install ffmpeg` (macOS).
- Vérifier : `ffmpeg -version`.

### Erreur de transcription (500)

- Vérifier que ffmpeg est installé.
- Tester avec le modèle `base` : `WHISPER_MODEL=base`.
- Vérifier les logs du backend pour le message d’erreur exact.

### Permission micro refusée

- Sur iOS : Paramètres > MedNote > Autoriser le micro.
- Sur Android : Paramètres > Applications > MedNote > Autorisations > Microphone.

### Timeout upload

- La transcription peut prendre 30–60 s selon la longueur et le modèle.
- Timeout configuré à 120 s dans `mobile/src/config.ts` (`UPLOAD_TIMEOUT_MS`).

### Android SDK / "Failed to resolve the Android SDK path"

Cette erreur apparaît si tu lances `expo start --android` sans avoir installé le SDK Android.

**Option A – Tester sur ton téléphone (recommandé, sans SDK) :**
- Lance simplement `npm start` (sans `--android`)
- Scanne le QR code avec **Expo Go** sur ton téléphone
- Aucune installation du SDK Android nécessaire

**Option B – Utiliser l’émulateur Android :**
1. Installer [Android Studio](https://developer.android.com/studio)
2. Ouvrir Android Studio → More Actions → Virtual Device Manager → créer un appareil virtuel
3. Configurer les variables d’environnement dans `~/.bashrc` ou `~/.profile` :

```bash
export ANDROID_HOME=$HOME/Android/Sdk
export PATH=$PATH:$ANDROID_HOME/emulator
export PATH=$PATH:$ANDROID_HOME/platform-tools
```

4. Redémarrer le terminal, puis `cd mobile && npm start` et appuyer sur `a` pour Android.

---

## Commandes rapides

```bash
# Backend
cd backend && source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Mobile
cd mobile && npm start
```

---

## Plan de test recommandé (checklist)

### 1) Smoke test backend

- [ ] `GET /health` retourne `{ "ok": true }`
- [ ] `POST /transcribe` avec un audio valide retourne `id`, `transcript`, `structured`
- [ ] `POST /transcribe` avec fichier vide retourne `400`

### 2) Test mode IA

- [ ] `POST /transcribe-ai` sans `OPENAI_API_KEY` ne casse pas l’API (fallback heuristique)
- [ ] `POST /transcribe-ai` avec clé valide remplit `extraction_meta.mode = "ai"` si succès
- [ ] `validation_issues` et `requires_review` sont présents

### 3) Test persistance

- [ ] `GET /notes` affiche la note nouvellement créée
- [ ] `GET /notes/{id}` retourne `extraction_meta` cohérent (`ai` / `fallback` / `heuristic`)

### 4) Test mobile (Expo Go)

- [ ] Bouton `/health` fonctionnel
- [ ] Enregistrement puis envoi fonctionnel
- [ ] Historique + détail note affichés
