# app.py
# วิธีรัน:
# 1. ติดตั้งไลบรารีที่จำเป็น: pip install Flask Flask-SocketIO eventlet
# 2. รันไฟล์นี้ด้วยคำสั่ง: python app.py
# 3. เปิดเว็บเบราว์เซอร์ไปที่ http://127.0.0.1:5000

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, join_room, leave_room, emit
import random
import string
import time

# --- การตั้งค่าพื้นฐาน ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-key-for-the-game!'
socketio = SocketIO(app, async_mode='eventlet')

# --- ข้อมูลหลักของเกม ---
rooms = {}  # เก็บข้อมูลห้องทั้งหมด { 'room_id': { 'players': {}, 'game_state': {} } }

# --- การตั้งค่าเกม ---
OBJECTIVE_DURATION = 45  # เวลาสำหรับเป้าหมายแต่ละรายการ (วินาที)

# สูตรอาหารทั้งหมด
RECIPES = {
    'สลัดผัก': {'ingredients': sorted(['ผักกาด', 'มะเขือเทศ', 'แครอท']), 'points': 50, 'time_bonus': 10},
    'เบอร์เกอร์': {'ingredients': sorted(['ขนมปัง', 'เนื้อ', 'ชีส']), 'points': 100, 'time_bonus': 15},
    'แซนด์วิช': {'ingredients': sorted(['ขนมปัง', 'แฮม', 'ผักกาด']), 'points': 80, 'time_bonus': 12},
    'สเต็ก': {'ingredients': sorted(['เนื้อ', 'มันฝรั่ง', 'แครอท']), 'points': 150, 'time_bonus': 20},
    'ไข่ดาว': {'ingredients': sorted(['ไข่', 'ไข่']), 'points': 40, 'time_bonus': 8},
    'พิซซ่า': {'ingredients': sorted(['แป้งพิซซ่า', 'ซอส', 'ชีส', 'แฮม']), 'points': 200, 'time_bonus': 25},
}
ALL_INGREDIENTS = list(set(ing for recipe in RECIPES.values() for ing in recipe['ingredients']))

# --- การตั้งค่าด่าน ---
LEVEL_DEFINITIONS = {
    1: {'target_score': 300, 'time': 180, 'spawn_interval': 5}, # ลดเวลาเพื่อให้ของออกเร็วขึ้น
    2: {'target_score': 500, 'time': 150, 'spawn_interval': 4},
    3: {'target_score': 800, 'time': 120, 'spawn_interval': 3},
}

# --- ฟังก์ชันเสริมสำหรับจัดการเป้าหมาย ---
def assign_new_objective(player_state):
    """สุ่มและกำหนดเป้าหมายใหม่ให้ผู้เล่น พร้อมเวลาหมดอายุ"""
    objective_name = random.choice(list(RECIPES.keys()))
    player_state['objective'] = {
        'name': objective_name,
        'expires_at': time.time() + OBJECTIVE_DURATION
    }

# --- หน้าเว็บหลัก ---
@app.route('/')
def index():
    # ส่งไฟล์ HTML ที่มีทั้ง CSS และ JavaScript อยู่ในตัว
    return render_template_string(open('templates/index.html', encoding='utf-8').read())

# --- การจัดการการเชื่อมต่อ SocketIO ---
@socketio.on('connect')
def handle_connect():
    print(f"ผู้เล่นเชื่อมต่อเข้ามา: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"ผู้เล่นตัดการเชื่อมต่อ: {request.sid}")
    
    room_id_to_update = None
    player_sid_to_remove = request.sid
    
    for room_id, room_data in rooms.items():
        if player_sid_to_remove in room_data['players']:
            room_id_to_update = room_id
            break
            
    if not room_id_to_update:
        return

    room = rooms.get(room_id_to_update)
    if not room: return

    player_name = room['players'].get(player_sid_to_remove, {}).get('name', 'Unknown')
    
    if player_sid_to_remove in room['players']:
        del room['players'][player_sid_to_remove]
    print(f"ผู้เล่น {player_name} ออกจากห้อง {room_id_to_update}")

    if not room['players']:
        print(f"ห้อง {room_id_to_update} ว่างเปล่า กำลังลบห้อง...")
        if room.get('game_state'):
            room['game_state']['is_active'] = False
        if room_id_to_update in rooms:
             del rooms[room_id_to_update]
        return

    game_state = room.get('game_state')
    if game_state and game_state.get('is_active'):
        if player_sid_to_remove in game_state['player_order_sids']:
            game_state['player_order_sids'].remove(player_sid_to_remove)
        if player_sid_to_remove in game_state['players_state']:
            del game_state['players_state'][player_sid_to_remove]

        if len(game_state['player_order_sids']) < 1:
            game_state['is_active'] = False
            total_final_score = game_state.get('total_score', 0) + game_state.get('score', 0)
            socketio.emit('game_over', {
                'total_score': total_final_score, 
                'message': 'ผู้เล่นไม่พอที่จะเล่นต่อ เกมจบลง'
            }, room=room_id_to_update)
            room['game_state'] = None
        else:
            player_sids = game_state['player_order_sids']
            for i, sid in enumerate(player_sids):
                left_neighbor_sid = player_sids[i - 1] if len(player_sids) > 1 else sid
                right_neighbor_sid = player_sids[(i + 1) % len(player_sids)] if len(player_sids) > 1 else sid
                socketio.emit('update_neighbors', {
                    'left_neighbor': room['players'][left_neighbor_sid]['name'],
                    'right_neighbor': room['players'][right_neighbor_sid]['name']
                }, room=sid)
            ui_state = get_augmented_state_for_ui(room_id_to_update)
            if ui_state:
                socketio.emit('update_game_state', ui_state, room=room_id_to_update)

    if room.get('host_sid') == player_sid_to_remove and room['players']:
        new_host_sid = list(room['players'].keys())[0]
        room['host_sid'] = new_host_sid
        socketio.emit('new_host', {'host_sid': new_host_sid}, room=room_id_to_update)

    socketio.emit('update_lobby', {
        'players': [{'sid': sid, 'name': p['name']} for sid, p in room['players'].items()],
        'host_sid': room.get('host_sid'),
        'room_id': room_id_to_update
    }, room=room_id_to_update)

# --- ระบบล็อบบี้และห้อง ---
@socketio.on('create_room')
def handle_create_room(data):
    player_name = data.get('name', 'ผู้เล่นนิรนาม')
    room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    while room_id in rooms:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    
    rooms[room_id] = {
        'players': {request.sid: {'name': player_name}},
        'game_state': None,
        'host_sid': request.sid
    }
    join_room(room_id)
    emit('room_created', {'room_id': room_id, 'is_host': True})
    socketio.emit('update_lobby', {
        'players': [{'sid': sid, 'name': p['name']} for sid, p in rooms[room_id]['players'].items()],
        'host_sid': rooms[room_id]['host_sid'],
        'room_id': room_id
    }, room=room_id)

@socketio.on('join_room')
def handle_join_room(data):
    player_name = data.get('name', 'ผู้เล่นนิรนาม')
    room_id = data.get('room_id', '').upper()

    if room_id not in rooms:
        emit('error_message', {'message': 'ไม่พบห้องนี้!'})
        return
    
    if rooms[room_id].get('game_state') and rooms[room_id]['game_state'].get('is_active'):
        emit('error_message', {'message': 'เกมในห้องนี้เริ่มไปแล้ว!'})
        return

    if len(rooms[room_id]['players']) >= 8:
        emit('error_message', {'message': 'ห้องเต็มแล้ว!'})
        return

    rooms[room_id]['players'][request.sid] = {'name': player_name}
    join_room(room_id)
    emit('join_success', {'room_id': room_id, 'is_host': request.sid == rooms[room_id]['host_sid']})
    socketio.emit('update_lobby', {
        'players': [{'sid': sid, 'name': p['name']} for sid, p in rooms[room_id]['players'].items()],
        'host_sid': rooms[room_id]['host_sid'],
        'room_id': room_id
    }, room=room_id)

# --- ฟังก์ชันเสริมสำหรับสร้าง State ---
def get_augmented_state_for_ui(room_id):
    room = rooms.get(room_id)
    if not room or not room.get('game_state'):
        return None

    game_state = room['game_state']
    ui_state = game_state.copy()
    
    all_player_objectives = []
    for sid, p_state in game_state.get('players_state', {}).items():
        player_name = room['players'].get(sid, {}).get('name', '???')
        objective_data = p_state.get('objective')
        if objective_data and 'name' in objective_data:
            recipe_details = RECIPES[objective_data['name']]
            all_player_objectives.append({
                'player_name': player_name,
                'objective_name': objective_data['name'],
                'ingredients': recipe_details['ingredients'],
                'points': recipe_details['points'],
                'expires_at': objective_data.get('expires_at', 0)
            })
    
    ui_state['all_player_objectives'] = all_player_objectives
    return ui_state

# --- ระบบเริ่มเกมและ Game Loop ---
def game_loop(room_id):
    last_spawn_time = time.time()

    with app.app_context():
        while rooms.get(room_id) and rooms[room_id].get('game_state'):
            game_state = rooms[room_id]['game_state']
            
            if not game_state.get('is_active'):
                break
            
            current_time = time.time()

            # --- ตรวจสอบเป้าหมายหมดเวลา ---
            for sid, p_state in game_state['players_state'].items():
                if p_state.get('objective') and p_state['objective'].get('expires_at'):
                    if current_time > p_state['objective']['expires_at']:
                        assign_new_objective(p_state)
                        socketio.emit('show_alert', {'message': 'เป้าหมายหมดเวลา! ได้รับเมนูใหม่'}, room=sid)

            game_state['time_left'] -= 1
            
            spawn_interval = LEVEL_DEFINITIONS[game_state['level']]['spawn_interval']
            
            # *** START OF CHANGES: ระบบสุ่มวัตถุดิบใหม่ ***
            if current_time - last_spawn_time > spawn_interval:
                all_player_sids = list(game_state['players_state'].keys())
                if all_player_sids:
                    # 1. รวบรวมวัตถุดิบที่เป็นไปได้ทั้งหมดจากเป้าหมายของผู้เล่นทุกคน
                    possible_ingredients = []
                    for sid in all_player_sids:
                        objective = game_state['players_state'][sid].get('objective')
                        if objective and objective.get('name') in RECIPES:
                            possible_ingredients.extend(RECIPES[objective['name']]['ingredients'])
                    
                    # ถ้าไม่มีเป้าหมายเลย ก็สุ่มจากวัตถุดิบทั้งหมด
                    if not possible_ingredients:
                        possible_ingredients = ALL_INGREDIENTS

                    # 2. สุ่มวัตถุดิบ 1 ชิ้น
                    if possible_ingredients:
                        ingredient_to_spawn = random.choice(possible_ingredients)
                        
                        # 3. สุ่มผู้เล่น 1 คนเพื่อรับวัตถุดิบ
                        recipient_sid = random.choice(all_player_sids)
                        
                        # 4. ส่งวัตถุดิบ
                        socketio.emit('receive_item', {'item': {'type': 'ingredient', 'name': ingredient_to_spawn}}, room=recipient_sid)
                
                last_spawn_time = time.time()
            # *** END OF CHANGES ***

            if game_state['time_left'] <= 0:
                game_state['is_active'] = False
                total_final_score = game_state.get('total_score', 0) + game_state.get('score', 0)
                socketio.emit('game_over', {'total_score': total_final_score, 'message': 'หมดเวลา!'}, room=room_id)
                if rooms.get(room_id):
                    rooms[room_id]['game_state'] = None 
                break

            ui_state = get_augmented_state_for_ui(room_id)
            if ui_state:
                socketio.emit('update_game_state', ui_state, room=room_id)
            socketio.sleep(1)

@socketio.on('start_game')
def handle_start_game(data):
    room_id = data.get('room_id')
    if room_id not in rooms or rooms[room_id]['host_sid'] != request.sid:
        return

    room = rooms[room_id]
    player_sids = list(room['players'].keys())
    random.shuffle(player_sids)

    players_state = {}
    for sid in player_sids:
        players_state[sid] = {'plate': [], 'objective': None}
        assign_new_objective(players_state[sid])
    
    start_level = 1
    room['game_state'] = {
        'is_active': True,
        'level': start_level,
        'score': 0,
        'total_score': 0,
        'target_score': LEVEL_DEFINITIONS[start_level]['target_score'],
        'time_left': LEVEL_DEFINITIONS[start_level]['time'],
        'player_order_sids': player_sids,
        'players_state': players_state
    }
    
    ui_state = get_augmented_state_for_ui(room_id)
    for i, sid in enumerate(player_sids):
        left_neighbor_sid = player_sids[i - 1] if len(player_sids) > 1 else sid
        right_neighbor_sid = player_sids[(i + 1) % len(player_sids)] if len(player_sids) > 1 else sid
        
        emit('game_started', {
            'initial_state': ui_state,
            'your_sid': sid,
            'your_name': room['players'][sid]['name'],
            'left_neighbor': room['players'][left_neighbor_sid]['name'],
            'right_neighbor': room['players'][right_neighbor_sid]['name']
        }, room=sid)

    socketio.start_background_task(target=game_loop, room_id=room_id)
    print(f"เกมในห้อง {room_id} เริ่มขึ้นแล้ว!")

# --- ระบบการกระทำของผู้เล่น ---
@socketio.on('player_action')
def handle_player_action(data):
    room_id = data.get('room_id')
    action_type = data.get('type')
    
    if not room_id or room_id not in rooms or not rooms[room_id].get('game_state'): return
    game_state = rooms[room_id]['game_state']
    if not game_state.get('is_active'): return
    
    player_sid = request.sid
    player_state = game_state['players_state'].get(player_sid)
    if not player_state: return
    
    if action_type == 'pass_item':
        item_data = data.get('item')
        direction = data.get('direction')
        player_index = game_state['player_order_sids'].index(player_sid)
        if isinstance(item_data, dict) and item_data.get('type') == 'plate':
            player_state['plate'] = []
        
        if len(game_state['player_order_sids']) > 1:
            target_sid = game_state['player_order_sids'][player_index - 1] if direction == 'left' else game_state['player_order_sids'][(player_index + 1) % len(game_state['player_order_sids'])]
        else:
            target_sid = player_sid
        socketio.emit('receive_item', {'item': item_data}, room=target_sid)

    elif action_type == 'add_to_plate':
        if player_state.get('plate') is not None:
             player_state['plate'] = data.get('new_plate_contents', [])

    elif action_type == 'take_from_conveyor':
        if data['item']['type'] == 'plate':
             player_state['plate'] = data['item']['contents']

    elif action_type == 'trash_item':
        if data.get('item_type') == 'plate':
            player_state['plate'] = []

    elif action_type == 'get_empty_plate':
        if player_state.get('plate') is None:
            player_state['plate'] = []

    elif action_type == 'submit_order':
        if player_state.get('plate') is None:
            emit('action_fail', {'message': 'คุณไม่มีจาน!'})
            return

        player_plate = sorted(player_state['plate'])
        player_objective_data = player_state.get('objective')
        if not player_objective_data: return

        player_objective_name = player_objective_data['name']
        required_ingredients = RECIPES[player_objective_name]['ingredients']
        
        if player_objective_name and player_plate == required_ingredients:
            points_earned = RECIPES[player_objective_name]['points']
            game_state['score'] += points_earned
            game_state['time_left'] = min(game_state['time_left'] + RECIPES[player_objective_name]['time_bonus'], 999)
            
            assign_new_objective(player_state)
            player_state['plate'] = [] 
            emit('action_success', {'message': f'ทำ {player_objective_name} สำเร็จ! (+{points_earned} คะแนน)'})
            
            if game_state['score'] >= game_state['target_score']:
                current_level = game_state['level']
                game_state['total_score'] += game_state['score']
                
                next_level = current_level + 1
                if next_level in LEVEL_DEFINITIONS:
                    game_state['is_active'] = False
                    socketio.emit('level_complete', {
                        'level': current_level,
                        'level_score': game_state['score'],
                        'total_score': game_state['total_score']
                    }, room=room_id)
                    socketio.sleep(5)

                    game_state['level'] = next_level
                    game_state['score'] = 0
                    game_state['target_score'] = LEVEL_DEFINITIONS[next_level]['target_score']
                    game_state['time_left'] += 45
                    
                    for sid in game_state['players_state']:
                        game_state['players_state'][sid]['plate'] = []
                    
                    socketio.emit('clear_all_items', {}, room=room_id)

                    game_state['is_active'] = True
                    socketio.emit('start_next_level', get_augmented_state_for_ui(room_id), room=room_id)
                else:
                    game_state['is_active'] = False
                    total_final_score = game_state.get('total_score', 0)
                    socketio.emit('game_won', {'total_score': total_final_score}, room=room_id)
                    if rooms.get(room_id):
                        rooms[room_id]['game_state'] = None
        else:
            emit('action_fail', {'message': 'สูตรไม่ถูกต้อง!'})

    ui_state = get_augmented_state_for_ui(room_id)
    if ui_state:
        socketio.emit('update_game_state', ui_state, room=room_id)

if __name__ == '__main__':
    import os
    if not os.path.exists('templates'):
        os.makedirs('templates')

    html_content = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ครัวอลหม่าน</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Kanit:wght@400;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Kanit', sans-serif; }
        .item, .plate { 
            cursor: grab; user-select: none; 
            transition: transform 0.2s ease-in-out, opacity 0.2s ease-in-out, box-shadow 0.2s ease-in-out;
        }
        .item:active, .plate:active { cursor: grabbing; }
        .dragging {
            opacity: 0.6; transform: scale(1.05) rotate(3deg) !important;
            box-shadow: 0 10px 20px rgba(0,0,0,0.2); cursor: grabbing;
        }
        .drop-zone { border: 2px dashed #ccc; transition: all 0.2s; }
        .drop-zone.drag-over { border-color: #4ade80; background-color: #f0fdf4; transform: scale(1.02); }
        .plate-items-container { min-height: 40px; }
        .item-in-plate { background-color: #dcfce7; color: #166534; }
        .plate-stack {
            border: 3px solid #9ca3af; background-color: #f3f4f6;
            box-shadow: 0 2px 0 #9ca3af, 0 4px 0 #e5e7eb, 0 6px 0 #9ca3af;
            cursor: pointer; transition: all 0.1s ease-in-out;
        }
        .plate-stack:active {
            transform: translateY(2px);
            box-shadow: 0 1px 0 #9ca3af, 0 2px 0 #e5e7eb, 0 3px 0 #9ca3af;
        }
        .player-tag {
            padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem;
            font-weight: bold; margin-left: 8px;
        }
        .screen-overlay {
            position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            background-color: rgba(0, 0, 0, 0.75);
            display: flex; align-items: center; justify-content: center;
            z-index: 50;
            transition: opacity 0.3s ease;
        }
        /* --- START: Popup/Toast Styles --- */
        .popup-box {
            transform: scale(0.7);
            opacity: 0;
        }
        .screen-overlay:not(.hidden) .popup-box {
            opacity: 1;
            animation: popup-bounce-in 0.4s cubic-bezier(0.68, -0.55, 0.27, 1.55) forwards;
        }
        @keyframes popup-bounce-in {
            0% { transform: scale(0.7); opacity: 0; }
            70% { transform: scale(1.05); }
            100% { transform: scale(1); opacity: 1; }
        }
        .toast {
            animation: toast-in 0.5s forwards, toast-out 0.5s 4s forwards;
            pointer-events: none;
        }
        @keyframes toast-in {
            from { transform: translateX(120%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes toast-out {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(120%); opacity: 0; }
        }
        /* --- END: Popup/Toast Styles --- */
    </style>
</head>
<body class="bg-gray-100 text-gray-800 flex items-center justify-center min-h-screen p-4">

    <div id="main-container" class="w-full max-w-7xl bg-white rounded-xl shadow-2xl p-6 transition-all duration-500 relative overflow-hidden">

        <!-- หน้าจอสร้าง/เข้าร่วมห้อง -->
        <div id="login-screen">
            <h1 class="text-4xl font-bold text-center text-orange-500 mb-6">ครัวอลหม่าน</h1>
            <div class="max-w-sm mx-auto">
                <input id="player-name" type="text" placeholder="ใส่ชื่อของคุณ" class="w-full p-3 border rounded-lg mb-4 focus:ring-2 focus:ring-orange-400 focus:outline-none">
                <input id="room-code-input" type="text" placeholder="ใส่รหัสห้อง (ถ้ามี)" class="w-full p-3 border rounded-lg mb-4 focus:ring-2 focus:ring-orange-400 focus:outline-none uppercase">
                <div class="flex space-x-4">
                    <button id="join-btn" class="w-full bg-blue-500 text-white p-3 rounded-lg font-bold hover:bg-blue-600 transition">เข้าร่วมห้อง</button>
                    <button id="create-btn" class="w-full bg-green-500 text-white p-3 rounded-lg font-bold hover:bg-green-600 transition">สร้างห้องใหม่</button>
                </div>
            </div>
        </div>

        <!-- หน้าจอรอเล่น -->
        <div id="lobby-screen" class="hidden">
            <h2 class="text-3xl font-bold text-center mb-2">ห้องรอเล่น</h2>
            <p class="text-center text-gray-500 mb-4">รหัสห้อง: <span id="room-code-display" class="font-bold text-2xl text-red-500 bg-gray-200 px-3 py-1 rounded-md cursor-pointer" title="คลิกเพื่อคัดลอก"></span></p>
            <div class="bg-gray-50 p-4 rounded-lg min-h-[200px]">
                <h3 class="font-bold mb-2">ผู้เล่นในห้อง:</h3>
                <ul id="player-list" class="list-disc list-inside space-y-2"></ul>
            </div>
            <button id="start-game-btn" class="hidden w-full mt-6 bg-orange-500 text-white p-4 rounded-lg font-bold text-xl hover:bg-orange-600 transition">เริ่มเกม!</button>
            <button id="leave-room-btn" class="w-full mt-2 bg-red-500 text-white p-2 rounded-lg font-bold hover:bg-red-600 transition">ออกจากห้อง</button>
        </div>

        <!-- หน้าจอเล่นเกม -->
        <div id="game-screen" class="hidden">
            <!-- Game UI -->
            <div class="grid grid-cols-4 gap-4 text-center mb-4 p-3 bg-gray-100 rounded-lg">
                <div>ด่าน: <span id="level" class="font-bold text-lg">1</span></div>
                <div>คะแนนด่านนี้: <span id="score" class="font-bold text-lg">0</span> / <span id="target-score" class="font-bold text-lg">0</span></div>
                <div class="text-2xl font-bold text-red-500">เวลา: <span id="time">180</span></div>
                <div><span id="player-count" class="font-bold text-lg">0</span> ผู้เล่น</div>
            </div>
            <div class="grid grid-cols-12 gap-4">
                <div class="col-span-3 space-y-4">
                    <div class="bg-yellow-50 p-3 rounded-lg">
                        <h3 class="font-bold text-lg mb-2 text-center">เป้าหมายของคุณ</h3>
                        <div id="my-objective-timer" class="text-center font-bold text-xl mb-2"></div>
                        <ul id="objectives-list" class="space-y-2">
                        </ul>
                    </div>
                </div>
                <div class="col-span-6 flex flex-col space-y-2">
                    <div class="text-center font-bold text-lg">พื้นที่ทำงานของ <span id="my-name" class="text-purple-600"></span></div>
                    <div id="conveyor-belt" class="drop-zone min-h-[80px] p-2 bg-gray-200 rounded-lg flex items-center flex-wrap gap-2">
                        <span class="text-gray-500">ของที่ได้รับจะมาที่นี่...</span>
                    </div>
                    <div id="workspace" class="drop-zone flex-grow p-2 bg-blue-50 rounded-lg flex flex-col items-center justify-center relative">
                        <h4 class="font-bold text-gray-400 absolute top-2">โต๊ะทำงาน</h4>
                    </div>
                    <button id="submit-order-btn" class="w-full bg-green-500 text-white p-3 rounded-lg font-bold hover:bg-green-600 transition">ส่งอาหาร (จากโต๊ะทำงาน)</button>
                </div>
                <div class="col-span-3 flex flex-col space-y-4">
                    <div id="pass-left-zone" class="drop-zone p-4 rounded-lg text-center bg-blue-100 flex-grow flex flex-col items-center justify-center">
                        <h4 class="text-sm font-bold text-blue-800">ส่งของให้ (ซ้าย)</h4>
                        <p id="pass-left-name" class="font-bold text-xl text-blue-900"></p>
                    </div>
                    <div id="pass-right-zone" class="drop-zone p-4 rounded-lg text-center bg-green-100 flex-grow flex flex-col items-center justify-center">
                        <h4 class="text-sm font-bold text-green-800">ส่งของให้ (ขวา)</h4>
                        <p id="pass-right-name" class="font-bold text-xl text-green-900"></p>
                    </div>
                    <div id="trash-zone" class="drop-zone p-4 rounded-lg text-center bg-red-100 flex-grow flex items-center justify-center">
                        <h4 class="font-bold text-red-800">ถังขยะ</h4>
                    </div>
                    <div id="plate-stack" class="plate-stack p-4 rounded-lg text-center">
                         <h4 class="font-bold text-gray-700">กองจาน (คลิกเพื่อหยิบ)</h4>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- หน้าจอจบเกม / สรุป -->
        <div id="level-complete-screen" class="hidden screen-overlay">
            <div class="bg-white p-8 rounded-xl shadow-2xl text-center popup-box">
                <h1 id="level-complete-title" class="text-4xl font-bold text-green-500 mb-4">ผ่านด่าน!</h1>
                <p id="level-complete-message" class="text-xl mb-2"></p>
                <p id="total-score-message" class="text-2xl mb-6"></p>
                <p class="text-gray-500">เตรียมตัวสำหรับด่านต่อไป...</p>
            </div>
        </div>
        <div id="game-over-screen" class="hidden screen-overlay">
            <div class="bg-white p-8 rounded-xl shadow-2xl text-center popup-box">
                <h1 class="text-5xl font-bold text-red-600 mb-4">เกมจบแล้ว!</h1>
                <p id="game-over-message" class="text-xl text-gray-600 mb-4"></p>
                <p class="text-2xl mb-6">คะแนนรวมทั้งหมด: <span id="final-total-score" class="font-bold">0</span></p>
                <button id="back-to-lobby-btn" class="bg-blue-500 text-white p-3 rounded-lg font-bold hover:bg-blue-600 transition">กลับไปที่ล็อบบี้</button>
            </div>
        </div>
        <div id="game-won-screen" class="hidden screen-overlay">
            <div class="bg-white p-8 rounded-xl shadow-2xl text-center popup-box">
                <h1 class="text-5xl font-bold text-yellow-500 mb-4">คุณชนะ!</h1>
                <p class="text-xl text-gray-600 mb-4">สุดยอดไปเลย! คุณผ่านทุกด่านแล้ว</p>
                <p class="text-2xl mb-6">คะแนนรวมทั้งหมด: <span id="final-won-score" class="font-bold">0</span></p>
                <button id="won-back-to-lobby-btn" class="bg-blue-500 text-white p-3 rounded-lg font-bold hover:bg-blue-600 transition">กลับไปที่ล็อบบี้</button>
            </div>
        </div>
    </div>

    <!-- Popup สำหรับข้อความสำคัญ -->
    <div id="popup-overlay" class="hidden screen-overlay" style="z-index: 100;">
        <div class="popup-box bg-white p-6 rounded-xl shadow-2xl text-center w-full max-w-sm mx-4">
            <p id="popup-message" class="text-lg mb-6 text-gray-700"></p>
            <button id="popup-close-btn" class="w-full bg-blue-500 text-white px-6 py-2 rounded-lg font-bold hover:bg-blue-600 transition focus:outline-none focus:ring-2 focus:ring-blue-400">ตกลง</button>
        </div>
    </div>

    <!-- Toast Container สำหรับการแจ้งเตือนเล็กๆ น้อยๆ -->
    <div id="toast-container" class="fixed top-5 right-5 z-[100] w-full max-w-xs space-y-3"></div>


<script>
    const socket = io();
    let currentRoomId = null;
    let myName = '';
    let mySid = '';
    let isHost = false;
    let draggedData = null; 
    let draggedElement = null;
    let objectiveTimerInterval = null;

    // --- UI Elements ---
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
    const workspace = document.getElementById('workspace');
    const submitOrderBtn = document.getElementById('submit-order-btn');
    const plateStack = document.getElementById('plate-stack');
    const passLeftNameEl = document.getElementById('pass-left-name');
    const passRightNameEl = document.getElementById('pass-right-name');

    // Popup elements
    const popupOverlay = document.getElementById('popup-overlay');
    const popupMessage = document.getElementById('popup-message');
    const popupCloseBtn = document.getElementById('popup-close-btn');

    // End screens elements
    const levelCompleteMessageEl = document.getElementById('level-complete-message');
    const totalScoreMessageEl = document.getElementById('total-score-message');
    const gameOverMessageEl = document.getElementById('game-over-message');
    const finalTotalScoreEl = document.getElementById('final-total-score');
    const finalWonScoreEl = document.getElementById('final-won-score');
    const backToLobbyBtn = document.getElementById('back-to-lobby-btn');
    const wonBackToLobbyBtn = document.getElementById('won-back-to-lobby-btn');

    function showScreen(screenName) {
        if(objectiveTimerInterval) clearInterval(objectiveTimerInterval);
        allScreens.forEach(id => screens[id].classList.add('hidden'));
        if (screenName && screens[screenName]) {
            screens[screenName].classList.remove('hidden');
        }
    }
    
    // *** START OF CHANGES: New Toast & Popup Functions ***
    function showToast(message, type = 'info') {
        const toastContainer = document.getElementById('toast-container');
        if (!toastContainer) return;
        const toast = document.createElement('div');
        
        let bgColor, textColor, icon;
        switch (type) {
            case 'success':
                bgColor = 'bg-green-500'; textColor = 'text-white'; icon = '✓';
                break;
            case 'warning':
                bgColor = 'bg-yellow-500'; textColor = 'text-white'; icon = '!';
                break;
            case 'error':
                bgColor = 'bg-red-500'; textColor = 'text-white'; icon = '✗';
                break;
            default:
                bgColor = 'bg-blue-500'; textColor = 'text-white'; icon = 'i';
        }

        toast.className = `toast p-4 rounded-lg shadow-lg flex items-center space-x-3 ${bgColor} ${textColor} font-bold`;
        toast.innerHTML = `<span>${message}</span>`;
        
        toastContainer.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, 4500); // Remove after animation finishes
    }

    function showPopup(message) {
        popupMessage.textContent = message;
        popupOverlay.classList.remove('hidden');
    }
    popupCloseBtn.addEventListener('click', () => popupOverlay.classList.add('hidden'));
    popupOverlay.addEventListener('click', (e) => {
        if (e.target === popupOverlay) {
            popupOverlay.classList.add('hidden');
        }
    });
    // *** END OF CHANGES ***

    function createItemElement(itemName) {
        const item = document.createElement('div');
        item.textContent = itemName;
        item.className = 'item bg-yellow-200 text-yellow-800 px-3 py-1 rounded-full font-semibold shadow-sm m-1';
        item.draggable = true;
        item.id = 'item-' + Date.now() + Math.random();
        item.addEventListener('dragstart', (e) => {
            draggedData = {type: 'ingredient', name: itemName};
            draggedElement = item;
            e.dataTransfer.setData('text/plain', '');
            setTimeout(() => item.classList.add('dragging'), 0);
        });
        item.addEventListener('dragend', () => item.classList.remove('dragging'));
        return item;
    }

    function createPlateElement(contents = []) {
        const plate = document.createElement('div');
        plate.className = 'plate drop-zone bg-white p-3 rounded-lg shadow-md w-4/5 flex flex-col items-center';
        plate.draggable = true;
        plate.id = 'plate-' + Date.now() + Math.random();
        const title = document.createElement('span');
        title.className = 'font-bold text-sm mb-2 text-gray-600';
        title.textContent = 'จาน';
        plate.appendChild(title);
        const itemsContainer = document.createElement('div');
        itemsContainer.className = 'plate-items-container flex flex-wrap justify-center gap-1';
        contents.forEach(ing => {
            const itemEl = document.createElement('span');
            itemEl.className = 'item-in-plate px-2 py-1 rounded text-xs font-medium';
            itemEl.textContent = ing;
            itemsContainer.appendChild(itemEl);
        });
        plate.appendChild(itemsContainer);
        plate.addEventListener('dragstart', (e) => {
            e.stopPropagation();
            draggedData = {type: 'plate', contents: contents};
            draggedElement = plate;
            e.dataTransfer.setData('text/plain', '');
            setTimeout(() => plate.classList.add('dragging'), 0);
        });
        plate.addEventListener('dragend', () => plate.classList.remove('dragging'));
        plate.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); plate.classList.add('drag-over'); });
        plate.addEventListener('dragleave', e => { e.stopPropagation(); plate.classList.remove('drag-over'); });
        plate.addEventListener('drop', e => {
            e.preventDefault(); e.stopPropagation();
            plate.classList.remove('drag-over');
            if (draggedData && draggedData.type === 'ingredient') {
                const newContents = [...contents, draggedData.name];
                if (newContents.length <= 6) {
                    socket.emit('player_action', { room_id: currentRoomId, type: 'add_to_plate', new_plate_contents: newContents });
                    draggedElement.remove();
                }
            }
        });
        return plate;
    }

    document.querySelectorAll('.drop-zone').forEach(zone => {
        zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
        zone.addEventListener('dragleave', e => { zone.classList.remove('drag-over'); });
        zone.addEventListener('drop', e => {
            e.preventDefault(); zone.classList.remove('drag-over');
            if (!draggedElement || !draggedData || (draggedElement.contains(e.target) && zone.id !== 'workspace')) return;
            const targetId = zone.id;
            switch (targetId) {
                case 'pass-left-zone':
                case 'pass-right-zone':
                    socket.emit('player_action', { room_id: currentRoomId, type: 'pass_item', direction: targetId.includes('left') ? 'left' : 'right', item: draggedData });
                    draggedElement.remove();
                    break;
                case 'trash-zone':
                    socket.emit('player_action', { room_id: currentRoomId, type: 'trash_item', item_type: draggedData.type });
                    draggedElement.remove();
                    break;
                case 'workspace':
                    if (draggedData.type === 'plate' && !workspace.querySelector('.plate')) {
                         socket.emit('player_action', { room_id: currentRoomId, type: 'take_from_conveyor', item: draggedData });
                         draggedElement.remove();
                    }
                    break;
            }
            draggedElement = null; draggedData = null;
        });
    });

    createBtn.addEventListener('click', () => {
        myName = playerNameInput.value.trim();
        if (!myName) { showPopup('กรุณาใส่ชื่อของคุณ!'); return; }
        socket.emit('create_room', { name: myName });
    });
    joinBtn.addEventListener('click', () => {
        myName = playerNameInput.value.trim();
        const roomId = roomCodeInput.value.trim().toUpperCase();
        if (!myName || !roomId) { showPopup('กรุณาใส่ชื่อและรหัสห้อง!'); return; }
        socket.emit('join_room', { name: myName, room_id: roomId });
    });
    leaveRoomBtn.addEventListener('click', () => location.reload());
    roomCodeDisplay.addEventListener('click', () => {
        if(currentRoomId) navigator.clipboard.writeText(currentRoomId).then(() => showToast('คัดลอกรหัสห้องแล้ว!', 'success'));
    });
    startGameBtn.addEventListener('click', () => socket.emit('start_game', { room_id: currentRoomId }));
    submitOrderBtn.addEventListener('click', () => socket.emit('player_action', { room_id: currentRoomId, type: 'submit_order' }));
    backToLobbyBtn.addEventListener('click', () => {
        showScreen('lobby');
    });
    wonBackToLobbyBtn.addEventListener('click', () => showScreen('lobby'));
    plateStack.addEventListener('click', () => {
        if (!workspace.querySelector('.plate')) {
            socket.emit('player_action', { room_id: currentRoomId, type: 'get_empty_plate' });
        } else {
            showToast('คุณมีจานบนโต๊ะทำงานแล้ว!', 'warning');
        }
    });

    socket.on('connect', () => { mySid = socket.id; showScreen('login'); });
    socket.on('disconnect', () => { showPopup('การเชื่อมต่อหลุด!'); showScreen('login'); location.reload(); });
    socket.on('room_created', (data) => {
        currentRoomId = data.room_id; isHost = data.is_host;
        roomCodeDisplay.textContent = currentRoomId; showScreen('lobby');
    });
    socket.on('join_success', (data) => {
        currentRoomId = data.room_id; isHost = data.is_host;
        roomCodeDisplay.textContent = currentRoomId; showScreen('lobby');
    });
    socket.on('update_lobby', (data) => {
        if (screens.lobby.classList.contains('hidden')) return;
        if (currentRoomId !== data.room_id) return;
        playerList.innerHTML = '';
        data.players.forEach(p => {
            const li = document.createElement('li'); li.className = 'text-gray-700';
            li.textContent = p.name;
            if (p.sid === data.host_sid) {
                 const hostTag = document.createElement('span');
                 hostTag.className = 'player-tag bg-yellow-400 text-yellow-900';
                 hostTag.textContent = 'Host'; li.appendChild(hostTag);
            }
            if (p.sid === mySid) {
                 const youTag = document.createElement('span');
                 youTag.className = 'player-tag bg-blue-400 text-white';
                 youTag.textContent = 'You'; li.appendChild(youTag);
            }
            playerList.appendChild(li);
        });
        isHost = (mySid === data.host_sid);
        startGameBtn.classList.toggle('hidden', !(isHost && data.players.length >= 1));
    });
    socket.on('new_host', (data) => {
        isHost = (mySid === data.host_sid);
        if (isHost) showToast('คุณได้รับตำแหน่ง Host!', 'info');
    });
    socket.on('error_message', (data) => showPopup(data.message));
    socket.on('game_started', (data) => {
        showScreen('game');
        mySid = data.your_sid;
        passLeftNameEl.textContent = data.left_neighbor;
        passRightNameEl.textContent = data.right_neighbor;
        myNameEl.textContent = data.your_name;
        updateGameStateUI(data.initial_state);
    });
    socket.on('update_game_state', (state) => updateGameStateUI(state));
    socket.on('update_neighbors', (data) => {
        passLeftNameEl.textContent = data.left_neighbor;
        passRightNameEl.textContent = data.right_neighbor;
    });
    socket.on('receive_item', (data) => {
        if (conveyorBelt.querySelector('span.text-gray-500')) conveyorBelt.innerHTML = '';
        const itemData = data.item;
        let element = (itemData.type === 'plate') ? createPlateElement(itemData.contents) : createItemElement(itemData.name);
        if (element) conveyorBelt.appendChild(element);
    });
    socket.on('action_success', (data) => showToast(data.message, 'success'));
    socket.on('action_fail', (data) => showToast(data.message, 'error'));
    socket.on('show_alert', (data) => showToast(data.message, 'info'));

    socket.on('clear_all_items', () => {
        conveyorBelt.innerHTML = '<span class="text-gray-500">ของที่ได้รับจะมาที่นี่...</span>';
    });
    socket.on('level_complete', (data) => {
        levelCompleteMessageEl.textContent = `คะแนนในด่าน ${data.level}: ${data.level_score}`;
        totalScoreMessageEl.textContent = `คะแนนรวม: ${data.total_score}`;
        showScreen('level-complete');
    });
    socket.on('start_next_level', (data) => {
        showScreen('game');
        updateGameStateUI(data);
    });
    socket.on('game_over', (data) => {
        finalTotalScoreEl.textContent = data.total_score;
        gameOverMessageEl.textContent = data.message || '';
        gameOverMessageEl.classList.toggle('hidden', !data.message);
        showScreen('game-over');
    });
    socket.on('game_won', (data) => {
        finalWonScoreEl.textContent = data.total_score;
        showScreen('game-won');
    });

    function updateGameStateUI(state) {
        if (!state || screens.game.classList.contains('hidden')) return;
        scoreEl.textContent = state.score;
        targetScoreEl.textContent = state.target_score;
        timeEl.textContent = state.time_left;
        levelEl.textContent = state.level;
        playerCountEl.textContent = state.player_order_sids.length;

        const myObjectiveDisplay = state.all_player_objectives.find(obj => obj.player_name === myName);
        
        if(objectiveTimerInterval) clearInterval(objectiveTimerInterval);
        objectiveTimerInterval = setInterval(() => {
            const timerEl = document.getElementById('my-objective-timer');
            if (myObjectiveDisplay && timerEl) {
                 const expiryTimeMs = myObjectiveDisplay.expires_at * 1000;
                 const nowMs = Date.now();
                 const timeLeft = Math.max(0, Math.round((expiryTimeMs - nowMs) / 1000));
                 timerEl.innerHTML = `เหลือเวลา: <span class="text-red-500">${timeLeft}</span> วิ`;
                 if (timeLeft <= 10 && timeLeft > 0) {
                     timerEl.classList.add('animate-pulse');
                 } else {
                     timerEl.classList.remove('animate-pulse');
                 }
            }
        }, 1000);
        
        objectivesListEl.innerHTML = '';
        if (myObjectiveDisplay) {
            const ingredients = myObjectiveDisplay.ingredients.join(', ');
            objectivesListEl.innerHTML = `
                <li class="bg-green-100 p-3 rounded-lg shadow-sm border-l-4 border-green-500">
                    <div class="font-bold text-green-800 text-lg">${myObjectiveDisplay.objective_name}</div>
                    <div class="text-xs text-gray-500 mb-1">(${myObjectiveDisplay.points} คะแนน)</div>
                    <div class="text-sm text-gray-600">ส่วนผสม: ${ingredients}</div>
                </li>`;
        } else {
            if(objectiveTimerInterval) clearInterval(objectiveTimerInterval);
            document.getElementById('my-objective-timer').innerHTML = '';
            objectivesListEl.innerHTML = '<li>ไม่มีเป้าหมายในขณะนี้</li>';
        }
        
        const myState = state.players_state[mySid];
        workspace.innerHTML = '<h4 class="font-bold text-gray-400 absolute top-2">โต๊ะทำงาน</h4>';
        if (myState && Array.isArray(myState.plate)) {
            workspace.appendChild(createPlateElement(myState.plate));
        }
    }
</script>
</body>
</html>
    """
    with open('templates/index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)

    print("เซิร์ฟเวอร์กำลังจะเริ่มที่ http://127.0.0.1:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)

