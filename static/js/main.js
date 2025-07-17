// main.js (เวอร์ชันปรับปรุง)
// --- ภาพรวมการเปลี่ยนแปลง ---
// 1. ปรับปรุงฟังก์ชัน updateGameStateUI: เพื่อลดการ re-render ที่ไม่จำเป็น
//    - `updatePlateUI`: อัปเดตเฉพาะไอเท็มในจานที่เปลี่ยนแปลง
//    - `updateObjectivesUI`: อัปเดตเฉพาะเป้าหมายเมื่อมีการเปลี่ยนแปลงจริงๆ
// 2. ปรับปรุงการจัดการ State: แยกฟังก์ชันการอัปเดตส่วนต่างๆ ของ UI ให้ชัดเจนขึ้น
//    ทำให้โค้ดอ่านง่ายและลดโอกาสเกิดข้อผิดพลาด

const socket = io();

// --- Global State ---
let currentRoomId = null;
let myName = '';
let mySid = '';
let isHost = false;
let myAbility = null;
let myCurrentObjective = null; // เก็บข้อมูล objective ปัจจุบันเพื่อเปรียบเทียบ

// --- Audio ---
let audioInitialized = false;
const sounds = {};

// --- DOM Elements ---
const screens = {};
['login', 'lobby', 'game', 'level-complete', 'game-over', 'game-won'].forEach(id => screens[id] = document.getElementById(`${id}-screen`));
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
const settingsBtn = document.getElementById('settings-btn');
const settingsPopup = document.getElementById('settings-popup');
const settingsCloseBtn = document.getElementById('settings-close-btn');
const volumeSlider = document.getElementById('volume-slider');
const themeToggleBtn = document.getElementById('theme-toggle');

// --- Audio Functions ---
function convertVolumeToDb(value) {
    return value == 0 ? -Infinity : (value / 100) * 40 - 40;
}

function initAudio() {
    if (audioInitialized) return;
    Tone.start();
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

// --- UI Functions ---
function showScreen(screenName) {
    Object.values(screens).forEach(s => s.classList.add('hidden'));
    if (screens[screenName]) screens[screenName].classList.remove('hidden');
}

function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;
    const toast = document.createElement('div');
    const colors = {
        success: 'bg-green-500 text-white',
        error: 'bg-red-500 text-white',
        info: 'bg-blue-500 text-white'
    };
    toast.className = `toast p-4 rounded-lg shadow-lg flex items-center space-x-3 ${colors[type] || colors.info} font-bold`;
    toast.innerHTML = `<span>${message}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4500);
}

function showPopup(message) {
    popupMessage.textContent = message;
    popupOverlay.classList.remove('hidden');
}

// --- Drag and Drop ---
let isDragging = false, draggedElement = null, ghostElement = null, draggedData = null, currentDropZone = null;

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
    const { clientX, clientY } = event.touches ? event.touches[0] : event;
    ghostElement.style.left = `${clientX - ghostElement.offsetWidth / 2}px`;
    ghostElement.style.top = `${clientY - ghostElement.offsetHeight / 2}px`;
    ghostElement.style.display = 'none';
    const elementUnder = document.elementFromPoint(clientX, clientY);
    ghostElement.style.display = '';
    const dropZone = elementUnder ? elementUnder.closest('.drop-zone') : null;
    if (currentDropZone && currentDropZone !== dropZone) currentDropZone.classList.remove('drag-over');
    if (dropZone) dropZone.classList.add('drag-over');
    currentDropZone = dropZone;
}

function endDrag() {
    if (!isDragging) return;
    isDragging = false;
    let dropSuccessful = false;
    if (currentDropZone) {
        currentDropZone.classList.remove('drag-over');
        dropSuccessful = handleDrop(currentDropZone);
    }
    document.body.removeChild(ghostElement);
    draggedElement.classList.remove('dragging');
    if (dropSuccessful) draggedElement.remove();
    document.removeEventListener('mousemove', moveGhost);
    document.removeEventListener('touchmove', moveGhost);
    document.removeEventListener('mouseup', endDrag);
    document.removeEventListener('touchend', endDrag);
}

function handleDrop(zone) {
    if (!draggedData) return false;
    const targetId = zone.id;

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
        case 'ability-station':
            if (draggedData.type === 'ingredient') {
                socket.emit('use_ability', { room_id: currentRoomId, item_name: draggedData.name });
                return true; // Assume success, server will send fail message if needed
            }
            return false;
        default:
            if (zone.classList.contains('plate') && draggedData.type === 'ingredient') {
                const plateElement = zone;
                const plateData = JSON.parse(plateElement.dataset.contents);
                const ingredientToAdd = draggedData.name;
                
                const requiredIngredients = myCurrentObjective?.ingredients.map(i => i.name) || [];
                if (!requiredIngredients.includes(ingredientToAdd)) {
                    showToast('วัตถุดิบนี้ไม่อยู่ในเมนูเป้าหมาย!', 'error');
                    playSound('error');
                    return false;
                }
                const requiredCount = requiredIngredients.filter(i => i === ingredientToAdd).length;
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
            return false;
    }
}

// --- Element Creation ---
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
    plate.id = 'plate-' + Date.now();
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
function setupEventListeners() {
    createBtn.addEventListener('click', () => { initAudio(); playSound('click'); myName = playerNameInput.value.trim(); if (!myName) { showPopup('กรุณาใส่ชื่อของคุณ!'); return; } socket.emit('create_room', { name: myName }); });
    joinBtn.addEventListener('click', () => { initAudio(); playSound('click'); myName = playerNameInput.value.trim(); const roomId = roomCodeInput.value.trim().toUpperCase(); if (!myName || !roomId) { showPopup('กรุณาใส่ชื่อและรหัสห้อง!'); return; } socket.emit('join_room', { name: myName, room_id: roomId }); });
    leaveRoomBtn.addEventListener('click', () => { playSound('click'); location.reload(); });
    roomCodeDisplay.addEventListener('click', () => { if(currentRoomId) navigator.clipboard.writeText(currentRoomId).then(() => { showToast('คัดลอกรหัสห้องแล้ว!', 'success'); playSound('click'); }); });
    startGameBtn.addEventListener('click', () => { playSound('levelUp'); socket.emit('start_game', { room_id: currentRoomId }); });
    submitOrderBtn.addEventListener('click', () => { playSound('click'); socket.emit('player_action', { room_id: currentRoomId, type: 'submit_order' }); });
    backToLobbyBtn.addEventListener('click', () => { playSound('click'); showScreen('lobby'); });
    wonBackToLobbyBtn.addEventListener('click', () => { playSound('click'); showScreen('lobby'); });
    popupCloseBtn.addEventListener('click', () => popupOverlay.classList.add('hidden'));
    settingsBtn.addEventListener('click', () => settingsPopup.classList.remove('hidden'));
    settingsCloseBtn.addEventListener('click', () => settingsPopup.classList.add('hidden'));
    volumeSlider.addEventListener('input', (e) => {
        const volumeValue = e.target.value;
        localStorage.setItem('gameVolume', volumeValue);
        if (audioInitialized) Tone.Destination.volume.value = convertVolumeToDb(volumeValue);
    });
    themeToggleBtn.addEventListener('click', () => {
        const currentTheme = localStorage.getItem('theme') || 'light';
        applyTheme(currentTheme === 'light' ? 'dark' : 'light');
    });
}

// --- Theme ---
function applyTheme(theme) {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    localStorage.setItem('theme', theme);
}

// --- Game State Update Functions ---
function updateGlobalUI(state) {
    scoreEl.textContent = state.score;
    targetScoreEl.textContent = state.target_score;
    timeEl.textContent = state.time_left;
    levelEl.textContent = state.level;
    playerCountEl.textContent = state.player_order_sids.length;
}

function updatePlateUI(myState) {
    const currentPlate = plateContainer.querySelector('.plate');
    const newContents = myState?.plate || [];
    const oldContents = currentPlate ? JSON.parse(currentPlate.dataset.contents) : null;

    if (JSON.stringify(newContents) !== JSON.stringify(oldContents)) {
        plateContainer.innerHTML = '';
        plateContainer.appendChild(createPlateElement(newContents));
    }
}

function updateObjectivesUI(allObjectives) {
    const newObjective = allObjectives.find(obj => obj.player_name === myName);
    
    // เปรียบเทียบ objective ใหม่กับเก่า ถ้าไม่เหมือนกันค่อย render ใหม่
    if (JSON.stringify(newObjective) === JSON.stringify(myCurrentObjective)) {
        return; // ไม่ต้องทำอะไรถ้า objective เหมือนเดิม
    }
    
    myCurrentObjective = newObjective;
    objectivesListEl.innerHTML = '';

    if (newObjective) {
        const ingredientsHtml = newObjective.ingredients.map(ing_data => {
            if (ing_data.hint && ing_data.base) {
                return `<span class="inline-flex items-center gap-1">${ing_data.name} <span class="text-xs font-semibold text-indigo-600 dark:text-indigo-400">(ใช้ ${ing_data.base} กับ ${ing_data.hint})</span></span>`;
            }
            return `<span>${ing_data.name}</span>`;
        }).join(' ');

        objectivesListEl.innerHTML = `
            <li class="bg-green-100 dark:bg-green-900/50 p-3 rounded-lg shadow-sm border-l-4 border-green-500 dark:border-green-400">
                <div class="font-bold text-green-800 dark:text-green-200 text-lg">${newObjective.objective_name}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400 mb-1">(${newObjective.points} คะแนน)</div>
                <div class="text-sm text-gray-600 dark:text-gray-300">ส่วนผสม:</div>
                <div class="text-2xl mt-1 flex flex-wrap gap-x-3 gap-y-1">${ingredientsHtml}</div>
            </li>`;
    } else {
        objectivesListEl.innerHTML = '<li>ไม่มีเป้าหมายในขณะนี้</li>';
    }
}

function updateAbilityStationUI(myState) {
    myAbility = myState?.ability;
    const processing = myState?.ability_processing;

    if (processing) {
        const verb = { 'กระทะ': 'ทอด', 'หม้อ': 'ต้ม', 'เขียง': 'หั่น' }[myAbility] || 'แปรรูป';
        const timeLeft = Math.ceil(processing.end_time - (Date.now() / 1000));
        abilityStationEl.innerHTML = `
            <h4 class="font-bold text-indigo-800 dark:text-indigo-200">${myAbility}</h4>
            <div class="text-lg font-semibold my-1">กำลัง${verb}...</div>
            <div class="text-4xl font-mono">${processing.input} → ${processing.output}</div>
            <div class="text-sm text-gray-500 mt-1">เหลือเวลา: ${timeLeft > 0 ? timeLeft : 0} วิ</div>`;
        abilityStationEl.classList.add('processing');
        abilityStationEl.classList.remove('drop-zone');
    } else if (myAbility) {
        abilityStationEl.innerHTML = `
            <h4 class="font-bold text-indigo-800 dark:text-indigo-200">ความสามารถ: ${myAbility}</h4>
            <p class="text-gray-500 dark:text-gray-400 mt-2">ลากวัตถุดิบมาที่นี่เพื่อใช้งาน</p>`;
        abilityStationEl.classList.remove('processing');
        abilityStationEl.classList.add('drop-zone');
    } else {
        abilityStationEl.innerHTML = `<h4 class="font-bold text-gray-600 dark:text-gray-400">ไม่มีความสามารถ</h4>`;
        abilityStationEl.classList.remove('processing', 'drop-zone');
    }
}

function updateGameStateUI(state) {
    if (!state || screens.game.classList.contains('hidden')) return;

    const myState = state.players_state ? state.players_state[mySid] : null;

    updateGlobalUI(state);
    updateObjectivesUI(state.all_player_objectives || []);
    if (myState) {
        updatePlateUI(myState);
        updateAbilityStationUI(myState);
    }
}

// --- Socket.IO Handlers ---
function setupSocketListeners() {
    socket.on('connect', () => { mySid = socket.id; showScreen('login'); });
    socket.on('disconnect', () => { showPopup('การเชื่อมต่อหลุด!'); showScreen('login'); setTimeout(() => location.reload(), 2000); });
    socket.on('room_created', (data) => { currentRoomId = data.room_id; isHost = data.is_host; roomCodeDisplay.textContent = currentRoomId; showScreen('lobby'); });
    socket.on('join_success', (data) => { currentRoomId = data.room_id; isHost = data.is_host; roomCodeDisplay.textContent = currentRoomId; showScreen('lobby'); });
    socket.on('update_lobby', (data) => {
        if (screens.lobby.classList.contains('hidden') || currentRoomId !== data.room_id) return;
        playerList.innerHTML = '';
        data.players.forEach(p => {
            const li = document.createElement('li');
            li.className = 'text-[var(--text-primary)]';
            li.textContent = p.name;
            if (p.sid === data.host_sid) li.innerHTML += ' <span class="player-tag bg-yellow-400 text-yellow-900">Host</span>';
            if (p.sid === mySid) li.innerHTML += ' <span class="player-tag bg-blue-400 text-white">You</span>';
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
    socket.on('update_game_state', updateGameStateUI);
    socket.on('update_neighbors', (data) => { passLeftNameEl.textContent = data.left_neighbor; passRightNameEl.textContent = data.right_neighbor; });
    socket.on('receive_item', (data) => {
        playSound('receive');
        const placeholder = conveyorBelt.querySelector('span');
        if (placeholder) placeholder.remove();
        if (data.item.type === 'ingredient') {
            conveyorBelt.appendChild(createItemElement(data.item.name));
        }
    });
    socket.on('action_success', (data) => { showToast(data.message, 'success'); if (data.sound) playSound(data.sound); });
    socket.on('action_fail', (data) => { showToast(data.message, 'error'); if (data.sound) playSound(data.sound); });
    socket.on('clear_all_items', () => { conveyorBelt.innerHTML = '<span class="text-[var(--text-secondary)] flex-shrink-0">วัตถุดิบที่ได้รับ...</span>'; });
    socket.on('level_complete', (data) => { playSound('levelUp'); levelCompleteMessageEl.textContent = `คะแนนในด่าน ${data.level}: ${data.level_score}`; totalScoreMessageEl.textContent = `คะแนนรวม: ${data.total_score}`; showScreen('level-complete'); });
    socket.on('start_next_level', (data) => { showScreen('game'); updateGameStateUI(data); });
    socket.on('game_over', (data) => { playSound('gameOver'); finalTotalScoreEl.textContent = data.total_score; gameOverMessageEl.textContent = data.message || ''; gameOverMessageEl.classList.toggle('hidden', !data.message); showScreen('game-over'); });
    socket.on('game_won', (data) => { playSound('levelUp'); finalWonScoreEl.textContent = data.total_score; showScreen('game-won'); });
}

// --- Initial Setup on Load ---
document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    applyTheme(savedTheme);
    const savedVolume = localStorage.getItem('gameVolume') || '80';
    volumeSlider.value = savedVolume;
    setupEventListeners();
    setupSocketListeners();
});
