from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, JSON  # Remplacement de JSONB par JSON
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# Connexion à votre conteneur Docker MySQL (Port 3307)
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://myuser:mypassword@localhost:3307/techpacks_db"

# Correction de la variable passée à create_engine
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==============================================================================
# NIVEAU 1 : DOCUMENTS
# ==============================================================================
class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False, unique=True)
    brand = Column(String(100), default="Inconnu")
    page_count = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default="pending")

    pages = relationship("PageModel", back_populates="document", cascade="all, delete-orphan")
    # CHANGEMENT #1 : on ajoute ici le lien vers les demandes de confirmation de marque
    # liées à ce document, pour pouvoir écrire par exemple "mon_document.confirmations_marque"
    # depuis le code Python plus tard, si besoin.
    confirmations_marque = relationship("MarqueAConfirmerModel", back_populates="document", cascade="all, delete-orphan")


# ==============================================================================
# NIVEAU 2 : PAGES
# ==============================================================================
class PageModel(Base):
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    page_number = Column(Integer, nullable=False)
    image_path = Column(String(512), nullable=False)
    raw_text = Column(Text, nullable=True)

    # Classification de la page (ex: "Tableau de mesures", "BOM")
    category = Column(String(100), nullable=True)
    category_confidence = Column(Float, nullable=True)

    # Sécurisation de la fiabilité de l'IA :
    needs_review = Column(Boolean, default=False)

    document = relationship("DocumentModel", back_populates="pages")
    extractions = relationship("ExtractionModel", back_populates="page", cascade="all, delete-orphan")
    bom_items = relationship("BOMItemModel", back_populates="page", cascade="all, delete-orphan")
    measurements = relationship("MeasurementModel", back_populates="page", cascade="all, delete-orphan")


# ==============================================================================
# NIVEAU 3 : EXTRACTIONS (Le filet de sécurité JSON flexible pour MySQL)
# ==============================================================================
class ExtractionModel(Base):
    __tablename__ = "extractions"

    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(100), nullable=False)
    data = Column(JSON, nullable=False)  # MySQL utilise JSON à la place de JSONB
    confidence = Column(Float, nullable=True)

    page = relationship("PageModel", back_populates="extractions")


# ==============================================================================
# BLOC ANALYTIQUE : TABLES NORMALISÉES DÉDIÉES
# ==============================================================================
class BOMItemModel(Base):
    __tablename__ = "bom_items"

    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    item_type = Column(String(100))             # Tissu principal, Bouton, Zip, Fil
    placement = Column(String(255))             # ex: Poche arrière, fermeture centrale
    material_composition = Column(String(255))  # ex: 100% Coton, Métal
    supplier = Column(String(100))
    cost = Column(Float, nullable=True)

    page = relationship("PageModel", back_populates="bom_items")


class MeasurementModel(Base):
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    measurement_point = Column(String(255))  # ex: Tour de taille, Longueur totale
    size = Column(String(50))                # ex: S, M, L, XL
    value_cm = Column(Float, nullable=False)
    tolerance = Column(String(50))

    page = relationship("PageModel", back_populates="measurements")


# ==============================================================================
# TABLE : MARQUES EN ATTENTE DE CONFIRMATION MANUELLE
# ------------------------------------------------------------------------------
# CHANGEMENT #2 : classe entièrement corrigée. Voici les 5 erreurs qui existaient
# dans la version d'origine, et pourquoi chacune empêchait le fichier de fonctionner :
#
#   a) Indentation cassée : "__tablename__" n'était pas aligné avec le reste du
#      corps de la classe. En Python, l'indentation définit la structure du code
#      (contrairement à d'autres langages où ce sont des accolades) -- un mauvais
#      alignement provoque un plantage immédiat au démarrage (IndentationError).
#
#   b) "TimeStamp" n'existe pas dans SQLAlchemy (ni importé, ni orthographié
#      correctement). On utilise "DateTime", déjà importé en haut du fichier,
#      exactement comme pour "uploaded_at" dans DocumentModel plus haut.
#
#   c) La colonne s'appelait "nom_fichier", alors que le code de classification
#      (techpack_classifier.py) insère dans une colonne "nom_dossier". Si les
#      deux noms ne correspondent pas EXACTEMENT, l'insertion échoue avec une
#      erreur "colonne inconnue". On renomme ici en "nom_dossier" pour que tout
#      le projet utilise le même nom partout.
#
#   d) "techpack_id" n'était pas relié formellement à la table "documents" par
#      une vraie clé étrangère (ForeignKey) -- on l'ajoute, ça garantit que
#      chaque confirmation pointe bien vers un document qui existe réellement.
#
#   e) La relation "page = relationship(...)" n'avait aucun sens : elle essayait
#      de relier une demande de confirmation de marque (qui concerne un document
#      ENTIER) à une PAGE précise, sans même avoir de colonne "page_id". On la
#      remplace par une relation vers DocumentModel, qui est la bonne relation
#      logique ici.
# ==============================================================================
class MarqueAConfirmerModel(Base):
    __tablename__ = "marque_a_confirmer"

    id = Column(Integer, primary_key=True, index=True)
    techpack_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    nom_dossier = Column(String(255), nullable=False)
    statut = Column(String(20), default="en_attente")  # 'en_attente' ou 'confirme'
    marque_confirmee = Column(String(100), nullable=True)
    date_creation = Column(DateTime, default=datetime.utcnow)
    date_confirmation = Column(DateTime, nullable=True)

    document = relationship("DocumentModel", back_populates="confirmations_marque")


# ==============================================================================
# TABLE : MÉMOIRE APPRISE DES ASSOCIATIONS "NOM DE DOSSIER -> MARQUE"
# ------------------------------------------------------------------------------
# CHANGEMENT #3 : dans la version d'origine, cette table était écrite en langage
# SQL brut ("CREATE TABLE regles_marque_apprises (...)") collé directement au
# milieu du fichier Python. Ce n'est pas du code Python valide -- Python
# provoquerait une erreur de syntaxe (SyntaxError) dès qu'il essaierait de lire
# ces lignes, avant même de démarrer le programme. On la transforme ici en une
# vraie classe SQLAlchemy, exactement comme toutes les autres tables du fichier,
# pour que "Base.metadata.create_all(bind=engine)" puisse aussi la créer.
# ==============================================================================
class RegleMarqueAppriseModel(Base):
    __tablename__ = "regles_marque_apprises"

    id = Column(Integer, primary_key=True, index=True)
    motif_nom_fichier = Column(String(255), nullable=False)  # ex: "guidelines_denim"
    marque = Column(String(100), nullable=False)              # ex: "GAS"
    date_creation = Column(DateTime, default=datetime.utcnow)


def initialiser_base_de_donnees():
    Base.metadata.create_all(bind=engine)
    print("-> Succès : L'architecture MySQL 3 niveaux + Tables Analytiques est créée dans Docker !")


if __name__ == "__main__":
    initialiser_base_de_donnees()