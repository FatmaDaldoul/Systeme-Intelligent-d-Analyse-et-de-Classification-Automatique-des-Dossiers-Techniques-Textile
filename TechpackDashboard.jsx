import { useState, useEffect, useCallback, useRef } from "react";
import { Upload, FileText, Clock, CheckCircle2, AlertCircle, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";

// ============================================================
// Adresse de ton backend FastAPI. Si tu changes de port ou que tu
// déploies ailleurs plus tard, c'est la seule ligne à modifier.
// ============================================================
const API_BASE = "http://127.0.0.1:8000";

// Petit dictionnaire pour afficher chaque statut avec sa couleur et son icône
const STATUTS = {
  en_cours: { label: "En cours", icon: Clock, classes: "bg-amber-50 text-amber-700 border-amber-200" },
  termine: { label: "Terminé", icon: CheckCircle2, classes: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  erreur: { label: "Erreur", icon: AlertCircle, classes: "bg-rose-50 text-rose-700 border-rose-200" },
  pending: { label: "En attente", icon: Clock, classes: "bg-stone-100 text-stone-600 border-stone-200" },
};

function StatutBadge({ statut }) {
  const info = STATUTS[statut] || STATUTS.pending;
  const Icon = info.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${info.classes}`}>
      <Icon className="w-3.5 h-3.5" />
      {info.label}
    </span>
  );
}

export default function TechpackDashboard() {
  const [documents, setDocuments] = useState([]);
  const [chargement, setChargement] = useState(true);
  const [erreurConnexion, setErreurConnexion] = useState(false);
  const [enUpload, setEnUpload] = useState(false);
  const [messageUpload, setMessageUpload] = useState(null);
  const [ligneOuverte, setLigneOuverte] = useState(null);
  const [detailPages, setDetailPages] = useState({});
  const fileInputRef = useRef(null);

  // --- Récupère la liste des documents depuis le backend ---
  const chargerDocuments = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/documents`);
      if (!res.ok) throw new Error("Réponse serveur invalide");
      const data = await res.json();
      setDocuments(data);
      setErreurConnexion(false);
    } catch (err) {
      setErreurConnexion(true);
    } finally {
      setChargement(false);
    }
  }, []);

  useEffect(() => {
    chargerDocuments();
  }, [chargerDocuments]);

  // --- Actualisation automatique toutes les 4 secondes tant qu'un
  //     document est encore "en_cours" (pour voir le statut évoluer
  //     sans avoir à recharger la page soi-même) ---
  useEffect(() => {
    const yADesDocsEnCours = documents.some((d) => d.statut === "en_cours");
    if (!yADesDocsEnCours) return;

    const intervalle = setInterval(chargerDocuments, 4000);
    return () => clearInterval(intervalle);
  }, [documents, chargerDocuments]);

  // --- Envoi d'un nouveau PDF au backend ---
  const gererUpload = async (fichier) => {
    if (!fichier) return;
    if (!fichier.name.toLowerCase().endsWith(".pdf")) {
      setMessageUpload({ type: "erreur", texte: "Seuls les fichiers PDF sont acceptés." });
      return;
    }

    setEnUpload(true);
    setMessageUpload(null);

    const formData = new FormData();
    formData.append("file", fichier);

    try {
      const res = await fetch(`${API_BASE}/upload-techpack`, { method: "POST", body: formData });
      if (!res.ok) throw new Error("Échec de l'upload");
      const data = await res.json();
      setMessageUpload({ type: "succes", texte: `"${fichier.name}" reçu, traitement lancé (id ${data.document_id}).` });
      chargerDocuments();
    } catch (err) {
      setMessageUpload({ type: "erreur", texte: "Impossible de contacter le serveur. Vérifie que le backend tourne (uvicorn main:app --reload)." });
    } finally {
      setEnUpload(false);
    }
  };

  // --- Ouvrir/fermer le détail d'un document, en chargeant ses pages si besoin ---
  const basculerDetail = async (id) => {
    if (ligneOuverte === id) {
      setLigneOuverte(null);
      return;
    }
    setLigneOuverte(id);
    if (!detailPages[id]) {
      try {
        const res = await fetch(`${API_BASE}/documents/${id}`);
        const data = await res.json();
        setDetailPages((prev) => ({ ...prev, [id]: data.pages || [] }));
      } catch {
        setDetailPages((prev) => ({ ...prev, [id]: [] }));
      }
    }
  };

  const nombreEnCours = documents.filter((d) => d.statut === "en_cours").length;
  const nombreTermines = documents.filter((d) => d.statut === "termine").length;

  return (
    <div className="min-h-screen bg-stone-50 text-stone-900 font-sans">
      <div className="max-w-4xl mx-auto px-6 py-10">

        {/* ============ EN-TÊTE STYLE "FICHE TECHNIQUE" ============ */}
        <div className="border border-stone-300 bg-white rounded-sm mb-8">
          <div className="flex items-center justify-between border-b border-stone-300 px-5 py-3">
            <h1 className="text-lg font-semibold tracking-tight">Techpack Analyzer</h1>
            <span className="font-mono text-xs text-stone-400">v0.1</span>
          </div>
          <div className="grid grid-cols-3 divide-x divide-stone-200">
            <div className="px-5 py-3">
              <div className="text-[11px] uppercase tracking-wide text-stone-400 mb-1">Connexion serveur</div>
              <div className={`text-sm font-medium ${erreurConnexion ? "text-rose-600" : "text-emerald-600"}`}>
                {erreurConnexion ? "Hors ligne" : "En ligne"}
              </div>
            </div>
            <div className="px-5 py-3">
              <div className="text-[11px] uppercase tracking-wide text-stone-400 mb-1">Documents</div>
              <div className="text-sm font-mono font-medium">{documents.length}</div>
            </div>
            <div className="px-5 py-3">
              <div className="text-[11px] uppercase tracking-wide text-stone-400 mb-1">En cours</div>
              <div className="text-sm font-mono font-medium">{nombreEnCours}</div>
            </div>
          </div>
        </div>

        {erreurConnexion && (
          <div className="mb-6 flex items-start gap-2 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-sm px-4 py-3">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>Impossible de joindre le serveur à <span className="font-mono">{API_BASE}</span>. Vérifie que tu as bien lancé <span className="font-mono">uvicorn main:app --reload</span> dans ton terminal.</span>
          </div>
        )}

        {/* ============ ZONE D'UPLOAD ============ */}
        <div
          className="border-2 border-dashed border-stone-300 rounded-md bg-white px-6 py-10 text-center mb-8 hover:border-indigo-400 transition-colors cursor-pointer"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            gererUpload(e.dataTransfer.files?.[0]);
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => gererUpload(e.target.files?.[0])}
          />
          <Upload className="w-6 h-6 mx-auto mb-3 text-stone-400" />
          <p className="text-sm font-medium text-stone-700">
            {enUpload ? "Envoi en cours..." : "Clique ou dépose un Tech Pack (PDF) ici"}
          </p>
          <p className="text-xs text-stone-400 mt-1">Le traitement démarre automatiquement en arrière-plan</p>
        </div>

        {messageUpload && (
          <div
            className={`mb-6 text-sm rounded-sm px-4 py-3 border ${
              messageUpload.type === "succes"
                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                : "bg-rose-50 text-rose-700 border-rose-200"
            }`}
          >
            {messageUpload.texte}
          </div>
        )}

        {/* ============ LISTE DES DOCUMENTS ============ */}
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-500">Documents</h2>
          <button
            onClick={chargerDocuments}
            className="flex items-center gap-1.5 text-xs text-stone-500 hover:text-indigo-600 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Actualiser
          </button>
        </div>

        {chargement ? (
          <p className="text-sm text-stone-400">Chargement...</p>
        ) : documents.length === 0 ? (
          <div className="border border-stone-200 bg-white rounded-md px-6 py-10 text-center">
            <FileText className="w-6 h-6 mx-auto mb-2 text-stone-300" />
            <p className="text-sm text-stone-400">Aucun document pour l'instant. Envoie un PDF ci-dessus pour commencer.</p>
          </div>
        ) : (
          <div className="border border-stone-200 rounded-md bg-white divide-y divide-stone-200 overflow-hidden">
            {documents.map((doc) => (
              <div key={doc.id}>
                <button
                  onClick={() => basculerDetail(doc.id)}
                  className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-stone-50 transition-colors"
                >
                  <FileText className="w-4 h-4 text-stone-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-stone-800 truncate">{doc.nom}</p>
                    <p className="text-xs text-stone-400 font-mono">
                      {doc.marque || "Marque inconnue"} · {doc.nombre_pages != null ? `${doc.nombre_pages} pages` : "..."}
                    </p>
                  </div>
                  <StatutBadge statut={doc.statut} />
                  {ligneOuverte === doc.id ? (
                    <ChevronUp className="w-4 h-4 text-stone-400" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-stone-400" />
                  )}
                </button>

                {ligneOuverte === doc.id && (
                  <div className="px-4 pb-4 bg-stone-50 border-t border-stone-200">
                    {!detailPages[doc.id] ? (
                      <p className="text-xs text-stone-400 pt-3">Chargement des pages...</p>
                    ) : detailPages[doc.id].length === 0 ? (
                      <p className="text-xs text-stone-400 pt-3">Pas encore de pages classifiées.</p>
                    ) : (
                      <div className="pt-3 grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                        {detailPages[doc.id].map((p) => (
                          <div
                            key={p.numero}
                            className="flex items-center justify-between text-xs bg-white border border-stone-200 rounded-sm px-2.5 py-1.5"
                          >
                            <span className="font-mono text-stone-400">Page {p.numero}</span>
                            <span className="text-stone-700">{p.categorie || "—"}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
