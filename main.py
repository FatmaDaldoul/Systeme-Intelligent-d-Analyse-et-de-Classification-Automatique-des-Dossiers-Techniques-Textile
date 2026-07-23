"""
============================================================
main.py -- Le point d'entrée de ton application backend
============================================================

C'est le fichier que tu lances pour démarrer ton "serveur" -- le
programme qui reste allumé et qui écoute les demandes (upload de
PDF, consultation de documents, etc.), un peu comme une caisse de
magasin qui reste ouverte et attend les clients.

Pour le lancer, dans ton terminal (dans le dossier du projet) :
    uvicorn main:app --reload

Explication de cette commande :
  - "uvicorn" est le programme qui fait vraiment tourner le serveur
    (FastAPI a besoin de lui pour fonctionner, un peu comme une
    voiture a besoin d'un moteur en plus du volant)
  - "main:app" veut dire "dans le fichier main.py, utilise la
    variable qui s'appelle app" (on la crée plus bas)
  - "--reload" redémarre automatiquement le serveur à chaque fois
    que tu modifies et sauvegardes ce fichier, pratique pendant
    le développement
============================================================
"""
import os
import shutil #un module standard de Python qui sert à manipuler des fichiers et des dossiers. Son nom vient de Shell Utilities.
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
import pdfplumber            # Pour extraire le texte natif de chaque page du PDF
from pdf2image import convert_from_path  # Pour transformer chaque page du PDF en image (.png)
# On réutilise tout ce qu'on a déjà construit : la base de données
# et le classifieur -- pas besoin de réécrire quoi que ce soit ici.
from database import SessionLocal, DocumentModel, PageModel, MarqueAConfirmerModel
from classifier_techpacks import classify_tech_pack_document
# ============================================================
# ÉTAPE 1 : créer l'application FastAPI
# ------------------------------------------------------------
# "app" est l'objet central de tout le backend. C'est un peu comme
# la caisse enregistreuse elle-même -- tout ce qu'on ajoute après
# (les endpoints) vient s'y accrocher.
# ============================================================
app = FastAPI(title="Techpack Analyzer API")

# Dossier où on va stocker les PDF uploadés et les pages extraites
DOSSIER_STOCKAGE = "stockage_documents"
os.makedirs(DOSSIER_STOCKAGE, exist_ok=True)  # crée le dossier s'il n'existe pas déjà
# ============================================================
# ÉTAPE 2 : la fonction qui fait le VRAI travail (en arrière-plan)
# ------------------------------------------------------------
# Cette fonction ne sera pas appelée directement par l'utilisateur.
# Elle sera lancée "en coulisses" par FastAPI après avoir répondu
# à l'utilisateur, grâce à BackgroundTasks (voir plus bas).
#
# Elle fait, dans l'ordre :
#   1. Extraire chaque page du PDF en image (.png) -- nécessaire
#      pour que la vision (BakLLaVA) puisse "regarder" la page
#   2. Extraire le texte natif de chaque page -- c'est LE levier
#      le plus important qu'on a identifié ensemble pour la marque
#      (rappel : le texte natif est fiable à 100%, contrairement à
#      l'OCR ou à la vision)
#   3. Appeler classify_tech_pack_document(), qui gère déjà tout le
#      reste (mémoire apprise -> texte -> vision -> file d'attente)
#   4. Écrire les résultats dans la base de données (table "pages")
#   5. Marquer le document comme "terminé"
# ============================================================
def traiter_document_en_arriere_plan(document_id: int, chemin_pdf: str, nom_dossier: str):
    session = SessionLocal()

    try:
        # --- 1. Créer un sous-dossier propre pour ce document ---
        dossier_pages = os.path.join(DOSSIER_STOCKAGE, nom_dossier)
        os.makedirs(dossier_pages, exist_ok=True)

        # --- 2. Convertir chaque page du PDF en image PNG ---
        # convert_from_path lit le PDF et renvoie une liste d'images,
        # une par page, dans l'ordre.
        images = convert_from_path(chemin_pdf)

        pages_a_classifier = []  # va contenir (chemin_image, texte) pour chaque page

        # --- 3. Extraire le texte natif de chaque page avec pdfplumber ---
        # C'est ICI qu'on applique la correction prioritaire identifiée
        # ensemble : utiliser le texte natif du PDF (pas de l'OCR), qui
        # est beaucoup plus fiable pour retrouver la marque par texte
        # avant même d'avoir besoin de la vision.
        with pdfplumber.open(chemin_pdf) as pdf:
            for numero_page, (image, page_pdf) in enumerate(zip(images, pdf.pages), start=1):
                # Sauvegarder l'image de la page sur le disque
                chemin_image = os.path.join(dossier_pages, f"page_{numero_page}.png")
                image.save(chemin_image, "PNG")

                # Extraire le texte natif de cette page (peut être vide
                # si la page est uniquement visuelle, comme les guidelines GAS)
                texte_page = page_pdf.extract_text() or ""

                pages_a_classifier.append((chemin_image, texte_page))

        # --- 4. Appeler le classifieur qu'on a déjà construit et testé ---
        # Cette fonction gère TOUT le reste : mémoire apprise, texte,
        # vision, et ajout à la file de confirmation si besoin -- on n'a
        # rien à réécrire ici, on réutilise le travail déjà fait.
        resultats = classify_tech_pack_document(
            pages_a_classifier,
            techpack_id=document_id,
            nom_dossier=nom_dossier
        )

        # --- 5. Écrire chaque page classifiée dans la base de données ---
        for numero_page, (categorie, marque) in enumerate(resultats, start=1):
            chemin_image, texte_page = pages_a_classifier[numero_page - 1]
            nouvelle_page = PageModel(
                document_id=document_id,
                page_number=numero_page,
                image_path=chemin_image,
                raw_text=texte_page,
                category=categorie,
            )
            session.add(nouvelle_page)

        # --- 6. Mettre à jour le document : marque trouvée + statut "terminé" ---
        document = session.query(DocumentModel).filter_by(id=document_id).first()
        document.brand = resultats[0][1] if resultats else "Inconnu"  # même marque pour toutes les pages
        document.page_count = len(pages_a_classifier)
        document.status = "termine"
        session.commit()

        print(f"[BACKEND] Document '{nom_dossier}' traité avec succès ({len(pages_a_classifier)} pages)")

    except Exception as e:
        # Si quoi que ce soit se passe mal, on marque le document en erreur
        # plutôt que de le laisser bloqué silencieusement sur "en_cours"
        print(f"[BACKEND] ERREUR lors du traitement de '{nom_dossier}' : {e}")
        document = session.query(DocumentModel).filter_by(id=document_id).first()
        if document:
            document.status = "erreur"
            session.commit()
    finally:
        session.close()  # on referme toujours la session, même en cas d'erreur


# ============================================================
# ÉTAPE 3 : le premier endpoint -- upload d'un Tech Pack
# ------------------------------------------------------------
# @app.post("/upload-techpack") veut dire : "quand quelqu'un envoie
# une requête POST à l'adresse /upload-techpack, exécute la fonction
# juste en dessous".
#
# "async def" : le mot "async" permet à FastAPI de continuer à
# répondre à d'autres utilisateurs pendant que celui-ci upload son
# fichier, plutôt que de rester bloqué à l'attendre. Tu n'as pas
# besoin de comprendre tout le détail technique pour l'instant --
# retiens juste que c'est la convention à utiliser avec FastAPI.
# ============================================================
@app.post("/upload-techpack")
async def upload_techpack(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """
    Reçoit un fichier PDF, l'enregistre, crée une ligne "document" en
    base de données avec le statut "en_cours", puis lance le vrai
    traitement (classification) EN ARRIÈRE-PLAN -- la réponse à
    l'utilisateur part immédiatement, sans attendre la fin du travail.
    """
    # Vérification simple : on n'accepte que des PDF
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")

    # Le nom du dossier/document = le nom du fichier sans l'extension .pdf
    nom_dossier = file.filename.rsplit(".", 1)[0]

    # --- Sauvegarder le fichier PDF reçu sur le disque ---
    chemin_pdf = os.path.join(DOSSIER_STOCKAGE, file.filename)
    with open(chemin_pdf, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)  # copie le contenu du fichier reçu vers le disque

    # --- Créer la ligne "document" en base, avec le statut "en_cours" ---
    session = SessionLocal()
    nouveau_document = DocumentModel(
        filename=nom_dossier,
        status="en_cours",
        uploaded_at=datetime.utcnow(),
    )
    session.add(nouveau_document)
    session.commit()  # nécessaire pour que la base attribue un id au document
    document_id = nouveau_document.id
    session.close()

    # --- Lancer le vrai traitement EN ARRIÈRE-PLAN ---
    # C'est la ligne clé : au lieu d'appeler traiter_document_en_arriere_plan()
    # directement (ce qui ferait attendre l'utilisateur plusieurs minutes),
    # on dit à FastAPI "lance cette fonction après avoir répondu".
    background_tasks.add_task(traiter_document_en_arriere_plan, document_id, chemin_pdf, nom_dossier)

    # --- Répondre IMMÉDIATEMENT à l'utilisateur ---
    # Cette réponse part tout de suite, sans attendre que le traitement
    # (qui peut prendre plusieurs minutes) soit terminé.
    return {
        "message": "Document reçu, traitement en cours",
        "document_id": document_id,
        "statut": "en_cours",
    }


# ============================================================
# ÉTAPE 4 : endpoint pour consulter la liste des documents
# ------------------------------------------------------------
# @app.get("/documents") : quand quelqu'un demande (GET) la liste,
# on va chercher tous les documents en base et on les renvoie.
# ============================================================
@app.get("/documents")
def lister_documents():
    """Renvoie la liste de tous les documents, avec leur statut actuel."""
    session = SessionLocal()
    documents = session.query(DocumentModel).all()
    resultat = [
        {
            "id": d.id,
            "nom": d.filename,
            "marque": d.brand,
            "nombre_pages": d.page_count,
            "statut": d.status,
        }
        for d in documents
    ]
    session.close()
    return resultat


# ============================================================
# ÉTAPE 5 : endpoint pour voir le détail d'un document précis
# ------------------------------------------------------------
# "{document_id}" dans l'URL est une "variable de chemin" -- FastAPI
# capture automatiquement ce qui est écrit à cet endroit dans l'URL
# et le passe à la fonction. Exemple : /documents/3 -> document_id = 3
# ============================================================
@app.get("/documents/{document_id}")
def detail_document(document_id: int):
    """Renvoie le détail d'un document : ses pages, leur catégorie, etc."""
    session = SessionLocal()
    document = session.query(DocumentModel).filter_by(id=document_id).first()

    if not document:
        session.close()
        raise HTTPException(status_code=404, detail="Document introuvable")

    pages = [
        {"numero": p.page_number, "categorie": p.category, "needs_review": p.needs_review}
        for p in document.pages
    ]

    resultat = {
        "id": document.id,
        "nom": document.filename,
        "marque": document.brand,
        "statut": document.status,
        "pages": pages,
    }
    session.close()
    return resultat


# ============================================================
# ÉTAPE 6 : endpoint pour la file de confirmation manuelle de marque
# ------------------------------------------------------------
# C'est l'équivalent web de ton script confirmer_marque.py -- au lieu
# de taper des commandes Python dans un terminal, ce sera plus tard
# une vraie page avec des boutons dans ton interface.
# ============================================================
@app.get("/documents-a-verifier")
def documents_a_verifier():
    """Renvoie la liste des documents dont la marque attend une confirmation manuelle."""
    session = SessionLocal()
    en_attente = session.query(MarqueAConfirmerModel).filter_by(statut="en_attente").all()
    resultat = [
        {"id": m.id, "techpack_id": m.techpack_id, "nom_dossier": m.nom_dossier}
        for m in en_attente
    ]
    session.close()
    return resultat


@app.post("/confirmer-marque/{confirmation_id}")
def confirmer_marque_web(confirmation_id: int, marque: str, motif_memoire: str):
    """
    Confirme manuellement la marque d'un document, et alimente la mémoire
    apprise -- exactement la même logique que confirmer_marque.py, mais
    accessible via une requête web au lieu d'un script en ligne de commande.
    """
    session = SessionLocal()
    confirmation = session.query(MarqueAConfirmerModel).filter_by(id=confirmation_id).first()

    if not confirmation:
        session.close()
        raise HTTPException(status_code=404, detail="Confirmation introuvable")

    confirmation.statut = "confirme"
    confirmation.marque_confirmee = marque.upper().strip()
    confirmation.date_confirmation = datetime.utcnow()

    # On alimente aussi la mémoire apprise, comme dans confirmer_marque.py
    from database import RegleMarqueAppriseModel
    nouvelle_regle = RegleMarqueAppriseModel(motif_nom_fichier=motif_memoire.strip(), marque=marque.upper().strip())
    session.add(nouvelle_regle)

    session.commit()
    session.close()

    return {"message": f"Marque '{marque}' confirmée avec succès"}