"""
============================================================
indexation.py -- Prépare tes documents pour le chatbot
============================================================

C'est quoi le but de ce fichier, simplement ?

Le chatbot doit pouvoir répondre à des questions sur le CONTENU de tes
Tech Packs (ex: "quelle est la composition du tissu ?"). Pour ça, il ne
peut pas juste lire tout le texte de tous les documents à chaque question
-- ce serait trop lent et trop volumineux. À la place, on utilise une
technique appelée RAG (Retrieval-Augmented Generation) :

  1. On découpe le texte de chaque page en petits morceaux ("chunks")
  2. On transforme chaque morceau en une liste de nombres qui représente
     son SENS (pas juste les mots) -- c'est ce qu'on appelle un "embedding"
  3. On stocke tout ça dans une base spécialisée (Chroma) qui sait
     retrouver rapidement les morceaux les plus proches en SENS d'une
     question posée, même si les mots exacts ne correspondent pas

Analogie simple : au lieu de donner à quelqu'un une bibliothèque entière
à lire à chaque question, tu lui donnes un index qui pointe direct vers
les 3-4 pages les plus pertinentes pour sa question.

Ce script fait ce travail UNE FOIS pour tous les documents déjà en base
(à relancer après chaque nouveau document traité, ou à automatiser plus
tard directement dans main.py).
============================================================
"""

import chromadb  # gardé au cas où, mais on n'en crée plus d'instance directement ici

from database import SessionLocal, PageModel, DocumentModel
from vector_store import modele_embeddings, collection


def decouper_en_morceaux(texte: str, taille_max: int = 500) -> list:
    """
    Découpe un texte en morceaux ("chunks") d'environ taille_max caractères.

    EXPLICATION SIMPLE : une page entière peut être trop longue pour être
    traitée d'un bloc de façon précise -- on la découpe en morceaux plus
    petits et gérables, comme on découperait un long article en paragraphes
    avant de le résumer paragraphe par paragraphe.

    Ici on découpe simplement par bloc de caractères, ce qui est amplement
    suffisant pour commencer -- une version plus avancée découperait plutôt
    par phrase ou paragraphe complet, mais ce serait une optimisation pour
    plus tard, pas une priorité maintenant.
    """
    texte = (texte or "").strip()
    if not texte:
        return []
    return [texte[i:i + taille_max] for i in range(0, len(texte), taille_max)]


def indexer_une_page(page, document) -> int:
    """
    Indexe UNE SEULE page dans Chroma (au lieu de tout le pipeline complet).

    CHANGEMENT (utilisé par main.py) : cette fonction est extraite de
    indexer_toutes_les_pages() pour pouvoir être appelée automatiquement
    juste après qu'une page ait été classifiée,
    page : un objet PageModel (déjà sauvegardé en base)
    document : l'objet DocumentModel correspondant
    Retourne le nombre de morceaux indexés pour cette page (0 si la page
    n'avait pas de texte exploitable).
    """
    morceaux = decouper_en_morceaux(page.raw_text)
    if not morceaux:
        return 0

    for numero_morceau, morceau in enumerate(morceaux):
        identifiant = f"page_{page.id}_chunk_{numero_morceau}" #exp page_15_chunk_0
        embedding = modele_embeddings.encode(morceau).tolist()

        collection.upsert( #Update + Insert
            ids=[identifiant],
            embeddings=[embedding],
            documents=[morceau],
            metadatas=[{
                "document_id": page.document_id,
                "nom_document": document.filename if document else "inconnu",
                "page_number": page.page_number,
                "categorie": page.category or "Inconnue",
            }],
        )

    return len(morceaux)


def indexer_toutes_les_pages():
    """
    Parcourt toutes les pages déjà classifiées en base MySQL, et les
    indexe dans Chroma si ce n'est pas déjà fait.

    Utile pour un rattrapage global (ex: relancer une fois sur toute la
    base après avoir modifié la logique d'indexation), mais n'est plus
    indispensable au jour le jour depuis que indexer_une_page() est
    appelée automatiquement par main.py à la fin de chaque traitement.
    """
    session = SessionLocal()
    pages = session.query(PageModel).all()

    nombre_indexees = 0

    for page in pages:
        document = session.query(DocumentModel).filter_by(id=page.document_id).first()
        nombre_indexees += indexer_une_page(page, document)

    session.close()
    print(f"Indexation terminée : {nombre_indexees} morceaux de texte indexés dans Chroma.")


if __name__ == "__main__": #si ce fichier est execute directement 
    indexer_toutes_les_pages()