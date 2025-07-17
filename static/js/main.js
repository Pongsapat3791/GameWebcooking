const socket = io();
let currentRoomId = null;
let myName = '';
let mySid = '';
let isHost = false;
let myCurrentObjectiveIngredients = [];
let gameStateUpdateInterval = null;
let myAbility = null;
let isAbilityProcessing = false;

const ABILITIES_CONFIG = {
    'กระทะ': {'verb': 'ทอด', 'transformations': {'🥚': '🍳', '🥩': '🥓'}},
    'หม้อ': {'verb': 'ต้ม', 'transformations': {'🦐': '🦞', '🥔': '🍟'}},
    'เขียง': {'verb': 'หั่น', 'transformations': {'🥬': '🥗', '🥕': '🥒','🐟': '🍣'}}};

let audioInitialized = false;
const sounds = {};

// [MODIFIED] Function to convert slider value (0-100) to decibels for Tone.js
function convertVolumeToDb(value) {
    if (value == 0) return -Infinity;
    return (value / 100) * 40 - 40;
}

function initAudio() {
    if (audioInitialized) return;
    Tone.start();

    // [MODIFIED] Set master volume on initialization
    const savedVolume = localStorage.getItem('gameVolume') || '80';
    document.getElementById('volume-slider').value = savedVolume;
    Tone.Destination.volume.value = convertVolumeToDb(savedVolume);

    sounds.click = new Tone.Synth({ oscillator: { type: 'sine' }, envelope: { attack: 0.005, decay: 0.1, sustain: 0.3, release: 0.2 }, volume: -15 }).toDestination();
    sounds.success = new Tone.Synth({ oscillator: { type: 'triangle' }, envelope: { attack: 0.01, decay: 0.2, sustain: 0.1, release: 0.2 }, volume: -10 }).toDestination();
    sounds.error = new Tone.Synth({ oscillator: { type: 'square' }, envelope: { attack: 0.01, decay: 0.3, sustain: 0, release: 0.1 }, volume: -15 }).toDestination();
    sounds.receive = new Tone.MembraneSynth({ pitchDecay: 0.01, octaves: 5, envelope: { attack: 0.001, decay: 0.3, sustain: 0.01, release: 0.2 }, volume: -12 }).toDestination();
    sounds.trash = new Tone.NoiseSynth({ noise: { type: 'white' }, envelope: { attack: 0.005, decay: 0.1, sustain: 0, release: 0.1 }, volume: -20 }).toDestination();
    sounds.levelUp = new Tone.PolySynth(Tone.Synth, { oscillator: { type: "fatsawtooth" }, envelope: { attack: 0.01, decay: 0.5, sustain: 0.2, release: 0.5 }, volume: -8 }).toDestination();
    sounds.gameOver = new Tone.PolySynth(Tone.Synth, { oscillator: { type: "fatsquare" }, envelope: { attack: 0.01, decay: 0.8, sustain: 0.1, release: 1 }, volume: -8 }).toDestination();
    audioInitialized = true;
}
function playSound(soundName) {
    if (!audioInitialized || !sounds[soundName]) return;
    try {
        switch(soundName) {
            case 'click': sounds.click.triggerAttackRelease('C5', '8n'); break;
            case 'success':
                sounds.success.triggerAttackRelease('C5', '16n', Tone.now());
                sounds.success.triggerAttackRelease('E5', '16n', Tone.now() + 0.1);
                sounds.success.triggerAttackRelease('G5', '16n', Tone.now() + 0.2);
                break;
            case 'error': sounds.error.triggerAttackRelease('C3', '8n'); break;
            case 'receive': sounds.receive.triggerAttackRelease('C2', '8n'); break;
            case 'trash': sounds.trash.triggerAttack('8n'); break;
            case 'levelUp': sounds.levelUp.triggerAttackRelease(["C4", "E4", "G4", "C5"], "0.5"); break;
            case 'gameOver': sounds.gameOver.triggerAttackRelease(["C4", "G3", "C3"], "1"); break;
        }
    } catch (e) { console.error(`Error playing sound ${soundName}:`, e); }
}

const allScreens = ['login', 'lobby', 'game', 'level-complete', 'game-over', 'game-won'];
const screens = {};
allScreens.forEach(id => screens[id] = document.getElementById(`${id}-screen`));
const playerNameInput = document.getElementById('player-name');
const roomCodeInput = document.getElementById('room-code-input');
const createBtn = document.getElementById('create-btn');
const joinBtn = document.getElementById('join-btn');
const leaveRoomBtn = document.getElementById('leave-room-btn');
const roomCodeDisplay = document.getElementById('room-code-display');
const playerList = document.getElementById('player-list');
const startGameBtn = document.getElementById('start-game-btn');
const scoreEl = document.getElementById('score');
const targetScoreEl = document.getElementById('target-score');
const timeEl = document.getElementById('time');
const levelEl = document.getElementById('level');
const playerCountEl = document.getElementById('player-count');
const myNameEl = document.getElementById('my-name');
const objectivesListEl = document.getElementById('objectives-list');
const conveyorBelt = document.getElementById('conveyor-belt');
const plateContainer = document.getElementById('plate-container');
const submitOrderBtn = document.getElementById('submit-order-btn');
const passLeftNameEl = document.getElementById('pass-left-name');
const passRightNameEl = document.getElementById('pass-right-name');
const popupOverlay = document.getElementById('popup-overlay');
const popupMessage = document.getElementById('popup-message');
const popupCloseBtn = document.getElementById('popup-close-btn');
const levelCompleteMessageEl = document.getElementById('level-complete-message');
const totalScoreMessageEl = document.getElementById('total-score-message');
const gameOverMessageEl = document.getElementById('game-over-message');
const finalTotalScoreEl = document.getElementById('final-total-score');
const finalWonScoreEl = document.getElementById('final-won-score');
const backToLobbyBtn = document.getElementById('back-to-lobby-btn');
const wonBackToLobbyBtn = document.getElementById('won-back-to-lobby-btn');
const abilityStationEl = document.getElementById('ability-station');

// [ADDED] Settings elements
const settingsBtn = document.getElementById('settings-btn');
const settingsPopup = document.getElementById('settings-popup');
const settingsCloseBtn = document.getElementById('settings-close-btn');
const volumeSlider = document.getElementById('volume-slider');
const themeToggleBtn = document.getElementById('theme-toggle');

function showScreen(screenName) {
    allScreens.forEach(id => screens[id].classList.add('hidden'));
    if (screenName && screens[screenName]) {
        screens[screenName].classList.remove('hidden');
    }
}

function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;
    const toast = document.createElement('div');
    let bgColor, textColor;
    switch (type) {
        case 'success': bgColor = 'bg-green-500'; textColor = 'text-white'; break;
        case 'error': bgColor = 'bg-red-500'; textColor = 'text-white'; break;
        default: bgColor = 'bg-blue-500'; textColor = 'text-white';
    }
    toast.className = `toast p-4 rounded-lg shadow-lg flex items-center space-x-3 ${bgColor} ${textColor} font-bold`;
    toast.innerHTML = `<span>${message}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 4500);
}

function showPopup(message) {
    popupMessage.textContent = message;
    popupOverlay.classList.remove('hidden');
}
popupCloseBtn.addEventListener('click', () => popupOverlay.classList.add('hidden'));

let isDragging = false;
let draggedElement = null;
let ghostElement = null;
let draggedData = null;
let currentDropZone = null;

function startDrag(event, data, element) {
    if (isDragging) return;
    event.preventDefault();
    isDragging = true;
    draggedElement = element;
    draggedData = data;
    ghostElement = element.cloneNode(true);
    ghostElement.classList.add('ghost-drag');
    document.body.appendChild(ghostElement);
    draggedElement.classList.add('dragging');
    moveGhost(event);
    document.addEventListener('mousemove', moveGhost, { passive: false });
    document.addEventListener('touchmove', moveGhost, { passive: false });
    document.addEventListener('mouseup', endDrag);
    document.addEventListener('touchend', endDrag);
}

function moveGhost(event) {
    if (!isDragging) return;
    event.preventDefault();
    const x = event.touches ? event.touches[0].clientX : event.clientX;
    const y = event.touches ? event.touches[0].clientY : event.clientY;
    ghostElement.style.left = `${x - ghostElement.offsetWidth / 2}px`;
    ghostElement.style.top = `${y - ghostElement.offsetHeight / 2}px`;
    ghostElement.style.display = 'none';
    const elementUnder = document.elementFromPoint(x, y);
    ghostElement.style.display = '';
    const dropZone = elementUnder ? elementUnder.closest('.drop-zone') : null;
    if (currentDropZone && currentDropZone !== dropZone) {
        currentDropZone.classList.remove('drag-over');
    }
    if (dropZone) {
        dropZone.classList.add('drag-over');
    }
    currentDropZone = dropZone;
}

function endDrag(event) {
    if (!isDragging) return;
    isDragging = false;
    
    let dropSuccessful = false;
    if (currentDropZone) {
        currentDropZone.classList.remove('drag-over');
        dropSuccessful = handleDrop(currentDropZone);
    }

    document.body.removeChild(ghostElement);
    draggedElement.classList.remove('dragging');

    if (dropSuccessful) {
         draggedElement.remove();
    }

    document.removeEventListener('mousemove', moveGhost);
    document.removeEventListener('touchmove', moveGhost);
    document.removeEventListener('mouseup', endDrag);
    document.removeEventListener('touchend', endDrag);
}

function handleDrop(zone) {
    if (!draggedData) return false;
    const targetId = zone.id;

    if (targetId === 'ability-station') {
        if (draggedData.type === 'ingredient') {
            if (isAbilityProcessing) {
                showToast('กำลังใช้งานความสามารถอยู่', 'error');
                playSound('error');
                return false;
            }
            if (!myAbility) {
                showToast('คุณไม่มีความสามารถ', 'error');
                playSound('error');
                return false;
            }
            const abilityConfig = ABILITIES_CONFIG[myAbility];
            if (!abilityConfig || !abilityConfig.transformations[draggedData.name]) {
                showToast('วัตถุดิบนี้ใช้กับความสามารถของคุณไม่ได้', 'error');
                playSound('error');
                return false;
            }

            socket.emit('use_ability', { room_id: currentRoomId, item_name: draggedData.name });
            return true;
        } else {
            playSound('error');
            return false;
        }
    }
    
    if (draggedData.type === 'plate') {
         playSound('error');
         return false;
    }

    switch (targetId) {
        case 'pass-left-zone':
        case 'pass-right-zone':
            socket.emit('player_action', { room_id: currentRoomId, type: 'pass_item', direction: targetId.includes('left') ? 'left' : 'right', item: draggedData });
            playSound('receive');
            return true;
        case 'trash-zone':
            socket.emit('player_action', { room_id: currentRoomId, type: 'trash_item' });
            playSound('trash');
            return true;
        default:
            if (zone.classList.contains('plate') && draggedData.type === 'ingredient') {
                const plateElement = zone;
                const plateData = JSON.parse(plateElement.dataset.contents);
                const ingredientToAdd = draggedData.name;
                if (!myCurrentObjectiveIngredients.includes(ingredientToAdd)) {
                    showToast('วัตถุดิบนี้ไม่อยู่ในเมนูเป้าหมาย!', 'error');
                    playSound('error');
                    return false;
                }
                const requiredCount = myCurrentObjectiveIngredients.filter(i => i === ingredientToAdd).length;
                const currentCount = plateData.filter(i => i === ingredientToAdd).length;
                if (currentCount >= requiredCount) {
                    showToast(`ใส่ ${ingredientToAdd} ครบตามสูตรแล้ว!`, 'warning');
                    playSound('error');
                    return false;
                }
                const newContents = [...plateData, ingredientToAdd];
                if (newContents.length <= 6) {
                    socket.emit('player_action', { room_id: currentRoomId, type: 'add_to_plate', new_plate_contents: newContents });
                    playSound('click');
                    return true;
                }
            }
            break;
    }
    return false;
}

function createItemElement(itemName) {
    const item = document.createElement('div');
    item.textContent = itemName;
    item.className = 'item bg-yellow-200 text-yellow-800 dark:bg-yellow-700 dark:text-yellow-100 font-semibold shadow-sm m-1';
    item.id = 'item-' + Date.now() + Math.random();
    const data = {type: 'ingredient', name: itemName};
    item.addEventListener('mousedown', (e) => startDrag(e, data, item));
    item.addEventListener('touchstart', (e) => startDrag(e, data, item));
    return item;
}

function createPlateElement(contents = []) {
    const plate = document.createElement('div');
    plate.className = 'plate drop-zone bg-[var(--bg-secondary)] p-3 rounded-lg shadow-md w-4/5 flex flex-col items-center border-[var(--border-color)]';
    plate.id = 'plate-' + Date.now() + Math.random();
    plate.dataset.contents = JSON.stringify(contents);
    const title = document.createElement('span');
    title.className = 'font-bold text-sm mb-2 text-[var(--text-secondary)]';
    title.textContent = 'จาน';
    plate.appendChild(title);
    const itemsContainer = document.createElement('div');
    itemsContainer.className = 'plate-items-container flex flex-wrap justify-center gap-2 items-center';
    contents.forEach(ing => {
        const itemEl = document.createElement('span');
        itemEl.className = 'item-in-plate';
        itemEl.textContent = ing;
        itemsContainer.appendChild(itemEl);
    });
    plate.appendChild(itemsContainer);
    return plate;
}

// --- Event Listeners ---
createBtn.addEventListener('click', () => { initAudio(); playSound('click'); myName = playerNameInput.value.trim(); if (!myName) { showPopup('กรุณาใส่ชื่อของคุณ!'); return; } socket.emit('create_room', { name: myName }); });
joinBtn.addEventListener('click', () => { initAudio(); playSound('click'); myName = playerNameInput.value.trim(); const roomId = roomCodeInput.value.trim().toUpperCase(); if (!myName || !roomId) { showPopup('กรุณาใส่ชื่อและรหัสห้อง!'); return; } socket.emit('join_room', { name: myName, room_id: roomId }); });
leaveRoomBtn.addEventListener('click', () => { playSound('click'); location.reload(); });
roomCodeDisplay.addEventListener('click', () => { if(currentRoomId) navigator.clipboard.writeText(currentRoomId).then(() => { showToast('คัดลอกรหัสห้องแล้ว!', 'success'); playSound('click'); }); });
startGameBtn.addEventListener('click', () => { playSound('levelUp'); socket.emit('start_game', { room_id: currentRoomId }); });
submitOrderBtn.addEventListener('click', () => { playSound('click'); socket.emit('player_action', { room_id: currentRoomId, type: 'submit_order' }); });
backToLobbyBtn.addEventListener('click', () => { playSound('click'); showScreen('lobby'); });
wonBackToLobbyBtn.addEventListener('click', () => { playSound('click'); showScreen('lobby'); });

// [ADDED] Settings Listeners
settingsBtn.addEventListener('click', () => { settingsPopup.classList.remove('hidden'); });
settingsCloseBtn.addEventListener('click', () => { settingsPopup.classList.add('hidden'); });
volumeSlider.addEventListener('input', (e) => {
    const volumeValue = e.target.value;
    localStorage.setItem('gameVolume', volumeValue);
    if (audioInitialized) {
        Tone.Destination.volume.value = convertVolumeToDb(volumeValue);
    }
});


// --- Socket.IO Listeners ---
socket.on('connect', () => { mySid = socket.id; showScreen('login'); });
socket.on('disconnect', () => { showPopup('การเชื่อมต่อหลุด!'); showScreen('login'); setTimeout(() => location.reload(), 2000); });
socket.on('room_created', (data) => { currentRoomId = data.room_id; isHost = data.is_host; roomCodeDisplay.textContent = currentRoomId; showScreen('lobby'); });
socket.on('join_success', (data) => { currentRoomId = data.room_id; isHost = data.is_host; roomCodeDisplay.textContent = currentRoomId; showScreen('lobby'); });
socket.on('update_lobby', (data) => {
    if (screens.lobby.classList.contains('hidden')) return;
    if (currentRoomId !== data.room_id) return;
    playerList.innerHTML = '';
    data.players.forEach(p => {
        const li = document.createElement('li'); li.className = 'text-[var(--text-primary)]'; li.textContent = p.name;
        if (p.sid === data.host_sid) { const hostTag = document.createElement('span'); hostTag.className = 'player-tag bg-yellow-400 text-yellow-900'; hostTag.textContent = 'Host'; li.appendChild(hostTag); }
        if (p.sid === mySid) { const youTag = document.createElement('span'); youTag.className = 'player-tag bg-blue-400 text-white'; youTag.textContent = 'You'; li.appendChild(youTag); }
        playerList.appendChild(li);
    });
    isHost = (mySid === data.host_sid);
    startGameBtn.classList.toggle('hidden', !(isHost && data.players.length >= 1));
});
socket.on('new_host', (data) => { isHost = (mySid === data.host_sid); if (isHost) showToast('คุณได้รับตำแหน่ง Host!', 'info'); });
socket.on('error_message', (data) => { showPopup(data.message); playSound('error'); });
socket.on('game_started', (data) => {
    showScreen('game');
    mySid = data.your_sid;
    passLeftNameEl.textContent = data.left_neighbor;
    passRightNameEl.textContent = data.right_neighbor;
    myNameEl.textContent = data.your_name;
    updateGameStateUI(data.initial_state);
});
socket.on('update_game_state', (state) => updateGameStateUI(state));
socket.on('update_neighbors', (data) => { passLeftNameEl.textContent = data.left_neighbor; passRightNameEl.textContent = data.right_neighbor; });
socket.on('receive_item', (data) => {
    playSound('receive');
    const placeholder = conveyorBelt.querySelector('span');
    if (placeholder) placeholder.remove();
    const itemData = data.item;
    if (itemData.type === 'ingredient') { let element = createItemElement(itemData.name); if (element) conveyorBelt.appendChild(element); }
});
socket.on('action_success', (data) => { showToast(data.message, 'success'); if (data.sound) playSound(data.sound); });
socket.on('action_fail', (data) => { showToast(data.message, 'error'); if (data.sound) playSound(data.sound); });
socket.on('clear_all_items', () => { conveyorBelt.innerHTML = '<span class="text-[var(--text-secondary)] flex-shrink-0">วัตถุดิบที่ได้รับ...</span>'; });
socket.on('level_complete', (data) => { playSound('levelUp'); levelCompleteMessageEl.textContent = `คะแนนในด่าน ${data.level}: ${data.level_score}`; totalScoreMessageEl.textContent = `คะแนนรวม: ${data.total_score}`; showScreen('level-complete'); });
socket.on('start_next_level', (data) => { showScreen('game'); updateGameStateUI(data); });
socket.on('game_over', (data) => { playSound('gameOver'); finalTotalScoreEl.textContent = data.total_score; gameOverMessageEl.textContent = data.message || ''; gameOverMessageEl.classList.toggle('hidden', !data.message); showScreen('game-over'); });
socket.on('game_won', (data) => { playSound('levelUp'); finalWonScoreEl.textContent = data.total_score; showScreen('game-won'); });

function updateGameStateUI(state) {
    if (!state || screens.game.classList.contains('hidden')) return;
    
    if (gameStateUpdateInterval) clearInterval(gameStateUpdateInterval);

    scoreEl.textContent = state.score;
    targetScoreEl.textContent = state.target_score;
    timeEl.textContent = state.time_left;
    levelEl.textContent = state.level;
    playerCountEl.textContent = state.player_order_sids.length;

    const myObjectiveDisplay = state.all_player_objectives.find(obj => obj.player_name === myName);
    objectivesListEl.innerHTML = '';
    if (myObjectiveDisplay) {
        myCurrentObjectiveIngredients = myObjectiveDisplay.ingredients.map(i => i.name);
        
        const ingredientsHtml = myObjectiveDisplay.ingredients.map(ing_data => {
            if (ing_data.hint && ing_data.base) {
                return `<span class="inline-flex items-center gap-1">${ing_data.name} <span class="text-xs font-semibold text-indigo-600 dark:text-indigo-400">(ใช้ ${ing_data.base} กับ ${ing_data.hint})</span></span>`;
            } else {
                return `<span>${ing_data.name}</span>`;
            }
        }).join(' ');

        objectivesListEl.innerHTML = `
            <li class="bg-green-100 dark:bg-green-900/50 p-3 rounded-lg shadow-sm border-l-4 border-green-500 dark:border-green-400">
                <div class="font-bold text-green-800 dark:text-green-200 text-lg">${myObjectiveDisplay.objective_name}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400 mb-1">(${myObjectiveDisplay.points} คะแนน)</div>
                <div class="text-sm text-gray-600 dark:text-gray-300">ส่วนผสม:</div>
                <div class="text-2xl mt-1 flex flex-wrap gap-x-3 gap-y-1">${ingredientsHtml}</div>
            </li>`;
    } else {
        myCurrentObjectiveIngredients = [];
        objectivesListEl.innerHTML = '<li>ไม่มีเป้าหมายในขณะนี้</li>';
    }

    const myState = state.players_state[mySid];
    
    if (myState && abilityStationEl) {
        myAbility = myState.ability;
        isAbilityProcessing = !!myState.ability_processing;
        const ability = myState.ability;
        const processing = myState.ability_processing;

        if (processing) {
            const updateTimer = () => {
                const timeLeft = Math.ceil(processing.end_time - (Date.now() / 1000));
                if (timeLeft <= 0) {
                    clearInterval(gameStateUpdateInterval);
                }
                const verb = ABILITIES_CONFIG[ability]?.verb || 'แปรรูป';
                abilityStationEl.innerHTML = `
                    <h4 class="font-bold text-indigo-800 dark:text-indigo-200">${ability}</h4>
                    <div class="text-lg font-semibold my-1">กำลัง${verb}...</div>
                    <div class="text-4xl font-mono">${processing.input} → ${processing.output}</div>
                    <div class="text-sm text-gray-500 mt-1">เหลือเวลา: ${timeLeft > 0 ? timeLeft : 0} วิ</div>
                `;
            };
            updateTimer();
            gameStateUpdateInterval = setInterval(updateTimer, 500);

            abilityStationEl.classList.remove('drop-zone');
            abilityStationEl.classList.add('processing');
        } else if (ability) {
            abilityStationEl.innerHTML = `
                <h4 class="font-bold text-indigo-800 dark:text-indigo-200">ความสามารถ: ${ability}</h4>
                <p class="text-gray-500 dark:text-gray-400 mt-2">ลากวัตถุดิบมาที่นี่เพื่อใช้งาน</p>
            `;
            abilityStationEl.classList.add('drop-zone');
            abilityStationEl.classList.remove('processing');
        } else {
            abilityStationEl.innerHTML = `
                <h4 class="font-bold text-gray-600 dark:text-gray-400">ไม่มีความสามารถ</h4>
            `;
            abilityStationEl.classList.remove('drop-zone', 'processing');
        }
    }
    
    plateContainer.innerHTML = '';
    if (myState && Array.isArray(myState.plate)) {
        plateContainer.appendChild(createPlateElement(myState.plate));
    }
}

// --- [MODIFIED] Theme Toggle Logic ---
function applyTheme(theme) {
    if (theme === 'dark') {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
    localStorage.setItem('theme', theme);
}

themeToggleBtn.addEventListener('click', () => {
    const currentTheme = localStorage.getItem('theme') || 'light';
    applyTheme(currentTheme === 'light' ? 'dark' : 'light');
});

// --- Initial Setup on Load ---
document.addEventListener('DOMContentLoaded', () => {
    // Apply saved theme or system preference
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (savedTheme) {
        applyTheme(savedTheme);
    } else {
        applyTheme(prefersDark ? 'dark' : 'light');
    }

    // Set initial volume slider position
    const savedVolume = localStorage.getItem('gameVolume') || '80';
    volumeSlider.value = savedVolume;
});
