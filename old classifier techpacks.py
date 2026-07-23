import requests  # Permet d'envoyer des requêtes HTTP à l'API Ollama
import base64    # Permet d'encoder l'image PNG en texte Base64 lisible par l'API
from PIL import Image  # Permet d'ouvrir et manipuler l'image
import io        # Fournit une mémoire tampon temporaire pour la conversion de l'image
import json      # Permet de décoder la réponse JSON structurée reçue de l'IA
import os        # Permet de vérifier l'existence des fichiers sur le disque
import re        # Permet le matching par mots-clés avec limites de mot (\b)
from typing import Optional, Tuple  # Utilisé pour typer proprement les retours de fonctions

# --- CONFIGURATION DE L'API OLLAMA ---
OLLAMA_API_URL = "http://localhost:11434/api/generate"

# Liste stricte des catégories autorisées pour l'industrie textile
CLASSIFICATION_OPTIONS = [
    "BOM",
    "Measurement Sheet",
    "Technical Sketch",
    "Artwork",
    "Fabric Information",
    "Trims & Accessories",
    "Packaging",
    "Labels",
    "Sewing Instructions",
    "Colorways",
    "Autres documents techniques"
]

# --- DICTIONNAIRE DE MOTS-CLES PONDÉRÉ PAR CATEGORIE ---
# Chaque mot-clé a un poids : 2 pour une expression distinctive (peu de faux positifs),
# 1 pour un mot générique (peut apparaître dans plusieurs catégories, donc moins fiable seul).
KEYWORDS = {
    "Measurement Sheet": {
        "strong": [
            ("size spec", 2), ("grading", 2), ("tolerance", 2), ("point of measure", 2),
            ("pom", 2), ("chest measurement", 2), ("waist measurement", 2), ("inseam", 2),
            ("req meas", 2), ("vendor meas", 2), ("graded spec", 2), ("grade rules", 2),
        ],
        "size_columns": [r"\bxs\b", r"\bs\b", r"\bm\b", r"\bl\b", r"\bxl\b",
                          r"\b28\b", r"\b30\b", r"\b32\b", r"\b34\b", r"\b36\b", r"\b38\b"]
    },
    "BOM": {
        "strong": [
            ("bill of materials", 3), ("component location", 3), ("material id", 3),
            ("trim card", 2), ("supplier", 1), ("composition", 1), ("consumption", 1),
            ("fabric", 0.5), ("cotton", 0.5), ("polyester", 0.5),
        ],
    },
    "Technical Sketch": {
        "strong": [
            ("detail sketch", 3), ("front view", 2), ("back view", 2),
            ("construction detail", 2), ("cad sketch", 2), ("flat sketch", 2),
            ("technical drawing", 2), ("construction", 1),
        ],
    },
    "Artwork": {
        "strong": [
            ("print placement", 2), ("embroidery", 2), ("screen print", 2),
            ("artwork design", 2), ("graphic placement", 2), ("positioning", 1),
            ("technique embroidery", 2), ("artwork", 1),
        ],
    },
    "Fabric Information": {
        "strong": [
            ("tensile strength", 3), ("washing test", 2), ("shrinkage", 2), ("gsm", 2),
            ("weave", 1), ("colorfastness", 2), ("fabric test", 2),
        ],
    },
    "Trims & Accessories": {
        "strong": [
            ("zipper", 2), ("rivet", 2), ("eyelet", 2), ("velcro", 2), ("slider", 1),
            ("elastic tape", 2), ("trim detail", 2), ("customization", 1),
        ],
    },
    "Packaging": {
        "strong": [
            ("polybag code", 3), ("folding instructions", 2), ("shipping mark", 2),
            ("master pack", 2), ("carton", 1), ("polybag", 1), ("packing of", 2),
            ("fold the sleeves", 2), ("insert in the polybag", 2), 
        ],
    },
    "Labels": {
        "strong": [
            ("main label", 2), ("care label", 2), ("hangtag", 2), ("size label", 2),
            ("barcode", 1), ("waist tag", 2), ("fit label", 2), ("inch label", 2),
            ("fold line", 1), ("additional tag", 2), ("stitched with", 1),
        ],
    },
    "Sewing Instructions": {
        "strong": [
            ("spi", 1), ("seam allowance", 2), ("hemming", 1), ("overlock", 2),
            ("stitches per inch", 2), ("construction set", 2), ("thread page", 2),
        ],
    },
    "Colorways": {
        "strong": [
            ("color proposal", 3), ("colorway", 2), ("pantone", 2), ("color code", 2),
            ("assortment", 1), ("tpg", 1),
        ],
    },
}
COVER_PAGE_EXPLICIT_MARKER = "cover page"
SOFTWARE_REPORT_MARKERS = ["lectra", "aama", "esportazione", "tacche eliminate"]# lorsque le texte contient un de ces mots, le programme sait immédiatement que 
#Cette page n'appartient à aucune catégorie métier.Elle sera directement classée comme :Autres documents techniques Le programme évite ainsi d'appeler inutilement l'IA.
# cette liste contient toutes les marques que vous traitez habituellement.
KNOWN_BRANDS = [
    "RALPH LAUREN", "HUGO BOSS", "GUESS", "TOMMY HILFIGER", "CALVIN KLEIN",
    "LEVI'S", "GAP", "NIKE", "ADIDAS", "ZARA", "H&M", "UNIQLO",
    "LACOSTE", "BURBERRY", "GUCCI", "PRADA",
    "GAS", "5TATE OF MIND", "STATE OF MIND",
]
def classify_by_text(text_content: str, page_number: Optional[int] = None) -> Tuple[Optional[str], float]:
    """
    Classification textuelle par score de mots-clés.
    page_number est optionnel : s'il est fourni, la règle Cover Page ne se
    déclenche que si le terme est explicitement présent ET que ce n'est pas
    une répétition d'en-tête sur une page > 1 (les templates comme Ralph Lauren
    répètent souvent des champs administratifs sur chaque page).
    Renvoie (categorie, score) ou (None, 0) si le résultat est ambigu.
    """
    text_lower = re.sub(r'\s+', ' ', text_content.lower()).strip()  #r'\s+' tous les espaces, tabulations ou retours à la ligne sont remplaces par un seul espace 
    #.strip() Elle supprime les espaces au début et à la fin.

    if any(marker in text_lower for marker in SOFTWARE_REPORT_MARKERS):   #Est-ce qu'au moins un des mots de la liste apparaît dans le texte ?
        return "Autres documents techniques", 98

    if "sample evaluation image" in text_lower:  #Est-ce que cette expression existe ?
        return "Autres documents techniques", 96

    if COVER_PAGE_EXPLICIT_MARKER in text_lower:
        if page_number is None or page_number == 1:
            return "Autres documents techniques", 99

    # --- Scoring pondéré avec limite de mot stricte (\b) ---
    # Chaque mot-clé rapporte son poids (2-3 pour distinctif, 0.5-1 pour générique)
    # au lieu d'un point fixe -> "fabric" seul ne suffit plus à classer en BOM.
    scores = {}
    for category, rules in KEYWORDS.items():
        score = 0.0
        for kw, poids in rules.get("strong", []):
            if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                score += poids
        scores[category] = score

    # Bonus Measurement Sheet uniquement si au moins 3 colonnes de tailles distinctes
    # ET qu'un mot-clé de mesure est déjà présent (évite un faux positif basé uniquement
    size_cols_found = sum(1 for pattern in KEYWORDS["Measurement Sheet"]["size_columns"]
                           if re.search(pattern, text_lower))
    if size_cols_found >= 3 and scores["Measurement Sheet"] > 0:
        scores["Measurement Sheet"] += 2

    sorted_scores = sorted(scores.values(), reverse=True)
    best_category = max(scores, key=scores.get)
    best_score = sorted_scores[0]
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0

    if best_score >= 2 and (best_score - second_score) >= 1:
        return best_category, best_score

    if len(text_lower) < 100:
        return "Autres documents techniques", 97

    return None, 0


#EXTRACTION DE LA MARQUE PAR TEXTE (rapide, fiable)

def extract_brand_by_text(text_content: str) -> Optional[str]:
    """
    Cherche la marque directement dans le texte extrait (OCR).
    Beaucoup plus fiable que la vision quand le nom est écrit en toutes lettres.
    """
    # NORMALISATION : même logique que pour la catégorie -> évite qu'un saut de ligne
    # au milieu du nom de marque ("5TATE\nOF MIND") empêche la détection.
    text_upper = re.sub(r'\s+', ' ', text_content.upper()).strip()

    for brand in KNOWN_BRANDS:
        pattern = r'\s+'.join(re.escape(mot) for mot in brand.split())
        if re.search(pattern, text_upper):
            return brand

    match = re.search(r'PROPERTY OF ([A-Z\s]+?)\s+(CORPORATION|CORP|INC|LTD)', text_upper)#il veut trouver PROPERTY OF puis des lettres majuscules et des espaces
    #puis CORPORATION ou CORP  ou INC ou LTD
    if match:
        return match.group(1).strip() #si on trouve RALPH LAUREN CORP ; group(1) est Ral.. et groupe(2) est CORP et strip pour enlever les espaces du deb et de fin

    return None
# FALLBACK VISION (uniquement si le texte échoue)
def encode_image_to_base64(image_path: str) -> Optional[str]:
    """
    Ouvre une image sur le disque et la convertit en une chaîne de texte Base64
    afin qu'elle puisse être transmise dans la requête JSON vers Ollama.
    """
    if not os.path.exists(image_path):
        print(f"Erreur : L'image n'existe pas : {image_path}")
        return None
    try:
        with Image.open(image_path) as img:
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"Erreur lors de l'encodage de l'image : {e}")
        return None


def classify_by_vision(image_path: str, text_content: str) -> str:
    """
    Fallback vision : appelé UNIQUEMENT si le texte n'a pas donné de réponse fiable.
    Prompt volontairement court et focalisé sur une seule tâche pour maximiser
    les chances que LLaVA suive réellement les instructions.
    """
    base64_image = encode_image_to_base64(image_path)
    if not base64_image:
        return "Autres documents techniques"

    prompt = f"""Tu regardes une page de Tech Pack textile. Choisis UNE SEULE catégorie parmi cette liste exacte :
{", ".join(CLASSIFICATION_OPTIONS)}

Règle clé : un grand tableau avec des colonnes de tailles (S, M, L, XL, 32, 34...) = "Measurement Sheet".
Un grand tableau qui liste des tissus/fournisseurs/fournitures sans tailles = "BOM".
Une page de garde avec peu de contenu central (juste des références, un titre, un numéro de board) = "Autres documents techniques".

Texte visible sur la page : "{text_content[:500]}"

Réponds uniquement avec ce JSON, rien d'autre :
{{"category": "..."}}"""

    payload = {
        "model": "llava",
        "prompt": prompt,
        "images": [base64_image],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 42}
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=300)
        if response.status_code == 200:
            result = response.json()
            data = json.loads(result.get("response", "{}"))
            category = data.get("category", "Autres documents techniques")
            return category if category in CLASSIFICATION_OPTIONS else "Autres documents techniques"
        else:
            print(f"Erreur API Ollama (Code {response.status_code})")
    except Exception as e:
        print(f"Erreur lors du traitement vision (catégorie) : {e}")

    return "Autres documents techniques"


def extract_brand_by_vision(image_path: str, text_content: str) -> str:
    """
    Fallback vision pour la marque, appelé UNIQUEMENT si le texte n'a rien trouvé
    (ex: la marque n'apparaît que dans un logo, sans texte OCR correspondant).
    """
    base64_image = encode_image_to_base64(image_path)
    if not base64_image:
        return "Inconnu"

    prompt = f"""Trouve le nom de la marque de vêtements propriétaire de ce document (ex: RALPH LAUREN, HUGO BOSS, GUESS).
Ne confonds JAMAIS la marque avec le nom d'une usine ou d'un fournisseur.
Des mots comme "Factory", "Mills", "Denim House", "Ltd", "Sourcing" indiquent un fournisseur ou un site, PAS une marque.

Texte de la page : "{text_content[:500]}"

Réponds uniquement avec ce JSON :
{{"brand": "NOM_EN_MAJUSCULES ou INCONNU"}}"""

    payload = {
        "model": "llava",
        "prompt": prompt,
        "images": [base64_image],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 42}
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=300)
        if response.status_code == 200:
            result = response.json()
            data = json.loads(result.get("response", "{}"))
            brand_brute = data.get("brand", "Inconnu").upper().strip()

            # FILTRE ANTI-HALLUCINATION : LLaVA confond parfois un titre de page
            # (ex: "INCH LABEL MAN-WOMAN") avec une marque. On rejette tout résultat
            # trop long ou contenant des mots typiques de titre/section plutôt qu'un nom.
            mots_suspects = ["LABEL", "SIZE", "CODE", "STYLE", "MAN-WOMAN", "SHEET",
                              "SKETCH", "INSTRUCTION", "PAGE", "DETAIL"]
            trop_long = len(brand_brute.split()) > 4
            contient_mot_suspect = any(mot in brand_brute for mot in mots_suspects)
            if trop_long or contient_mot_suspect:
                return "Inconnu"

            return brand_brute
        else:
            print(f"Erreur API Ollama (Code {response.status_code})")
    except Exception as e:
        print(f"Erreur lors du traitement vision (marque) : {e}")

    return "Inconnu"
def classify_tech_pack_page(image_path: str, text_content: str, page_number: Optional[int] = None) -> Tuple[str, str]:
    if not os.path.exists(image_path):
        print(f"Erreur : L'image n'existe pas : {image_path}")
        return "Autres documents techniques", "Inconnu"

    # --- Catégorie ---
    category, score = classify_by_text(text_content, page_number)
    if category is None:
        print(f"[INFO] Texte ambigu -> fallback vision pour {os.path.basename(image_path)}")
        category = classify_by_vision(image_path, text_content)
    else:
        print(f"[INFO] Classifié par texte : {category} (score={score})")

    # --- Marque ---
    brand = extract_brand_by_text(text_content)
    if brand is None:
        print("[INFO] Marque non trouvée par texte -> fallback vision")
        brand = extract_brand_by_vision(image_path, text_content)

    brand = (brand or "Inconnu").upper().strip()

    print(f"[IA Décision] Catégorie : '{category}' | Marque détectée : '{brand}'")
    return category, brand