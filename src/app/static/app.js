document.addEventListener('alpine:init', () => {
    Alpine.data('app', () => ({
        // Tabs
        activeTab: 'sessions', // 'sessions', 'source_db', 'prompts'
        
        // Sessions State
        sessions: [],
        activeSession: null,
        checkItems: [],
        matchResults: {}, // check_item_id -> result
        selectedItem: null,
        
        // Source DB State
        sourceDocs: [],
        selectedDoc: null,
        docItems: [], // items for selected doc (fetched on demand)
        matchingSourceDocIds: [],
        matchedSourceDocs: [],
        
        // Prompts State
        promptTemplates: [],
        selectedPrompt: null,
        editingPrompt: { name: '', content: '', industry: '' },
        isEditingNewPrompt: false,
        
        // Loading States
        loading: {
            sessions: false,
            docs: false,
            prompts: false,
            uploadA: false,
            uploadB: false,
            matching: false,
            export: false,
            docDetails: false
        },
        
        // Forms
        formA: {
            file: null,
            promptTemplateId: '',
            categories: '固定荷重, 積載荷重, 積雪荷重, 風荷重, 地震荷重, 材料強度, その他'
        },
        formB: {
            file: null,
            title: '',
            version: '',
            categories: '固定荷重, 積載荷重, 積雪荷重, 風荷重, 地震荷重, 材料強度, その他'
        },
        
        // Notification
        notification: null, // { type: 'success'|'error', message: '' }
        
        init() {
            this.fetchSessions();
            this.fetchSourceDocs();
            this.fetchPromptTemplates();
        },
        
        showNotification(message, type = 'success') {
            this.notification = { type, message };
            setTimeout(() => {
                if (this.notification && this.notification.message === message) {
                    this.notification = null;
                }
            }, 5000);
        },
        
        // Format dates helper
        formatDate(dateStr) {
            if (!dateStr) return '';
            try {
                const d = new Date(dateStr);
                return d.toLocaleString('ja-JP', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                });
            } catch (e) {
                return dateStr;
            }
        },

        // Helper to get filename from path
        getFilename(path) {
            if (!path) return '';
            const parts = path.split('/');
            const rawFilename = parts[parts.length - 1];
            // Remove UUID prefix if matched
            return rawFilename.replace(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_?/, '');
        },
        
        // ------------------
        // SESSIONS API
        // ------------------
        async fetchSessions() {
            this.loading.sessions = true;
            try {
                const res = await fetch('/api/v1/sessions');
                if (!res.ok) throw new Error('セッションの取得に失敗しました');
                this.sessions = await res.json();
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.sessions = false;
            }
        },
        
        async selectSession(session) {
            this.activeSession = session;
            this.selectedItem = null;
            this.checkItems = [];
            this.matchResults = {};
            this.matchingSourceDocIds = [];
            
            this.loading.sessions = true;
            try {
                // Fetch check items
                const itemsRes = await fetch(`/api/v1/sessions/${session.id}/items`);
                if (!itemsRes.ok) throw new Error('チェック項目の取得に失敗しました');
                this.checkItems = await itemsRes.json();
                
                // Fetch match results
                const resultsRes = await fetch(`/api/v1/sessions/${session.id}/results`);
                if (resultsRes.ok) {
                    const resultsList = await resultsRes.json();
                    this.matchResults = {};
                    resultsList.forEach(r => {
                        this.matchResults[r.check_item_id] = r;
                    });
                    this.updateMatchedSourceDocs();
                }
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.sessions = false;
            }
        },
        
        async uploadFileA() {
            if (!this.formA.file) {
                this.showNotification('PDFファイルを選択してください。', 'error');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', this.formA.file);
            if (this.formA.promptTemplateId) {
                formData.append('prompt_template_id', this.formA.promptTemplateId);
            }
            if (this.formA.categories) {
                formData.append('categories', this.formA.categories);
            }
            
            this.loading.uploadA = true;
            try {
                const res = await fetch('/api/v1/sessions', {
                    method: 'POST',
                    body: formData
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'セッションの作成に失敗しました。');
                }
                const data = await res.json();
                this.showNotification('セッションを作成し、チェック項目を抽出しました。');
                await this.fetchSessions();
                
                // Select newly created session
                const newSession = this.sessions.find(s => s.id === data.id);
                if (newSession) {
                    this.selectSession(newSession);
                }
                
                // Reset form
                this.formA.file = null;
                this.formA.categories = '固定荷重, 積載荷重, 積雪荷重, 風荷重, 地震荷重, 材料強度, その他';
                const fileInput = document.getElementById('file-a-input');
                if (fileInput) fileInput.value = '';
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.uploadA = false;
            }
        },
        
        async runMatching() {
            if (!this.activeSession) return;
            
            this.loading.matching = true;
            try {
                const res = await fetch('/api/v1/match', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        session_id: this.activeSession.id,
                        document_ids: this.matchingSourceDocIds.length > 0 ? this.matchingSourceDocIds : null
                    })
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || '照合処理に失敗しました。');
                }
                const resultsList = await res.json();
                this.matchResults = {};
                resultsList.forEach(r => {
                    this.matchResults[r.check_item_id] = r;
                });
                this.updateMatchedSourceDocs();
                
                // Refresh session list and active session status
                await this.fetchSessions();
                const updated = this.sessions.find(s => s.id === this.activeSession.id);
                if (updated) this.activeSession = updated;
                
                this.showNotification('AI照合が完了しました。');
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.matching = false;
            }
        },
        
        async updateStatus(item, status) {
            const result = this.matchResults[item.id];
            if (!result) {
                this.showNotification('照合結果がありません。まず照合を実行してください。', 'error');
                return;
            }
            
            try {
                const res = await fetch(`/api/v1/results/${result.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status })
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'ステータスの更新に失敗しました。');
                }
                const updatedResult = await res.json();
                this.matchResults[item.id] = updatedResult;
                this.updateMatchedSourceDocs();
                this.showNotification(`ステータスを「${status}」に更新しました。`);
            } catch (err) {
                this.showNotification(err.message, 'error');
            }
        },
        
        async exportAnnotatedPdf() {
            if (!this.activeSession) return;
            
            this.loading.export = true;
            try {
                const res = await fetch(`/api/v1/sessions/${this.activeSession.id}/export`, {
                    method: 'POST'
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'PDFのエクスポートに失敗しました。');
                }
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                
                const originalName = this.getFilename(this.activeSession.file_a_path);
                a.download = `checked_${originalName || 'output.pdf'}`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                
                // Refresh sessions to update status to 'exported'
                await this.fetchSessions();
                const updated = this.sessions.find(s => s.id === this.activeSession.id);
                if (updated) this.activeSession = updated;
                
                this.showNotification('アノテーション済みPDFをダウンロードしました。');
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.export = false;
            }
        },

        async exportExcelReport() {
            if (!this.activeSession) return;
            
            this.loading.export = true;
            try {
                const res = await fetch(`/api/v1/sessions/${this.activeSession.id}/export-excel`, {
                    method: 'POST'
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Excelレポートのエクスポートに失敗しました。');
                }
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                
                const originalName = this.getFilename(this.activeSession.file_a_path);
                const baseName = originalName ? originalName.substring(0, originalName.lastIndexOf('.')) : 'report';
                a.download = `verification_report_${baseName}.xlsx`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                
                // Refresh sessions to update status
                await this.fetchSessions();
                const updated = this.sessions.find(s => s.id === this.activeSession.id);
                if (updated) this.activeSession = updated;
                
                this.showNotification('Excelレポートをダウンロードしました。');
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.export = false;
            }
        },

        async exportSourceAnnotatedPdf(docId, docFilename) {
            if (!this.activeSession) return;
            
            this.loading.export = true;
            try {
                const res = await fetch(`/api/v1/source-documents/sessions/${this.activeSession.id}/source-documents/${docId}/export`, {
                    method: 'POST'
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || '出典PDFのエクスポートに失敗しました。');
                }
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `annotated_${docFilename || 'source.pdf'}`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                this.showNotification(`出典「${docFilename}」の注釈付きPDFをダウンロードしました。`);
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.export = false;
            }
        },

        async exportAllSourceAnnotatedPdfs() {
            if (!this.activeSession) return;
            
            this.loading.export = true;
            try {
                const res = await fetch(`/api/v1/source-documents/sessions/${this.activeSession.id}/export-all`, {
                    method: 'POST'
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || '出典PDFの一括エクスポートに失敗しました。');
                }
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `annotated_sources_${this.activeSession.id.substring(0, 8)}.zip`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                this.showNotification('すべての出典PDFをZIP一括ダウンロードしました。');
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.export = false;
            }
        },

        updateMatchedSourceDocs() {
            if (!this.activeSession) {
                this.matchedSourceDocs = [];
                return;
            }
            
            const counts = {};
            Object.values(this.matchResults).forEach(r => {
                if (r.status === 'approved' && r.source_item && r.source_item.document_id) {
                    const docId = r.source_item.document_id;
                    counts[docId] = (counts[docId] || 0) + 1;
                }
            });
            
            const matched = [];
            this.sourceDocs.forEach(doc => {
                if (counts[doc.id]) {
                    matched.push({
                        id: doc.id,
                        title: doc.title,
                        filename: doc.filename,
                        match_count: counts[doc.id]
                    });
                }
            });
            this.matchedSourceDocs = matched;
        },
        
        // ------------------
        // SOURCE DOCS API
        // ------------------
        async fetchSourceDocs() {
            this.loading.docs = true;
            try {
                const res = await fetch('/api/v1/source-documents');
                if (!res.ok) throw new Error('出典文書リストの取得に失敗しました');
                this.sourceDocs = await res.json();
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.docs = false;
            }
        },
        
        async uploadSourceDoc() {
            if (!this.formB.file) {
                this.showNotification('PDFファイルを選択してください。', 'error');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', this.formB.file);
            formData.append('title', this.formB.title || '');
            formData.append('version', this.formB.version || '');
            if (this.formB.categories) {
                formData.append('categories', this.formB.categories);
            }
            
            this.loading.uploadB = true;
            try {
                const res = await fetch('/api/v1/source-documents', {
                    method: 'POST',
                    body: formData
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || '出典文書のアップロードに失敗しました。');
                }
                this.showNotification('出典文書をアップロードし、データを抽出しました。');
                this.formB.file = null;
                this.formB.title = '';
                this.formB.version = '';
                this.formB.categories = '固定荷重, 積載荷重, 積雪荷重, 風荷重, 地震荷重, 材料強度, その他';
                const fileInput = document.getElementById('file-b-input');
                if (fileInput) fileInput.value = '';
                
                await this.fetchSourceDocs();
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.uploadB = false;
            }
        },
        
        async deleteSourceDoc(docId) {
            if (!confirm('本当にこの出典文書を削除しますか？紐づく抽出データも削除されます。')) return;
            
            this.loading.docs = true;
            try {
                const res = await fetch(`/api/v1/source-documents/${docId}`, {
                    method: 'DELETE'
                });
                if (!res.ok) throw new Error('出典文書の削除に失敗しました');
                this.showNotification('出典文書を削除しました。');
                if (this.selectedDoc && this.selectedDoc.id === docId) {
                    this.selectedDoc = null;
                    this.docItems = [];
                }
                await this.fetchSourceDocs();
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.docs = false;
            }
        },

        async selectSourceDoc(doc) {
            this.selectedDoc = doc;
            this.docItems = [];
            
            this.loading.docDetails = true;
            try {
                const res = await fetch(`/api/v1/source-documents/${doc.id}/items`);
                if (!res.ok) throw new Error('出典データの取得に失敗しました');
                this.docItems = await res.json();
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.docDetails = false;
            }
        },
        
        // ------------------
        // PROMPT TEMPLATES API
        // ------------------
        async fetchPromptTemplates() {
            this.loading.prompts = true;
            try {
                const res = await fetch('/api/v1/prompt-templates');
                if (!res.ok) throw new Error('プロンプトテンプレートの取得に失敗しました');
                this.promptTemplates = await res.json();
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.prompts = false;
            }
        },
        
        selectPrompt(prompt) {
            this.selectedPrompt = prompt;
            this.isEditingNewPrompt = false;
            this.editingPrompt = {
                name: prompt.name,
                content: prompt.content,
                industry: prompt.industry || ''
            };
        },
        
        startNewPrompt() {
            this.selectedPrompt = null;
            this.isEditingNewPrompt = true;
            this.editingPrompt = { name: '', content: '', industry: '建築構造' };
        },
        
        async savePrompt() {
            if (!this.editingPrompt.name || !this.editingPrompt.content) {
                this.showNotification('名前とテンプレート本文は必須入力です。', 'error');
                return;
            }
            
            this.loading.prompts = true;
            try {
                let res;
                if (this.isEditingNewPrompt) {
                    res = await fetch('/api/v1/prompt-templates', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(this.editingPrompt)
                    });
                } else {
                    res = await fetch(`/api/v1/prompt-templates/${this.selectedPrompt.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(this.editingPrompt)
                    });
                }
                
                if (!res.ok) throw new Error('プロンプトテンプレートの保存に失敗しました');
                
                const saved = await res.json();
                this.showNotification('プロンプトテンプレートを保存しました。');
                await this.fetchPromptTemplates();
                this.selectPrompt(saved);
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.prompts = false;
            }
        },
        
        async deletePrompt(promptId) {
            if (!confirm('本当にこのテンプレートを削除しますか？')) return;
            
            this.loading.prompts = true;
            try {
                const res = await fetch(`/api/v1/prompt-templates/${promptId}`, {
                    method: 'DELETE'
                });
                if (!res.ok) throw new Error('テンプレートの削除に失敗しました');
                this.showNotification('テンプレートを削除しました。');
                this.selectedPrompt = null;
                this.isEditingNewPrompt = false;
                await this.fetchPromptTemplates();
            } catch (err) {
                this.showNotification(err.message, 'error');
            } finally {
                this.loading.prompts = false;
            }
        }
    }));
});
