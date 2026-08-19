// static/app.js
document.addEventListener("DOMContentLoaded", () => {

    // ── Owner & Demo Mode Detection ──────────────────────────────────────────────
    const urlParams = new URLSearchParams(window.location.search);
    const ownerKey = urlParams.get("key") || "";
    const isOwner = ownerKey.length > 0;

    if (!isOwner) {
        document.getElementById("demo-banner").classList.add("visible");
        document.body.classList.add("demo-mode");
    }

    // ── Toast Notifications ──────────────────────────────────────────────────────
    const toastContainer = document.getElementById("toast-container");
    function showToast(msg, type = "") {
        const el = document.createElement("div");
        el.className = "toast" + (type ? " toast-" + type : "");
        el.textContent = msg;
        toastContainer.appendChild(el);
        setTimeout(() => el.remove(), 3100);
    }

    // ── API Helper ───────────────────────────────────────────────────────────────
    async function apiCall(method, path, body = null) {
        const opts = {
            method,
            headers: { "Content-Type": "application/json" },
        };
        if (isOwner) opts.headers["X-Owner-Token"] = ownerKey;
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(path, opts);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || res.statusText);
        }
        if (res.status === 204) return null;
        return res.json();
    }

    // ── Buffer & Cooldown Controller (Prevents Accidental Double Actions) ──────
    const ACTION_BUFFER_MS = 750;
    let isActionPending = false;
    let lastActionTimestamp = 0;
    const pendingCreations = new Map();

    async function executeWithBuffer(actionFn, buttonEl = null) {
        const now = Date.now();
        if (isActionPending || (now - lastActionTimestamp < ACTION_BUFFER_MS)) {
            return false;
        }
        isActionPending = true;
        lastActionTimestamp = now;
        if (buttonEl) {
            buttonEl.disabled = true;
            buttonEl.style.opacity = "0.6";
            buttonEl.style.cursor = "not-allowed";
        }
        try {
            await actionFn();
        } finally {
            setTimeout(() => {
                isActionPending = false;
                if (buttonEl) {
                    buttonEl.disabled = false;
                    buttonEl.style.opacity = "";
                    buttonEl.style.cursor = "";
                }
            }, ACTION_BUFFER_MS);
        }
        return true;
    }

    // ── Navigation Tabs (Notes vs Graph) ────────────────────────────────────────
    const tabBtnNotes = document.getElementById("tab-btn-notes");
    const tabBtnGraph = document.getElementById("tab-btn-graph");
    const notesView = document.getElementById("notes-view");
    const graphView = document.getElementById("graph-view");

    function switchView(viewName) {
        if (viewName === "notes") {
            tabBtnNotes.classList.add("active");
            tabBtnGraph.classList.remove("active");
            notesView.classList.add("active");
            graphView.classList.remove("active");
            loadNotes();
        } else {
            tabBtnGraph.classList.add("active");
            tabBtnNotes.classList.remove("active");
            graphView.classList.add("active");
            notesView.classList.remove("active");
            setTimeout(() => {
                refreshGraph();
            }, 50);
        }
    }

    tabBtnNotes.addEventListener("click", () => switchView("notes"));
    tabBtnGraph.addEventListener("click", () => switchView("graph"));

    // ════════════════════════════════════════════════════════════════════════════
    // 1. NOTES VIEW (Google Keep Style)
    // ════════════════════════════════════════════════════════════════════════════

    let allNotes = [];
    let activeQuickColor = "default";
    let activeModalColor = "default";
    let editingNoteId = null;

    const notesGrid = document.getElementById("notes-grid");
    const searchNotesInput = document.getElementById("search-notes-input");

    // Quick "Take a note..." Bar Logic
    const takeNoteContainer = document.getElementById("take-note-container");
    const takeNoteCollapsed = document.getElementById("take-note-collapsed");
    const takeNoteExpanded = document.getElementById("take-note-expanded");
    const quickNotePlaceholder = document.getElementById("quick-note-placeholder");
    const quickNoteTitle = document.getElementById("quick-note-title");
    const quickNoteContent = document.getElementById("quick-note-content");
    const quickNoteCloseBtn = document.getElementById("quick-note-close-btn");
    const quickNoteSaveBtn = document.getElementById("quick-note-save-btn");
    const quickColorPicker = document.getElementById("quick-color-picker");
    const quickSyntaxToggleBtn = document.getElementById("quick-syntax-toggle-btn");
    const quickSyntaxGuidePanel = document.getElementById("quick-syntax-guide-panel");

    quickNotePlaceholder.addEventListener("click", () => {
        takeNoteCollapsed.style.display = "none";
        takeNoteExpanded.style.display = "block";
        quickNoteTitle.focus();
    });

    if (quickSyntaxToggleBtn && quickSyntaxGuidePanel) {
        quickSyntaxToggleBtn.addEventListener("click", () => {
            const isHidden = quickSyntaxGuidePanel.style.display === "none";
            quickSyntaxGuidePanel.style.display = isHidden ? "block" : "none";
        });
    }

    quickNoteCloseBtn.addEventListener("click", resetQuickNoteBar);

    function resetQuickNoteBar() {
        quickNoteTitle.value = "";
        quickNoteContent.value = "";
        activeQuickColor = "default";
        updateColorDots(quickColorPicker, "default");
        if (quickSyntaxGuidePanel) quickSyntaxGuidePanel.style.display = "none";
        takeNoteExpanded.style.display = "none";
        takeNoteCollapsed.style.display = "block";
    }

    // Keyboard shortcuts for Quick Note (Cmd + Enter or Ctrl + Enter to save)
    [quickNoteTitle, quickNoteContent].forEach(inputEl => {
        if (!inputEl) return;
        inputEl.addEventListener("keydown", (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                if (!isActionPending && (Date.now() - lastActionTimestamp >= ACTION_BUFFER_MS)) {
                    quickNoteSaveBtn.click();
                }
            } else if (e.key === "Escape") {
                resetQuickNoteBar();
            }
        });
    });

    // Auto-save on click outside Take Note container
    document.addEventListener("click", (e) => {
        if (takeNoteExpanded.style.display !== "none" && !takeNoteContainer.contains(e.target)) {
            if (isActionPending || (Date.now() - lastActionTimestamp < ACTION_BUFFER_MS)) return;
            const title = quickNoteTitle.value.trim();
            const content = quickNoteContent.value.trim();
            if (title || content) {
                quickNoteSaveBtn.click();
            } else {
                resetQuickNoteBar();
            }
        }
    });

    // Color Pickers Setup
    function setupColorPicker(pickerContainer, onSelect) {
        const dots = pickerContainer.querySelectorAll(".color-dot");
        dots.forEach(dot => {
            dot.addEventListener("click", (e) => {
                e.stopPropagation();
                const color = dot.getAttribute("data-color");
                dots.forEach(d => d.classList.remove("active"));
                dot.classList.add("active");
                onSelect(color);
            });
        });
    }

    function updateColorDots(pickerContainer, color) {
        const dots = pickerContainer.querySelectorAll(".color-dot");
        dots.forEach(dot => {
            if (dot.getAttribute("data-color") === color) {
                dot.classList.add("active");
            } else {
                dot.classList.remove("active");
            }
        });
    }

    setupColorPicker(quickColorPicker, (color) => { activeQuickColor = color; });

    quickNoteSaveBtn.addEventListener("click", async () => {
        const title = quickNoteTitle.value.trim();
        const content = quickNoteContent.value.trim();
        const color = activeQuickColor;
        if (!title && !content) {
            resetQuickNoteBar();
            return;
        }

        // 1. Immediately clear entry boxes and reset quick note bar
        resetQuickNoteBar();
        showToast("✨ Note created!", "success");

        // 2. Execute note creation with 750ms buffer and draft restoration on error
        await executeWithBuffer(async () => {
            try {
                await handleSaveNote({ title, content, color, pinned: false });
            } catch (err) {
                // Restore draft text if save failed
                takeNoteCollapsed.style.display = "none";
                takeNoteExpanded.style.display = "block";
                quickNoteTitle.value = title;
                quickNoteContent.value = content;
                showToast("❌ Creation failed — draft restored to entry box.", "error");
            }
        }, quickNoteSaveBtn);
    });

    // Fetch and render notes
    let hasLoadedNotes = false;
    async function loadNotes(force = false) {
        if (hasLoadedNotes && !force) return;
        try {
            allNotes = await apiCall("GET", "/api/notes");
            hasLoadedNotes = true;
            renderNotesGrid();
        } catch (err) {
            console.error("Failed to load notes:", err);
            showToast("Failed to load notes.", "error");
        }
    }


    function renderNotesGrid() {
        notesGrid.innerHTML = "";
        const query = searchNotesInput.value.toLowerCase().trim();

        const filtered = allNotes.filter(n => {
            if (!query) return true;
            return (n.title && n.title.toLowerCase().includes(query)) ||
                   (n.content && n.content.toLowerCase().includes(query));
        });

        if (filtered.length === 0) {
            notesGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-secondary); padding: 40px;">No notes found. Click "Take a note..." above to create one.</div>`;
            return;
        }

        filtered.forEach(note => {
            const card = document.createElement("div");
            card.className = `note-card note-color-${note.color || 'default'}`;

            // Pin button
            const pinBtn = document.createElement("button");
            pinBtn.className = `note-card-pin-btn ${note.pinned ? 'pinned' : ''}`;
            pinBtn.innerHTML = note.pinned ? '📌' : '📌';
            pinBtn.title = note.pinned ? 'Unpin note' : 'Pin note';
            pinBtn.addEventListener("click", async (e) => {
                e.stopPropagation();
                await handleUpdateNote(note.id, { pinned: !note.pinned });
            });

            // 1-Click Trash/Delete button directly on card hover
            const trashBtn = document.createElement("button");
            trashBtn.className = "note-card-trash-btn";
            trashBtn.innerHTML = "🗑";
            trashBtn.title = "Delete note";
            trashBtn.addEventListener("click", async (e) => {
                e.stopPropagation();
                await handleDeleteNote(note.id);
            });

            const titleEl = document.createElement("div");
            titleEl.className = "note-card-title";
            titleEl.textContent = note.title || "Untitled";

            const contentEl = document.createElement("div");
            contentEl.className = "note-card-content";
            contentEl.textContent = note.content || "";

            card.appendChild(pinBtn);
            card.appendChild(trashBtn);
            if (note.title) card.appendChild(titleEl);
            card.appendChild(contentEl);

            // Add fade gradient if content exceeds maximum truncated preview height
            setTimeout(() => {
                if (contentEl.scrollHeight > 165) {
                    contentEl.classList.add("is-truncated");
                }
            }, 10);

            card.addEventListener("click", () => openNoteModal(note));

            notesGrid.appendChild(card);
        });
    }

    searchNotesInput.addEventListener("input", renderNotesGrid);

    // ── Sync Status Badge Controller ──────────────────────────────────────────
    const syncStatusBadge = document.getElementById("sync-status-badge");
    const syncStatusText = document.getElementById("sync-status-text");

    function updateSyncStatus(state, msg = "") {
        if (!syncStatusBadge || !syncStatusText) return;
        syncStatusBadge.className = "sync-badge " + state;
        if (state === "synced") {
            syncStatusText.textContent = msg || "Synced";
        } else if (state === "syncing") {
            syncStatusText.textContent = msg || "Syncing graph...";
        } else if (state === "error") {
            syncStatusText.textContent = msg || "Sync error (retry)";
        }
    }

    if (syncStatusBadge) {
        syncStatusBadge.addEventListener("click", () => {
            if (syncStatusBadge.classList.contains("error")) {
                updateSyncStatus("syncing", "Retrying sync...");
                loadNotes(true).then(() => {
                    refreshGraph(true);
                    updateSyncStatus("synced", "Synced");
                }).catch(() => {
                    updateSyncStatus("error", "Sync error");
                });
            }
        });
    }

    // Save/Update Note Logic (0ms Optimistic UI + Background Sync)
    async function handleSaveNote(noteData) {
        // 1. Instant 0ms Optimistic UI Update
        const tempId = "temp-" + Date.now();
        const optimisticNote = {
            id: tempId,
            ...noteData,
            source: "manual",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString()
        };
        
        allNotes.unshift(optimisticNote);
        renderNotesGrid();

        if (!isOwner) {
            showToast("✏️ Demo mode — note saved locally.", "warn");
            return optimisticNote;
        }

        // 2. Background Sync
        updateSyncStatus("syncing", "Syncing graph...");
        const syncPromise = (async () => {
            try {
                const savedNote = await apiCall("POST", "/api/notes", noteData);
                const idx = allNotes.findIndex(n => n.id === tempId);
                if (idx !== -1) allNotes[idx] = savedNote;
                if (editingNoteId === tempId) editingNoteId = savedNote.id;
                renderNotesGrid();
                refreshGraph(true);
                updateSyncStatus("synced", "Synced");
                showToast("✅ Note saved & graph synced!", "success");
                return savedNote;

            } catch (err) {
                const idx = allNotes.findIndex(n => n.id === tempId);
                if (idx !== -1) {
                    allNotes.splice(idx, 1);
                    renderNotesGrid();
                }
                updateSyncStatus("error", "Sync error");
                showToast("❌ Save failed: " + err.message, "error");
                throw err;
            } finally {
                pendingCreations.delete(tempId);
            }
        })();

        pendingCreations.set(tempId, syncPromise);
        return syncPromise;
    }

    async function handleUpdateNote(noteId, updates) {
        // 1. Instant 0ms Optimistic UI Update
        const noteIndex = allNotes.findIndex(n => n.id === noteId);
        let backupNote = null;
        if (noteIndex !== -1) {
            backupNote = { ...allNotes[noteIndex] };
            Object.assign(allNotes[noteIndex], updates, { updated_at: new Date().toISOString() });
            renderNotesGrid();
        }

        if (!isOwner) {
            showToast("✏️ Demo mode — changes won't persist.", "warn");
            return;
        }

        let targetId = noteId;
        if (typeof noteId === "string" && noteId.startsWith("temp-")) {
            if (pendingCreations.has(noteId)) {
                updateSyncStatus("syncing", "Waiting for creation before updating...");
                try {
                    const savedNote = await pendingCreations.get(noteId);
                    if (savedNote && savedNote.id) {
                        targetId = savedNote.id;
                    } else {
                        return;
                    }
                } catch (err) {
                    return;
                }
            } else {
                return;
            }
        }

        // 2. Background Sync
        updateSyncStatus("syncing", "Syncing graph...");
        try {
            const updated = await apiCall("PUT", `/api/notes/${targetId}`, updates);
            const idx = allNotes.findIndex(n => n.id === targetId || n.id === noteId);
            if (idx !== -1) allNotes[idx] = updated;
            renderNotesGrid();
            refreshGraph(true);
            updateSyncStatus("synced", "Synced");
        } catch (err) {
            if (noteIndex !== -1 && backupNote) {
                allNotes[noteIndex] = backupNote;
                renderNotesGrid();
            }
            updateSyncStatus("error", "Sync error");
            showToast("❌ Update failed: " + err.message, "error");
        }
    }

    async function handleDeleteNote(noteId) {
        if (!confirm("Are you sure you want to delete this note?")) return;

        // 1. Instant 0ms Optimistic UI Update
        const noteIndex = allNotes.findIndex(n => n.id === noteId);
        let deletedNote = null;
        if (noteIndex !== -1) {
            deletedNote = allNotes[noteIndex];
            allNotes.splice(noteIndex, 1);
            renderNotesGrid();
            closeModal();
        }

        if (!isOwner) {
            showToast("✏️ Demo mode — note deleted locally.", "warn");
            return;
        }

        let targetId = noteId;
        if (typeof noteId === "string" && noteId.startsWith("temp-")) {
            if (pendingCreations.has(noteId)) {
                updateSyncStatus("syncing", "Waiting for creation before deleting...");
                try {
                    const savedNote = await pendingCreations.get(noteId);
                    if (savedNote && savedNote.id) {
                        targetId = savedNote.id;
                    } else {
                        return;
                    }
                } catch (err) {
                    return;
                }
            } else {
                return;
            }
        }

        // 2. Background Sync
        updateSyncStatus("syncing", "Syncing graph...");
        try {
            await apiCall("DELETE", `/api/notes/${targetId}`);
            refreshGraph(true);
            updateSyncStatus("synced", "Synced");
            showToast("✅ Note deleted & graph synced!", "success");

        } catch (err) {
            if (deletedNote && noteIndex !== -1) {
                allNotes.splice(noteIndex, 0, deletedNote);
                renderNotesGrid();
            }
            updateSyncStatus("error", "Sync error");
            showToast("❌ Delete failed: " + err.message, "error");
        }
    }

    // ── Note Modal Editor & Syntax Cheatsheet ──────────────────────────────────
    const modalOverlay = document.getElementById("modal-overlay");
    const noteModalBox = document.getElementById("note-modal-box");
    const directModalBox = document.getElementById("direct-modal-box");
    const noteModalTitle = document.getElementById("note-modal-title");
    const noteModalContent = document.getElementById("note-modal-content");
    const modalColorPicker = document.getElementById("modal-color-picker");
    const syntaxGuideToggleBtn = document.getElementById("syntax-guide-toggle-btn");
    const syntaxGuidePanel = document.getElementById("syntax-guide-panel");
    const noteModalCloseBtn = document.getElementById("note-modal-close-btn");
    const noteModalCancelBtn = document.getElementById("note-modal-cancel-btn");
    const noteModalSaveBtn = document.getElementById("note-modal-save-btn");
    const noteModalDeleteBtn = document.getElementById("note-modal-delete-btn");

    setupColorPicker(modalColorPicker, (color) => { activeModalColor = color; });

    syntaxGuideToggleBtn.addEventListener("click", () => {
        const isHidden = syntaxGuidePanel.style.display === "none";
        syntaxGuidePanel.style.display = isHidden ? "block" : "none";
    });

    function openNoteModal(note = null) {
        noteModalBox.style.display = "block";
        directModalBox.style.display = "none";
        syntaxGuidePanel.style.display = "none";

        if (note) {
            editingNoteId = note.id;
            noteModalTitle.value = note.title || "";
            noteModalContent.value = note.content || "";
            activeModalColor = note.color || "default";
            updateColorDots(modalColorPicker, activeModalColor);
            noteModalDeleteBtn.style.display = "inline-flex";
        } else {
            editingNoteId = null;
            noteModalTitle.value = "";
            noteModalContent.value = "";
            activeModalColor = "default";
            updateColorDots(modalColorPicker, "default");
            noteModalDeleteBtn.style.display = "none";
        }

        modalOverlay.classList.add("open");
        setTimeout(() => noteModalContent.focus(), 100);
    }

    function closeModal() {
        modalOverlay.classList.remove("open");
        noteModalBox.style.display = "none";
        directModalBox.style.display = "none";
        editingNoteId = null;
    }

    noteModalCloseBtn.addEventListener("click", closeModal);
    noteModalCancelBtn.addEventListener("click", closeModal);
    document.getElementById("direct-modal-close-btn").addEventListener("click", closeModal);
    modalOverlay.addEventListener("click", e => { if (e.target === modalOverlay) closeModal(); });

    noteModalSaveBtn.addEventListener("click", async () => {
        const title = noteModalTitle.value.trim();
        const content = noteModalContent.value.trim();
        const color = activeModalColor;
        const targetEditingId = editingNoteId;

        if (!title && !content) { closeModal(); return; }

        // 1. Immediately close modal & clear modal inputs
        closeModal();
        showToast(targetEditingId ? "✨ Note updated!" : "✨ Note created!", "success");

        // 2. Execute modal save/update with 750ms buffer and error restoration
        await executeWithBuffer(async () => {
            try {
                if (targetEditingId) {
                    await handleUpdateNote(targetEditingId, { title, content, color });
                } else {
                    await handleSaveNote({ title, content, color, pinned: false });
                }
            } catch (err) {
                // Restore modal with draft text if operation failed
                openNoteModal({ id: targetEditingId, title, content, color });
                showToast("❌ Operation failed — draft restored to modal.", "error");
            }
        }, noteModalSaveBtn);
    });

    noteModalDeleteBtn.addEventListener("click", async () => {
        if (editingNoteId) {
            await handleDeleteNote(editingNoteId);
        }
    });

    // ════════════════════════════════════════════════════════════════════════════
    // 2. GRAPH VIEW (D3 Force Simulation & Position Caching)
    // ════════════════════════════════════════════════════════════════════════════

    const colors = { group: "#ec4899", person: "#10b981", default: "#94a3b8" };
    const svg = d3.select("#graph-svg");
    const container = d3.select("#canvas-container");
    const searchInput = document.getElementById("search-input");
    const filterMembership = document.getElementById("filter-membership");
    const filterIntroduction = document.getElementById("filter-introduction");
    const resetButton = document.getElementById("reset-button");
    const detailCard = document.getElementById("detail-card");
    const closeCardBtn = document.getElementById("close-card-btn");
    const cardName = document.getElementById("card-name");
    const cardTypeBadge = document.getElementById("card-type-badge");
    const cardMetadata = document.getElementById("card-metadata");
    const cardContexts = document.getElementById("card-contexts");

    let width = container.node() ? container.node().clientWidth : window.innerWidth;
    let height = container.node() ? container.node().clientHeight : window.innerHeight;
    svg.attr("width", width).attr("height", height);

    const g = svg.append("g");

    const zoom = d3.zoom()
        .scaleExtent([0.1, 8])
        .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);

    const simulation = d3.forceSimulation()
        .force("link", d3.forceLink().id(d => d.id).distance(d => d.type === "membership" ? 28 : 50))
        .force("charge", d3.forceManyBody().strength(-60))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collision", d3.forceCollide().radius(15))
        .force("x", d3.forceX(width / 2).strength(0.14))
        .force("y", d3.forceY(height / 2).strength(0.14));

    let allNodes = [];
    let allLinks = [];
    let linkElements, nodeElements;
    let selectedNode = null;

    // ── LocalStorage Node Position Cache Helpers ──────────────────────────────
    const POS_CACHE_KEY = "social_tree_node_positions";

    function getSavedPositions() {
        try {
            const parsed = JSON.parse(localStorage.getItem(POS_CACHE_KEY) || "{}");
            const clean = {};
            for (const [id, pos] of Object.entries(parsed)) {
                if (pos && typeof pos.x === "number" && !isNaN(pos.x) && typeof pos.y === "number" && !isNaN(pos.y)) {
                    clean[id] = pos;
                }
            }
            return clean;
        } catch (e) {
            return {};
        }
    }

    function savePositions() {
        const positions = {};
        allNodes.forEach(n => {
            if (typeof n.x === "number" && !isNaN(n.x) && typeof n.y === "number" && !isNaN(n.y)) {
                positions[n.id] = { x: n.x, y: n.y };
            }
        });
        try {
            localStorage.setItem(POS_CACHE_KEY, JSON.stringify(positions));
        } catch (e) {
            console.warn("Could not save positions to localStorage:", e);
        }
    }

    let hasLoadedGraph = false;
    function refreshGraph(force = false) {
        if (hasLoadedGraph && !force && allNodes.length > 0) {
            updateGraph();
            return;
        }
        fetch("/api/graph")
            .then(r => r.json())
            .then(data => {
                allNodes = data.nodes;
                allLinks = data.edges;
                hasLoadedGraph = true;
                
                // Restore saved positions if available
                const saved = getSavedPositions();
                allNodes.forEach(n => {
                    if (saved[n.id]) {
                        n.x = saved[n.id].x;
                        n.y = saved[n.id].y;
                    }
                });

                updateGraph();
                setupSearch();
                setupFilters();
            })
            .catch(err => {
                console.error("Error loading graph:", err);
            });
    }


    // ── HSL Cluster Color & Centrality Heatmap Helpers ────────────────────────
    function getContextColor(contextName) {
        if (!contextName) return "#10b981";
        let hash = 0;
        for (let i = 0; i < contextName.length; i++) {
            hash = contextName.charCodeAt(i) + ((hash << 5) - hash);
        }
        const hue = Math.abs(hash) % 360;
        return `hsl(${hue}, 85%, 62%)`;
    }

    function getNodeColor(node) {
        if (node.type === "group") {
            return getContextColor(node.name);
        }
        if (node.contexts && node.contexts.length > 0) {
            return getContextColor(node.contexts[0]);
        }
        return "#10b981";
    }

    function updateGraph() {
        g.selectAll("*").remove();

        width = container.node() ? (container.node().clientWidth || window.innerWidth) : window.innerWidth;
        height = container.node() ? (container.node().clientHeight || window.innerHeight) : window.innerHeight;
        svg.attr("width", width).attr("height", height);

        simulation.force("center", d3.forceCenter(width / 2, height / 2));
        simulation.force("x", d3.forceX(width / 2).strength(0.14));
        simulation.force("y", d3.forceY(height / 2).strength(0.14));

        g.append("defs").selectAll("marker")
            .data(["introduction", "membership"])
            .enter().append("marker")
            .attr("id", d => `arrow-${d}`)
            .attr("viewBox", "0 -5 10 10")
            .attr("refX", 22).attr("refY", 0)
            .attr("markerWidth", 6).attr("markerHeight", 6)
            .attr("orient", "auto")
            .append("path")
            .attr("fill", d => d === "membership" ? "#ec4899" : "#94a3b8")
            .attr("d", "M0,-5L10,0L0,5");

        const showMembership = filterMembership.checked;
        const showIntroduction = filterIntroduction.checked;

        const filteredLinks = allLinks.filter(l => {
            if (l.type === "membership" && !showMembership) return false;
            if (l.type === "introduction" && !showIntroduction) return false;
            return true;
        });

        // Calculate node degree centrality (connectivity count)
        const nodeDegree = {};
        filteredLinks.forEach(l => {
            const srcId = typeof l.source === "object" ? l.source.id : l.source;
            const tgtId = typeof l.target === "object" ? l.target.id : l.target;
            nodeDegree[srcId] = (nodeDegree[srcId] || 0) + 1;
            nodeDegree[tgtId] = (nodeDegree[tgtId] || 0) + 1;
        });

        const filteredNodes = allNodes.filter(n => {
            if (!showMembership && !showIntroduction) return false;
            return true;
        });

        linkElements = g.append("g").attr("class", "links")
            .selectAll("line").data(filteredLinks).enter().append("line")
            .attr("class", d => `link ${d.type}`)
            .style("stroke", d => {
                if (d.type === "membership") {
                    const tgtId = typeof d.target === "object" ? d.target.id : d.target;
                    const tgtNode = allNodes.find(n => n.id === tgtId);
                    return tgtNode ? getNodeColor(tgtNode) : "#ec4899";
                }
                return "#94a3b8";
            })
            .style("stroke-dasharray", d => d.type === "membership" ? "3,3" : "none")
            .attr("marker-end", d => `url(#arrow-${d.type})`);

        nodeElements = g.append("g").attr("class", "nodes")
            .selectAll(".node").data(filteredNodes).enter().append("g")
            .attr("class", "node")
            .call(drag(simulation))
            .on("click", handleNodeClick)
            .on("mouseover", handleMouseOver)
            .on("mouseout", handleMouseOut);

        // Render colorful nodes with centrality sizing & neon aura
        nodeElements.append("circle")
            .attr("r", d => {
                const deg = nodeDegree[d.id] || 0;
                if (d.type === "group") return 11 + Math.min(deg, 8) * 0.8;
                return 6 + Math.min(deg, 6) * 1.2;
            })
            .attr("fill", d => getNodeColor(d))
            .style("filter", d => {
                const c = getNodeColor(d);
                const deg = nodeDegree[d.id] || 0;
                if (deg >= 4 || d.type === "group") {
                    return `drop-shadow(0px 0px 8px ${c})`;
                }
                return `drop-shadow(0px 0px 3px ${c}80)`;
            })
            .style("stroke", d => {
                const deg = nodeDegree[d.id] || 0;
                return deg >= 4 ? "#ffffff" : "rgba(11, 15, 25, 0.8)";
            })
            .style("stroke-width", d => {
                const deg = nodeDegree[d.id] || 0;
                return deg >= 4 ? "2px" : "1px";
            });

        nodeElements.append("text")
            .attr("dx", d => {
                const deg = nodeDegree[d.id] || 0;
                return (d.type === "group" ? 14 : 9) + Math.min(deg, 6);
            })
            .attr("dy", ".35em")
            .text(d => d.name);

        simulation.nodes(filteredNodes);
        simulation.force("link").links(filteredLinks);
        simulation.alpha(0.8).restart();

        simulation.on("tick", () => {
            linkElements
                .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
            nodeElements.attr("transform", d => `translate(${d.x},${d.y})`);
        });

        // Save position cache when simulation finishes settling
        simulation.on("end", savePositions);
    }

    function handleNodeClick(event, d) {
        event.stopPropagation();
        selectedNode = d;

        cardName.textContent = d.name;
        cardTypeBadge.textContent = d.type;
        cardTypeBadge.style.backgroundColor = (d.type === "group" ? colors.group : colors.person) + "40";
        cardTypeBadge.style.color = d.type === "group" ? colors.group : colors.person;

        cardMetadata.innerHTML = "";
        const meta = d.metadata || [];
        if (meta.length > 0) {
            meta.forEach(tag => {
                const span = document.createElement("span");
                span.className = "tag"; span.textContent = tag;
                cardMetadata.appendChild(span);
            });
        } else { cardMetadata.textContent = "None"; }

        cardContexts.innerHTML = "";
        const ctxs = d.contexts || [];
        if (ctxs.length > 0) {
            ctxs.forEach(tag => {
                const span = document.createElement("span");
                span.className = "tag"; span.textContent = tag;
                cardContexts.appendChild(span);
            });
        } else { cardContexts.textContent = "None"; }

        detailCard.style.display = "block";
    }

    closeCardBtn.addEventListener("click", () => {
        detailCard.style.display = "none";
        selectedNode = null;
    });

    document.getElementById("card-edit-btn").addEventListener("click", () => {
        if (!selectedNode) return;
        // Search for node's note in allNotes or open node modal
        showToast("Tip: Edit the note corresponding to this node in the Notes tab!", "info");
    });

    function handleMouseOver(event, d) {
        const connected = new Set([d.id]);
        linkElements.each(l => {
            const src = l.source.id, tgt = l.target.id;
            if (src === d.id) connected.add(tgt);
            if (tgt === d.id) connected.add(src);
        });
        nodeElements.classed("dimmed", n => !connected.has(n.id));
        linkElements.classed("dimmed", l => l.source.id !== d.id && l.target.id !== d.id);
    }

    function handleMouseOut() {
        nodeElements.classed("dimmed", false);
        linkElements.classed("dimmed", false);
    }

    function setupSearch() {
        searchInput.addEventListener("input", e => {
            const q = e.target.value.toLowerCase().trim();
            if (!q) {
                nodeElements.classed("highlighted", false).classed("dimmed", false);
                linkElements.classed("dimmed", false);
                return;
            }
            const matches = new Set();
            nodeElements.each(d => {
                const nameMatch = d.name && d.name.toLowerCase().includes(q);
                const typeMatch = d.type && d.type.toLowerCase().includes(q);
                const metaMatch = d.metadata && d.metadata.some(m => m.toLowerCase().includes(q));
                const ctxMatch = d.contexts && d.contexts.some(c => c.toLowerCase().includes(q));

                if (nameMatch || typeMatch || metaMatch || ctxMatch) {
                    matches.add(d.id);
                }
            });
            nodeElements.classed("highlighted", d => matches.has(d.id)).classed("dimmed", d => !matches.has(d.id));
            linkElements.classed("dimmed", true);
        });
    }

    function setupFilters() {
        filterMembership.addEventListener("change", updateGraph);
        filterIntroduction.addEventListener("change", updateGraph);
        resetButton.addEventListener("click", () => {
            filterMembership.checked = true;
            filterIntroduction.checked = true;
            searchInput.value = "";
            detailCard.style.display = "none";
            selectedNode = null;
            localStorage.removeItem(POS_CACHE_KEY); // Clear position cache on reset
            refreshGraph(true);
            svg.transition().duration(750).call(zoom.transform, d3.zoomIdentity);
        });
    }

    function drag(sim) {
        return d3.drag()
            .on("start", (e) => { if (!e.active) sim.alphaTarget(0.3).restart(); e.subject.fx = e.subject.x; e.subject.fy = e.subject.y; })
            .on("drag",  (e) => { e.subject.fx = e.x; e.subject.fy = e.y; })
            .on("end",   (e) => {
                if (!e.active) sim.alphaTarget(0);
                e.subject.fx = null;
                e.subject.fy = null;
                savePositions();
            });
    }

    // Direct Add Buttons on Graph View
    document.getElementById("btn-add-person").addEventListener("click", () => openNoteModal({ title: "New Note", content: "Name" }));
    document.getElementById("btn-add-group").addEventListener("click", () => openNoteModal({ title: "Group Name:", content: "- Person 1\n- Person 2" }));
    document.getElementById("btn-add-connection").addEventListener("click", () => openNoteModal({ title: "Introductions", content: "Alice -> Bob" }));

    // ── Mobile Control Drawer Logic ──────────────────────────────────────────
    const mobileToggleFab = document.getElementById("btn-mobile-toggle-controls");
    const mobileCloseBtn = document.getElementById("btn-close-mobile-controls");
    const controlPanelEl = document.getElementById("control-panel");
    const graphSvgEl = document.getElementById("graph-svg");

    if (mobileToggleFab && controlPanelEl) {
        mobileToggleFab.addEventListener("click", (e) => {
            e.stopPropagation();
            controlPanelEl.classList.add("mobile-open");
        });
    }

    if (mobileCloseBtn && controlPanelEl) {
        mobileCloseBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            controlPanelEl.classList.remove("mobile-open");
        });
    }

    if (graphSvgEl && controlPanelEl) {
        graphSvgEl.addEventListener("click", () => {
            if (window.innerWidth <= 768 && controlPanelEl.classList.contains("mobile-open")) {
                controlPanelEl.classList.remove("mobile-open");
            }
        });
    }

    // ── Initial Load ─────────────────────────────────────────────────────────────
    loadNotes();


    document.addEventListener("keydown", e => {
        if (e.key === "Escape") {
            closeModal();
            if (controlPanelEl) controlPanelEl.classList.remove("mobile-open");
        }
    });
});
