import requests  # Permet d'envoyer des requêtes HTTP à l'API Ollama
import base64    # Permet d'encoder l'image PNG en texte Base64 lisible par l'API
from PIL import Image  # Permet d'ouvrir et manipuler l'image
import io        # Fournit une mémoire tampon temporaire pour la conversion de l'image
import json      # Permet de décoder la réponse JSON structurée reçue de l'IA
import os        # Permet de vérifier l'existence des fichiers sur le disque
import re        # Permet le matching par mots-clés avec limites de mot (\b)
from typing import Optional, Tuple, List  # Utilisé pour typer proprement les retours de fonctions
import mysql.connector  # Permet de se connecter à la base MySQL pour la mémoire apprise et la file de confirmation

# --- CONFIGURATION DE L'API OLLAMA ---
OLLAMA_API_URL = "http://localhost:11434/api/generate"

# --- CONFIGURATION MYSQL ---
# CHANGEMENT #13 : ces valeurs sont maintenant alignées EXACTEMENT sur celles de
# database.py (mysql+pymysql://myuser:mypassword@localhost:3307/techpacks_db).
# Avant, ce dictionnaire utilisait des valeurs différentes (port par défaut 3306,
# utilisateur "root", base "techpack_analyzer") -- ce qui aurait empêché toute
# connexion, puisque le conteneur Docker MySQL écoute sur le port 3307, avec un
# utilisateur et une base différents. Les deux fichiers doivent TOUJOURS pointer
# vers la même base pour que la mémoire apprise et la file de confirmation
# fonctionnent correctement.
DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "myuser",
    "password": "mypassword",
    "database": "techpacks_db",
}


def get_db_connection():
    """Ouvre une connexion à la base MySQL. À appeler à chaque fonction qui a besoin de la base."""
    return mysql.connector.connect(**DB_CONFIG)


# ============================================================
# CHANGEMENT #10 : mémoire apprise des associations nom -> marque
# ------------------------------------------------------------
# EXPLICATION SIMPLE : quand quelqu'un confirme manuellement qu'un
# dossier contenant "guidelines_denim" dans son nom est de la marque
# GAS, on retient cette info dans une table. La prochaine fois qu'un
# nouveau dossier contient ce même motif dans son nom, on retrouve
# directement la marque sans avoir besoin d'appeler l'IA du tout.
# Ce n'est PAS de l'intelligence artificielle ni de l'entraînement de
# modèle -- c'est une simple mémoire de correspondances, comme un
# carnet d'adresses.
# ============================================================
def chercher_marque_dans_memoire(nom_dossier: str) -> Optional[str]:
    """
    Vérifie si le nom du dossier correspond à un motif déjà appris.
    Retourne la marque si un motif connu est trouvé dans le nom, sinon None.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT motif_nom_fichier, marque FROM regles_marque_apprises")
        regles = cursor.fetchall()
        cursor.close()
        conn.close()

        nom_dossier_lower = nom_dossier.lower()
        for motif, marque in regles:
            if motif.lower() in nom_dossier_lower:
                print(f"[MEMOIRE] Motif '{motif}' trouvé dans '{nom_dossier}' -> marque : {marque}")
                return marque
        return None
    except Exception as e:
        print(f"[ERREUR] Impossible de consulter la mémoire apprise : {e}")
        return None


def ajouter_a_la_file_de_confirmation(techpack_id: int, nom_dossier: str):
    """
    Enregistre un document dont la marque n'a pas pu être détectée
    automatiquement, pour qu'un humain la confirme plus tard dans l'interface.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO marque_a_confirmer (techpack_id, nom_dossier, statut) VALUES (%s, %s, 'en_attente')",
            (techpack_id, nom_dossier)
        )
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[FILE D'ATTENTE] '{nom_dossier}' ajouté à la file de confirmation manuelle")
    except Exception as e:
        print(f"[ERREUR] Impossible d'ajouter à la file de confirmation : {e}")

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

# ============================================================
# CHANGEMENT #1 : dictionnaire de définitions visuelles par catégorie
# ------------------------------------------------------------
# POURQUOI : dans l'ancien code, le prompt vision de classify_by_vision()
# ne donnait une règle de distinction que pour 3 catégories sur 11
# (Measurement Sheet / BOM / Autres documents techniques). Pour les 8
# autres, LLaVA devait deviner sans aucun critère visuel -> c'est la
# cause principale des confusions observées dans l'évaluation
# (Technical Sketch <-> Sewing Instructions <-> Measurement Sheet,
# Labels <-> Technical Sketch <-> Autres documents techniques).
# On centralise ces définitions ici pour les réutiliser dans le prompt.
# ============================================================
CATEGORY_DEFINITIONS = {
    "BOM": "tableau listant tissus/fournitures/composants avec fournisseurs, sans mesures corporelles",
    "Measurement Sheet": "tableau de mesures avec points numérotés (POM) et colonnes de tailles (S,M,L,32,34...)",
    "Technical Sketch": "dessin technique du vêtement (silhouette avant/arrière), sans étapes de montage ni mesures",
    "Sewing Instructions": "étapes de montage/couture numérotées, souvent avec petits croquis d'assemblage",
    "Labels": "visuel d'étiquette à coudre (rectangle avec texte réglementaire, composition, taille)",
    "Trims & Accessories": "zoom sur fermetures, rivets, boutons, élastiques (accessoires physiques, pas de tableau)",
    "Fabric Information": "résultats de tests textile (résistance, rétrécissement, GSM, colorfastness)",
    "Artwork": "placement d'impression, broderie, motifs graphiques",
    "Colorways": "palette de couleurs, références Pantone, variantes de coloris",
    "Packaging": "instructions de pliage, cartons, étiquetage d'expédition",
    "Autres documents techniques": "page de garde, rapport logiciel (ex: Lectra), contenu non classifiable",
}

# --- DICTIONNAIRE DE MOTS-CLES PONDÉRÉ PAR CATEGORIE ---
# Chaque mot-clé a un poids : 2-3 pour une expression distinctive (peu de faux positifs),
# 1 ou moins pour un mot générique (peut apparaître dans plusieurs catégories, donc moins fiable seul).
#
# ============================================================
# CHANGEMENT #2 : mots-clés enrichis pour les catégories les plus faibles
# ------------------------------------------------------------
# POURQUOI : dans l'évaluation, "Sewing Instructions" n'avait que 6 mots-clés
# dont 4 à poids 1 seulement. Comme le seuil d'acceptation est
# best_score >= 2, un seul mot-clé faible ne suffisait presque jamais
# -> la page tombait presque systématiquement en fallback vision, qui
# elle-même manquait de guidage (voir CHANGEMENT #1). Résultat observé :
# 0/2 correctes sur Sewing Instructions. On ajoute des mots-clés plus
# nombreux et plus distinctifs pour que la classification texte (rapide
# et fiable) suffise plus souvent, sans avoir besoin de la vision.
# Idem pour Trims & Accessories et Fabric Information.
# ============================================================
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
        # AJOUT : "gsm value", "pilling", "colour fastness", "rub test" (variante orthographique),
        # "wash test" en plus de "washing test". Ces termes apparaissent souvent dans les
        # rapports de test tissu mais étaient absents de la liste initiale.
        "strong": [
            ("tensile strength", 3), ("washing test", 2), ("wash test", 2), ("shrinkage", 2),
            ("gsm", 2), ("gsm value", 2), ("weave", 1), ("colorfastness", 2),
            ("colour fastness", 2), ("fabric test", 2), ("pilling", 2), ("rub test", 2),
        ],
    },
    "Trims & Accessories": {
        # AJOUT : "button", "snap button", "drawcord", "cord lock", "trim sheet" -> ce sont
        # des composants physiques très fréquents dans les pages trims qui manquaient.
        "strong": [
            ("zipper", 2), ("rivet", 2), ("eyelet", 2), ("velcro", 2), ("slider", 1),
            ("elastic tape", 2), ("trim detail", 2), ("trim sheet", 2), ("customization", 1),
            ("button", 1.5), ("snap button", 2), ("drawcord", 2), ("cord lock", 2),
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
        # AJOUT : mots-clés plus distinctifs et à poids plus élevé pour que le score
        # dépasse enfin le seuil de 2 sans avoir besoin du fallback vision.
        "strong": [
            ("stitch type", 3), ("seam allowance", 2), ("overlock", 2), ("topstitch", 2),
            ("construction sequence", 3), ("assembly step", 2), ("thread count", 2),
            ("stitches per inch", 2), ("construction set", 2), ("thread page", 2),
            ("spi", 1), ("hemming", 1),
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
SOFTWARE_REPORT_MARKERS = ["lectra", "aama", "esportazione", "tacche eliminate"]
# lorsque le texte contient un de ces mots, le programme sait immédiatement que
# cette page n'appartient à aucune catégorie métier. Elle sera directement classée comme :
# "Autres documents techniques". Le programme évite ainsi d'appeler inutilement l'IA.

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
    text_lower = re.sub(r'\s+', ' ', text_content.lower()).strip()

    if any(marker in text_lower for marker in SOFTWARE_REPORT_MARKERS):
        return "Autres documents techniques", 98

    if "sample evaluation image" in text_lower:
        return "Autres documents techniques", 96

    if COVER_PAGE_EXPLICIT_MARKER in text_lower:
        if page_number is None or page_number == 1:
            return "Autres documents techniques", 99

    scores = {}
    for category, rules in KEYWORDS.items():
        score = 0.0
        for kw, poids in rules.get("strong", []):
            if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                score += poids
        scores[category] = score

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


def extract_brand_by_text(text_content: str) -> Optional[str]:
    """
    Cherche la marque directement dans le texte extrait (OCR).
    Beaucoup plus fiable que la vision quand le nom est écrit en toutes lettres.
    Inchangé : cette fonction n'était pas en cause dans les erreurs observées.
    """
    text_upper = re.sub(r'\s+', ' ', text_content.upper()).strip()

    for brand in KNOWN_BRANDS:
        pattern = r'\s+'.join(re.escape(mot) for mot in brand.split())
        if re.search(pattern, text_upper):
            return brand

    match = re.search(r'PROPERTY OF ([A-Z\s]+?)\s+(CORPORATION|CORP|INC|LTD)', text_upper)
    if match:
        return match.group(1).strip()

    return None


def encode_image_to_base64(image_path: str) -> Optional[str]:
    """
    Ouvre une image sur le disque et la convertit en une chaîne de texte Base64
    afin qu'elle puisse être transmise dans la requête JSON vers Ollama.
    Inchangé.
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


# ============================================================
# CHANGEMENT #8 (suite) : fonctions de parsing "tolérantes"
# ------------------------------------------------------------
# EXPLICATION SIMPLE : imagine que tu demandes à quelqu'un de remplir une
# fiche avec une seule case "brand: ...". Parfois il répond correctement.
# Parfois il écrit la mauvaise étiquette sur la case, ou oublie de fermer
# sa phrase. Avant, dès que la fiche n'était pas parfaite, on la jetait
# entièrement à la poubelle (json.loads() plantait -> exception -> valeur
# par défaut). Maintenant, si la fiche est mal remplie, on cherche quand
# même le mot qu'on veut dedans avec une recherche de motif (regex),
# comme si on cherchait "brand" ou "category" au milieu d'une phrase mal
# ponctuée, plutôt que d'exiger une fiche parfaitement carrée.
# ============================================================
def parse_category_response(raw_text: str) -> str:
    """Extrait la catégorie d'une réponse JSON, même si elle est mal formée."""
    try:
        data = json.loads(raw_text)
        return data.get("category", "Autres documents techniques")
    except (json.JSONDecodeError, AttributeError):
        # Le JSON est cassé -> on cherche quand même "category": "..." dans le texte brut
        match = re.search(r'"category"\s*:\s*"([^"]+)"', raw_text)
        if match:
            return match.group(1)
        print(f"[DEBUG] Impossible d'extraire la catégorie de la réponse brute : {raw_text[:200]}")
        return "Autres documents techniques"


def parse_brand_response(raw_text: str) -> str:
    """Extrait la marque d'une réponse JSON, même si elle est mal formée."""
    try:
        data = json.loads(raw_text)
        return data.get("brand", "Inconnu").upper().strip()
    except (json.JSONDecodeError, AttributeError):
        # Le JSON est cassé -> on cherche quand même "brand": "..." dans le texte brut
        match = re.search(r'"brand"\s*:\s*"([^"]+)"', raw_text)
        if match:
            return match.group(1).upper().strip()
        print(f"[DEBUG] Impossible d'extraire la marque de la réponse brute : {raw_text[:200]}")
        return "Inconnu"


def classify_by_vision(image_path: str, text_content: str) -> str:
    """
    Fallback vision : appelé UNIQUEMENT si le texte n'a pas donné de réponse fiable.

    ============================================================
    CHANGEMENT #3 : prompt enrichi avec une définition pour CHAQUE catégorie
    ------------------------------------------------------------
    POURQUOI : voir CHANGEMENT #1. On construit maintenant dynamiquement
    la liste des catégories + leur définition visuelle à partir de
    CATEGORY_DEFINITIONS, au lieu de ne donner une règle que pour 3
    catégories sur 11. Ça donne à LLaVA un critère de décision pour
    chaque option, ce qui doit réduire les confusions Technical Sketch /
    Sewing Instructions / Measurement Sheet / Labels observées dans
    la matrice de confusion de l'évaluation.
    ============================================================
    """
    base64_image = encode_image_to_base64(image_path)
    if not base64_image:
        return "Autres documents techniques"

    # On construit la liste "- Categorie: definition" pour chaque catégorie connue
    definitions_txt = "\n".join(
        f"- {cat}: {CATEGORY_DEFINITIONS[cat]}" for cat in CLASSIFICATION_OPTIONS
    )

    prompt = f"""Tu regardes une page de Tech Pack textile. Choisis UNE SEULE catégorie parmi cette liste exacte :

{definitions_txt}

Texte visible sur la page : "{text_content[:500]}"

Réponds uniquement avec ce JSON, rien d'autre :
{{"category": "..."}}"""

    # ============================================================
    # CHANGEMENT #7 : nom du modèle corrigé + keep_alive + timeout augmenté
    # ------------------------------------------------------------
    # POURQUOI : le payload appelait encore "llava" alors que tu es passé à
    # BakLLaVA -> Ollama renvoyait une erreur 404 (modèle introuvable dans
    # l'ID exact attendu). On utilise maintenant "bakllava:latest", le nom
    # exact tel qu'affiché par `ollama list`.
    # "keep_alive": "30m" dit à Ollama de garder le modèle chargé en mémoire
    # pendant 30 minutes après chaque appel, au lieu de le décharger et de
    # devoir le recharger à zéro à chaque nouvelle page -> beaucoup plus rapide.
    # Le timeout passe de 300s (5 min) à 600s (10 min) car BakLLaVA est plus
    # lourd et plus lent que LLaVA, surtout sur les premiers appels.
    # ============================================================
    payload = {
        "model": "bakllava:latest",
        "prompt": prompt,
        "images": [base64_image],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 42},
        "keep_alive": "30m"
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=600)
        if response.status_code == 200:
            result = response.json()
            # ============================================================
            # CHANGEMENT #8 : parsing JSON tolérant aux réponses mal formées
            # ------------------------------------------------------------
            # POURQUOI : BakLLaVA respecte moins bien le format JSON strict que
            # LLaVA (ex: réponse coupée, mauvaise clé). Avant, un json.loads()
            # qui échouait faisait perdre TOUTE la réponse, même si elle
            # contenait une info exploitable. On utilise maintenant une
            # fonction de secours (voir plus bas) qui essaie d'abord le JSON
            # propre, puis une recherche par motif si le JSON est cassé.
            # ============================================================
            category = parse_category_response(result.get("response", "{}"))
            return category if category in CLASSIFICATION_OPTIONS else "Autres documents techniques"
        else:
            print(f"Erreur API Ollama (Code {response.status_code})")
    except Exception as e:
        print(f"Erreur lors du traitement vision (catégorie) : {e}")
        # CHANGEMENT #6 (voir plus bas) : log de la réponse brute pour debug,
        # même en cas d'exception (ex: JSON mal formé renvoyé par LLaVA).
        try:
            print(f"[DEBUG] Réponse brute Ollama (catégorie) : {result.get('response', 'AUCUNE')}")
        except Exception:
            print("[DEBUG] Aucune réponse HTTP exploitable reçue.")

    return "Autres documents techniques"


def extract_brand_by_vision(image_path: str, text_content: str) -> str:
    """
    Fallback vision pour la marque, appelé UNIQUEMENT si le texte n'a rien trouvé
    (ex: la marque n'apparaît que dans un logo, sans texte OCR correspondant).

    ============================================================
    CHANGEMENT #4 : la liste KNOWN_BRANDS est maintenant injectée dans le prompt
    ------------------------------------------------------------
    POURQUOI : l'ancien prompt ne donnait que 3 exemples de marques dans une
    phrase ("ex: RALPH LAUREN, HUGO BOSS, GUESS"), ce qui forçait LLaVA à
    deviner en lecture libre. Une tâche de reconnaissance sur liste fermée
    est beaucoup plus fiable pour un modèle vision qu'une tâche de lecture
    libre. On donne maintenant la liste complète des marques clientes.
    ============================================================
    """
    base64_image = encode_image_to_base64(image_path)
    if not base64_image:
        return "Inconnu"

    # ============================================================
    # CHANGEMENT #9 : consigne anti-invention ("anti-hallucination")
    # ------------------------------------------------------------
    # EXPLICATION SIMPLE : avant, le modèle se comportait un peu comme
    # quelqu'un qui répond "Levi's" à la question "quelle marque ?" juste
    # parce que la page parle de denim -> il devine à partir du SUJET du
    # document, pas de ce qu'il voit vraiment écrit ou dessiné. On lui
    # interdit maintenant explicitement de faire ce raisonnement, et on
    # lui rappelle qu'il a le droit de répondre "je ne sais pas" -- ce
    # n'est pas un échec, c'est la bonne réponse s'il n'est pas sûr.
    # ============================================================
    prompt = f"""Trouve le nom de la marque de vêtements propriétaire de ce document.

Marques possibles (si tu reconnais l'une d'elles, réponds EXACTEMENT ce nom) :
{", ".join(KNOWN_BRANDS)}

Si tu vois un logo ou un nom de marque qui ne figure pas dans cette liste, réponds quand
même le nom que tu lis. Si aucun logo ni nom de marque n'est visible sur l'image
(ex: la page ne contient qu'un schéma technique ou un tableau), réponds "INCONNU".

RÈGLE IMPORTANTE : base ta réponse UNIQUEMENT sur un logo ou un nom que tu vois
RÉELLEMENT écrit ou dessiné sur l'image. Ne devine JAMAIS la marque à partir du
sujet ou du type de vêtement (ex: ce n'est pas parce que la page parle de "denim"
ou de "jean" que la marque est forcément Levi's). Si tu hésites entre plusieurs
marques ou que tu n'es pas certain d'avoir vu un logo clair, réponds "INCONNU" --
c'est une réponse acceptée et préférable à une supposition.

Ne confonds JAMAIS la marque avec le nom d'une usine ou d'un fournisseur.
Des mots comme "Factory", "Mills", "Denim House", "Ltd", "Sourcing" indiquent un fournisseur
ou un site, PAS une marque.

Texte de la page : "{text_content[:500]}"

Réponds uniquement avec ce JSON :
{{"brand": "NOM_EN_MAJUSCULES ou INCONNU"}}"""

    # Même correction #7 que pour la catégorie : bon nom de modèle, keep_alive, timeout augmenté
    payload = {
        "model": "bakllava:latest",
        "prompt": prompt,
        "images": [base64_image],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 42},
        "keep_alive": "30m"
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=600)
        if response.status_code == 200:
            result = response.json()
            # Même correction #8 que pour la catégorie : parsing tolérant
            brand_brute = parse_brand_response(result.get("response", "{}"))

            mots_suspects = ["LABEL", "SIZE", "CODE", "STYLE", "MAN-WOMAN", "SHEET",
                              "SKETCH", "INSTRUCTION", "PAGE", "DETAIL"]
            trop_long = len(brand_brute.split()) > 4
            contient_mot_suspect = any(mot in brand_brute for mot in mots_suspects)

            # ============================================================
            # CHANGEMENT #6 : log explicite quand le filtre anti-hallucination rejette
            # une réponse. Dans l'ancien code, ce rejet était silencieux -> impossible
            # de savoir si LLaVA voyait vraiment le logo ou si c'est le filtre qui
            # a jeté une réponse potentiellement valide. Ce log permet de diagnostiquer
            # rapidement en 5 minutes sur un petit échantillon de pages.
            # ============================================================
            if trop_long or contient_mot_suspect:
                print(f"[DEBUG] Marque rejetée par filtre anti-hallucination : "
                      f"'{brand_brute}' (trop_long={trop_long}, mot_suspect={contient_mot_suspect})")
                return "Inconnu"

            return brand_brute
        else:
            print(f"Erreur API Ollama (Code {response.status_code})")
    except Exception as e:
        print(f"Erreur lors du traitement vision (marque) : {e}")
        try:
            print(f"[DEBUG] Réponse brute Ollama (marque) : {result.get('response', 'AUCUNE')}")
        except Exception:
            print("[DEBUG] Aucune réponse HTTP exploitable reçue.")

    return "Inconnu"


# ============================================================
# CHANGEMENT #5 (LE PLUS IMPORTANT) : détection de marque au niveau DOCUMENT,
# plus au niveau PAGE.
# ------------------------------------------------------------
# POURQUOI : c'était la cause racine de la quasi-totalité des 23 erreurs
# de marque dans l'évaluation. Dans un Tech Pack, le logo de la marque
# apparaît en général une seule fois, sur la page de garde. En demandant
# à LLaVA de chercher un logo sur CHAQUE page (y compris des pages de
# guidelines ou de schémas sans aucun logo), on lui demandait de trouver
# quelque chose qui n'existe simplement pas sur l'image -> il ne pouvait
# que répondre INCONNU. La preuve dans les résultats : dès qu'une page 1
# d'un dossier échouait à trouver la marque, TOUTES les pages suivantes
# du même dossier échouaient aussi (ex: les 5 pages de 568336_01_COACHJACKET,
# les 15 pages de 583132_guidelines_denim_ss24).
#
# La correction : on traite un dossier de Tech Pack comme une unité.
# On cherche la marque uniquement sur les premières pages (là où elle a
# le plus de chances d'être visible), puis on propage ce résultat unique
# à TOUTES les pages du même dossier, au lieu de relancer une détection
# par page.
# ============================================================
def extract_brand_for_document(pages: List[Tuple[str, str]], nom_dossier: str = "", max_pages_to_check: int = 3) -> str:
    """
    Détecte la marque UNE SEULE FOIS pour tout un dossier de Tech Pack.

    pages : liste ordonnée de tuples (image_path, text_content) pour TOUTES
            les pages du même document/dossier (page 1 en premier).
    nom_dossier : nom du dossier/document, utilisé pour vérifier la mémoire apprise.
    max_pages_to_check : nombre de pages à inspecter avant d'abandonner
            (la marque est presque toujours sur les toutes premières pages).

    Retourne la marque trouvée (en majuscules) ou "INCONNU" si rien n'a fonctionné
    (dans ce cas, le document devra être ajouté à la file de confirmation manuelle
    par l'appelant, voir classify_tech_pack_document()).
    """
    # ============================================================
    # CHANGEMENT #11 : la mémoire apprise est vérifiée EN PREMIER,
    # avant même le texte et la vision.
    # ------------------------------------------------------------
    # POURQUOI : si ce motif de nom de dossier a déjà été confirmé
    # manuellement par le passé, pas besoin de refaire tout le travail
    # de détection (texte, puis vision) -- on gagne du temps et on évite
    # une nouvelle erreur possible du modèle sur un cas déjà résolu.
    # ============================================================
    if nom_dossier:
        marque_memorisee = chercher_marque_dans_memoire(nom_dossier)
        if marque_memorisee:
            return marque_memorisee.upper().strip()

    pages_a_verifier = pages[:max_pages_to_check]

    # 1) On essaie ensuite le texte (rapide, fiable, pas d'appel modèle) sur
    #    chacune des premières pages.
    for image_path, text_content in pages_a_verifier:
        brand = extract_brand_by_text(text_content)
        if brand:
            return brand.upper().strip()

    # 2) Si le texte n'a rien donné sur aucune des premières pages, on
    #    tente la vision, toujours limitée aux premières pages.
    for image_path, text_content in pages_a_verifier:
        brand = extract_brand_by_vision(image_path, text_content)
        if brand and brand != "Inconnu":
            return brand.upper().strip()

    # 3) Rien n'a fonctionné : on ne renvoie plus juste "INCONNU" en silence,
    #    l'appelant devra ajouter ce document à la file de confirmation manuelle.
    return "INCONNU"


def classify_tech_pack_page(image_path: str, text_content: str, page_number: Optional[int] = None) -> str:
    """
    Classifie UNE page (catégorie uniquement). La marque n'est plus gérée ici :
    elle doit être calculée une seule fois par dossier via extract_brand_for_document(),
    puis passée/assignée à toutes les pages du dossier par l'appelant.
    Voir classify_tech_pack_document() ci-dessous pour l'usage recommandé.
    """
    if not os.path.exists(image_path):
        print(f"Erreur : L'image n'existe pas : {image_path}")
        return "Autres documents techniques"

    category, score = classify_by_text(text_content, page_number)
    if category is None:
        print(f"[INFO] Texte ambigu -> fallback vision pour {os.path.basename(image_path)}")
        category = classify_by_vision(image_path, text_content)
    else:
        print(f"[INFO] Classifié par texte : {category} (score={score})")

    print(f"[IA Décision] Catégorie : '{category}'")
    return category


def classify_tech_pack_document(pages: List[Tuple[str, str]], techpack_id: int = 0, nom_dossier: str = "") -> List[Tuple[str, str]]:
    """
    Point d'entrée recommandé : traite un dossier de Tech Pack complet.

    pages : liste ordonnée de (image_path, text_content), une entrée par page,
            page 1 en premier.
    techpack_id : identifiant du document en base MySQL (nécessaire pour la file
            de confirmation si la marque n'est pas détectée).
    nom_dossier : nom du dossier, utilisé pour la mémoire apprise et pour identifier
            le document dans l'interface de confirmation manuelle.

    Retourne une liste de (categorie, marque), une entrée par page, dans le
    même ordre que l'entrée. La marque est identique pour toutes les pages
    du dossier (calculée une seule fois, voir CHANGEMENT #5). Si la marque
    est "INCONNU", le document a été automatiquement ajouté à la file de
    confirmation manuelle (table marque_a_confirmer) -- ce n'est plus une
    erreur silencieuse, c'est une action en attente et visible.
    """
    # Marque calculée UNE SEULE FOIS pour tout le dossier
    brand = extract_brand_for_document(pages, nom_dossier=nom_dossier)
    print(f"[IA Décision] Marque du document (appliquée à {len(pages)} pages) : '{brand}'")

    # ============================================================
    # CHANGEMENT #12 : si rien n'a permis de détecter la marque,
    # on n'écrit plus juste "INCONNU" dans la base en silence --
    # on ajoute le document à la file de confirmation manuelle,
    # pour qu'un humain tranche via l'interface, comme prévu dans
    # le flux "1. upload -> 2. détection auto -> 3. confirmation si échec".
    # ============================================================
    if brand == "INCONNU" and techpack_id:
        ajouter_a_la_file_de_confirmation(techpack_id, nom_dossier)

    resultats = []
    for i, (image_path, text_content) in enumerate(pages, start=1):
        category = classify_tech_pack_page(image_path, text_content, page_number=i)
        resultats.append((category, brand))

    return resultats