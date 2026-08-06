from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, JSON  # Remplacement de JSONB par JSON
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# Connexion à votre conteneur Docker MySQL (Port 3307)
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://myuser:mypassword@localhost:3307/techpacks_db"

# Correction de la variable passée à create_engine
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
# NIVEAU 1 : DOCUMENTS
class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False, unique=True)
    brand = Column(String(100), default="Inconnu")
    page_count = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default="pending")

    pages = relationship("PageModel", back_populates="document", cascade="all, delete-orphan")
    # back_populates="document" Dans l'autre classe (PageModel), la relation inverse s'appelle document.
    #cascade= "all "Toutes les opérations effectuées sur le document s'appliquent aussi aux pages."
    #cascade= delete-orphan si des pages n'ont plus de document : elles sont orphelines.SQLAlchemy les supprime automatiquement.
    confirmations_marque = relationship("MarqueAConfirmerModel", back_populates="document", cascade="all, delete-orphan")

# NIVEAU 2 : PAGES
class PageModel(Base):
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False) 
    page_number = Column(Integer, nullable=False)
    image_path = Column(String(512), nullable=False)
    raw_text = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    category_confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, default=False)
    document = relationship("DocumentModel", back_populates="pages")
    extractions = relationship("ExtractionModel", back_populates="page", cascade="all, delete-orphan")
    bom_items = relationship("BOMItemModel", back_populates="page", cascade="all, delete-orphan")
    measurements = relationship("MeasurementModel", back_populates="page", cascade="all, delete-orphan")
# NIVEAU 3 : EXTRACTIONS (Le filet de sécurité JSON flexible pour MySQL)
class ExtractionModel(Base):
    __tablename__ = "extractions"

    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(100), nullable=False)
    data = Column(JSON, nullable=False)  
    confidence = Column(Float, nullable=True)

    page = relationship("PageModel", back_populates="extractions")
# BLOC ANALYTIQUE : TABLES NORMALISÉES DÉDIÉES
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