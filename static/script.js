document.addEventListener('DOMContentLoaded', function () {

    // Planner: modal for adding meals
    const modalOverlay = document.getElementById('meal-select-modal');
    const modalClose = document.getElementById('modal-close');
    const modalBody = document.getElementById('modal-meal-list');

    if (modalOverlay) {
        // Close modal on overlay click
        modalOverlay.addEventListener('click', function (e) {
            if (e.target === modalOverlay) {
                closeModal();
            }
        });
        if (modalClose) {
            modalClose.addEventListener('click', closeModal);
        }
    }

    window.openModal = function (date, slot) {
        const modal = document.getElementById('meal-select-modal');
        if (!modal) return;
        document.getElementById('modal-date').value = date;
        document.getElementById('modal-slot').value = slot;
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    };

    window.closeModal = function () {
        const modal = document.getElementById('meal-select-modal');
        if (!modal) return;
        modal.classList.remove('active');
        document.body.style.overflow = '';
    };

    // Close modal on Escape key
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeModal();
    });

    // Tags input management
    const tagsInput = document.getElementById('tags-input');
    const tagsContainer = document.getElementById('tags-container');
    const tagsHidden = document.getElementById('tags-hidden');

    if (tagsInput && tagsContainer && tagsHidden) {
        // Add tag on Enter or comma
        tagsInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                addTag(this.value.trim());
            }
        });

        // Add tag on blur
        tagsInput.addEventListener('blur', function () {
            if (this.value.trim()) {
                addTag(this.value.trim());
            }
        });

        // Click on suggestion tags
        document.querySelectorAll('.tag-suggestion').forEach(function (el) {
            el.addEventListener('click', function () {
                addTag(this.dataset.tag);
                this.style.display = 'none';
            });
        });
    }

    function addTag(value) {
        value = value.replace(/,/g, '').trim().toLowerCase();
        if (!value) return;

        const existing = tagsContainer.querySelectorAll('.tag-item');
        for (let t of existing) {
            if (t.dataset.tag === value) return;
        }

        const tagEl = document.createElement('span');
        tagEl.className = 'tag-item';
        tagEl.dataset.tag = value;
        tagEl.innerHTML = value + ' <button type="button" class="remove-tag" onclick="removeTag(this)">&times;</button>';
        tagsContainer.insertBefore(tagEl, tagsInput);

        tagsInput.value = '';
        updateTagsHidden();
    }

    window.removeTag = function (btn) {
        btn.parentElement.remove();
        updateTagsHidden();
    };

    function updateTagsHidden() {
        const tags = [];
        tagsContainer.querySelectorAll('.tag-item').forEach(function (el) {
            tags.push(el.dataset.tag);
        });
        tagsHidden.value = tags.join(',');
    }

    // Ingredients management
    const ingredientsList = document.getElementById('ingredients-list');
    const addIngredientBtn = document.getElementById('add-ingredient-btn');

    if (ingredientsList && addIngredientBtn) {
        addIngredientBtn.addEventListener('click', function () {
            const row = document.createElement('div');
            row.className = 'ingredient-row';
            row.innerHTML = '<input type="text" name="ingredients" placeholder="Ex: 200g de pâtes" class="ingredient-input"> <button type="button" class="remove-ingredient" onclick="this.parentElement.remove()">&times;</button>';
            ingredientsList.appendChild(row);
            row.querySelector('.ingredient-input').focus();
        });
    }

    // Shopping list: checkbox toggle
    document.querySelectorAll('.shopping-item input[type="checkbox"]').forEach(function (cb) {
        cb.addEventListener('change', function () {
            this.closest('.shopping-item').classList.toggle('checked', this.checked);
        });
    });

    // Confirm delete
    document.querySelectorAll('.confirm-delete').forEach(function (el) {
        el.addEventListener('click', function (e) {
            if (!confirm('Supprimer ce plat ?')) {
                e.preventDefault();
            }
        });
    });

    // Dashboard filters auto-submit
    const filterForm = document.getElementById('filter-form');
    if (filterForm) {
        filterForm.querySelectorAll('select, input').forEach(function (el) {
            el.addEventListener('change', function () {
                filterForm.submit();
            });
        });
    }

});
