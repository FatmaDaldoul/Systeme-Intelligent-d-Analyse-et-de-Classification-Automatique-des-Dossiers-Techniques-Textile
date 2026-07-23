-- Supprime les doublons déjà créés (garde seulement la ligne la plus ancienne
-- pour chaque techpack_id en attente, supprime les répétitions).
DELETE t1 FROM marque_a_confirmer t1
INNER JOIN marque_a_confirmer t2
WHERE
    t1.id > t2.id
    AND t1.techpack_id = t2.techpack_id
    AND t1.statut = 'en_attente'
    AND t2.statut = 'en_attente';