document.addEventListener('DOMContentLoaded', function () {

    // ---------- Planner : modale de choix d'un plat ----------
    const modalOverlay = document.getElementById('meal-select-modal');
    const modalClose = document.getElementById('modal-close');
    const modalSearch = document.getElementById('modal-search');

    if (modalOverlay) {
        modalOverlay.addEventListener('click', function (e) {
            if (e.target === modalOverlay) closeModal();
        });
        if (modalClose) modalClose.addEventListener('click', closeModal);
    }

    if (modalSearch) {
        modalSearch.addEventListener('input', function () {
            const q = this.value.trim().toLowerCase();
            document.querySelectorAll('#modal-meal-list .meal-option').forEach(function (el) {
                el.style.display = !q || el.dataset.search.includes(q) ? '' : 'none';
            });
        });
    }

    window.openModal = function (date, slot) {
        const modal = document.getElementById('meal-select-modal');
        if (!modal) return;
        document.getElementById('modal-date').value = date;
        document.getElementById('modal-slot').value = slot;
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        if (modalSearch) { modalSearch.value = ''; modalSearch.dispatchEvent(new Event('input')); modalSearch.focus(); }
    };

    window.closeModal = function () {
        const modal = document.getElementById('meal-select-modal');
        if (!modal) return;
        modal.classList.remove('active');
        document.body.style.overflow = '';
    };

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeModal();
    });

    // ---------- Formulaire plat : tags ----------
    const tagsInput = document.getElementById('tags-input');
    const tagsContainer = document.getElementById('tags-container');
    const tagsHidden = document.getElementById('tags-hidden');

    function addTag(value) {
        value = value.replace(/,/g, '').trim().toLowerCase();
        if (!value) return;
        for (const t of tagsContainer.querySelectorAll('.tag-item')) {
            if (t.dataset.tag === value) return;
        }
        const tagEl = document.createElement('span');
        tagEl.className = 'tag-item';
        tagEl.dataset.tag = value;
        tagEl.textContent = value + ' ';
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'remove-tag';
        btn.innerHTML = '&times;';
        btn.addEventListener('click', function () { tagEl.remove(); updateTagsHidden(); });
        tagEl.appendChild(btn);
        tagsContainer.insertBefore(tagEl, tagsInput);
        tagsInput.value = '';
        updateTagsHidden();
    }

    function updateTagsHidden() {
        tagsHidden.value = Array.from(tagsContainer.querySelectorAll('.tag-item')).map(el => el.dataset.tag).join(',');
    }

    if (tagsInput && tagsContainer && tagsHidden) {
        // Les tags existants (édition) sont chargés depuis le champ caché.
        const initial = tagsHidden.value;
        tagsHidden.value = '';
        initial.split(',').forEach(addTag);

        tagsInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                addTag(this.value);
            }
        });
        tagsInput.addEventListener('blur', function () { addTag(this.value); });
        document.querySelectorAll('.tag-suggestion').forEach(function (el) {
            el.addEventListener('click', function () { addTag(this.dataset.tag); this.style.display = 'none'; });
        });
    }

    // ---------- Formulaire plat : ingrédients et étapes ----------
    function dynamicList(buttonId, listId, html) {
        const list = document.getElementById(listId);
        const btn = document.getElementById(buttonId);
        if (!list || !btn) return;
        btn.addEventListener('click', function () {
            const row = document.createElement('div');
            row.className = 'ingredient-row' + (listId === 'steps-list' ? ' step-row' : '');
            row.innerHTML = html;
            list.appendChild(row);
            row.querySelector('input, textarea').focus();
        });
    }
    const removeBtn = '<button type="button" class="remove-ingredient" onclick="this.parentElement.remove()" aria-label="Retirer">&times;</button>';
    dynamicList('add-ingredient-btn', 'ingredients-list',
        '<input type="text" name="ingredients" placeholder="Ex : 200 g de riz" class="ingredient-input">' + removeBtn);
    dynamicList('add-step-btn', 'steps-list',
        '<textarea name="steps" rows="2" placeholder="Décris l\'étape…"></textarea>' + removeBtn);

    // ---------- Filtres et recherche : mise à jour dynamique (sans rechargement) ----------
    const filterForm = document.getElementById('filter-form');
    if (filterForm && document.getElementById('meals-results')) {
        const searchInput = filterForm.querySelector('input[name="q"]');
        let timer = null, controller = null;

        async function refreshMeals() {
            const params = new URLSearchParams(new FormData(filterForm));
            Array.from(params.keys()).forEach(function (k) { if (!params.get(k)) params.delete(k); });
            const url = '/meals' + (params.toString() ? '?' + params.toString() : '');
            if (controller) controller.abort();
            controller = new AbortController();
            try {
                const res = await fetch(url, { signal: controller.signal, headers: { 'X-Requested-With': 'fetch' } });
                if (!res.ok || res.redirected) { window.location = url; return; }
                const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
                ['meals-results', 'meals-count', 'filter-chips', 'filter-row'].forEach(function (id) {
                    const fresh = doc.getElementById(id), cur = document.getElementById(id);
                    if (fresh && cur) cur.innerHTML = fresh.innerHTML;
                });
                history.replaceState(null, '', url);
            } catch (err) {
                if (err.name !== 'AbortError') window.location = url;
            }
        }

        filterForm.addEventListener('submit', function (e) { e.preventDefault(); clearTimeout(timer); refreshMeals(); });
        filterForm.addEventListener('change', function (e) {
            if (e.target === searchInput) return;
            clearTimeout(timer);
            refreshMeals();
        });
        if (searchInput) {
            searchInput.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(refreshMeals, 250); });
        }
    }

    // ---------- Batch cooking : sélection ----------
    const batchChecks = document.querySelectorAll('.batch-check');
    if (batchChecks.length) {
        const bar = document.getElementById('batch-bar');
        const count = document.getElementById('batch-count');
        const ids = document.getElementById('batch-ids');
        const MAX = 6;
        function refresh() {
            const picked = Array.from(batchChecks).filter(c => c.checked);
            ids.value = picked.map(c => c.value).join(',');
            count.textContent = picked.length;
            bar.hidden = picked.length === 0;
            batchChecks.forEach(function (c) {
                c.closest('.batch-card').classList.toggle('selected', c.checked);
                c.disabled = !c.checked && picked.length >= MAX;
            });
        }
        batchChecks.forEach(c => c.addEventListener('change', refresh));
        refresh();
    }

    // ---------- Liste de courses : cases cochées mémorisées par semaine ----------
    const shopping = document.querySelector('.shopping-container[data-week]');
    if (shopping) {
        const storeKey = 'shopping-' + shopping.dataset.week;
        let checked = {};
        try { checked = JSON.parse(localStorage.getItem(storeKey) || '{}'); } catch (e) { checked = {}; }
        const items = shopping.querySelectorAll('.shopping-item');
        const progress = document.getElementById('shopping-progress');

        function save() { try { localStorage.setItem(storeKey, JSON.stringify(checked)); } catch (e) { /* stockage indisponible */ } }
        function updateProgress() {
            if (!progress) return;
            const done = Array.from(items).filter(i => i.querySelector('input').checked).length;
            progress.textContent = done + ' / ' + items.length + ' dans le panier';
        }
        items.forEach(function (item) {
            const cb = item.querySelector('input');
            cb.checked = !!checked[item.dataset.key];
            item.classList.toggle('checked', cb.checked);
            cb.addEventListener('change', function () {
                item.classList.toggle('checked', cb.checked);
                if (cb.checked) checked[item.dataset.key] = 1; else delete checked[item.dataset.key];
                save();
                updateProgress();
            });
        });
        updateProgress();

        const uncheck = document.getElementById('shopping-uncheck');
        if (uncheck) uncheck.addEventListener('click', function () {
            checked = {};
            save();
            items.forEach(function (i) { i.querySelector('input').checked = false; i.classList.remove('checked'); });
            updateProgress();
        });

        const copy = document.getElementById('shopping-copy');
        if (copy) copy.addEventListener('click', function () {
            const lines = [];
            shopping.querySelectorAll('.aisle, .shopping-item').forEach(function (el) {
                if (el.classList.contains('aisle')) lines.push('\n' + el.textContent.trim());
                else if (!el.querySelector('input').checked) lines.push('- ' + el.querySelector('.item-name').textContent.trim());
            });
            const text = lines.join('\n').trim();
            const done = function () { copy.textContent = '✅ Copié'; setTimeout(function () { copy.textContent = '📋 Copier'; }, 1500); };
            if (navigator.clipboard) navigator.clipboard.writeText(text).then(done);
        });
    }

    // Session batch : cases à cocher simples
    document.querySelectorAll('.batch-recipe ~ *, .detail-columns .shopping-item').forEach(function (el) {
        const cb = el.querySelector && el.querySelector('input[type="checkbox"]');
        if (cb) cb.addEventListener('change', function () { el.classList.toggle('checked', cb.checked); });
    });
});

// =====================================================================
// Mode admin
// =====================================================================
document.addEventListener('DOMContentLoaded', function () {
    function toast(msg) {
        const t = document.createElement('div');
        t.className = 'toast';
        t.textContent = msg;
        document.body.appendChild(t);
        setTimeout(function () { t.remove(); }, 2200);
    }
    async function post(url, body) {
        const res = await fetch(url, { method: 'POST', body: body });
        if (!res.ok) {
            let detail = 'Erreur ' + res.status;
            try { detail = (await res.json()).detail || detail; } catch (e) { /* pas de JSON */ }
            throw new Error(detail);
        }
        return res.json().catch(function () { return {}; });
    }

    // ---- tableau : édition rapide d'un champ ----
    document.querySelectorAll('[data-field]').forEach(function (el) {
        el.addEventListener('change', async function () {
            const fd = new FormData();
            fd.append('field', el.dataset.field);
            fd.append('value', el.value);
            try {
                await post('/admin/meals/' + el.dataset.id + '/field', fd);
                el.classList.remove('saved'); void el.offsetWidth; el.classList.add('saved');
            } catch (e) { toast(e.message); }
        });
        if (el.tagName === 'INPUT') el.addEventListener('keydown', function (e) { if (e.key === 'Enter') el.blur(); });
    });

    // ---- tableau : suppression d'une ligne ----
    document.querySelectorAll('[data-delete]').forEach(function (btn) {
        btn.addEventListener('click', async function () {
            if (!confirm('Supprimer « ' + btn.dataset.name + ' » ?')) return;
            const res = await fetch('/meals/' + btn.dataset.delete + '/delete', { method: 'POST' });
            if (res.ok) { document.getElementById('row-' + btn.dataset.delete).remove(); toast('Supprimé'); }
            else toast('Suppression impossible');
        });
    });

    // ---- tableau : sélection multiple ----
    const checks = document.querySelectorAll('.row-check');
    if (checks.length) {
        const bar = document.getElementById('bulk-bar');
        const count = document.getElementById('bulk-count');
        const all = document.getElementById('check-all');
        const merge = document.getElementById('bulk-merge');
        function refresh() {
            const n = Array.from(checks).filter(c => c.checked).length;
            count.textContent = n;
            bar.hidden = n === 0;
            merge.disabled = n < 2;
            checks.forEach(c => c.closest('tr').classList.toggle('is-selected', c.checked));
        }
        checks.forEach(c => c.addEventListener('change', refresh));
        all.addEventListener('change', function () { checks.forEach(c => { c.checked = all.checked; }); refresh(); });
        refresh();
    }

    // ---- doublons : la recette gardée n'est pas supprimée ----
    document.querySelectorAll('.dup-form').forEach(function (form) {
        function sync() {
            const keep = form.querySelector('input[name="keep"]:checked');
            form.querySelectorAll('.dup-item').forEach(function (item) {
                const radio = item.querySelector('input[name="keep"]');
                item.classList.toggle('keep', radio.checked);
                item.querySelector('.dup-remove').checked = !radio.checked;
            });
        }
        form.querySelectorAll('input[name="keep"]').forEach(r => r.addEventListener('change', sync));
        sync();
    });

    // ---- modale photo ----
    const modal = document.getElementById('img-modal');
    if (!modal) return;
    let current = null;
    const el = id => document.getElementById(id);

    function previewHtml(url, name, region) {
        if (url) return '<img class="photo" src="' + url + '" alt="">';
        return '<div class="photo photo-fallback region-' + region + '"><span>' + name.charAt(0).toUpperCase() + '</span></div>';
    }
    function showPane(name) {
        modal.querySelectorAll('.img-pane').forEach(p => p.classList.toggle('active', p.dataset.pane === name));
        modal.querySelectorAll('.img-tabs .chip').forEach(c => c.classList.toggle('active', c.dataset.pane === name));
    }
    function open(btn) {
        current = { id: btn.dataset.imageEdit, name: btn.dataset.name, url: btn.dataset.url, region: btn.dataset.region };
        el('img-name').textContent = current.name;
        el('img-preview').innerHTML = previewHtml(current.url, current.name, current.region);
        el('img-state').textContent = current.url ? 'Photo actuelle' : 'Aucune photo pour le moment';
        el('img-query').value = current.name;
        el('img-results').innerHTML = '';
        showPane('search');
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
    function close() { modal.classList.remove('active'); document.body.style.overflow = ''; }
    function done(newUrl) {
        toast('Photo enregistrée');
        const row = document.getElementById('row-' + current.id);
        if (row) {
            const thumb = row.querySelector('.thumb-btn');
            thumb.dataset.url = newUrl || '';
            thumb.innerHTML = previewHtml(newUrl, current.name, current.region);
            close();
        } else {
            setTimeout(function () { location.reload(); }, 500);
        }
    }
    async function send(fd) {
        try { const r = await post('/admin/meals/' + current.id + '/image', fd); done(r.image_url); }
        catch (e) { toast(e.message); }
    }

    document.addEventListener('click', function (e) {
        const b = e.target.closest('[data-image-edit]');
        if (b) { e.preventDefault(); e.stopPropagation(); open(b); }
    });
    modal.addEventListener('click', function (e) { if (e.target === modal) close(); });
    modal.querySelector('[data-img-close]').addEventListener('click', close);
    modal.querySelectorAll('.img-tabs .chip').forEach(c => c.addEventListener('click', () => showPane(c.dataset.pane)));

    el('img-clear').addEventListener('click', function () {
        const fd = new FormData(); fd.append('clear', '1'); send(fd);
    });

    el('img-search-form').addEventListener('submit', async function (e) {
        e.preventDefault();
        const box = el('img-results');
        box.innerHTML = '<p class="hint">Recherche…</p>';
        try {
            const res = await fetch('/admin/image-search?q=' + encodeURIComponent(el('img-query').value));
            if (!res.ok) throw new Error((await res.json()).detail || 'Recherche impossible');
            const items = await res.json();
            if (!items.length) { box.innerHTML = '<p class="hint">Aucun résultat. Essaie un autre nom ou colle un lien.</p>'; return; }
            box.innerHTML = '';
            items.forEach(function (it) {
                const b = document.createElement('button');
                b.type = 'button'; b.className = 'img-result'; b.title = it.title;
                const img = document.createElement('img'); img.src = it.thumb; img.loading = 'lazy'; img.alt = '';
                const span = document.createElement('span'); span.textContent = it.title;
                b.appendChild(img); b.appendChild(span);
                b.addEventListener('click', function () {
                    const fd = new FormData();
                    fd.append('url', it.full); fd.append('download', '1'); fd.append('credit', it.credit);
                    send(fd);
                });
                box.appendChild(b);
            });
        } catch (err) { box.innerHTML = '<p class="hint">' + err.message + '</p>'; }
    });

    el('img-url-form').addEventListener('submit', function (e) {
        e.preventDefault();
        const fd = new FormData();
        fd.append('url', el('img-url').value.trim());
        if (el('img-url-download').checked) fd.append('download', '1');
        send(fd);
    });

    function sendFile(file) {
        if (!file) return;
        const fd = new FormData(); fd.append('file', file); send(fd);
    }
    el('img-file').addEventListener('change', function () { sendFile(this.files[0]); });
    const drop = el('img-drop');
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', function (e) { sendFile(e.dataTransfer.files[0]); });
    // coller une image depuis le presse-papiers
    document.addEventListener('paste', function (e) {
        if (!modal.classList.contains('active')) return;
        const f = Array.from(e.clipboardData.files).find(f => f.type.startsWith('image/'));
        if (f) sendFile(f);
    });
});
