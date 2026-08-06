"""
============================================================
vector_store.py -- Point d'accès UNIQUE à Chroma et au modèle d'embeddings
============================================================

POURQUOI CE FICHIER EXISTE : avant, indexation.py ET chat_service.py
créaient chacun leur PROPRE connexion à Chroma et leur PROPRE copie du
modèle d'embeddings. Tant qu'on les utilisait séparément (chacun lancé
individuellement), ça fonctionnait. Mais dès que main.py a voulu
importer les DEUX en même temps, avoir deux connexions indépendantes
ouvertes simultanément vers le même dossier Chroma a provoqué un
plantage silencieux au démarrage.

LA SOLUTION : un seul endroit qui crée la connexion et le modèle, UNE
SEULE FOIS -- tous les autres fichiers viennent le chercher ici plutôt
que d'en recréer un chacun de leur côté. C'est un peu comme avoir une
seule prise électrique centrale plutôt que chaque appareil qui essaie
de tirer son propre câble jusqu'au compteur.
============================================================
"""
#Chroma est donc juste une base de données spécialisée pour stocker des vecteurs et calculer des distances entre eux rapidement
import chromadb
from sentence_transformers import SentenceTransformer

print("[VECTOR_STORE] Chargement du modèle d'embeddings (une seule fois pour toute l'application)...")
modele_embeddings = SentenceTransformer("all-MiniLM-L6-v2")

client_chroma = chromadb.PersistentClient(path="./chroma_db")
collection = client_chroma.get_or_create_collection("techpacks")