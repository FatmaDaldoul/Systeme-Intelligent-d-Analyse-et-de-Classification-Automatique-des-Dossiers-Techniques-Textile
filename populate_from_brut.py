import os
from database import SessionLocal, DocumentModel, PageModel  # Connexion à la base de données et modèles SQLAlchemy
from classifier_techpacks import classify_tech_pack_page   # Importation de notre nouvelle fonction d'IA

def synchroniser_dataset_brut_vers_db(base_dir="dataset_brut"):
    """
    Parcourt le dossier 'dataset_brut', crée les documents, analyse chaque page avec l'IA,
    met à jour dynamiquement la marque du document et enregistre les informations en base de données.
    """
    session = SessionLocal()  # Initialisation de la session de base de données
    
    # Vérification de sécurité initiale : le dossier source existe-t-il ?
    if not os.path.exists(base_dir):
        print(f"Erreur : Le dossier '{base_dir}' est introuvable.")
        return

    try:
        # 1. Lister tous les sous-dossiers de premier niveau (chaque dossier représente un Tech Pack)
        sous_dossiers = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]

        if not sous_dossiers:
            print("Aucun dossier trouvé dans dataset_brut.")
            return

        # Boucle sur chaque dossier de Tech Pack détecté
        for nom_dossier in sous_dossiers:
            chemin_dossier = os.path.join(base_dir, nom_dossier)
            nom_pdf_original = f"{nom_dossier}.pdf"
            
            # Éviter les doublons : On vérifie si ce fichier PDF a déjà été synchronisé auparavant
            doc_existant = session.query(DocumentModel).filter_by(filename=nom_pdf_original).first()
            if doc_existant:
                print(f"[-] '{nom_pdf_original}' est déjà enregistré en base (ID: {doc_existant.id}).")
                continue  # Passe au dossier suivant pour éviter de dupliquer le traitement

            print(f"\n[+] Synchronisation et classification du document : {nom_pdf_original}")
            
            # Étape préliminaire : Compter le nombre d'images PNG pour définir le nombre de pages
            fichiers = os.listdir(chemin_dossier)
            images_pages = sorted(
                [f for f in fichiers if f.endswith(".png")], 
                key=lambda x: int(x.split("_")[1].split(".")[0])
            )
            nb_pages = len(images_pages)

            # Insertion Niveau 1 : Le Document
            # On l'initialise temporairement avec "En cours..." pour la marque.
            # Elle sera corrigée dès que l'IA aura analysé la première page !
            nouveau_doc = DocumentModel(
                filename=nom_pdf_original,
                brand="En cours...",
                page_count=nb_pages,
                status="completed"
            )
            session.add(nouveau_doc)
            session.flush()  # Demande à la base de générer l'ID de nouveau_doc sans commiter définitivement

            # Variable pour suivre si on a réussi à identifier la marque du vêtement
            marque_finale_identifiee = "Inconnu"

            # Insertion Niveau 2 : Parcours et classification de chaque page individuelle
            for fichier_img in images_pages:
                # Extraction propre du numéro de la page depuis son nom de fichier (ex: page_1.png -> 1)
                num_page = int(fichier_img.split("_")[1].split(".")[0])
                fichier_txt = f"page_{num_page}.txt"
                
                # Reconstitution des chemins absolus
                chemin_txt = os.path.join(chemin_dossier, fichier_txt)
                chemin_image_complete = os.path.join(chemin_dossier, fichier_img)
                
                # Lecture du texte brut extrait en amont par pdfplumber
                texte_brut = ""
                if os.path.exists(chemin_txt):
                    with open(chemin_txt, "r", encoding="utf-8") as f:
                        texte_brut = f.read()

                # ---- DÉBUT DE LA CLASSIFICATION INTELLIGENTE ----
                print(f"   -> Appel IA (Llava) en cours pour la Page {num_page}...")
                
                # L'IA analyse conjointement la photo PNG et le texte brut extrait
                # Elle nous retourne à présent DEUX éléments : la catégorie ET la marque
                # On transmet le numéro de page réel : la règle "Cover Page" du classifieur
                # ne doit se déclencher que sur la page 1, pas sur un en-tête répété
                # (certains templates comme Ralph Lauren répètent les mêmes champs
                # administratifs sur chaque page).
                categorie_ia, marque_extraite_ia = classify_tech_pack_page(
                    chemin_image_complete, texte_brut, page_number=num_page
                )
                
                print(f"      [IA Décision] Catégorie : '{categorie_ia}' | Marque détectée : '{marque_extraite_ia}'")
                # ---- FIN DE LA CLASSIFICATION INTELLIGENTE ----

                # LOGIQUE DE MISE A JOUR DE LA MARQUE :
                # Si c'est la première page (page 1) et que l'IA a trouvé une vraie marque, ou si le document est encore marqué "En cours..."
                if marque_extraite_ia != "Inconnu" and marque_finale_identifiee == "Inconnu":
                    marque_finale_identifiee = marque_extraite_ia
                    nouveau_doc.brand = marque_finale_identifiee  # Mise à jour directe de la colonne dans le document parent

                # Création et configuration de l'objet PageModel lié à la base
                nouvelle_page = PageModel(
                    document_id=nouveau_doc.id,  # Clé étrangère pointant vers l'ID généré au flush()
                    page_number=num_page,
                    image_path=chemin_image_complete,
                    raw_text=texte_brut,
                    category=categorie_ia,          # Catégorie structurée trouvée par l'IA
                    category_confidence=0.85,       # Score théorique de confiance
                    needs_review=False
                )
                session.add(nouvelle_page)  # Enfile la page pour l'insertion SQL
            
            # Si après avoir scanné toutes les pages, aucune marque claire n'est sortie, on applique "Inconnu"
            if nouveau_doc.brand == "En cours...":
                nouveau_doc.brand = "Inconnu"

            # Enregistrement définitif du document et de l'ensemble de ses pages associées
            session.commit()
            print(f"   -> Succès : {nb_pages} pages synchronisées en base pour ce document (Marque : {nouveau_doc.brand}).")

    except Exception as e:
        session.rollback()  # Annulation immédiate de toutes les requêtes en attente en cas d'erreur bloquante
        print(f"[-] Erreur critique survenue pendant la synchronisation : {e}")
    finally:
        session.close()     # Libération propre des connexions de la session SQL

if __name__ == "__main__":
    synchroniser_dataset_brut_vers_db()