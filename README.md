# TechPack Analyzer

**Système Intelligent d'Analyse et de Classification Automatique des Dossiers Techniques Textile**

Projet de fin d'études — une application qui lit automatiquement des Tech Packs (dossiers techniques textile, PDF multi-pages), classe chaque page dans une catégorie métier, identifie la marque du client, et permet d'interroger le contenu des documents via un chatbot.

---

## Fonctionnalités

- **Lecture automatique de Tech Packs** (PDF multi-pages) : extraction du texte natif et des images de chaque page
- **Classification par catégorie** de chaque page, parmi 11 catégories métier :
  BOM, Measurement Sheet, Technical Sketch, Labels, Sewing Instructions, Artwork, Fabric Information, Trims & Accessories, Packaging, Colorways, Autres documents techniques
- **Identification de la marque** du document, avec un système à plusieurs niveaux (mémoire apprise → texte → vision → confirmation manuelle)
- **Explication de la classification** : chaque page classée par texte affiche les mots-clés exacts qui ont motivé la décision, pas une boîte noire
- **Chatbot RAG** pour poser des questions en langage naturel sur le contenu des documents, avec citation des sources (document + page)
- **Réponses directes pour les questions de métadonnées** (nombre de pages, statut, marque, catégorie d'une page précise, catégories présentes, résumé complet) — sans passer par la recherche sémantique, qui n'est pas adaptée à ce type de question
- **File de confirmation manuelle** pour les marques non identifiées automatiquement, avec alimentation d'une mémoire apprise pour les documents similaires futurs
- **Interface web** avec suivi des documents en cours de traitement, chat, et file de vérification

---

## Architecture

```
┌─────────────┐      upload PDF       ┌──────────────────┐
│   Frontend  │ ───────────────────▶  │   Backend         │
│  React/Vite │                       │   FastAPI          │
│             │ ◀───────────────────  │  (traitement async)│
└─────────────┘   statut / résultats  └─────────┬─────────┘
                                                  │
                    ┌─────────────────────────────┼─────────────────────────┐
                    │                              │                         │
              ┌─────▼──────┐              ┌────────▼────────┐        ┌───────▼───────┐
              │   MySQL     │              │  Ollama (local)  │        │  ChromaDB      │
              │  (Docker)   │              │  BakLLaVA (vision)│        │ (base vectorielle,
              │  métadonnées│              │  llama3.2:3b (chat)│       │  RAG / chatbot)│
              └─────────────┘              └──────────────────┘        └────────────────┘
```

Le traitement d'un document se fait **en arrière-plan côté serveur** (FastAPI `BackgroundTasks`) : fermer le site ou le navigateur n'interrompt jamais un traitement en cours, tant que le backend (`uvicorn`) reste lancé.

---

## Stack technique

| Composant | Technologie |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Base de données | MySQL 8.0 (Docker), SQLAlchemy |
| Classification (vision) | Ollama + BakLLaVA (local, CPU) |
| Chatbot (texte) | Ollama + llama3.2:3b (local, CPU) |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) |
| Base vectorielle | ChromaDB (stockage local, `./chroma_db`) |
| Extraction PDF | pdfplumber (texte natif) + pdf2image (images, nécessite Poppler) |
| Frontend | React (Vite), Tailwind CSS, lucide-react |

---

## Structure du projet

```
techpack_analyzer/
├── main.py                    # Backend FastAPI : upload, traitement, endpoints, chat
├── database.py                # Modèles SQLAlchemy (documents, pages, BOM, mesures, marque à confirmer...)
├── classifier_techpacks.py    # Classification (catégorie + marque), mémoire apprise
├── vector_store.py            # Point d'accès unique partagé à Chroma + modèle d'embeddings
├── indexation.py               # Indexation des pages classifiées dans Chroma
├── chat_service.py            # Logique du chatbot RAG + réponses directes (métadonnées)
├── confirmer_marque.py        # Script CLI de confirmation manuelle de marque
├── evaluate_classifier.py     # Évaluation de précision sur un jeu de test annoté (CSV)
├── ingerer_dataset_test.py    # Ingestion réelle du dataset de test dans l'app (pages + index Chroma)
├── diagnostic_indexation.py   # Diagnostic de ce qui est réellement indexé dans Chroma
├── docker-compose.yml         # Service MySQL
└── frontend/
    └── src/
        └── App.jsx            # Interface React (Documents / Chat / À vérifier)
```

---

## Installation

### Prérequis
- Python 3.10+
- Node.js + npm
- Docker Desktop
- [Ollama](https://ollama.com) installé localement
- Poppler installé et ajouté au PATH (nécessaire pour `pdf2image`)

### 1. Cloner le dépôt et installer les dépendances Python
```bash
git clone <url-du-depot>
cd techpack_analyzer
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Lancer MySQL avec Docker
```bash
docker-compose up -d
```

### 3. Initialiser la base de données
```bash
python database.py
```

### 4. Télécharger les modèles Ollama
```bash
ollama pull bakllava
ollama pull llama3.2:3b
```

### 5. Installer les dépendances frontend
```bash
cd frontend
npm install
```

---

## Utilisation

L'application nécessite **deux serveurs lancés simultanément, dans deux terminaux séparés** :

**Terminal 1 — Backend** (à la racine du projet, venv activé) :
```bash
uvicorn main:app
```
*(sans `--reload` : ChromaDB écrit dans le dossier du projet, ce qui perturbe la surveillance de fichiers et fait planter le rechargement automatique)*

**Terminal 2 — Frontend** :
```bash
cd frontend
npm run dev
```

Puis ouvrir l'URL affichée par Vite (généralement `http://localhost:5173`).

> **Important** : le traitement d'un document tourne côté backend, indépendamment du navigateur. Fermer l'onglet ou le site ne l'arrête pas — seul l'arrêt du terminal `uvicorn` le ferait.

---

## Comment fonctionne la classification

Chaque page suit une cascade de méthodes, de la plus rapide/fiable à la plus coûteuse :

1. **Texte (mots-clés pondérés)** — recherche de termes métier dans le texte natif extrait de la page, avec un score par catégorie. Si un score dépasse nettement les autres, la catégorie est retenue et les mots-clés déclencheurs sont conservés (affichés dans l'interface : *"Classée à cause de : ..."*).
2. **Vision (BakLLaVA)** — si le texte est ambigu ou absent, la page est envoyée au modèle de vision, qui l'analyse directement à partir de l'image.

Pour la **marque**, la cascade est : mémoire apprise (motifs déjà confirmés manuellement) → texte (liste de marques connues) → confirmation manuelle si rien n'est trouvé. *(La détection de marque par vision a été désactivée : testée et mesurée, elle produisait des faux positifs confiants — ex: associer à tort des pages "denim" à Levi's — jugés plus dangereux qu'une incertitude honnête envoyée en confirmation manuelle.)*

---

## Comment fonctionne le chatbot

Le chatbot distingue deux types de questions :

- **Questions sur une donnée déjà connue** (nombre de pages, statut, marque, catégorie d'une page précise, résumé complet...) → réponse **directe depuis MySQL**, sans recherche sémantique — rapide et fiable à 100%.
- **Questions sur le contenu réel** (composition d'un tissu, mesures, instructions...) → **RAG** (Retrieval-Augmented Generation) : recherche sémantique dans ChromaDB pour trouver les passages pertinents, puis génération de réponse par `llama3.2:3b`, avec citation des sources.

---

## Évaluer la précision du classifieur

```bash
python evaluate_classifier.py
```
Nécessite un fichier `file.csv` (vérité terrain : `filename,true_category,true_brand`) et un dossier `dataset_brut/` contenant les pages du jeu de test. Produit un rapport avec précision par catégorie/marque, matrice de confusion, et détail des erreurs — sans jamais écrire dans la base "réelle" utilisée par l'application (voir `ingerer_dataset_test.py` pour peupler l'interface avec de vrais documents à des fins de démonstration).

---

## Limites connues

- BakLLaVA tourne en local sur CPU (pas de GPU) : les appels vision peuvent prendre jusqu'à plusieurs minutes, et le traitement de documents avec beaucoup de pages ambiguës peut être lent.
- La classification par mots-clés reste sensible aux pages au contenu très ambigu ou visuellement similaire entre catégories proches (ex: Technical Sketch / Sewing Instructions / Measurement Sheet).
- L'extraction de texte sur certains PDF utilisant des polices non standard (ex: exports Lectra) peut être illisible — ces cas sont détectés et signalés plutôt que silencieusement mal exploités.

---

## Auteur

Projet de fin d'études — développé par Fatma.
