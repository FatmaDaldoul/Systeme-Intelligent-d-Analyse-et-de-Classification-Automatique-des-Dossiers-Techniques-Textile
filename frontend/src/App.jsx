import React, { useState, useEffect, useRef } from "react";
import { 
  Upload, FileText, Clock, CheckCircle2, AlertCircle, ChevronDown, ChevronUp, 
  RefreshCw, Send, MessageSquare, Trash2, Eye, Tag, Layers, Search, ShieldAlert, Sparkles
} from "lucide-react";

const API_BASE = "http://127.0.0.1:8000";

const STATUTS = {
  en_cours: { label: "En cours", classes: "bg-amber-50 text-amber-700 border-amber-200 icon-spin" },
  termine: { label: "Terminé", classes: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  erreur: { label: "Erreur", classes: "bg-rose-50 text-rose-700 border-rose-200" },
  pending: { label: "En attente", classes: "bg-slate-100 text-slate-600 border-slate-200" },
};

function StatutBadge({ statut }) {
  const info = STATUTS[statut] || STATUTS.pending;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${info.classes}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {info.label}
    </span>
  );
}

export default function App() {
  const [ongletActif, setOngletActif] = useState("documents");
  const [documents, setDocuments] = useState([]);
  const [enAttente, setEnAttente] = useState([]);
  const [chargement, setChargement] = useState(true);

  const chargerDocuments = async () => {
    try {
      const res = await fetch(`${API_BASE}/documents`);
      if (res.ok) setDocuments(await res.json());
    } catch (err) {
      console.error("Erreur chargement documents:", err);
    } finally {
      setChargement(false);
    }
  };

  const chargerEnAttente = async () => {
    try {
      const res = await fetch(`${API_BASE}/documents-a-verifier`);
      if (res.ok) setEnAttente(await res.json());
    } catch (err) {
      console.error("Erreur chargement vérifications:", err);
    }
  };

  useEffect(() => {
    chargerDocuments();
    chargerEnAttente();
    const interval = setInterval(() => {
      chargerDocuments();
      chargerEnAttente();
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 font-sans">
      {/* En-tête de navigation */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-indigo-600 text-white p-2 rounded-xl shadow-md shadow-indigo-100">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-base font-bold text-slate-900 leading-none">TechPack Analyzer</h1>
              <p className="text-xs text-slate-500 mt-0.5">Analyse & Classification Textile IA</p>
            </div>
          </div>

          <nav className="flex gap-2">
            {[
              { id: "documents", label: "Documents", count: documents.length, icon: FileText },
              { id: "chat", label: "Assistant Chat", icon: MessageSquare },
              { id: "verifier", label: "À vérifier", count: enAttente.length, alert: enAttente.length > 0, icon: ShieldAlert },
            ].map((tab) => {
              const Icon = tab.icon;
              const active = ongletActif === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setOngletActif(tab.id)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                    active
                      ? "bg-indigo-50 text-indigo-700 border border-indigo-200 shadow-sm"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                  {tab.count !== undefined && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                      tab.alert ? "bg-amber-100 text-amber-800" : active ? "bg-indigo-100 text-indigo-800" : "bg-slate-200 text-slate-700"
                    }`}>
                      {tab.count}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      {/* Contenu principal */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        {ongletActif === "documents" && (
          <OngletDocuments 
            documents={documents} 
            chargement={chargement} 
            chargerDocuments={chargerDocuments} 
          />
        )}
        {ongletActif === "chat" && <OngletChat documents={documents} />}
        {ongletActif === "verifier" && (
          <OngletVerification 
            enAttente={enAttente} 
            chargerEnAttente={chargerEnAttente} 
            chargerDocuments={chargerDocuments} 
          />
        )}
      </main>
    </div>
  );
}

/* ============================================================
   ONGLET 1 : Documents & Détails exhaustifs avec Suppression
   ============================================================ */
function OngletDocuments({ documents, chargement, chargerDocuments }) {
  const [enUpload, setEnUpload] = useState(false);
  const [messageUpload, setMessageUpload] = useState(null);
  const [documentOuvert, setDocumentOuvert] = useState(null);
  const [detailComplet, setDetailComplet] = useState({});
  const fileInputRef = useRef(null);

  const gererUpload = async (fichier) => {
    if (!fichier) return;
    setEnUpload(true);
    setMessageUpload(null);
    const formData = new FormData();
    formData.append("file", fichier);
    try {
      const res = await fetch(`${API_BASE}/upload-techpack`, { method: "POST", body: formData });
      if (!res.ok) throw new Error("Erreur lors de l'upload");
      setMessageUpload({ type: "succes", texte: `Document "${fichier.name}" envoyé avec succès.` });
      chargerDocuments();
    } catch (err) {
      setMessageUpload({ type: "erreur", texte: err.message });
    } finally {
      setEnUpload(false);
    }
  };

  const supprimerDocument = async (id, nom) => {
    if (!window.confirm(`Voulez-vous vraiment supprimer définitivement "${nom}" ?`)) return;
    try {
      const res = await fetch(`${API_BASE}/documents/${id}`, { method: "DELETE" });
      if (res.ok) {
        chargerDocuments();
        if (documentOuvert === id) setDocumentOuvert(null);
      }
    } catch (err) {
      alert("Erreur lors de la suppression : " + err.message);
    }
  };

  const basculerDetail = async (id) => {
    if (documentOuvert === id) {
      setDocumentOuvert(null);
      return;
    }
    setDocumentOuvert(id);
    try {
      const res = await fetch(`${API_BASE}/documents/${id}`);
      if (res.ok) {
        const data = await res.json();
        setDetailComplet((prev) => ({ ...prev, [id]: data }));
      }
    } catch (err) {
      console.error("Erreur chargement détails:", err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Zone de Drag & Drop */}
      <div
        onClick={() => fileInputRef.current?.click()}
        className="border-2 border-dashed border-indigo-200 hover:border-indigo-500 rounded-2xl bg-white p-8 text-center cursor-pointer transition-all hover:shadow-lg hover:shadow-indigo-50/50 group"
      >
        <input ref={fileInputRef} type="file" accept="application/pdf" className="hidden" onChange={(e) => gererUpload(e.target.files?.[0])} />
        <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center mx-auto mb-3 group-hover:scale-110 transition-transform">
          <Upload className="w-6 h-6" />
        </div>
        <p className="text-sm font-semibold text-slate-800">
          {enUpload ? "Traitement et téléversement..." : "Cliquez ou déposez un dossier technique (PDF) ici"}
        </p>
        <p className="text-xs text-slate-400 mt-1">Analyse vision et extraction de texte automatiques</p>
      </div>

      {messageUpload && (
        <div className={`p-4 rounded-xl text-sm border flex items-center gap-2 ${
          messageUpload.type === "succes" ? "bg-emerald-50 text-emerald-800 border-emerald-200" : "bg-rose-50 text-rose-800 border-rose-200"
        }`}>
          {messageUpload.type === "succes" ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
          {messageUpload.texte}
        </div>
      )}

      {/* Liste des documents */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h2 className="text-sm font-bold text-slate-700 uppercase tracking-wider">Dossiers analysés</h2>
          <button onClick={chargerDocuments} className="text-xs text-indigo-600 font-medium flex items-center gap-1 hover:underline">
            <RefreshCw className="w-3.5 h-3.5" /> Rafraîchir
          </button>
        </div>

        {chargement ? (
          <div className="p-8 text-center text-slate-400">Chargement des données...</div>
        ) : documents.length === 0 ? (
          <div className="p-12 text-center text-slate-400">Aucun document dans la base.</div>
        ) : (
          <div className="divide-y divide-slate-100">
            {documents.map((doc) => {
              const estOuvert = documentOuvert === doc.id;
              const details = detailComplet[doc.id];
              return (
                <div key={doc.id} className="transition-colors">
                  <div className="p-4 sm:px-6 flex items-center justify-between gap-4 hover:bg-slate-50">
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <div className="p-2.5 bg-slate-100 text-slate-600 rounded-lg shrink-0">
                        <FileText className="w-5 h-5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h3 className="text-sm font-semibold text-slate-900 truncate">{doc.nom}</h3>
                        <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5">
                          <span className="font-medium text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">Marque: {doc.marque}</span>
                          <span>{doc.nombre_pages || "?"} pages</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <StatutBadge statut={doc.statut} />
                      <button
                        onClick={() => basculerDetail(doc.id)}
                        className="p-2 hover:bg-indigo-50 text-slate-600 hover:text-indigo-600 rounded-lg transition-colors"
                        title="Voir le détail"
                      >
                        {estOuvert ? <ChevronUp className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                      <button
                        onClick={() => supprimerDocument(doc.id, doc.nom)}
                        className="p-2 hover:bg-rose-50 text-slate-400 hover:text-rose-600 rounded-lg transition-colors"
                        title="Supprimer définitivement"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {/* VUE DÉTAILLÉE EXHAUSTIVE */}
                  {estOuvert && details && (
                    <div className="bg-slate-50/80 p-6 border-t border-slate-100 space-y-4">
                      {/* Résumé analytique */}
                      <div className="grid grid-cols-3 gap-4 mb-4">
                        <div className="bg-white p-3 rounded-xl border border-slate-200">
                          <span className="text-xs text-slate-400 block font-medium">Composants BOM</span>
                          <span className="text-lg font-bold text-slate-800">{details.statistiques?.total_bom_items || 0}</span>
                        </div>
                        <div className="bg-white p-3 rounded-xl border border-slate-200">
                          <span className="text-xs text-slate-400 block font-medium">Points de mesure</span>
                          <span className="text-lg font-bold text-slate-800">{details.statistiques?.total_measurements || 0}</span>
                        </div>
                        <div className="bg-white p-3 rounded-xl border border-slate-200">
                          <span className="text-xs text-slate-400 block font-medium">Avertissements Vision</span>
                          <span className="text-lg font-bold text-amber-600">{details.statistiques?.pages_a_verifier || 0}</span>
                        </div>
                      </div>

                      {/* Liste détaillée des pages */}
                      <div className="space-y-3">
                        {details.pages.map((p) => (
                          <div key={p.id} className="bg-white rounded-xl border border-slate-200 p-4 space-y-3 shadow-sm">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-bold bg-slate-100 text-slate-700 px-2 py-1 rounded-md">
                                  Page {p.numero}
                                </span>
                                <span className="text-sm font-semibold text-slate-800">{p.categorie}</span>
                              </div>

                              <div className="flex items-center gap-2">
                                {p.confiance ? (
                                  <span className="text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-md font-mono">
                                    Score: {p.confiance.toFixed(1)}
                                  </span>
                                ) : (
                                  <span className="text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-md font-mono">
                                    Vision BakLLaVA
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Aperçu Texte Extrait */}
                            {p.apercu_texte && (
                              <div className="text-xs text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-100 font-mono leading-relaxed max-h-24 overflow-y-auto">
                                <span className="font-semibold text-slate-400 block mb-1">TEXTE EXTRAIT:</span>
                                {p.apercu_texte}
                              </div>
                            )}

                            {/* Affichage des éléments BOM s'il y en a */}
                            {p.bom_items.length > 0 && (
                              <div className="text-xs border border-slate-100 rounded-lg overflow-hidden">
                                <div className="bg-slate-100 font-semibold p-2 text-slate-700">Nomenclature (BOM)</div>
                                <div className="p-2 space-y-1">
                                  {p.bom_items.map((b) => (
                                    <div key={b.id} className="flex justify-between text-slate-600 border-b border-slate-50 last:border-0 py-1">
                                      <span>{b.item_type} - {b.placement}</span>
                                      <span className="font-medium text-slate-800">{b.material_composition} ({b.supplier || 'N/A'})</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Affichage des mesures s'il y en a */}
                            {p.measurements.length > 0 && (
                              <div className="text-xs border border-slate-100 rounded-lg overflow-hidden">
                                <div className="bg-slate-100 font-semibold p-2 text-slate-700">Tableau de Mesures</div>
                                <div className="p-2 grid grid-cols-2 gap-2">
                                  {p.measurements.map((m) => (
                                    <div key={m.id} className="bg-slate-50 p-2 rounded border border-slate-100">
                                      <span className="font-medium text-slate-700 block">{m.measurement_point}</span>
                                      <span className="text-slate-500">Taille {m.size}: {m.value_cm} cm (Tolérance {m.tolerance})</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ============================================================
   ONGLET 2 : Chat RAG
   ============================================================ */
function OngletChat({ documents }) {
  const [messages, setMessages] = useState([]);
  const [saisie, setSaisie] = useState("");
  const [enAttente, setEnAttente] = useState(false);
  const [documentCible, setDocumentCible] = useState("");
  const finRef = useRef(null);

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const envoyerQuestion = async () => {
    if (!saisie.trim() || enAttente) return;
    const q = saisie.trim();
    setMessages((prev) => [...prev, { role: "user", texte: q }]);
    setSaisie("");
    setEnAttente(true);

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, document_id: documentCible ? Number(documentCible) : null }),
      });
      if (res.ok) {
        const data = await res.json();
        setMessages((prev) => [...prev, { role: "bot", texte: data.reponse, sources: data.sources || [] }]);
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: "bot", texte: "Erreur de connexion au chatbot." }]);
    } finally {
      setEnAttente(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm h-[75vh] flex flex-col overflow-hidden">
      <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-indigo-600" />
          <span className="font-semibold text-slate-800 text-sm">Assistant TechPack RAG</span>
        </div>
        <select
          value={documentCible}
          onChange={(e) => setDocumentCible(e.target.value)}
          className="text-xs bg-white border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">Interroger tous les documents</option>
          {documents.map((d) => (
            <option key={d.id} value={d.id}>{d.nom}</option>
          ))}
        </select>
      </div>

      <div className="flex-1 p-6 overflow-y-auto space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-slate-400 my-auto pt-12">
            <MessageSquare className="w-12 h-12 mx-auto mb-3 text-slate-200" />
            <p className="text-sm">Posez des questions sur les tissus, mesures ou instructions de vos Tech Packs.</p>
          </div>
        )}
        {messages.map((m, idx) => (
          <div key={idx} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[75%] rounded-2xl p-4 text-sm ${
              m.role === "user" ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-800"
            }`}>
              <p className="whitespace-pre-wrap leading-relaxed">{m.texte}</p>
              {m.sources && m.sources.length > 0 && (
                <div className="mt-3 pt-2 border-t border-slate-200/50 text-xs text-slate-500 space-y-0.5">
                  <span className="font-semibold block text-[10px] uppercase tracking-wider">Sources:</span>
                  {m.sources.map((s, i) => (
                    <div key={i}>• {s.document} (Page {s.page})</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {enAttente && (
          <div className="flex justify-start">
            <div className="bg-slate-100 text-slate-500 rounded-2xl p-4 text-sm animate-pulse">
              Recherche des informations dans les documents...
            </div>
          </div>
        )}
        <div ref={finRef} />
      </div>

      <div className="p-4 border-t border-slate-200 flex gap-2 bg-white">
        <input
          type="text"
          value={saisie}
          onChange={(e) => setSaisie(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && envoyerQuestion()}
          placeholder="Ex: Quelle est la composition du tissu principal ?"
          className="flex-1 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <button
          onClick={envoyerQuestion}
          disabled={enAttente || !saisie.trim()}
          className="bg-indigo-600 text-white rounded-xl px-5 py-2.5 hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

/* ============================================================
   ONGLET 3 : À vérifier (Confirmation Marque Sans Redondance)
   ============================================================ */
function OngletVerification({ enAttente, chargerEnAttente, chargerDocuments }) {
  const [saisies, setSaisies] = useState({});

  const validerConfirmation = async (item) => {
    const s = saisies[item.id] || {};
    if (!s.marque || !s.motif) {
      alert("Veuillez remplir la marque ET le motif de recherche.");
      return;
    }

    try {
      const url = `${API_BASE}/confirmer-marque/${item.id}?marque=${encodeURIComponent(s.marque)}&motif_memoire=${encodeURIComponent(s.motif)}`;
      const res = await fetch(url, { method: "POST" });
      if (res.ok) {
        chargerEnAttente();
        chargerDocuments();
      }
    } catch (err) {
      alert("Erreur lors de la confirmation : " + err.message);
    }
  };

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-6">
      <div className="flex items-center justify-between border-b border-slate-100 pb-4">
        <div>
          <h2 className="text-base font-bold text-slate-800">Confirmation manuelle des marques</h2>
          <p className="text-xs text-slate-500">Validation unique par dossier pour enrichir la mémoire apprise</p>
        </div>
        <button onClick={chargerEnAttente} className="text-xs text-indigo-600 flex items-center gap-1 font-medium">
          <RefreshCw className="w-3.5 h-3.5" /> Actualiser
        </button>
      </div>

      {enAttente.length === 0 ? (
        <div className="text-center py-12 text-slate-400">
          <CheckCircle2 className="w-10 h-10 mx-auto mb-2 text-emerald-500" />
          <p className="text-sm font-medium">Toutes les marques sont confirmées !</p>
        </div>
      ) : (
        <div className="space-y-4">
          {enAttente.map((item) => (
            <div key={item.id} className="border border-slate-200 rounded-xl p-4 bg-slate-50/50 flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="flex-1">
                <span className="text-xs font-semibold text-indigo-600 block">Document ID: {item.techpack_id}</span>
                <h3 className="text-sm font-bold text-slate-800">{item.nom_dossier}</h3>
              </div>

              <div className="flex items-center gap-3 w-full sm:w-auto">
                <input
                  type="text"
                  placeholder="Vraie Marque (ex: GAS)"
                  onChange={(e) => setSaisies((p) => ({ ...p, [item.id]: { ...p[item.id], marque: e.target.value } }))}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-2 w-full sm:w-36 focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                />
                <input
                  type="text"
                  placeholder="Motif (ex: guidelines_denim)"
                  onChange={(e) => setSaisies((p) => ({ ...p, [item.id]: { ...p[item.id], motif: e.target.value } }))}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-2 w-full sm:w-44 focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                />
                <button
                  onClick={() => validerConfirmation(item)}
                  className="bg-indigo-600 text-white text-xs font-semibold px-4 py-2 rounded-lg hover:bg-indigo-700 transition-colors shrink-0"
                >
                  Confirmer
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}