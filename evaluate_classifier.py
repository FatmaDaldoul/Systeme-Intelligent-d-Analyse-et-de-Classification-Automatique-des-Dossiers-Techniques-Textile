import csv
import os
from collections import defaultdict

# ============================================================
# CHANGEMENT #4 : import de la base de données réelle
# ------------------------------------------------------------
# POURQUOI : jusqu'ici, l'évaluation ne servait qu'à mesurer un pourcentage
# de précision, sans jamais toucher à la vraie base MySQL. Maintenant que
# techpack_classifier.py peut ajouter un document à la file de confirmation
# manuelle (table marque_a_confirmer), il a besoin d'un VRAI techpack_id qui
# existe réellement dans la table "documents" -- sinon la clé étrangère
# (ForeignKey) refusera l'insertion. On importe donc SessionLocal et
# DocumentModel depuis database.py pour créer une vraie ligne "document"
# par dossier avant de le classifier.
# ============================================================
from database import SessionLocal, DocumentModel

# ============================================================
# CHANGEMENT #1 : import mis à jour
# ------------------------------------------------------------
# POURQUOI : le fichier classifier a été renommé/réorganisé -> le module
# s'appelle maintenant "techpack_classifier" et expose classify_tech_pack_document,
# qui gère catégorie + marque ensemble pour un dossier entier.
# On importe aussi classify_tech_pack_page séparément au cas où on voudrait
# classifier une page isolée, mais evaluer() n'utilisera que la version document.
# ============================================================
from classifier_techpacks import classify_tech_pack_document

# --- CONFIGURATION ---
CSV_PATH = "file.csv"           # Fichier de vérité terrain (filename,true_category,true_brand)
BASE_DIR = "dataset_brut"       # Dossier racine contenant les sous-dossiers de tech packs
TXT_EXTENSION = ".txt"          # Chaque page_N.png a un page_N.txt correspondant


def charger_verite_terrain(csv_path):
    """Lit le CSV et renvoie une liste de dicts {filename, true_category, true_brand}."""
    lignes = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("filename") or not row["filename"].strip():
                continue
            lignes.append({
                "filename": row["filename"].strip(),
                "true_category": row["true_category"].strip(),
                "true_brand": row["true_brand"].strip(),
            })
    return lignes


def extraire_numero_page(filename):
    """
    Extrait le numéro de page depuis un chemin du type
    'dossier/page_12.png' -> 12
    Renvoie None si le format ne correspond pas.
    Inchangé.
    """
    try:
        nom_fichier = os.path.basename(filename)
        sans_ext = nom_fichier.rsplit(".", 1)[0]
        num_str = sans_ext.split("_")[-1]
        return int(num_str)
    except (ValueError, IndexError):
        return None


# ============================================================
# CHANGEMENT #2 : nouvelle fonction pour grouper les lignes du CSV par dossier
# ------------------------------------------------------------
# POURQUOI : avant, chaque page était traitée indépendamment, donc la marque
# était recherchée page par page (et se trompait souvent, cf. évaluation
# précédente). Maintenant que la marque se détecte une seule fois par
# document (voir techpack_classifier.classify_tech_pack_document), il faut
# regrouper les pages qui appartiennent au même Tech Pack AVANT de les
# classifier, pour appeler la fonction une seule fois par dossier avec
# toutes ses pages dans l'ordre.
# ============================================================
def grouper_par_dossier(verite_terrain):
    """
    Regroupe les lignes du CSV par dossier (le Tech Pack auquel elles appartiennent),
    et trie les pages de chaque dossier par numéro de page croissant.

    Retourne un dict : { "nom_dossier": [ligne1, ligne2, ...], ... }
    """
    groupes = defaultdict(list)
    for ligne in verite_terrain:
        dossier = os.path.dirname(ligne["filename"])
        groupes[dossier].append(ligne)

    # Tri des pages de chaque dossier par numéro de page, pour que la page 1
    # (celle qui a le plus de chances de contenir le logo) soit bien en premier
    for dossier in groupes:
        groupes[dossier].sort(key=lambda l: extraire_numero_page(l["filename"]) or 0)

    return groupes


def obtenir_ou_creer_document(session, nom_dossier: str) -> int:
    """
    Cherche si un document avec ce nom existe déjà en base (table "documents").
    S'il existe, renvoie son id. Sinon, le crée et renvoie le nouvel id.

    C'est nécessaire car techpack_classifier.classify_tech_pack_document() a
    maintenant besoin d'un techpack_id réel pour pouvoir, si besoin, ajouter
    ce document à la file de confirmation manuelle (table marque_a_confirmer),
    qui exige une clé étrangère valide vers "documents".
    """
    document_existant = session.query(DocumentModel).filter_by(filename=nom_dossier).first()
    if document_existant:
        return document_existant.id

    nouveau_document = DocumentModel(filename=nom_dossier, status="en_cours_evaluation")
    session.add(nouveau_document)
    session.commit()  # nécessaire pour que la base attribue un id au nouveau document
    return nouveau_document.id


def evaluer():
    verite_terrain = charger_verite_terrain(CSV_PATH)

    if not verite_terrain:
        print(f"Erreur : aucune ligne valide trouvée dans '{CSV_PATH}'.")
        return

    total = 0
    categorie_correcte = 0
    marque_correcte = 0
    les_deux_correctes = 0

    confusion = defaultdict(lambda: defaultdict(int))
    erreurs_categorie = []
    erreurs_marque = []
    fichiers_manquants = []

    groupes = grouper_par_dossier(verite_terrain)
    print(f"Évaluation sur {len(verite_terrain)} pages, regroupées en {len(groupes)} dossiers...\n")

    compteur_global = 0

    # ============================================================
    # CHANGEMENT #5 : une session MySQL est ouverte une seule fois,
    # avant la boucle, et réutilisée pour tous les dossiers.
    # ------------------------------------------------------------
    # EXPLICATION SIMPLE : une "session" est comme une conversation
    # ouverte avec la base de données -- on l'ouvre une fois, on
    # l'utilise pour toutes nos questions/écritures, et on la ferme
    # à la fin, plutôt que de raccrocher et rappeler à chaque dossier.
    # ============================================================
    session = SessionLocal()

    # ============================================================
    # CHANGEMENT #3 : boucle restructurée -> on itère par DOSSIER, pas par page
    # ------------------------------------------------------------
    # POURQUOI : c'est le coeur de la correction. On construit d'abord la liste
    # complète des pages (image + texte) d'un dossier, puis on appelle UNE SEULE
    # FOIS classify_tech_pack_document() pour tout le dossier. Cette fonction
    # renvoie une liste de (categorie, marque) dans le même ordre que les pages
    # fournies -> on peut ensuite comparer chaque résultat à la vérité terrain
    # correspondante, page par page, sans jamais recalculer la marque à chaque page.
    # ============================================================
    for dossier, lignes_dossier in groupes.items():
        pages_a_classifier = []       # liste de (image_path, texte_brut) pour ce dossier
        lignes_valides = []           # lignes CSV correspondantes (même ordre, même longueur)

        for ligne in lignes_dossier:
            rel_path = ligne["filename"]
            chemin_image = os.path.join(BASE_DIR, rel_path)

            sous_dossier = os.path.dirname(rel_path)
            nom_png = os.path.basename(rel_path)
            nom_txt = nom_png.rsplit(".", 1)[0] + TXT_EXTENSION
            chemin_txt = os.path.join(BASE_DIR, sous_dossier, nom_txt)

            if not os.path.exists(chemin_image):
                fichiers_manquants.append(chemin_image)
                continue

            texte_brut = ""
            if os.path.exists(chemin_txt):
                with open(chemin_txt, "r", encoding="utf-8") as f:
                    texte_brut = f.read()

            pages_a_classifier.append((chemin_image, texte_brut))
            lignes_valides.append(ligne)

        if not pages_a_classifier:
            # Tout le dossier était manquant, on passe au suivant
            continue

        # ============================================================
        # CHANGEMENT #6 : on récupère/crée un vrai techpack_id en base,
        # puis on le transmet à classify_tech_pack_document() avec le nom
        # du dossier -- ces deux infos étaient absentes avant, or elles
        # sont nécessaires pour que la mémoire apprise (recherche par nom)
        # et la file de confirmation manuelle (écriture avec une vraie
        # clé étrangère) fonctionnent réellement pendant l'évaluation,
        # et pas seulement en théorie.
        # ============================================================
        techpack_id = obtenir_ou_creer_document(session, dossier)
        resultats = classify_tech_pack_document(pages_a_classifier, techpack_id=techpack_id, nom_dossier=dossier)

        # On reconstitue les résultats page par page pour les comparer à la vérité terrain
        # (le score de confiance, 3e valeur du tuple, n'est pas utilisé ici -- il sert
        # uniquement à l'affichage dans l'interface web, voir main.py)
        for ligne, (categorie_predite, marque_predite, _score) in zip(lignes_valides, resultats):
            rel_path = ligne["filename"]
            vraie_categorie = ligne["true_category"]
            vraie_marque = ligne["true_brand"]

            total += 1
            compteur_global += 1
            confusion[vraie_categorie][categorie_predite] += 1

            cat_ok = (categorie_predite.strip().lower() == vraie_categorie.strip().lower())
            marque_ok = (marque_predite.strip().lower() == vraie_marque.strip().lower())

            if cat_ok:
                categorie_correcte += 1
            else:
                erreurs_categorie.append({
                    "fichier": rel_path,
                    "attendu": vraie_categorie,
                    "obtenu": categorie_predite,
                })

            if marque_ok:
                marque_correcte += 1
            else:
                erreurs_marque.append({
                    "fichier": rel_path,
                    "attendu": vraie_marque,
                    "obtenu": marque_predite,
                })

            if cat_ok and marque_ok:
                les_deux_correctes += 1

            statut = "OK" if (cat_ok and marque_ok) else "ERREUR"
            print(f"[{compteur_global}/{len(verite_terrain)}] {statut} - {rel_path}")
            if not cat_ok:
                print(f"    Catégorie -> attendu: '{vraie_categorie}' | obtenu: '{categorie_predite}'")
            if not marque_ok:
                print(f"    Marque    -> attendu: '{vraie_marque}' | obtenu: '{marque_predite}'")

    session.close()  # CHANGEMENT #5 (suite) : on referme la session proprement, une fois tous les dossiers traités

    # ============================================================
    # RAPPORT FINAL (inchangé)
    # ============================================================
    print("\n" + "=" * 60)
    print("RÉSULTATS DE L'ÉVALUATION")
    print("=" * 60)

    if fichiers_manquants:
        print(f"\nATTENTION : {len(fichiers_manquants)} fichier(s) introuvable(s) (ignorés) :")
        for f in fichiers_manquants[:10]:
            print(f"   - {f}")
        if len(fichiers_manquants) > 10:
            print(f"   ... et {len(fichiers_manquants) - 10} de plus")

    if total == 0:
        print("\nAucune page évaluée (tous les fichiers étaient manquants).")
        return

    print(f"\nPages évaluées : {total}")
    print(f"Précision Catégorie : {categorie_correcte}/{total} ({100*categorie_correcte/total:.1f}%)")
    print(f"Précision Marque    : {marque_correcte}/{total} ({100*marque_correcte/total:.1f}%)")
    print(f"Précision Globale (les deux justes) : {les_deux_correctes}/{total} ({100*les_deux_correctes/total:.1f}%)")

    print("\n" + "-" * 60)
    print("MATRICE DE CONFUSION (Catégorie réelle -> Catégorie prédite)")
    print("-" * 60)
    for vraie_cat in sorted(confusion.keys()):
        predictions = confusion[vraie_cat]
        total_cat = sum(predictions.values())
        correctes = predictions.get(vraie_cat, 0)
        print(f"\n{vraie_cat} ({correctes}/{total_cat} correctes) :")
        for pred_cat, count in sorted(predictions.items(), key=lambda x: -x[1]):
            marqueur = "OK " if pred_cat == vraie_cat else "NON"
            print(f"   {marqueur} prédit comme '{pred_cat}': {count}")

    if erreurs_categorie:
        print("\n" + "-" * 60)
        print(f"DÉTAIL DES {len(erreurs_categorie)} ERREURS DE CATÉGORIE")
        print("-" * 60)
        for e in erreurs_categorie:
            print(f"  {e['fichier']}")
            print(f"     attendu: {e['attendu']}  |  obtenu: {e['obtenu']}")

    if erreurs_marque:
        print("\n" + "-" * 60)
        print(f"DÉTAIL DES {len(erreurs_marque)} ERREURS DE MARQUE")
        print("-" * 60)
        for e in erreurs_marque:
            print(f"  {e['fichier']}")
            print(f"     attendu: {e['attendu']}  |  obtenu: {e['obtenu']}")

    print("\n" + "=" * 60)
    print("Fin de l'évaluation.")
    print("=" * 60)


if __name__ == "__main__":
    evaluer()