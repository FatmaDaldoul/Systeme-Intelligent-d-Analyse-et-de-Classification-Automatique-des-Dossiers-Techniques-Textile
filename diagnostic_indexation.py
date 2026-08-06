"""
Script de diagnostic : vérifie combien de morceaux de texte sont
réellement indexés dans Chroma pour un document précis, et affiche
leur contenu -- pour comprendre pourquoi le chatbot ne trouve rien.
"""

from vector_store import collection
from database import SessionLocal, DocumentModel, PageModel


def diagnostiquer_document(nom_partiel: str):
    session = SessionLocal()
    documents = session.query(DocumentModel).filter(DocumentModel.filename.like(f"%{nom_partiel}%")).all()

    if not documents:
        print(f"Aucun document trouvé contenant '{nom_partiel}' dans son nom.")
        return

    for doc in documents:
        print(f"\n=== Document id={doc.id} : {doc.filename} ===")
        print(f"Statut : {doc.status} | Marque : {doc.brand} | Pages en base (MySQL) : {doc.page_count}")

        pages = session.query(PageModel).filter_by(document_id=doc.id).all()
        print(f"Nombre de pages réellement en base : {len(pages)}")
        for p in pages:
            texte_apercu = (p.raw_text or "").strip()[:100]
            print(f"  - Page {p.page_number} | Catégorie : {p.category} | Texte extrait ({len(p.raw_text or '')} caractères) : \"{texte_apercu}\"")

        # Vérifier ce qui est réellement dans Chroma pour ce document
        resultats = collection.get(where={"document_id": doc.id})
        nombre_chunks = len(resultats.get("ids", []))
        print(f"Nombre de morceaux indexés dans Chroma pour ce document : {nombre_chunks}")
        if nombre_chunks > 0:
            print("Aperçu des morceaux indexés :")
            for texte in resultats.get("documents", [])[:5]:
                print(f"  -> \"{texte[:150]}\"")

    session.close()


if __name__ == "__main__":
    nom = input("Nom (ou partie du nom) du document à diagnostiquer : ")
    diagnostiquer_document(nom)