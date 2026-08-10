"""
============================================================
chat_service.py -- Le "cerveau" du chatbot
============================================================

C'est ici que se passe la vraie logique du chatbot : recevoir une
question, trouver les passages pertinents dans les Tech Packs déjà
indexés (grâce à indexation.py), puis demander à un modèle de langage
(llama3.2:3b) de rédiger une réponse en se basant UNIQUEMENT sur ces
passages -- pas sur ses connaissances générales.

C'est le principe du RAG (Retrieval-Augmented Generation) :
  RETRIEVAL  = on cherche les passages pertinents (avec Chroma)
  AUGMENTED  = on les ajoute au prompt, pour "augmenter" les connaissances du modèle
  GENERATION = le modèle génère une réponse à partir de ça

Pourquoi c'est mieux qu'un chatbot "normal" : sans RAG, le modèle
répondrait avec des connaissances générales sur la mode/le textile,
sans jamais avoir vu TES documents précis. Avec RAG, il répond en
se basant sur le contenu réel de tes Tech Packs.
============================================================
"""

import requests
import re
# ============================================================
# CHANGEMENT #19 (suite) : même correction que dans indexation.py --
# on utilise la connexion Chroma et le modèle d'embeddings partagés
# depuis vector_store.py, au lieu d'en recréer une deuxième instance
# ici (c'est ça qui causait le plantage au démarrage de main.py).
# ============================================================
from vector_store import modele_embeddings, collection
from database import SessionLocal, DocumentModel, PageModel
OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODELE_GENERATION = "llama3.2:3b"  # le modèle texte, différent de bakllava (vision)
#questions de métadonnées, répondues SANS RAG
# EXPLICATION SIMPLE : "combien de pages fait ce document ?" n'a pas
# de réponse dans le TEXTE d'une page -- c'est une info qui vit dans
# la table "documents" de MySQL (page_count, status, brand...), pas
# dans Chroma. Chercher ça par recherche de sens ne peut jamais
# fonctionner, quel que soit le nombre de morceaux indexés.
# On détecte donc D'ABORD si la question ressemble à une question de
# métadonnée, et si oui, on répond directement depuis la base de
# données -- rapide, fiable à 100%, sans même avoir besoin d'appeler
# le modèle de génération.
MOTIFS_METADONNEES = {
    # Vérifié en premier (voir plus bas) car le plus englobant -- si la
    # personne demande "tout", pas la peine de deviner quel sous-type précis
    # elle veut.
    "resume": [r"toutes? les? informations?", r"informations? compl[èe]tes?", r"r[ée]sum[ée]", r"dis[ -]?moi tout", r"d[ée]taille?\s*(tout|ce document)"],
    "nom": [r"nom (complet )?du (document|fichier)", r"comment s'appelle", r"quel est le (nom|fichier)"],
    "nombre_pages": [r"combien.*(page|pages)", r"nombre.*(page|pages)"],
    "statut": [r"statut", r"o[uù].*(en est|traitement)", r"termin[ée]", r"fini"],
    "marque": [r"quelle.*marque", r"marque.*(document|c'est|de ce)"],
    "categories_presentes": [r"quelles? cat[ée]gories", r"quels? types? de pages", r"liste.*(cat[ée]gorie|page)"],
    "a_verifier": [r"(pages?|combien).*(à|a) v[ée]rifier", r"pages? incertaines?", r"vision"],
}


def detecter_question_metadonnee(question: str) -> str | None:
    """
    Renvoie le type de métadonnée demandée ("nombre_pages", "statut",
    "marque") si la question y ressemble, sinon None.
    """
    question_lower = question.lower()
    for type_meta, motifs in MOTIFS_METADONNEES.items():
        for motif in motifs:
            if re.search(motif, question_lower):
                return type_meta
    return None


def repondre_metadonnee(type_meta: str, document_id: int) -> str:
    """
    Va chercher directement en base MySQL l'information demandée,
    pour ce document précis. Nécessite un document_id -- si aucun
    document n'est ciblé (recherche sur "tous les documents"), on ne
    peut pas répondre à ce type de question de façon fiable.
    """
    if not document_id:
        return "Précise sur quel document tu poses la question (choisis-le dans la liste), je ne peux pas répondre à ce type de question sur tous les documents à la fois."

    session = SessionLocal()
    document = session.query(DocumentModel).filter_by(id=document_id).first()
    session.close()

    if not document:
        return "Je ne trouve pas ce document."

    if type_meta == "nombre_pages":
        if document.page_count is None:
            return f"Le nombre de pages de \"{document.filename}\" n'est pas encore connu (traitement peut-être en cours)."
        return f"\"{document.filename}\" contient {document.page_count} pages."

    if type_meta == "statut":
        libelles = {"en_cours": "en cours de traitement", "termine": "terminé", "erreur": "en erreur"}
        return f"Le statut de \"{document.filename}\" est : {libelles.get(document.status, document.status)}."

    if type_meta == "marque":
        if not document.brand or document.brand.upper() == "INCONNU":
            return f"La marque de \"{document.filename}\" n'a pas encore été identifiée (elle attend peut-être une confirmation manuelle)."
        return f"La marque de \"{document.filename}\" est : {document.brand}."

    if type_meta == "nom":
        return f"Le nom complet de ce document est : \"{document.filename}\"."

    if type_meta == "categories_presentes":
        session = SessionLocal()
        pages = session.query(PageModel).filter_by(document_id=document_id).all()
        session.close()
        if not pages:
            return f"\"{document.filename}\" n'a pas encore de pages classifiées."
        compteur = {}
        for p in pages:
            cle = p.category or "Non classifiée"
            compteur[cle] = compteur.get(cle, 0) + 1
        details = ", ".join(f"{cat} ({n})" for cat, n in sorted(compteur.items(), key=lambda x: -x[1]))
        return f"\"{document.filename}\" contient les catégories suivantes : {details}."

    if type_meta == "a_verifier":
        session = SessionLocal()
        pages = session.query(PageModel).filter_by(document_id=document_id).all()
        session.close()
        a_verifier = [p for p in pages if p.needs_review]
        if not a_verifier:
            return f"Aucune page de \"{document.filename}\" n'a besoin d'être vérifiée en priorité -- toutes ont été classées par analyse de texte, avec un score de confiance."
        numeros = ", ".join(str(p.page_number) for p in sorted(a_verifier, key=lambda p: p.page_number))
        return f"{len(a_verifier)} page(s) de \"{document.filename}\" ont été classées par analyse d'image (pas de score numérique, à vérifier en priorité) : page(s) {numeros}."

    if type_meta == "resume":
        session = SessionLocal()
        pages = session.query(PageModel).filter_by(document_id=document_id).all()
        session.close()

        libelles_statut = {"en_cours": "en cours de traitement", "termine": "terminé", "erreur": "en erreur"}
        marque_txt = document.brand if (document.brand and document.brand.upper() != "INCONNU") else "non identifiée"
        nb_a_verifier = sum(1 for p in pages if p.needs_review)

        compteur = {}
        for p in pages:
            cle = p.category or "Non classifiée"
            compteur[cle] = compteur.get(cle, 0) + 1
        categories_txt = ", ".join(f"{cat} ({n})" for cat, n in sorted(compteur.items(), key=lambda x: -x[1])) or "aucune page classifiée pour l'instant"

        return (
            f"Résumé de \"{document.filename}\" :\n"
            f"- Statut : {libelles_statut.get(document.status, document.status)}\n"
            f"- Marque : {marque_txt}\n"
            f"- Nombre de pages : {document.page_count if document.page_count is not None else len(pages)}\n"
            f"- Catégories présentes : {categories_txt}\n"
            f"- Pages à vérifier en priorité (issues de la vision) : {nb_a_verifier}\n"
            f"- Date d'ajout : {document.uploaded_at.strftime('%d/%m/%Y à %H:%M') if document.uploaded_at else 'inconnue'}"
        )

    return "Je ne sais pas répondre à cette question de métadonnée."


# ============================================================
# AJOUT : questions du type "quelle est la classe/catégorie de la page N ?"
# ------------------------------------------------------------
# EXPLICATION SIMPLE : même principe que les questions de métadonnées
# ci-dessus -- la catégorie d'une page N'EST PAS écrite dans le texte de
# la page elle-même, c'est une donnée que le classifieur a calculée et
# stockée à côté (colonne "category" de la table "pages"). Chercher ça
# par recherche de SENS (Chroma) ne peut jamais bien fonctionner : Chroma
# retrouve juste le texte qui "ressemble" le plus à la question posée,
# ce qui donne une réponse plausible en apparence mais fausse sur le fond
# (ex: citer des pages au hasard qui parlent de "numérotation").
# On détecte donc ce type de question séparément, avec son propre motif
# (qui doit aussi extraire le numéro de page demandé), et on répond
# directement depuis MySQL, comme pour les autres métadonnées.
# ============================================================
MOTIF_CATEGORIE_PAGE = re.compile(r"classe|cat[ée]gorie")
MOTIF_NUMERO_PAGE = re.compile(r"page\s*n?[°ºo]?\s*(\d+)")


def detecter_question_categorie_page(question: str):
    """
    Renvoie le numéro de page (int) si la question ressemble à "quelle est
    la classe/catégorie de la page N ?", sinon None.
    """
    question_lower = question.lower()
    if not MOTIF_CATEGORIE_PAGE.search(question_lower):
        return None
    match = MOTIF_NUMERO_PAGE.search(question_lower)
    if not match:
        return None
    return int(match.group(1))


def repondre_categorie_page(document_id: int, numero_page: int) -> str:
    """Cherche directement en base la catégorie d'une page précise d'un document."""
    if not document_id:
        return "Précise sur quel document tu poses la question (choisis-le dans la liste), je ne peux pas chercher une page précise sans savoir dans quel document."

    session = SessionLocal()
    page = session.query(PageModel).filter_by(document_id=document_id, page_number=numero_page).first()
    session.close()

    if not page:
        return f"Je ne trouve pas de page {numero_page} pour ce document."
    if not page.category:
        return f"La page {numero_page} n'a pas encore été classifiée."

    reponse = f"La page {numero_page} est classée \"{page.category}\"."
    if page.category_confidence is not None:
        reponse += f" Elle a été trouvée par analyse du texte (score de confiance {page.category_confidence:.1f})."
    elif page.needs_review:
        reponse += " Elle a été trouvée par analyse de l'image (pas de score numérique pour ce type de détection -- à vérifier en priorité si un doute)."
    return reponse


def chercher_passages_pertinents(question: str, document_id: int = None, nombre_resultats: int = 5) -> list:
    """
    Cherche dans Chroma les morceaux de texte les plus proches en SENS
    de la question posée (pas juste les mots exacts).

    document_id (optionnel) : si fourni, ne cherche que dans les pages
    de ce document précis -- utile si l'utilisateur veut interroger un
    Tech Pack en particulier plutôt que tous en même temps.
    """
    # On transforme la question en embedding, avec le MÊME modèle que
    # celui utilisé pour indexer les documents -- c'est indispensable,
    # sinon les nombres générés ne seraient pas comparables entre eux
    # (un peu comme comparer des distances mesurées en mètres avec
    # d'autres mesurées en miles, sans convertir).
    embedding_question = modele_embeddings.encode(question).tolist()

    filtre = {"document_id": document_id} if document_id else None

    resultats = collection.query(
        query_embeddings=[embedding_question],
        n_results=nombre_resultats,
        where=filtre,
    )

    # resultats["documents"][0] contient la liste des morceaux de texte trouvés
    # resultats["metadatas"][0] contient leurs infos associées (page, catégorie...)
    passages = []
    documents_trouves = resultats.get("documents", [[]])[0]
    metadonnees_trouvees = resultats.get("metadatas", [[]])[0]

    for texte, meta in zip(documents_trouves, metadonnees_trouvees):
        passages.append({
            "texte": texte,
            "document": meta.get("nom_document", "inconnu"),
            "page": meta.get("page_number", "?"),
            "categorie": meta.get("categorie", "inconnue"),
        })

    return passages


def construire_prompt(question: str, passages: list) -> str:
    """
    Assemble la question et les passages trouvés dans un prompt clair
    pour le modèle de génération -- avec des instructions explicites
    pour qu'il reste honnête (même principe que pour la marque : mieux
    vaut "je ne sais pas" qu'une réponse inventée).
    """
    if not passages:
        contexte = "(Aucun passage pertinent trouvé dans les documents indexés.)"
    else:
        blocs = []
        for p in passages:
            blocs.append(f"[Document: {p['document']} | Page {p['page']} | Catégorie: {p['categorie']}]\n{p['texte']}")
        contexte = "\n\n---\n\n".join(blocs)

    prompt = f"""Tu es un assistant qui répond à des questions sur des Tech Packs (dossiers techniques textile).

Voici des extraits pertinents trouvés dans les documents :

{contexte}

Question : {question}

Consignes :
- Réponds UNIQUEMENT à partir des extraits ci-dessus, jamais à partir de connaissances générales.
- Si les extraits ne permettent pas de répondre à la question, dis clairement "Je ne trouve pas cette information dans les documents indexés" -- ne devine jamais.
- Cite le document et la page d'où vient l'information quand c'est pertinent.
- Réponds de façon claire et concise, en français.
"""
    return prompt


def repondre_question(question: str, document_id: int = None) -> dict:
    """
    Point d'entrée principal : reçoit une question, renvoie une réponse
    construite à partir des documents indexés, accompagnée des sources
    utilisées (pour que l'utilisateur puisse vérifier d'où vient l'info).
    """
    # --- Étape 0a : "quelle est la classe/catégorie de la page N ?" ---
    # Vérifié EN PREMIER, avant les métadonnées générales et avant le RAG :
    # c'est le cas le plus précis (un numéro de page exact), donc le plus
    # fiable à traiter directement, s'il est détecté.
    numero_page_demande = detecter_question_categorie_page(question)
    if numero_page_demande is not None:
        return {
            "reponse": repondre_categorie_page(document_id, numero_page_demande),
            "sources": [],
        }

    # --- Étape 0b : est-ce une autre question de métadonnée ? ---
    # Si oui, on répond directement depuis MySQL, sans passer par Chroma
    # ni par le modèle de génération -- plus rapide et 100% fiable pour
    # ce type précis de question.
    type_meta = detecter_question_metadonnee(question)
    if type_meta:
        return {
            "reponse": repondre_metadonnee(type_meta, document_id),
            "sources": [],
        }

    passages = chercher_passages_pertinents(question, document_id=document_id)
    prompt = construire_prompt(question, passages)

    payload = {
        "model": MODELE_GENERATION,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},  # basse température = réponses plus factuelles, moins "créatives"
        "keep_alive": "30m",
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
        if response.status_code == 200:
            reponse_texte = response.json().get("response", "").strip()
        else:
            reponse_texte = f"Erreur du modèle (code {response.status_code})."
    except requests.exceptions.Timeout:
        reponse_texte = "Le modèle a mis trop de temps à répondre. Réessaie."
    except Exception as e:
        reponse_texte = f"Erreur lors de la génération : {e}"

    return {
        "reponse": reponse_texte,
        "sources": [{"document": p["document"], "page": p["page"]} for p in passages],
    }


if __name__ == "__main__":
    # Petit test rapide en ligne de commande, sans passer par l'API web,
    # pour vérifier que tout fonctionne avant de brancher l'endpoint.
    question_test = input("Pose une question sur tes Tech Packs : ")
    resultat = repondre_question(question_test)
    print("\n--- Réponse ---")
    print(resultat["reponse"])
    print("\n--- Sources ---")
    for s in resultat["sources"]:
        print(f"  - {s['document']} (page {s['page']})")