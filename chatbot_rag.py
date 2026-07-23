from sqlalchemy.orm import Session
from langchain_community.llms import Ollama
from langchain_core.prompts import PromptTemplate
from database import SessionLocal, PageModel 

def repondre_question_techpack(document_id: int, categorie: str, question: str, model_name: str = "llama3:8b") -> str:
    db: Session = SessionLocal()
    try:
        # 1. RETRIEVAL : Extraction du texte MySQL filtré par ID et Catégorie
        pages = db.query(PageModel).filter(
            PageModel.document_id == document_id,
            PageModel.category == categorie
        ).all()

        if not pages:
            return f"Aucune page trouvée pour la catégorie '{categorie}' dans ce document."

        contexte_texte = "\n\n".join([page.raw_text for page in pages if page.raw_text])

        if not contexte_texte.strip():
            return f"Le texte extrait de la catégorie '{categorie}' est vide ou illisible."

        # 2. AUGMENTATION : Injection du contexte dans le Prompt
        prompt_template = PromptTemplate.from_template(
            """Tu es un assistant expert en dossiers techniques textiles (Tech Packs).
Réponds à la question de manière précise en te basant UNIQUEMENT sur le contexte fourni ci-dessous.
Si la réponse ne figure pas dans le contexte, indique simplement que la donnée n'est pas disponible.

--- CONTEXTE DU TECH PACK (Document {doc_id} - Catégorie: {categorie}) ---
{contexte}

--- QUESTION ---
{question}

--- RÉPONSE ---"""
        )

        prompt_final = prompt_template.format(
            doc_id=document_id,
            categorie=categorie,
            contexte=contexte_texte,
            question=question
        )

        # 3. GENERATION : Appel d'Ollama via LangChain
        llm = Ollama(model=model_name, temperature=0.1)
        reponse = llm.invoke(prompt_final)
        
        return reponse

    except Exception as e:
        return f"Erreur RAG : {str(e)}"
    finally:
        db.close()


if __name__ == "__main__":
    # Test ciblé sur le Document 8
    DOC_ID = 8
    CATEGORIE = "Measurement Sheet"
    QUESTION = "Quelles sont les mesures ou spécifications principales indiquées ?"

    print(f"🔍 Interrogation de MySQL pour le document {DOC_ID} [{CATEGORIE}]...")
    print(f"❓ Question : {QUESTION}\n")
    
    resultat = repondre_question_techpack(document_id=DOC_ID, categorie=CATEGORIE, question=QUESTION)
    
    print("🤖 --- Réponse du Chatbot ---")
    print(resultat)