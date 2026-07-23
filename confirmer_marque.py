"""
Script simple pour confirmer manuellement une marque en attente.
Plus tard, cette logique sera appelée par un endpoint FastAPI depuis
l'interface web (bouton "Confirmer" sur la page "À vérifier") --
pour l'instant, ce script en ligne de commande permet de tester le
système sans attendre d'avoir construit toute l'application web.
"""
import mysql.connector
from classifier_techpacks import DB_CONFIG


def lister_documents_en_attente():
    """Affiche tous les documents dont la marque attend une confirmation."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, techpack_id, nom_dossier, date_creation FROM marque_a_confirmer WHERE statut = 'en_attente'"
    )
    resultats = cursor.fetchall()
    cursor.close()
    conn.close()

    if not resultats:
        print("Aucun document en attente de confirmation.")
        return []

    print("\nDocuments en attente de confirmation de marque :\n")
    for id_, techpack_id, nom_dossier, date_creation in resultats:
        print(f"  [{id_}] {nom_dossier}  (techpack_id={techpack_id}, ajouté le {date_creation})")
    return resultats


def confirmer_marque(id_confirmation: int, marque: str, motif_memoire: str):
    """
    Confirme manuellement la marque d'un document en attente.

    id_confirmation : l'id de la ligne dans la table marque_a_confirmer (affiché entre crochets)
    marque : la marque choisie manuellement, ex: "GAS"
    motif_memoire : le morceau de nom de dossier à retenir pour la prochaine fois,
                    ex: "guidelines_denim" (doit être un mot ou groupe de mots qui
                    identifie bien ce type de document, sans être trop générique)
    """
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # 1) On marque la confirmation comme faite
    cursor.execute(
        "UPDATE marque_a_confirmer SET statut = 'confirme', marque_confirmee = %s, "
        "date_confirmation = NOW() WHERE id = %s",
        (marque.upper().strip(), id_confirmation)
    )

    # 2) On alimente la mémoire apprise avec ce nouveau motif, pour que les
    #    prochains documents similaires soient reconnus automatiquement
    cursor.execute(
        "INSERT INTO regles_marque_apprises (motif_nom_fichier, marque) VALUES (%s, %s)",
        (motif_memoire.strip(), marque.upper().strip())
    )

    conn.commit()
    cursor.close()
    conn.close()
    print(f"Marque '{marque}' confirmée, et motif '{motif_memoire}' ajouté à la mémoire apprise.")


if __name__ == "__main__":
    # Exemple d'utilisation en ligne de commande, à adapter/lancer manuellement :
    documents = lister_documents_en_attente()
    if documents:
        print("\nPour confirmer, appelle : confirmer_marque(id, 'MARQUE', 'motif_a_retenir')")
        print("Exemple : confirmer_marque(1, 'GAS', 'guidelines_denim')")