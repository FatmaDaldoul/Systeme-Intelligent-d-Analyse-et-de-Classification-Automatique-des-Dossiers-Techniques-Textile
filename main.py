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
import shutil
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
#  CORSMiddleware
# EXPLICATION SIMPLE : par défaut, un navigateur bloque une page web
# qui essaie d'appeler une API tournant sur une autre adresse (même
# 127.0.0.1 avec un port différent compte comme "une autre adresse").
# C'est une protection de sécurité normale du navigateur, appelée
# "CORS". Comme ton interface React va tourner séparément de ton
# backend et devra l'appeler, il faut dire explicitement à FastAPI
# "autorise ces appels" -- sinon toutes les requêtes échoueront
# silencieusement avec une erreur CORS dans la console du navigateur.
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber            # Pour extraire le texte natif de chaque page du PDF
from pdf2image import convert_from_path  # Pour transformer chaque page du PDF en image (.png)

# On réutilise tout ce qu'on a déjà construit : la base de données
# et le classifieur -- pas besoin de réécrire quoi que ce soit ici.
from database import SessionLocal, DocumentModel, PageModel, MarqueAConfirmerModel
# import du service de chat + Pydantic
# EXPLICATION SIMPLE : "BaseModel" de Pydantic sert à décrire précisément
# à quoi doit ressembler le JSON envoyé par l'utilisateur quand il pose
# une question -- un peu comme un formulaire avec des champs attendus.
# FastAPI utilise ça pour valider automatiquement les requêtes et
# refuser proprement celles qui sont mal formées.
from pydantic import BaseModel
from chat_service import repondre_question
# CHANGEMENT #18 : import de la fonction d'indexation d'une page
# Pour que chaque nouveau document soit automatiquement indexé dans
# Chroma dès la fin de son traitement, sans devoir relancer indexation.py
# manuellement à chaque fois.
from indexation import indexer_une_page
from classifier_techpacks import classify_tech_pack_document
from vector_store import collection


# ÉTAPE 1 : créer l'application FastAPI
# "app" est l'objet central de tout le backend. C'est un peu comme
# la caisse enregistreuse elle-même -- tout ce qu'on ajoute après
# (les endpoints) vient s'y accrocher.
app = FastAPI(title="Techpack Analyzer API")
# On autorise ici toutes les origines ("*") pour simplifier le développement.
# En production plus tard, on remplacera "*" par l'adresse exacte de ton
# vrai site web, pour ne pas laisser n'importe quel site appeler ton API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dossier où on va stocker les PDF uploadés et les pages extraites
DOSSIER_STOCKAGE = "stockage_documents"
os.makedirs(DOSSIER_STOCKAGE, exist_ok=True)  # crée le dossier s'il n'existe pas déjà


def texte_semble_lisible(texte: str) -> bool:
    """
    Certains PDF techniques (souvent générés par des logiciels comme Lectra)
    utilisent des polices "custom" sans table de correspondance Unicode
    correcte -- pdfplumber extrait alors des caractères, mais ce ne sont pas
    les bons, ce qui donne du charabia (ex: symboles, accents mal placés).
    Cette fonction estime si un texte est "normal" ou pas, en mesurant la
    proportion de caractères habituels (lettres, chiffres, ponctuation
    courante, espaces) -- si elle est trop faible, mieux vaut prévenir
    l'utilisatrice que d'afficher du charabia tel quel.
    """
    if not texte or not texte.strip():
        return True  # pas de texte du tout -- ce n'est pas "illisible", juste absent
    caracteres_normaux = sum(
        1 for c in texte if c.isalnum() or c.isspace() or c in ".,;:!?-_/()%'\"€$&+°"
    )
    ratio = caracteres_normaux / len(texte)
    return ratio > 0.75


# ÉTAPE 2 : la fonction qui fait le VRAI travail (en arrière-plan)
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
        # Créer un sous-dossier propre pour ce document ---
        dossier_pages = os.path.join(DOSSIER_STOCKAGE, nom_dossier)
        os.makedirs(dossier_pages, exist_ok=True)

        # Convertir chaque page du PDF en image PNG ---
        # convert_from_path lit le PDF et renvoie une liste d'images,
        # une par page, dans l'ordre.
        images = convert_from_path(chemin_pdf)

        pages_a_classifier = []  # va contenir (chemin_image, texte) pour chaque page

        # --- 3. Extraire le texte natif de chaque page avec pdfplumber ---
        # C'est ICI qu'on applique la correction prioritaire identifiée
        # ensemble : utiliser le texte natif du PDF (pas de l'OCR;Optical Character Recognition son role est de regarder une image et essayer de reconnaître le texte.),
        # locr peut faire des erreurs
        # est beaucoup plus fiable pour retrouver la marque par texte
        # avant même d'avoir besoin de la vision.
        with pdfplumber.open(chemin_pdf) as pdf:
            for numero_page, (image, page_pdf) in enumerate(zip(images, pdf.pages), start=1):    #ytl3ou kima (1, (image1, page1))
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
        # --- ET l'indexer automatiquement dans Chroma pour le chatbot ---
        # ============================================================
        # CHANGEMENT #18 (suite) : appel à indexer_une_page() ici, juste
        # après avoir créé et ajouté la page en base. Comme ça, dès qu'un
        # document est traité, ses pages sont IMMÉDIATEMENT disponibles
        # pour le chatbot -- plus besoin de relancer indexation.py à la
        # main après chaque upload.
        # ============================================================
        document_pour_indexation = session.query(DocumentModel).filter_by(id=document_id).first()
        for numero_page, (categorie, marque, score_confiance) in enumerate(resultats, start=1):
            chemin_image, texte_page = pages_a_classifier[numero_page - 1]
            nouvelle_page = PageModel(
                document_id=document_id,
                page_number=numero_page,
                image_path=chemin_image,
                raw_text=texte_page,
                category=categorie,
                category_confidence=score_confiance,
                # needs_review : on marque à surveiller toute page où la catégorie
                # vient de la vision (score=None) plutôt que d'un score de texte
                # solide -- utile pour repérer d'un coup d'oeil les classifications
                # les moins fiables dans l'interface.
                needs_review=(score_confiance is None),
            )
            session.add(nouvelle_page)
            session.flush()  # nécessaire pour que nouvelle_page.id soit déjà disponible avant le commit final

            try:
                indexer_une_page(nouvelle_page, document_pour_indexation)
            except Exception as e:
                print(f"[BACKEND] Indexation Chroma échouée pour la page {numero_page} : {e}")

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


# ÉTAPE 3 : le premier endpoint -- upload d'un Tech Pack
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

    # ============================================================
    # AJOUT : gestion du retraitement d'un document déjà existant.
    # ------------------------------------------------------------
    # POURQUOI : "filename" est une colonne UNIQUE dans la table
    # "documents" (voir database.py). Sans cette vérification, uploader
    # un fichier qui a déjà été traité provoquait une violation de
    # contrainte MySQL au moment du commit -> une erreur 500 non gérée
    # -> le frontend l'interprétait à tort comme "impossible de joindre
    # le serveur" (message générique du bloc catch), alors que le serveur
    # répondait très bien -- il refusait juste le doublon.
    # On choisit ici le comportement le plus intuitif pour l'utilisatrice :
    # ré-uploader un document déjà traité = le retraiter depuis zéro.
    # On supprime donc l'ancienne ligne (ce qui supprime aussi en cascade
    # ses pages, extractions, BOM, mesures et confirmations de marque,
    # grâce à cascade="all, delete-orphan" dans database.py), puis on
    # nettoie aussi ses anciens morceaux indexés dans Chroma (sinon ils
    # resteraient orphelins avec d'anciens page_id qui n'existent plus
    # en base, et pollueraient les résultats du chatbot).
    # ============================================================
    document_existant = session.query(DocumentModel).filter_by(filename=nom_dossier).first()
    if document_existant:
        print(f"[BACKEND] '{nom_dossier}' déjà traité -> suppression de l'ancienne version avant retraitement")
        try:
            collection.delete(where={"document_id": document_existant.id})
        except Exception as e:
            print(f"[BACKEND] Nettoyage Chroma de l'ancienne version échoué (pas bloquant) : {e}")
        session.delete(document_existant)
        session.commit()

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


# ÉTAPE 4 : endpoint pour consulter la liste des documents
# @app.get("/documents") : quand quelqu'un demande (GET) la liste,
# on va chercher tous les documents en base et on les renvoie.
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
            "date_ajout": d.uploaded_at.isoformat() if d.uploaded_at else None,
        }
        for d in documents
    ]
    session.close()
    return resultat


# ÉTAPE 5 : endpoint pour voir le détail d'un document précis
# "{document_id}" dans l'URL est une "variable de chemin" -- FastAPI
# capture automatiquement ce qui est écrit à cet endroit dans l'URL
# et le passe à la fonction. Exemple : /documents/3 -> document_id = 3
# --- AJOUT / REMPLACEMENT DANS main.py ---

@app.delete("/documents/{document_id}")
def supprimer_document(document_id: int):
    """
    Supprime définitivement un document de :
    1. La base MySQL (avec suppression en cascade des pages, BOM, mesures, confirmations)
    2. La base vectorielle ChromaDB
    3. Du disque local (images et PDF)
    """
    session = SessionLocal()
    document = session.query(DocumentModel).filter_by(id=document_id).first()

    if not document:
        session.close()
        raise HTTPException(status_code=404, detail="Document introuvable")

    nom_dossier = document.filename

    # 1. Nettoyage ChromaDB
    try:
        collection.delete(where={"document_id": document_id})
    except Exception as e:
        print(f"[BACKEND] Avertissement suppression Chroma : {e}")

    # 2. Nettoyage du stockage fichier (PDF + dossier d'images)
    chemin_pdf = os.path.join(DOSSIER_STOCKAGE, f"{nom_dossier}.pdf")
    if os.path.exists(chemin_pdf):
        try:
            os.remove(chemin_pdf)
        except Exception as e:
            print(f"[BACKEND] Erreur suppression PDF : {e}")

    dossier_images = os.path.join(DOSSIER_STOCKAGE, nom_dossier)
    if os.path.exists(dossier_images):
        try:
            shutil.rmtree(dossier_images)
        except Exception as e:
            print(f"[BACKEND] Erreur suppression dossier images : {e}")

    # 3. Suppression MySQL (Cascade gérée par SQLAlchemy)
    session.delete(document)
    session.commit()
    session.close()

    return {"message": f"Document '{nom_dossier}' et toutes ses données associées ont été supprimés avec succès."}


@app.get("/documents/{document_id}")
def detail_document(document_id: int):
    """Renvoie toutes les informations détaillées d'un document (Pages, BOM, Mesures)."""
    session = SessionLocal()
    document = session.query(DocumentModel).filter_by(id=document_id).first()

    if not document:
        session.close()
        raise HTTPException(status_code=404, detail="Document introuvable")

    pages_triees = sorted(document.pages, key=lambda p: p.page_number)

    pages = []
    totaux_bom = 0
    totaux_mesures = 0

    for p in pages_triees:
        bom_items = [
            {
                "id": b.id,
                "item_type": b.item_type,
                "placement": b.placement,
                "material_composition": b.material_composition,
                "supplier": b.supplier,
                "cost": b.cost
            }
            for b in p.bom_items
        ]
        measurements = [
            {
                "id": m.id,
                "measurement_point": m.measurement_point,
                "size": m.size,
                "value_cm": m.value_cm,
                "tolerance": m.tolerance
            }
            for m in p.measurements
        ]

        totaux_bom += len(bom_items)
        totaux_mesures += len(measurements)

        pages.append({
            "id": p.id,
            "numero": p.page_number,
            "categorie": p.category,
            "confiance": p.category_confidence,
            "needs_review": p.needs_review,
            "image_path": p.image_path,
            "apercu_texte": (p.raw_text or "").strip(),
            "a_du_texte": bool((p.raw_text or "").strip()),
            "bom_items": bom_items,
            "measurements": measurements
        })

    resultat = {
        "id": document.id,
        "nom": document.filename,
        "marque": document.brand,
        "statut": document.status,
        "nombre_pages": document.page_count,
        "date_ajout": document.uploaded_at.isoformat() if document.uploaded_at else None,
        "statistiques": {
            "total_bom_items": totaux_bom,
            "total_measurements": totaux_mesures,
            "pages_a_verifier": sum(1 for p in pages if p["needs_review"])
        },
        "pages": pages,
    }
    session.close()
    return resultat


@app.get("/documents-a-verifier")
def documents_a_verifier():
    """Renvoie la liste SANS REDONDANCE des documents en attente de confirmation."""
    session = SessionLocal()
    # Utilisation d'un dictionnaire pour dédoublonner strictement par nom_dossier
    en_attente = session.query(MarqueAConfirmerModel).filter_by(statut="en_attente").all()
    
    uniques = {}
    for m in en_attente:
        if m.nom_dossier not in uniques:
            uniques[m.nom_dossier] = {
                "id": m.id,
                "techpack_id": m.techpack_id,
                "nom_dossier": m.nom_dossier,
                "date_creation": m.date_creation.isoformat() if m.date_creation else None
            }
            
    session.close()
    return list(uniques.values())


@app.post("/confirmer-marque/{confirmation_id}")
def confirmer_marque_web(confirmation_id: int, marque: str, motif_memoire: str):
    """
    Confirme manuellement la marque d'un document, et alimente la mémoire
    apprise -- exactement la même logique que confirmer_marque.py, mais
    accessible via une requête web au lieu d'un script en ligne de commande.
    """
    session = SessionLocal()
    confirmation = session.query(MarqueAConfirmerModel).filter_by(id=confirmation_id).first() 
    #c'est equialent a SELECT *FROM marque_a_confirmer WHERE id = 5; et first siginifiequon doit afficher la premiere ligne
    if not confirmation:
        session.close()
        raise HTTPException(status_code=404, detail="Confirmation introuvable")

    confirmation.statut = "confirme"
    confirmation.marque_confirmee = marque.upper().strip()
    confirmation.date_confirmation = datetime.utcnow()   #la date et lheure actuelle

    from database import RegleMarqueAppriseModel
    nouvelle_regle = RegleMarqueAppriseModel(motif_nom_fichier=motif_memoire.strip(), marque=marque.upper().strip())
    session.add(nouvelle_regle)

    session.commit()
    session.close()

    return {"message": f"Marque '{marque}' confirmée avec succès"}


class QuestionChat(BaseModel):
    question: str
    document_id: int | None = None  # optionnel : cibler un document précis, ou chercher partout si absent


@app.post("/chat") #endpoint du chat
def poser_question(payload: QuestionChat):
    """
    Reçoit une question, cherche les passages pertinents dans les documents
    déjà indexés (via chat_service.py), génère une réponse avec llama3.2:3b,
    et renvoie la réponse accompagnée de ses sources (document + page).
    """
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="La question ne peut pas être vide")

    resultat = repondre_question(payload.question, document_id=payload.document_id)
    return resultat