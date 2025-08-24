// /static/js/notes.js
document.addEventListener('DOMContentLoaded', () => {
    const guideletList = document.getElementById('guidelet-list');
    const notesFeed = document.getElementById('notes-feed');
    const currentGuideletTitle = document.getElementById('current-guidelet-title');
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    let allNotesData = {};

    function renderNotes(guideletId) {
        notesFeed.innerHTML = ''; // Clear current notes
        const data = allNotesData[guideletId];
        if (!data || !data.notes.length) {
            notesFeed.innerHTML = '<p>You haven\'t saved any notes for this guidelet yet.</p>';
            currentGuideletTitle.textContent = data ? data.guidelet_title : 'No notes found.';
            return;
        }

        currentGuideletTitle.textContent = data.guidelet_title;

        data.notes.forEach(note => {
            const noteCard = document.createElement('div');
            noteCard.className = 'note-card';
            noteCard.dataset.noteId = note.id;

            const contextUrl = `/guidelet/${note.guidelet_id}/${note.chapter_number}?scrollTo=${note.message_index}`;

            noteCard.innerHTML = `
                <div class="note-card-saved-content">"${note.saved_content}"</div>
                <div class="note-card-user-thoughts">
                    <textarea class="user-comment-textarea" placeholder="Click to add your thoughts...">${note.user_comment}</textarea>
                </div>
                <div class="note-card-footer">
                    <button class="btn btn-danger delete-note-btn">Delete Note</button>
                    <a href="${contextUrl}" target="_blank" class="context-btn">View in Context</a>
                </div>
            `;
            notesFeed.appendChild(noteCard);
        });
    }

    function renderGuideletList() {
        guideletList.innerHTML = '';
        const guideletIds = Object.keys(allNotesData);

        if (guideletIds.length === 0) {
            guideletList.innerHTML = '<li>No notes found. Start learning and save some!</li>';
            return;
        }

        guideletIds.forEach(id => {
            const item = document.createElement('li');
            item.className = 'guidelet-list-item';
            item.dataset.guideletId = id;
            item.innerHTML = `<a href="#">${allNotesData[id].guidelet_title}</a>`;
            guideletList.appendChild(item);
        });

        // Add click handlers
        guideletList.querySelectorAll('.guidelet-list-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                guideletList.querySelector('.active')?.classList.remove('active');
                item.classList.add('active');
                renderNotes(item.dataset.guideletId);
            });
        });

        // Automatically select the first guidelet
        guideletList.querySelector('.guidelet-list-item').click();
    }

    async function fetchNotes() {
        try {
            const response = await fetch('/api/notes');
            allNotesData = await response.json();
            renderGuideletList();
        } catch (error) {
            console.error('Failed to fetch notes:', error);
            notesFeed.innerHTML = '<p>Could not load your notes. Please try again later.</p>';
        }
    }

    // Event listeners for updating and deleting notes
    notesFeed.addEventListener('focusout', async (e) => {
        if (e.target.classList.contains('user-comment-textarea')) {
            const noteCard = e.target.closest('.note-card');
            const noteId = noteCard.dataset.noteId;
            const newComment = e.target.value;

            // Find the original comment to see if it changed
            const guideletId = document.querySelector('.guidelet-list-item.active').dataset.guideletId;
            const originalNote = allNotesData[guideletId].notes.find(n => n.id == noteId);

            if (originalNote && originalNote.user_comment !== newComment) {
                try {
                    await fetch(`/api/notes/${noteId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': csrfToken },
                        body: JSON.stringify({ user_comment: newComment })
                    });
                    // Update local data to prevent re-saving unchanged notes
                    originalNote.user_comment = newComment; 
                } catch (error) {
                    console.error('Failed to update note:', error);
                }
            }
        }
    });

    notesFeed.addEventListener('click', async (e) => {
        if (e.target.classList.contains('delete-note-btn')) {
            if (confirm('Are you sure you want to delete this note?')) {
                const noteCard = e.target.closest('.note-card');
                const noteId = noteCard.dataset.noteId;

                try {
                    await fetch(`/api/notes/${noteId}`, { method: 'DELETE', headers: { 'X-CSRF-TOKEN': csrfToken } });
                    noteCard.remove(); // Remove from UI immediately
                } catch (error) {
                    console.error('Failed to delete note:', error);
                    alert('Could not delete note.');
                }
            }
        }
    });

    // Initial fetch
    fetchNotes();
});
