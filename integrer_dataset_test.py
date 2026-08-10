"""
============================================================
ingerer_dataset_test.py -- Fait apparaître réellement les documents
de ton dataset de test dans l'application web
============================================================

DIFFÉRENCE AVEC evaluate_classifier.py :
evaluate_classifier.py classifie tes documents de test UNIQUEMENT pour
mesurer un pourcentage de précision -- il ne sauvegarde aucune page en
base, n'indexe rien dans Chroma. C'est pour ça que ces documents
apparaissaient dans ton interface avec "? pages" et "Marque: Inconnu" :
ils n'ont jamais été réellement traités par le pipeline complet.

Ce script-ci fait exactement ce que fait main.py quand tu déposes un
vrai PDF dans la zone d'upload : il classifie CHAQUE page, l'enregistre
en base MySQL (avec sa catégorie, son score de confiance...), ET
l'indexe dans Chroma pour que le chatbot puisse répondre dessus.
Après ce script, tes documents de test se comportent comme des
documents normaux dans l'interface web.

ATTENTION -- IMPORTANT AVANT DE LANCER CE SCRIPT :
Arrête le backend (Ctrl+C dans le terminal où tourne "uvicorn main:app")
avant de lancer ce script, puis relance-le après. Ce script ouvre sa
propre connexion à Chroma (le dossier ./chroma_db) -- si le backend
tourne EN MÊME TEMPS et essaie d'y toucher aussi, c'est exactement le
scénario de plantage silencieux que tu avais déjà rencontré et corrigé
avec vector_store.py (deux connexions simultanées vers le même dossier
Chroma, mais ici depuis deux PROCESSUS Python différents, ce que
vector_store.py ne peut pas empêcher).

UTILISATION (dans PowerShell, venv activé) :

  Pour tout ingérer (peut être long, un ou deux appels vision par page) :
    python ingerer_dataset_test.py

  Pour tester sur un seul dossier d'abord (recommandé la première fois) :
    python ingerer_dataset_test.py 583132_guidelines_denim_ss24

  Pour plusieurs dossiers précis :
    python ingerer_dataset_test.py 583132_guidelines_denim_ss24 568336_01_COACHJACKET
============================================================
"""

import os
import sys

from database import SessionLocal, DocumentModel, PageModel
from classifier_techpacks import classify_tech_pack_document
from indexation import indexer_une_page
from vector_store import collection

BASE_DIR = "dataset_brut"       # même dossier que evaluate_classifier.py
TXT_EXTENSION = ".txt"


def lister_dossiers(base_dir: str) -> list:
    """Renvoie la liste triée des sous-dossiers de dataset_brut (un par Tech Pack)."""
    if not os.path.isdir(base_dir):
        print(f"Erreur : le dossier '{base_dir}' n'existe pas.")
        return []
    return sorted(
        d for d in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, d))
    )


def _numero_page(chemin_image: str) -> int:
    """Extrait le numéro depuis 'page_12.png' -> 12, pour trier dans le bon ordre."""
    nom = os.path.basename(chemin_image)
    try:
        return int(nom.rsplit(".", 1)[0].split("_")[-1])
    except (ValueError, IndexError):
        return 0


def charger_pages_dossier(base_dir: str, nom_dossier: str) -> list:
    """
    Charge (image_path, texte_brut) pour toutes les pages d'un dossier,
    triées par numéro de page croissant -- même principe que
    evaluate_classifier.py, mais sans dépendre d'un CSV de vérité terrain
    (on n'a pas besoin de connaître la "bonne réponse" pour ingérer).
    """
    chemin_dossier = os.path.join(base_dir, nom_dossier)
    fichiers_png = [f for f in os.listdir(chemin_dossier) if f.lower().endswith(".png")]

    pages = []
    for nom_png in fichiers_png:
        chemin_image = os.path.join(chemin_dossier, nom_png)
        nom_txt = nom_png.rsplit(".", 1)[0] + TXT_EXTENSION
        chemin_txt = os.path.join(chemin_dossier, nom_txt)

        texte_brut = ""
        if os.path.exists(chemin_txt):
            with open(chemin_txt, "r", encoding="utf-8") as f:
                texte_brut = f.read()

        pages.append((chemin_image, texte_brut))

    pages.sort(key=lambda item: _numero_page(item[0]))
    return pages


def ingerer_dossier(session, nom_dossier: str, pages: list):
    """
    Ingère UN dossier : (re)crée le document, classifie + enregistre chaque
    page, met à jour la marque/nombre de pages/statut, puis indexe dans Chroma.
    """
    # Même règle que le retraitement web (main.py, /upload-techpack) : si le
    # document existe déjà (ex: un "fantôme" créé par evaluate_classifier.py,
    # ou une ingestion précédente de ce script), on repart proprement de zéro.
    document_existant = session.query(DocumentModel).filter_by(filename=nom_dossier).first()
    if document_existant:
        try:
            collection.delete(where={"document_id": document_existant.id})
        except Exception as e:
            print(f"   [ATTENTION] Nettoyage Chroma échoué (pas bloquant) : {e}")
        session.delete(document_existant)
        session.commit()

    document = DocumentModel(filename=nom_dossier, status="en_cours")
    session.add(document)
    session.commit()  # nécessaire pour obtenir document.id

    print(f"-> '{nom_dossier}' ({len(pages)} pages) -- classification en cours...")
    resultats = classify_tech_pack_document(pages, techpack_id=document.id, nom_dossier=nom_dossier)
    marque_finale = resultats[0][1] if resultats else "INCONNU"

    nombre_morceaux_indexes = 0
    for numero_page, ((chemin_image, texte_page), (categorie, _marque, score, mots_matches)) in enumerate(zip(pages, resultats), start=1):
        page = PageModel(
            document_id=document.id,
            page_number=numero_page,
            image_path=chemin_image,
            raw_text=texte_page,
            category=categorie,
            category_confidence=score,
            matched_keywords=", ".join(mots_matches) if mots_matches else None,
            needs_review=(score is None),
        )
        session.add(page)
        session.commit()  # nécessaire pour obtenir page.id avant l'indexation Chroma
        nombre_morceaux_indexes += indexer_une_page(page, document)

    document.brand = marque_finale
    document.page_count = len(pages)
    document.status = "termine"
    session.commit()

    print(f"   OK -- marque : {marque_finale} | {nombre_morceaux_indexes} morceaux indexés dans Chroma")


def ingerer_tout(dossiers_a_traiter=None):
    """
    Ingère les dossiers demandés (ou TOUT dataset_brut/ si aucun n'est précisé).
    """
    session = SessionLocal()
    dossiers = dossiers_a_traiter or lister_dossiers(BASE_DIR)

    if not dossiers:
        print("Aucun dossier à traiter.")
        session.close()
        return

    print(f"{len(dossiers)} dossier(s) à ingérer.\n")
    for nom_dossier in dossiers:
        chemin_dossier = os.path.join(BASE_DIR, nom_dossier)
        if not os.path.isdir(chemin_dossier):
            print(f"-> '{nom_dossier}' ignoré (dossier introuvable dans {BASE_DIR})")
            continue
        pages = charger_pages_dossier(BASE_DIR, nom_dossier)
        if not pages:
            print(f"-> '{nom_dossier}' ignoré (aucune page .png trouvée)")
            continue
        ingerer_dossier(session, nom_dossier, pages)

    session.close()
    print("\nTerminé. Rafraîchis l'onglet Documents de l'interface web pour les voir.")


if __name__ == "__main__":
    dossiers_demandes = sys.argv[1:] or None
    ingerer_tout(dossiers_demandes)