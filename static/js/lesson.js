document.addEventListener('DOMContentLoaded', () => {
    // --- Element Selectors ---

    marked.setOptions({
    breaks: true
    });
    const chatBox = document.getElementById('chat-box');
    const inputArea = document.getElementById('input-area');
    const qnaInput = document.getElementById('qna-input');
    const sendQnaBtn = document.getElementById('send-qna-btn');
    const resetBtn = document.getElementById('reset-btn');
    const deleteLastBtn = document.getElementById('delete-last-btn');
    const setPersonaBtn = document.getElementById('set-persona-btn');
    const personaInput = document.getElementById('persona-input');

    let isWaitingForResponse = false;
    let messageCounter = 0;

    function safeTypeset(elements) {
        if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) {
            MathJax.typesetPromise(elements).catch((err) => console.log('MathJax typeset error:', err));
        }
    }
    
    async function saveNote(data) {
        try {
            const response = await fetch('/api/notes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': CSRF_TOKEN },
                body: JSON.stringify(data)
            });
            const result = await response.json();
            if (result.success) {
                // Show a temporary confirmation message
                const confirmation = document.createElement('div');
                confirmation.textContent = '✅ Note Saved!';
                confirmation.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #28a745; color: white; padding: 10px 20px; border-radius: 8px; z-index: 2000;';
                document.body.appendChild(confirmation);
                setTimeout(() => confirmation.remove(), 2000);
            } else {
                alert(result.message || 'Could not save note.');
            }
        } catch (error) {
            console.error('Error saving note:', error);
            alert('An error occurred while saving your note.');
        }
    }

    function updateAdventureMap(newActiveIndex) {
        const waypoints = document.querySelectorAll('.waypoint-item');
        if (!waypoints.length) return;

        waypoints.forEach((waypoint, index) => {
            // Reset classes
            waypoint.classList.remove('conquered', 'active', 'undiscovered');

            if (index < newActiveIndex) {
                waypoint.classList.add('conquered');
            } else if (index === newActiveIndex) {
                waypoint.classList.add('active');
            } else {
                waypoint.classList.add('undiscovered');
            }
        });
    }


    // --- Persona Logic (If exists on page) ---
    if (setPersonaBtn && personaInput) {
        setPersonaBtn.addEventListener('click', async () => {
            if (isWaitingForResponse) return;
            const personaText = personaInput.value.trim();
            if (personaText === "") return;

            addMessage(`Setting persona to: "${personaText}"`, 'student');
            await postToChat(`set persona: ${personaText}`, 'LESSON_FLOW');
        });
    }

    // --- Q&A Input Logic ---
    async function sendQuestion() {
        if (isWaitingForResponse) return;
        const question = qnaInput.value.trim();
        if (question === "") return;

        if (question.toLowerCase().startsWith('/note')) {
            const lastTutorMessage = chatBox.querySelector('.tutor-message:last-of-type');
            if (lastTutorMessage) {
                const comment = question.substring(5).trim(); // Get text after "/note "
                const noteData = {
                    lesson_id: LESSON_ID,
                    saved_content: lastTutorMessage.dataset.rawText,
                    user_comment: comment,
                    message_index: lastTutorMessage.dataset.messageIndex
                };
                saveNote(noteData);
                qnaInput.value = ''; // Clear input
            } else {
                alert("There's no tutor message to save yet.");
            }
            return; // Stop the function here
        }

        addMessage(question, 'student');
        qnaInput.value = '';
        isWaitingForResponse = true;

        try {
            const intentResponse = await fetch('/chat/intent', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': CSRF_TOKEN },
                body: JSON.stringify({ user_input: question, lesson_id: LESSON_ID })
            });

            if (!intentResponse.ok) {
                throw new Error(`Intent classifier failed with status: ${intentResponse.status}`);
            }
            const intentData = await intentResponse.json();

            if (intentData.intent === 'MEDIA_REQUEST') {
                postToChat(intentData.alt_text, 'MEDIA_REQUEST');
            } else {
                postToChat(intentData.query, 'QNA');
            }
        } catch (error) {
            console.error('Error sending question:', error);
            addMessage('Sorry, I had trouble understanding that question. Could you rephrase it?', 'tutor');
            isWaitingForResponse = false;
            showContinueButton();
        }
    }

    if (sendQnaBtn) {
        sendQnaBtn.addEventListener('click', sendQuestion);
    }
    
    if (qnaInput) {
        qnaInput.addEventListener('keypress', function(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                sendQuestion();
            }
        });
    }

    // --- Chat Control Button Logic ---
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            if (isWaitingForResponse) return;
            if (confirm('Are you sure you want to reset this entire conversation? Your progress in this chapter will be lost.')) {
                isWaitingForResponse = true;
                showLoadingIndicator();
                fetch('/chat/reset', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': CSRF_TOKEN },
                    body: JSON.stringify({ lesson_id: LESSON_ID })
                }).then(res => res.json()).then(data => {
                    if (data.success) {
                        window.location.reload();
                    } else {
                        alert('Could not reset conversation.');
                        isWaitingForResponse = false;
                        inputArea.innerHTML = '';
                    }
                }).catch(error => {
                    console.error('Reset error:', error);
                    alert('Could not reset conversation.');
                    isWaitingForResponse = false;
                    inputArea.innerHTML = '';
                });
            }
        });
    }

    if (deleteLastBtn) {
        deleteLastBtn.addEventListener('click', async () => {
            if (isWaitingForResponse) return;
            isWaitingForResponse = true;
            showLoadingIndicator();
            
            try {
                const response = await fetch('/chat/delete_last_turn', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': CSRF_TOKEN },
                    body: JSON.stringify({ lesson_id: LESSON_ID })
                });
                const data = await response.json();
                if (data.success) {
                    window.location.reload();
                } else {
                    alert(data.message || 'Could not delete the last turn.');
                    isWaitingForResponse = false;
                    inputArea.innerHTML = '';
                }
            } catch (error) {
                console.error('Delete last turn error:', error);
                alert('Could not delete the last turn.');
                isWaitingForResponse = false;
                inputArea.innerHTML = '';
            }
        });
    }
    
    // --- Rendering and UI Functions ---
    function addMessage(text, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}-message`;
        
        messageDiv.dataset.messageIndex = messageCounter;
        messageDiv.dataset.rawText = text;

        messageDiv.innerHTML = `
        <div class="message-content">${marked.parse(text, { breaks: true })}</div>
        <button class="pin-note-btn" title="Save to Notebook">📌</button>
        <div class="inline-note-form">
            <input type="text" class="inline-note-input" placeholder="Add a quick note... (Optional)">
            <button class="btn btn-primary btn-save-note">✓</button>
            <button class="btn btn-secondary btn-cancel-note">×</button>
        </div>
    `;

        chatBox.appendChild(messageDiv);
        // THIS IS THE FIX: Scroll the new message into view from the top.
        messageDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
        messageCounter++;

        if (window.handleHeaderScroll) {
            window.handleHeaderScroll();
        }

        if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) {
            MathJax.typesetPromise([messageDiv]).catch((err) => console.log('MathJax error:', err));
        }

        if (typeof hljs !== 'undefined') {
            messageDiv.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
        }
    }

    function addImageMessage(url, alt) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message tutor-message media-message';

        const magnifyContainer = document.createElement('div');
        magnifyContainer.className = 'magnify-container';

        const img = document.createElement('img');
        img.src = url;
        img.alt = alt;

        const loupe = document.createElement('div');
        loupe.className = 'magnify-loupe';

        let highResUrl = url;
        if (url.includes('/upload/')) {
            highResUrl = url.replace('/upload/', '/upload/q_auto:best/');
        }
        img.dataset.highResUrl = highResUrl;
        loupe.style.backgroundImage = `url(${highResUrl})`;

        magnifyContainer.appendChild(img);
        magnifyContainer.appendChild(loupe);
        messageDiv.appendChild(magnifyContainer);
        chatBox.appendChild(messageDiv);
        // THIS IS THE FIX: Scroll the new message into view from the top.
        messageDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function addAudioMessage(url, description) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message tutor-message audio-message';
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.src = url;
        messageDiv.appendChild(audio);
        chatBox.appendChild(messageDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function addVideoMessage(url) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message tutor-message media-message';
        const video = document.createElement('video');
        video.controls = true;
        video.src = url;
        messageDiv.appendChild(video);
        chatBox.appendChild(messageDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // --- THIS IS THE CORRECTED FUNCTION ---
    // This is the full, updated function for static/js/lesson.js

/**
 * Creates and appends a full-width, auto-resizing iframe container for an
 * interactive game into the chat box.
 * @param {string} gameId - The unique ID of the game to be loaded.
 * @param {string} title - The title of the game, used for accessibility.
 */
function addGameMessage(gameId, title) {
    // 1. Create the main message container. The 'game-message' class is crucial
    //    as it triggers the special full-width and flex-grow CSS rules in guidelet_player.html.
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message game-message';

    // 2. Create the iframe element that will contain the game.
    const iframe = document.createElement('iframe');
    
    // 3. Set the iframe's source URL. No unique ID is needed anymore.
    iframe.src = `/play/game/${gameId}`;
    
    // 4. Set standard security and accessibility attributes.
    iframe.sandbox = "allow-scripts allow-same-origin";
    iframe.title = title;

    // 5. Place the iframe inside our special message container.
    messageDiv.appendChild(iframe);
    
    // 6. Add the complete message bubble to the chat box.
    chatBox.appendChild(messageDiv);

    // 7. Automatically scroll to the bottom to reveal the new game.
    chatBox.scrollTop = chatBox.scrollHeight;
}
    
    function showMCQOptions(questionData) {
        inputArea.innerHTML = '';
        const questionText = document.createElement('p');
        questionText.innerHTML = marked.parse(questionData.question);
        inputArea.appendChild(questionText);
        
        const optionsContainer = document.createElement('div');
        optionsContainer.className = 'options-container';
        
        const options = Object.keys(questionData.options);
        
        for (let i = 0; i < options.length; i++) {
            const key = String.fromCharCode(65 + i);
            const button = document.createElement('button');
            button.className = 'btn btn-secondary';
            button.innerHTML = `${key}: ${marked.parse(questionData.options[options[i]])}`;
            button.dataset.answer = key;
            button.addEventListener('click', () => {
                if (isWaitingForResponse) return;
                const answerText = `${key}: ${questionData.options[options[i]]}`;
                addMessage(answerText, 'student');
                postToChat(key, 'LESSON_FLOW');
            });
            optionsContainer.appendChild(button);
        }
        inputArea.appendChild(optionsContainer);

        if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) {
            MathJax.typesetPromise([inputArea]).catch((err) => console.log('MathJax typeset error:', err));
        }
    }

    function showShortAnswerInput(questionData) {
        inputArea.innerHTML = '';
        const questionText = document.createElement('p');
        questionText.innerHTML = marked.parse(questionData.question);
        inputArea.appendChild(questionText);
        
        const answerTextarea = document.createElement('textarea');
        answerTextarea.rows = 3;
        answerTextarea.placeholder = "Type your answer here...";
        inputArea.appendChild(answerTextarea);
        
        const submitButton = document.createElement('button');
        submitButton.className = 'btn';
        submitButton.innerText = 'Submit Answer';
        submitButton.addEventListener('click', () => {
            if (isWaitingForResponse) return;
            const answer = answerTextarea.value.trim();
            if (answer === "") { 
                alert("Please type an answer."); 
                return; 
            }
            addMessage(answer, 'student');
            postToChat(answer, 'LESSON_FLOW');
        });
        inputArea.appendChild(submitButton);

        if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) {
            MathJax.typesetPromise([inputArea]).catch((err) => console.log('MathJax typeset error:', err));
        }
    }
    
    function showContinueButton() {
        inputArea.innerHTML = '';
        const buttonContainer = document.createElement('div');
        buttonContainer.style.textAlign = 'right';
        const continueButton = document.createElement('button');
        continueButton.innerText = 'Continue';
        continueButton.className = 'btn btn-primary'; 
        continueButton.addEventListener('click', () => {
            if (isWaitingForResponse) return;
            postToChat('Continue', 'LESSON_FLOW');
        });
        buttonContainer.appendChild(continueButton);
        inputArea.appendChild(buttonContainer);
    }

    function showLoadingIndicator() {
        inputArea.innerHTML = '';
        const spinner = document.createElement('div');
        spinner.className = 'loading-spinner';
        inputArea.appendChild(spinner);
    }

    // --- Core Chat Function ---
    async function postToChat(userInput = null, requestType = 'LESSON_FLOW') {
        isWaitingForResponse = true;
        if (qnaInput) qnaInput.disabled = true;
        if (sendQnaBtn) sendQnaBtn.disabled = true;
        
        showLoadingIndicator();

        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': CSRF_TOKEN },
                body: JSON.stringify({ lesson_id: LESSON_ID, user_input: userInput, request_type: requestType })
            });

            if (!response.ok) {
                throw new Error(`Server responded with status: ${response.status}`);
            }

            const data = await response.json();
            console.log("Data received from /chat:", data);
        
            isWaitingForResponse = false;
            if (qnaInput) qnaInput.disabled = false;
            if (sendQnaBtn) sendQnaBtn.disabled = false;
            if (data.xp_earned && data.xp_earned > 0) {
                showXpBubble(data.xp_earned);
            }

             if (data.new_stage_index !== undefined) {
                updateAdventureMap(data.new_stage_index);
            }
            
            if (data.media_url) {
                if (data.media_type === 'audio') {
                    addAudioMessage(data.media_url, "Listen to the clip above:"); 
                } else if (data.media_type === 'video') {
                    addVideoMessage(data.media_url);
                } else {
                    addImageMessage(data.media_url, "View the image above");
                }
            }
            if (data.tutor_text) {
                addMessage(data.tutor_text, 'tutor');
            }
            
            
            if (data.is_qna_response || data.is_system_message) {
                showContinueButton();
                return; 
            }

            if (data.interactive_game) {
                addGameMessage(data.interactive_game.game_id, data.interactive_game.title);
            } else if (data.is_lesson_end) {
                showLessonEndUI(data);
            } else if (data.question) {
                if (data.question.type === 'QUESTION_MCQ') {
                    showMCQOptions(data.question);
                } else if (data.question.type === 'QUESTION_SA') {
                    showShortAnswerInput(data.question);
                }
            } else {
                showContinueButton();
            }
        } catch (error) {
            console.error('Error in postToChat:', error);
            addMessage('Sorry, something went wrong and I could not process your request. Please try again or refresh the page.', 'tutor');
            isWaitingForResponse = false;
            if (qnaInput) qnaInput.disabled = false;
            if (sendQnaBtn) sendQnaBtn.disabled = false;
            showContinueButton();
        }
    }

    function showLessonEndUI(stateData) {
        inputArea.innerHTML = '';
        if (stateData.certificate_url) {
            const certLink = document.createElement('a');
            certLink.href = stateData.certificate_url;
            certLink.innerText = 'View Your Certificate!';
            certLink.className = 'btn btn-primary';
            inputArea.appendChild(certLink);
        } else if (stateData.next_chapter_url) {
            const nextChapterButton = document.createElement('a');
            nextChapterButton.href = stateData.next_chapter_url;
            nextChapterButton.innerText = 'Go to Next Chapter';
            nextChapterButton.className = 'btn btn-primary';
            inputArea.appendChild(nextChapterButton);
        }
    }
    /**
     * Creates a temporary visual element to show the user they've earned XP.
     * @param {number} xpAmount - The amount of XP earned.
     */
    function showXpBubble(xpAmount) {
        // --- THIS IS THE FIX ---
        // The bubble is now appended to the main wrapper, which is not cleared by other functions.
        const bubbleContainer = document.getElementById('bottom-controls-wrapper');
        if (!bubbleContainer) return; // Exit if the container isn't on the page

        // 1. Create the new div element for the bubble
        const bubble = document.createElement('div');
        
        // 2. Add the CSS class we defined in guidelet_player.html
        bubble.className = 'xp-bubble';
        
        // 3. Set its text content
        bubble.textContent = `+${xpAmount} XP!`;
        
        // 4. Add the bubble to the container
        bubbleContainer.appendChild(bubble);
        
        // 5. Set a timer to automatically remove the bubble from the page
        //    after its animation is finished (1500ms = 1.5s).
        setTimeout(() => {
            bubble.remove();
        }, 1500);
    }

    // --- Initialization Logic ---
    function initializeLesson() {
        let hasHistory = false;
        if (typeof initialHistory !== 'undefined' && initialHistory && typeof initialHistory === 'string') {
            try {
                const parsedHistory = JSON.parse(initialHistory);
                if (Array.isArray(parsedHistory) && parsedHistory.length > 0) {
                    hasHistory = true;
                    parsedHistory.forEach(message => {
                        if (message.type === 'text') {
                            addMessage(message.content, message.sender);
                        } else if (message.type === 'image') {
                            addImageMessage(message.url, message.alt);
                        } else if (message.type === 'audio') {
                            addAudioMessage(message.url, message.alt);
                        } else if (message.type === 'video') {
                            addVideoMessage(message.url);
                        }
                    });
                    
                    if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) {
                        safeTypeset([chatBox]);
                    }
                }
            } catch (e) {
                console.error("Could not parse chat history:", e);
            }
        }

        if (typeof currentState !== 'undefined' && currentState.is_lesson_end) {
            showLessonEndUI(currentState);
        } else if (typeof currentState !== 'undefined' && currentState.question) {
            if (currentState.question.type === 'QUESTION_MCQ') {
                showMCQOptions(currentState.question);
            } else if (currentState.question.type === 'QUESTION_SA') {
                showShortAnswerInput(currentState.question);
            }
        } else {
            if (hasHistory) {
                showContinueButton();
            } else {
                postToChat(null, 'LESSON_FLOW');
            }
        }
    }

    // Initialize the lesson
    initializeLesson();

    // --- Global Event Listener for Game Completion ---
    window.addEventListener('message', (event) => {
        if (event.origin !== window.location.origin) return;
        const data = event.data;
        if (data === 'game_complete') {
            console.log('Game completed! Automatically proceeding.');
            const lastGameMessage = chatBox.querySelector('.game-frame-container:last-of-type');
            if (lastGameMessage) {
                lastGameMessage.style.textAlign = 'center';
                lastGameMessage.innerHTML = `<p style="font-weight: bold; color: #28a745; margin: 10px;">Challenge Complete!</p>`;
            }
            inputArea.innerHTML = '';
            setTimeout(() => {
                postToChat('Continue', 'LESSON_FLOW');
            }, 1500);
        }
    });
});

// --- Lightbox/Modal Logic ---
document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById("image-modal");
    if (!modal) return;
    
    const modalImg = document.getElementById("modal-img");
    const closeBtn = modal.querySelector(".close-btn");
    const chatBox = document.getElementById('chat-box');
    
    if (chatBox) {
        chatBox.addEventListener('click', function(event) {
            const target = event.target;
            if (target.tagName === 'IMG' && target.closest('.media-message')) {
                modal.style.display = "block";
                modalImg.src = target.dataset.highResUrl || target.src;
            }
        });
    }
    
    function closeModal() {
        modal.style.display = "none";
    }
    
    if (closeBtn) closeBtn.onclick = closeModal;
    
    window.onclick = function(event) { 
        if (event.target == modal) closeModal(); 
    };
});

// --- Watch Time Analytics Heartbeat ---
document.addEventListener('DOMContentLoaded', () => {
    if (typeof GUIDLET_ID !== 'undefined' && typeof currentState !== 'undefined' && currentState.is_enrolled_student) {
        const HEARTBEAT_INTERVAL_SECONDS = 30;
        let accumulatedTime = 0;
        let heartbeatIntervalId = null;
        
        const sendHeartbeat = (isFinal = false) => {
            if (accumulatedTime > 0) {
                const payload = {
                    guidelet_id: GUIDLET_ID,
                    lesson_id: LESSON_ID,
                    seconds: Math.round(accumulatedTime)
                };
                
                if (isFinal) {
                    const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
                    navigator.sendBeacon('/api/heartbeat', blob);
                } else {
                    fetch('/api/heartbeat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': CSRF_TOKEN },
                        body: JSON.stringify(payload),
                        keepalive: true
                    }).catch(error => console.error('Heartbeat failed:', error));
                }
                accumulatedTime = 0;
            }
        };
        
        const startTracking = () => {
            if (heartbeatIntervalId) clearInterval(heartbeatIntervalId);
            heartbeatIntervalId = setInterval(() => {
                accumulatedTime += 1;
                if (accumulatedTime >= HEARTBEAT_INTERVAL_SECONDS) sendHeartbeat();
            }, 1000);
        };
        
        const stopTracking = () => {
            if (heartbeatIntervalId) clearInterval(heartbeatIntervalId);
            heartbeatIntervalId = null;
            sendHeartbeat();
        };
        
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) stopTracking(); 
            else startTracking();
        });
        
        window.addEventListener('beforeunload', () => stopTracking());
        
        if (!document.hidden) startTracking();
    } else {
        console.log("Watch time tracking disabled for this session.");
    }
});

// --- Hiding Header on Scroll ---
document.addEventListener('DOMContentLoaded', () => {
    const chatHeader = document.querySelector('.chat-header');
    const chatBox = document.getElementById('chat-box');
    
    if (chatHeader && chatBox) {
        let lastScrollTop = 0;
        
        const handleHeaderScroll = () => {
            let scrollTop = chatBox.scrollTop;
            const atBottom = chatBox.scrollHeight - chatBox.scrollTop <= chatBox.clientHeight + 1;
            
            if (scrollTop > lastScrollTop && scrollTop > 50 && !atBottom) {
                chatHeader.classList.add('header-hidden');
            } else if (scrollTop < lastScrollTop || scrollTop <= 50) {
                chatHeader.classList.remove('header-hidden');
            }
            lastScrollTop = scrollTop <= 0 ? 0 : scrollTop;
        };
        
        window.handleHeaderScroll = handleHeaderScroll; 
        chatBox.addEventListener('scroll', () => window.requestAnimationFrame(handleHeaderScroll));
    }
});

// --- Mobile Sidebar Logic ---
document.addEventListener('DOMContentLoaded', () => {
    const toggleBtn = document.getElementById('toggle-sidebar-btn');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const sidebarBackBtn = document.getElementById('sidebar-back-btn');
    
    function closeSidebar() {
        if (sidebar) sidebar.classList.remove('show');
        if (overlay) overlay.classList.remove('show');
    }
    
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            if (sidebar) sidebar.classList.toggle('show');
            if (overlay) overlay.classList.toggle('show');
        });
    }
    
    if (overlay) overlay.addEventListener('click', closeSidebar);
    if (sidebarBackBtn) sidebarBackBtn.addEventListener('click', closeSidebar);
});

document.addEventListener('DOMContentLoaded', () => {
    const chatBox = document.getElementById('chat-box');
    if (!chatBox) return;

    chatBox.addEventListener('click', (e) => {
        const message = e.target.closest('.message');
        if (!message) return;

        // User clicks the PIN button
        if (e.target.closest('.pin-note-btn')) {
            document.querySelectorAll('.message-note-mode').forEach(el => el.classList.remove('message-note-mode'));
            message.classList.add('message-note-mode');
            message.querySelector('.inline-note-input').focus();
        }

        // User clicks the CANCEL button
        if (e.target.closest('.btn-cancel-note')) {
            message.classList.remove('message-note-mode');
        }

        // User clicks the SAVE button
        if (e.target.closest('.btn-save-note')) {
            const comment = message.querySelector('.inline-note-input').value.trim();
            const noteData = {
                lesson_id: LESSON_ID,
                saved_content: message.dataset.rawText,
                user_comment: comment,
                message_index: message.dataset.messageIndex
            };
            saveNote(noteData);
            message.classList.remove('message-note-mode');
        }
    });
});


document.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const messageIndexToScroll = urlParams.get('scrollTo');

    if (messageIndexToScroll) {
        setTimeout(() => {
            const targetMessage = document.querySelector(`.message[data-message-index="${messageIndexToScroll}"]`);
            if (targetMessage) {
                targetMessage.scrollIntoView({ behavior: 'smooth', block: 'center' });
                
                targetMessage.style.transition = 'background-color 0.5s ease';
                targetMessage.style.backgroundColor = 'var(--accent-pink)';
                
                setTimeout(() => {
                    targetMessage.style.backgroundColor = '';
                }, 2000);
            }
        }, 500);
    }
});

// --- Image Magnifier Loupe Logic ---
document.addEventListener('DOMContentLoaded', () => {
    const chatBox = document.getElementById('chat-box');
    if (!chatBox) return;

    const zoomFactor = 2.5;

    function moveMagnifier(e) {
        const container = e.currentTarget;
        const img = container.querySelector('img');
        const loupe = container.querySelector('.magnify-loupe');

        if (!img || !loupe) return;

        const rect = img.getBoundingClientRect();
        const x = e.pageX - rect.left - window.scrollX;
        const y = e.pageY - rect.top - window.scrollY;

        loupe.style.left = (x - loupe.offsetWidth / 2) + "px";
        loupe.style.top = (y - loupe.offsetHeight / 2) + "px";

        const bgX = - (x * zoomFactor - loupe.offsetWidth / 2);
        const bgY = - (y * zoomFactor - loupe.offsetHeight / 2);
        loupe.style.backgroundPosition = `${bgX}px ${bgY}px`;
    }

    chatBox.addEventListener('mouseover', (e) => {
        const container = e.target.closest('.magnify-container');
        if (container) {
            const img = container.querySelector('img');
            const loupe = container.querySelector('.magnify-loupe');

            if (!img || !loupe) return;

            loupe.style.backgroundSize = `${img.width * zoomFactor}px ${img.height * zoomFactor}px`;
            loupe.style.display = "block";

            container.addEventListener('mousemove', moveMagnifier);
            container.addEventListener('mouseleave', () => {
                loupe.style.display = "none";
                container.removeEventListener('mousemove', moveMagnifier);
            }, { once: true });
        }
    });
});


// --- Mobile Q&A UI Toggle Logic ---
document.addEventListener('DOMContentLoaded', () => {
    const isMobile = window.getComputedStyle(document.getElementById('toggle-sidebar-btn')).display === 'block';

    if (isMobile) {
        const bottomControls = document.getElementById('bottom-controls');
        const lessonView = document.getElementById('lesson-view-controls');
        const qnaView = document.getElementById('qna-view-controls');
        const askQuestionBtn = document.getElementById('ask-question-btn-mobile');
        const backToLessonBtn = document.getElementById('back-to-lesson-btn-mobile');
        const qnaInput = document.getElementById('qna-input');

        const showLessonView = () => {
            bottomControls.classList.remove('mobile-chat-active');
            lessonView.classList.remove('hidden');
            qnaView.classList.add('hidden');
        };

        const showQnaView = () => {
            bottomControls.classList.add('mobile-chat-active');
            lessonView.classList.add('hidden');
            qnaView.classList.remove('hidden');
            qnaInput.focus();
        };

        if (askQuestionBtn) askQuestionBtn.addEventListener('click', showQnaView);
        if (backToLessonBtn) backToLessonBtn.addEventListener('click', showLessonView);

        const originalSendQuestion = window.sendQuestion;
        if (typeof originalSendQuestion === 'function') {
            window.sendQuestion = async function() {
                await originalSendQuestion();
                showLessonView();
            };
            
            const sendQnaBtn = document.getElementById('send-qna-btn');
            if(sendQnaBtn) sendQnaBtn.onclick = window.sendQuestion;
            if(qnaInput) qnaInput.addEventListener('keypress', (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    window.sendQuestion();
                }
            });
        }
    }

window.addEventListener('message', (event) => {
    
    // CRITICAL SECURITY CHECK:
    // Only accept messages from the same origin as the parent page.
    // This will automatically work for "http://127.0.0.1:5000" during local testing
    // and "https://www.guidee.me" in production.
    if (event.origin !== window.location.origin) {
        console.warn('Blocked a message from an untrusted origin:', event.origin);
        return;
    }

    const data = event.data;

    // The listener now ONLY handles the 'game_complete' message.
    // The complex resizing logic has been completely removed.
    if (data === 'game_complete') {
        console.log('Game completed! Automatically proceeding.');
        
        // Find the most recent game message bubble to display the completion message.
        const lastGameMessage = chatBox.querySelector('.message.game-message:last-of-type');
        if (lastGameMessage) {
            // Make the bubble look nice after completion.
            lastGameMessage.style.textAlign = 'center';
            lastGameMessage.style.padding = '20px';
            lastGameMessage.style.flexGrow = '0'; // Stop it from expanding now.
            lastGameMessage.innerHTML = `<p style="font-weight: bold; font-size: 1.2rem; color: var(--correct-color);">✓ Challenge Complete!</p>`;
        }
        
        // Clear the input area and move to the next step in the lesson after a short delay.
        inputArea.innerHTML = '';
        setTimeout(() => {
            postToChat('Continue', 'LESSON_FLOW');
        }, 1500);
    }
});


// --- NEW: Keyboard-aware resize for bottom input on mobile (Add after resizeIframe) ---
function adjustForKeyboard() {
    const visualHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    document.body.style.height = `${visualHeight}px`;
    document.querySelector('.main-chat-area').style.height = `${visualHeight}px`;
    document.querySelector('.chat-box').scrollTop = document.querySelector('.chat-box').scrollHeight;  // Auto-scroll to bottom
}

// --- NEW: Listen for viewport/keyboard changes (Add at the very end of the file) ---
if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', debounce(adjustForKeyboard, 100));
} else {
    window.addEventListener('resize', debounce(adjustForKeyboard, 100));
}
window.addEventListener('load', adjustForKeyboard);
});