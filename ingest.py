import os
import pdfplumber
from pdf2image import convert_from_path

def decouper_tech_pack(pdf_path, output_base_dir="dataset_brut"):
    """
    Prend un PDF de Tech Pack, extrait le texte et l'image de chaque page,
    et les stocke dans un dossier dédié au document.
    """
    # 1. Extraire le nom du fichier sans l'extension pour créer un sous-dossier propre
    nom_fichier = os.path.splitext(os.path.basename(pdf_path))[0]
    dossier_destination = os.path.join(output_base_dir, nom_fichier)
    
    # Créer les dossiers s'ils n'existent pas
    os.makedirs(dossier_destination, exist_ok=True)
    print(f"Début du traitement pour : {nom_fichier}")
    print(f"Les résultats seront enregistrés dans : {dossier_destination}")

    # 2. Conversion du PDF en images (une image par page)
    # dpi=200 garantit une excellente qualité pour l'affichage web et l'IA
    print("Extraction des images en cours (conversion en PNG)...")
    images = convert_from_path(pdf_path, dpi=200)

    # 3. Ouverture du PDF avec pdfplumber pour l'extraction de texte
    print("Extraction du texte en cours...")
    with pdfplumber.open(pdf_path) as pdf:
        # On boucle sur chaque page (on utilise enumerate pour avoir le numéro de l'index)
        for index, page in enumerate(pdf.pages):
            numero_page = index + 1
            print(f" -> Traitement de la Page {numero_page}/{len(pdf.pages)}...")

            # --- A. Extraction et sauvegarde du texte ---
            texte_brut = page.extract_text()
            chemin_texte = os.path.join(dossier_destination, f"page_{numero_page}.txt")
            
            with open(chemin_texte, "w", encoding="utf-8") as f_txt:
                # Si la page n'a pas de texte (juste une image), on écrit un indicateur
                if texte_brut:
                    f_txt.write(texte_brut)
                else:
                    f_txt.write("[Page vide ou contenant uniquement un dessin/schéma]")

            # --- B. Sauvegarde de l'image correspondante ---
            chemin_image = os.path.join(dossier_destination, f"page_{numero_page}.png")
            images[index].save(chemin_image, "PNG")

    print(f"Succès ! Le Tech Pack '{nom_fichier}' a été entièrement découpé.\n")

# --- ZONE DE TEST EN LOCAL ---
if __name__ == "__main__":
    # Créez un dossier 'tech_packs_tests' à côté de votre script et mettez-y vos PDF
    # Remplacez le nom du fichier ci-dessous par l'un de vos exemples (Guess, Hugo...)
    EXEMPLE_PDF = "211903413TOYAMAWASHWESTERNSHIRTJACKE_001Spec_DENIMHOUSE_1123_001.pdf" 
    
    if os.path.exists(EXEMPLE_PDF):
        decouper_tech_pack(EXEMPLE_PDF)
    else:
        print(f"Veuillez placer le fichier '{EXEMPLE_PDF}' dans le même dossier ou modifier le chemin.")

#c'est le code qui prend un pdf et cree un dossier dans dataset_brut sous le meme nom et met les photos dans des pdf et les textes brutes dans des fichiers textes de chaque page 