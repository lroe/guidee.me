// static/js/create.js

document.addEventListener('DOMContentLoaded', () => {
    const editor = document.getElementById('lesson-editor');
    const lessonForm = document.getElementById('lesson-form');
    const scriptInput = document.getElementById('script-input');
    
    // --- Button and Input Elements ---
    const addImageBtn = document.getElementById('add-image-btn');
    const addAudioBtn = document.getElementById('add-audio-btn');
    const addVideoBtn = document.getElementById('add-video-btn');
    const addMcqBtn = document.getElementById('add-mcq-btn');
    const addSaBtn = document.getElementById('add-sa-btn');
    const mediaUploadInput = document.getElementById('media-upload-input');
    const addGameBtn = document.getElementById('add-game-btn');


    // --- Save the user's last cursor position in the editor ---
    let savedRange = null;
    if (editor) {
        editor.addEventListener('focusout', () => {
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                savedRange = selection.getRangeAt(0);
            }
        });
        editor.addEventListener('click', () => {
             const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                savedRange = selection.getRangeAt(0);
            }
        });
    }

    // --- Helper function to insert any node at the cursor ---
    function insertNodeAtCursor(node) {
        const selection = window.getSelection();
        
        if (savedRange) {
            selection.removeAllRanges();
            selection.addRange(savedRange);
        } else if (editor) {
            editor.focus();
            const range = document.createRange();
            range.selectNodeContents(editor);
            range.collapse(false);
            selection.removeAllRanges();
            selection.addRange(range);
        }

        if (selection.getRangeAt && selection.rangeCount) {
            const range = selection.getRangeAt(0);
            range.deleteContents();
            range.insertNode(node);
            
            const newRange = document.createRange();
            newRange.setStartAfter(node);
            newRange.collapse(true);
            selection.removeAllRanges();
            selection.addRange(newRange);
            savedRange = newRange;
        } else if (editor) {
            editor.appendChild(node);
        }
    }

    function insertTextAtCursor(text) {
        const textNode = document.createTextNode(text);
        insertNodeAtCursor(textNode);
    }


    function createMediaPreview(type, url, description) {
        let container, mediaElement;
        if (type.toLowerCase() === 'image') {
            container = document.createElement('div');
            container.className = 'image-container';
            mediaElement = document.createElement('img');
            mediaElement.src = url;
            mediaElement.alt = description;
            mediaElement.style.maxWidth = '100%';
            mediaElement.style.display = 'block';
            mediaElement.style.borderRadius = '4px';
        } else if (type.toLowerCase() === 'audio') {
            container = document.createElement('div');
            container.className = 'audio-preview';
            mediaElement = document.createElement('audio');
            mediaElement.controls = true;
            mediaElement.src = url;
        } else if (type.toLowerCase() === 'video') {
            container = document.createElement('div');
            container.className = 'video-preview';
            mediaElement = document.createElement('video');
            mediaElement.controls = true;
            mediaElement.src = url;
            mediaElement.style.width = '100%';
        }

        if (container && mediaElement) {
            container.setAttribute('contenteditable', 'false');
            container.style.border = '1px solid #ccc';
            container.style.padding = '10px';
            container.style.margin = '10px 0';
            container.style.borderRadius = '5px';
            if (type.toLowerCase() !== 'image') container.style.maxWidth = '400px';

            container.appendChild(mediaElement);
            return container;
        }
        return null;
    }

    function insertMedia(type, file, description) {
        const mediaId = `media_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        const tag = `[${type.toUpperCase()}: description="${description}" id="${mediaId}"]`;
        const previewUrl = URL.createObjectURL(file);

        const container = createMediaPreview(type, previewUrl, description);
        if (!container) return;
        
        const hiddenInput = document.createElement('input');
        hiddenInput.type = 'hidden';
        hiddenInput.name = 'media_ids';
        hiddenInput.value = mediaId;
        
        const newContainer = new DataTransfer();
        newContainer.items.add(file);
        
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.name = 'media_files';
        fileInput.files = newContainer.files;
        fileInput.style.display = 'none';

        container.appendChild(hiddenInput);
        container.appendChild(fileInput);

        const textNode = document.createTextNode(tag);
        const br1 = document.createElement('br');
        const br2 = document.createElement('br');

        insertNodeAtCursor(br2);
        insertNodeAtCursor(container);
        insertNodeAtCursor(br1);
        insertNodeAtCursor(textNode);
    }
    
    async function handleNewImageFile(file) {
        const modal = document.createElement('div');
        modal.className = 'image-description-modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h2>Image Description</h2>
                <p>How would you like to add a description for this image?</p>
                <img src="${URL.createObjectURL(file)}" alt="Image preview" style="max-width: 100%; border-radius: 4px; margin-bottom: 15px;">
                <div class="modal-actions">
                    <button id="generate-desc-btn">Generate Automatically</button>
                    <button id="manual-desc-btn">Add Manually</button>
                </div>
                <div id="manual-input-container" style="display: none; margin-top: 15px;">
                    <textarea id="manual-desc-textarea" placeholder="Enter image description..."></textarea>
                    <button id="submit-manual-desc-btn">Submit</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        const generateBtn = document.getElementById('generate-desc-btn');
        const manualBtn = document.getElementById('manual-desc-btn');
        const manualInputContainer = document.getElementById('manual-input-container');
        const manualTextarea = document.getElementById('manual-desc-textarea');
        const submitManualBtn = document.getElementById('submit-manual-desc-btn');

        generateBtn.onclick = async () => { modal.remove(); await processImage(file, null); };
        manualBtn.onclick = () => {
            manualInputContainer.style.display = 'block';
            generateBtn.style.display = 'none';
            manualBtn.style.display = 'none';
        };
        submitManualBtn.onclick = async () => {
            const manualDescription = manualTextarea.value.trim();
            if (manualDescription) {
                modal.remove();
                await processImage(file, manualDescription);
            } else {
                alert('Please enter a description.');
            }
        };
    }

    async function processImage(file, manualDescription) {
        const originalButtonText = addImageBtn.textContent;
        addImageBtn.textContent = 'Processing...';
        addImageBtn.classList.add('is-generating');
        addImageBtn.disabled = true;

        let description = manualDescription;
        if (description === null) {
            addImageBtn.textContent = 'Generating...';
            try {
                const formData = new FormData();
                formData.append('file', file);
                const response = await fetch('/generate-caption', {
                    method: 'POST', body: formData,
                    headers: { 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') }
                });
                if (response.ok) {
                    const data = await response.json();
                    if (data.caption) description = data.caption;
                }
            } catch (error) { description = file.name; }
        }

        insertMedia('image', file, description || file.name);
        
        addImageBtn.textContent = originalButtonText;
        addImageBtn.classList.remove('is-generating');
        addImageBtn.disabled = false;
    }

    function handleNewAudioFile(file) {
        const description = prompt("Please enter a short description for this audio clip:", file.name);
        if (description !== null) insertMedia('audio', file, description);
    }

    function handleNewVideoFile(file) {
        const description = prompt("Please enter a short description for this video clip:", file.name);
        if (description !== null) insertMedia('video', file, description);
    }

    // --- Event Listeners ---
    if (addImageBtn) addImageBtn.addEventListener('click', () => { mediaUploadInput.accept = 'image/*'; mediaUploadInput.click(); });
    if (addAudioBtn) addAudioBtn.addEventListener('click', () => { mediaUploadInput.accept = 'audio/*'; mediaUploadInput.click(); });
    if (addVideoBtn) addVideoBtn.addEventListener('click', () => { mediaUploadInput.accept = 'video/*'; mediaUploadInput.click(); });
    if (addMcqBtn) addMcqBtn.addEventListener('click', () => { insertTextAtCursor(`[QUESTION: Your question? OPTIONS: A) Opt 1, B) Opt 2, C) Opt 3, D) Opt 4 ANSWER: B]`); });
    if (addSaBtn) addSaBtn.addEventListener('click', () => { insertTextAtCursor(`[QUESTION_SA: Your question? KEYWORDS: concept1, concept2]`); });

    if (addGameBtn) {
        addGameBtn.addEventListener('click', async () => {
            try {
                const response = await fetch('/api/creator/games');
                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                const games = await response.json();

                if (games.length === 0) {
                    alert("You don't have any saved games. Please create one in the Game Studio first.");
                    return;
                }

                const modal = document.createElement('div');
                modal.className = 'game-selector-modal';
                modal.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; padding: 20px; border-radius: 8px; box-shadow: 0 5px 15px rgba(0,0,0,0.3); z-index: 1001;';
                
                let gameOptionsHTML = games.map(game =>
                    `<div class="game-option" data-id="${game.id}" data-title="${game.title}" style="cursor: pointer; padding: 8px 12px; border-radius: 4px; margin-bottom: 5px;">${game.title}</div>`
                ).join('');

                modal.innerHTML = `
                    <h2 style="margin-top: 0;">Select a Game</h2>
                    <div id="game-list" style="max-height: 200px; overflow-y: auto;">${gameOptionsHTML}</div>
                    <button id="close-game-modal" style="margin-top: 15px; padding: 8px 15px;">Cancel</button>
                `;
                document.body.appendChild(modal);

                document.getElementById('game-list').addEventListener('click', (e) => {
                    if (e.target.classList.contains('game-option')) {
                        const gameId = e.target.dataset.id;
                        const gameTitle = e.target.dataset.title;
                        const gameTag = `\n[INTERACTIVE_GAME: id="${gameId}" title="${gameTitle}"]\n`;
                        insertTextAtCursor(gameTag);
                        document.body.removeChild(modal);
                    }
                });

                document.getElementById('close-game-modal').addEventListener('click', () => {
                     document.body.removeChild(modal);
                });

            } catch (error) {
                console.error('Failed to fetch games:', error);
                alert('Could not load your games. Please try again.');
            }
        });
    }

    if (mediaUploadInput) {
        mediaUploadInput.addEventListener('change', (event) => {
            if (event.target.files.length > 0) {
                const file = event.target.files[0];
                if (file.type.startsWith('image/')) handleNewImageFile(file);
                else if (file.type.startsWith('audio/')) handleNewAudioFile(file);
                else if (file.type.startsWith('video/')) handleNewVideoFile(file);
            }
            event.target.value = '';
        });
    }
    
    if (editor) {
        editor.addEventListener('paste', (event) => {
            event.preventDefault();
            const items = (event.clipboardData || window.clipboardData).items;
            let pastedImage = false;
            for (const item of items) {
                if (item.kind === 'file' && item.type.startsWith('image/')) {
                    if (item.getAsFile()) handleNewImageFile(item.getAsFile());
                    pastedImage = true;
                    break;
                }
            }
            if (!pastedImage) {
                const text = event.clipboardData.getData('text/plain');
                document.execCommand('insertText', false, text);
            }
        });
    }

    // --- THIS IS THE FIX: A NEW, ROBUST SCRIPT PARSING FUNCTION ---
    function convertEditorContentToPlainText(editorElement) {
        const tempDiv = editorElement.cloneNode(true);

        // Remove the visual media previews to not include them in the script
        tempDiv.querySelectorAll('.image-container, .audio-preview, .video-preview').forEach(el => el.remove());
        
        // Replace <br> with newlines for consistent spacing
        tempDiv.innerHTML = tempDiv.innerHTML.replace(/<br\s*[\/]?>/gi, "\n");

        // Use innerText to get a clean text representation
        // This automatically handles block elements like <p> and <div> by adding line breaks
        return tempDiv.innerText.trim();
    }
    // --- END OF FIX ---


    if (lessonForm) {
        lessonForm.addEventListener('submit', function(event) {
            const overlay = document.createElement('div');
            overlay.className = 'loading-overlay';
            overlay.innerHTML = `<div class="loading-spinner"></div><p>Saving your masterpiece... please wait.</p>`;
            const editorHtmlInput = document.getElementById('editor-html-input');

            try {
                document.body.appendChild(overlay);

                const tempDiv = document.createElement('div');
                if (editor) {
                    tempDiv.innerHTML = editor.innerHTML;
                }

                // Prepare editor_html by removing temporary blob previews
                const tempDivForSaving = tempDiv.cloneNode(true);
                tempDivForSaving.querySelectorAll('.image-container, .audio-preview, .video-preview').forEach(el => el.remove());
                
                if (editorHtmlInput) {
                    editorHtmlInput.value = tempDivForSaving.innerHTML;
                }

                // --- THIS IS THE FIX ---
                // Use the new, robust function to generate the raw script
                const scriptText = convertEditorContentToPlainText(editor);
                if (scriptInput) {
                    scriptInput.value = scriptText;
                }
                // --- END OF FIX ---
                
            } catch (e) {
                event.preventDefault();
                console.error("Error processing lesson content before submission:", e);
                if (document.body.contains(overlay)) {
                    document.body.removeChild(overlay);
                }
                alert("An error occurred while trying to save the chapter. Please check the browser console for details and try again.");
            }
        });
    }

    function initializeEditorWithPreviews() {
        if (!editor || typeof mediaMap === 'undefined') return;

        let content = editor.innerHTML;
        const mediaRegex = /\[(IMAGE|AUDIO|VIDEO):\s*description="([^"]*)"\s*id="([^"]*)"\]/g;
        
        const newContent = content.replace(mediaRegex, (fullTag, type, description, id) => {
            const permanentUrl = mediaMap[id];
            if (permanentUrl) {
                const previewElement = createMediaPreview(type, permanentUrl, description);
                if (previewElement) {
                    return `${fullTag}<br>${previewElement.outerHTML}<br>`;
                }
            }
            return fullTag;
        });

        editor.innerHTML = newContent;
    }

    if (typeof mediaMap !== 'undefined') {
        initializeEditorWithPreviews();
    }

    const modal = document.getElementById("image-modal");
    if (editor && modal) {
        const modalImg = document.getElementById("modal-img");
        const closeBtn = document.querySelector(".close-btn");

        editor.addEventListener('click', function(event) {
            if (event.target.tagName === 'IMG' && event.target.closest('.image-container')) {
                event.preventDefault();
                modal.style.display = "block";
                modalImg.src = event.target.dataset.highResUrl || event.target.src;
            }
        });

        function closeModal() {
            modal.style.display = "none";
        }

        if (closeBtn) closeBtn.onclick = closeModal;
        window.onclick = function(event) { if (event.target == modal) closeModal(); };
    }
});