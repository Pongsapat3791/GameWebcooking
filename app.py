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
    
    # ค้นหาว่าผู้เล่นอยู่ในห้องไหน
    for room_id, room_data in rooms.items():
        if request.sid in room_data['players']:
            room_id_to_update = room_id
            break
            
    if not room_id_to_update:
        return # ผู้เล่นไม่ได้อยู่ในห้องใดๆ

    room = rooms[room_id_to_update]
    player_name = room['players'][request.sid]['name']
    
    # ลบผู้เล่นออกจากรายชื่อในห้อง
    del room['players'][request.sid]
    print(f"ผู้เล่น {player_name} ออกจากห้อง {room_id_to_update}")

    # ถ้าห้องว่าง ให้ลบห้องทิ้ง
    if not room['players']:
        print(f"ห้อง {room_id_to_update} ว่างเปล่า กำลังลบห้อง...")
        if room.get('game_state'):
            room['game_state']['is_active'] = False
        del rooms[room_id_to_update]
        return

    # --- จัดการสถานะเกมหากเกมกำลังดำเนินอยู่ ---
    game_state = room.get('game_state')
    if game_state and game_state.get('is_active'):
        # ลบผู้เล่นออกจากส่วนของเกม
        if request.sid in game_state['player_order_sids']:
            game_state['player_order_sids'].remove(request.sid)
        if request.sid in game_state['players_state']:
            del game_state['players_state'][request.sid]

        # ตรวจสอบว่าเกมสามารถดำเนินต่อได้หรือไม่
        if len(game_state['player_order_sids']) < 2:
            game_state['is_active'] = False
            # แจ้งผู้เล่นที่เหลือว่าเกมจบแล้ว
            socketio.emit('game_over', {
                'score': game_state['score'], 
                'message': 'ผู้เล่นไม่พอที่จะเล่นต่อ เกมจบลง'
            }, room=room_id_to_update)
            room['game_state'] = None # รีเซ็ตสถานะเกมสำหรับล็อบบี้
        else:
            # เกมดำเนินต่อ, อัปเดตเพื่อนบ้านสำหรับผู้เล่นที่เหลือ
            player_sids = game_state['player_order_sids']
            for i, sid in enumerate(player_sids):
                left_neighbor_sid = player_sids[i - 1]
                right_neighbor_sid = player_sids[(i + 1) % len(player_sids)]
                socketio.emit('update_neighbors', {
                    'left_neighbor': room['players'][left_neighbor_sid]['name'],
                    'right_neighbor': room['players'][right_neighbor_sid]['name']
                }, room=sid)
            # ส่งสถานะเกมที่อัปเดตแล้วไปยังผู้เล่นที่เหลือทั้งหมด
            ui_state = get_augmented_state_for_ui(room_id_to_update)
            if ui_state:
                socketio.emit('update_game_state', ui_state, room=room_id_to_update)

    # --- อัปเดตล็อบบี้สำหรับผู้เล่นที่เหลือทั้งหมด (ทำเสมอ) ---
    # เลื่อนขั้นโฮสต์ใหม่หากคนเก่าออกไป
    if room.get('host_sid') == request.sid:
        new_host_sid = list(room['players'].keys())[0]
        room['host_sid'] = new_host_sid
        socketio.emit('new_host', {'host_sid': new_host_sid}, room=room_id_to_update)

    # ส่งข้อมูลล็อบบี้ที่อัปเดตแล้ว
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
        'host_sid': request.sid # คนสร้างเป็น host
    }
    join_room(room_id)
    print(f"ผู้เล่น {player_name} สร้างห้อง {room_id}")
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
    print(f"ผู้เล่น {player_name} เข้าร่วมห้อง {room_id}")
    emit('join_success', {'room_id': room_id, 'is_host': request.sid == rooms[room_id]['host_sid']})
    socketio.emit('update_lobby', {
        'players': [{'sid': sid, 'name': p['name']} for sid, p in rooms[room_id]['players'].items()],
        'host_sid': rooms[room_id]['host_sid'],
        'room_id': room_id
    }, room=room_id)

# --- ฟังก์ชันเสริมสำหรับสร้าง State ที่จะส่งให้ UI ---
def get_augmented_state_for_ui(room_id):
    room = rooms.get(room_id)
    if not room or not room.get('game_state'):
        return None

    game_state = room['game_state']
    ui_state = game_state.copy()

    # **สร้างลิสต์เป้าหมายของผู้เล่นทุกคนสำหรับ UI**
    all_player_objectives = []
    for sid, p_state in game_state.get('players_state', {}).items():
        player_name = room['players'].get(sid, {}).get('name', '???')
        objective_name = p_state.get('objective')
        if objective_name:
            all_player_objectives.append({
                'player_name': player_name,
                'objective_name': objective_name,
                'ingredients': RECIPES[objective_name]['ingredients'],
                'points': RECIPES[objective_name]['points']
            })
    
    ui_state['all_player_objectives'] = all_player_objectives
    return ui_state

# --- ระบบเริ่มเกมและ Game Loop ---
def game_loop(room_id):
    last_spawn_time = time.time()
    spawn_interval = 5  # วินาที

    with app.app_context():
        while rooms.get(room_id) and rooms[room_id].get('game_state'):
            game_state = rooms[room_id]['game_state']
            
            if not game_state.get('is_active'):
                break
            
            # ลดเวลา
            game_state['time_left'] -= 1

            # สุ่มวัตถุดิบจากเป้าหมายของผู้เล่นทุกคน
            if time.time() - last_spawn_time > spawn_interval:
                needed_ingredients = set()
                for p_state in game_state['players_state'].values():
                    objective_name = p_state.get('objective')
                    if objective_name:
                        needed_ingredients.update(RECIPES[objective_name]['ingredients'])
                
                if needed_ingredients:
                    item_to_spawn = random.choice(list(needed_ingredients))
                    # ส่งของให้ผู้เล่นแบบสุ่ม
                    random_player_sid = random.choice(list(game_state['players_state'].keys()))
                    socketio.emit('receive_item', {'item': {'type': 'ingredient', 'name': item_to_spawn}}, room=random_player_sid)
                last_spawn_time = time.time()

            # ตรวจสอบเวลาหมด
            if game_state['time_left'] <= 0:
                game_state['is_active'] = False
                socketio.emit('game_over', {'score': game_state['score']}, room=room_id)
                rooms[room_id]['game_state'] = None 
                break

            # ส่ง state ที่ปรับปรุงแล้วให้ UI
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

    # **สร้าง State ของผู้เล่นแต่ละคน พร้อมเป้าหมายส่วนตัว**
    players_state = {}
    for sid in player_sids:
        players_state[sid] = {
            'plate': [],
            'objective': random.choice(list(RECIPES.keys()))
        }

    room['game_state'] = {
        'is_active': True,
        'score': 0,
        'time_left': 180,
        'player_order_sids': player_sids,
        'players_state': players_state
    }
    
    # ส่งข้อมูลเริ่มต้นเกมให้แต่ละคน
    ui_state = get_augmented_state_for_ui(room_id)
    for i, sid in enumerate(player_sids):
        left_neighbor_sid = player_sids[i - 1]
        right_neighbor_sid = player_sids[(i + 1) % len(player_sids)]
        
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
    player_sid = request.sid
    if not game_state.get('is_active'): return
    
    player_state = game_state['players_state'].get(player_sid)
    if not player_state: return
    
    player_index = game_state['player_order_sids'].index(player_sid)
    
    if action_type == 'pass_item':
        item_data = data.get('item')
        direction = data.get('direction')
        if isinstance(item_data, dict) and item_data.get('type') == 'plate':
            player_state['plate'] = None
        target_sid = game_state['player_order_sids'][player_index - 1] if direction == 'left' else game_state['player_order_sids'][(player_index + 1) % len(game_state['player_order_sids'])]
        socketio.emit('receive_item', {'item': item_data}, room=target_sid)

    elif action_type == 'add_to_plate':
        if player_state.get('plate') is not None:
             player_state['plate'] = data.get('new_plate_contents', [])

    elif action_type == 'take_from_conveyor':
        item_type = data['item']['type']
        if item_type == 'plate':
             player_state['plate'] = data['item']['contents']

    elif action_type == 'trash_item':
        if data.get('item_type') == 'plate':
            player_state['plate'] = None

    elif action_type == 'get_empty_plate':
        if player_state.get('plate') is None:
            player_state['plate'] = []

    # **ส่งอาหารตามเป้าหมายส่วนตัว**
    elif action_type == 'submit_order':
        if player_state.get('plate') is None:
            socketio.emit('action_fail', {'message': 'คุณไม่มีจาน!'}, room=player_sid)
            return

        player_plate = sorted(player_state['plate'])
        player_objective = player_state.get('objective')
        order_matched = False

        if player_objective and player_plate == RECIPES[player_objective]['ingredients']:
            # ได้คะแนนและเวลา
            game_state['score'] += RECIPES[player_objective]['points']
            game_state['time_left'] = min(game_state['time_left'] + RECIPES[player_objective]['time_bonus'], 999)
            
            # **รับเป้าหมายใหม่**
            player_state['objective'] = random.choice(list(RECIPES.keys()))
            
            # คืนจานเปล่า
            player_state['plate'] = [] 
            order_matched = True
            socketio.emit('action_success', {'message': f'ทำ {player_objective} สำเร็จ!'}, room=player_sid)
        
        if not order_matched:
            socketio.emit('action_fail', {'message': 'สูตรไม่ถูกต้อง!'}, room=player_sid)

    # ส่ง state ที่อัปเดตแล้วให้ทุกคนในห้อง
    ui_state = get_augmented_state_for_ui(room_id)
    if ui_state:
        socketio.emit('update_game_state', ui_state, room=room_id)


if __name__ == '__main__':
    import os
    if not os.path.exists('templates'):
        os.makedirs('templates')

    # โค้ด HTML, CSS, และ JavaScript ทั้งหมดจะถูกเขียนลงในไฟล์ index.html
    # มีการแก้ไข UI ให้แสดงเป้าหมายและสูตรอาหารรวมกัน และนำส่วนที่ไม่ใช้ออก
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
        .item, .plate { cursor: grab; user-select: none; }
        .item:active, .plate:active { cursor: grabbing; }
        .drop-zone { border: 2px dashed #ccc; transition: all 0.2s; }
        .drop-zone.drag-over { border-color: #4ade80; background-color: #f0fdf4; transform: scale(1.02); }
        .plate-items-container { min-height: 40px; }
        .item-in-plate { background-color: #dcfce7; color: #166534; }
        .plate-stack {
            border: 3px solid #9ca3af;
            background-color: #f3f4f6;
            box-shadow: 0 2px 0 #9ca3af, 0 4px 0 #e5e7eb, 0 6px 0 #9ca3af;
            cursor: pointer;
            transition: all 0.1s ease-in-out;
        }
        .plate-stack:active {
            transform: translateY(2px);
            box-shadow: 0 1px 0 #9ca3af, 0 2px 0 #e5e7eb, 0 3px 0 #9ca3af;
        }
        .player-tag {
            padding: 2px 8px;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: bold;
            margin-left: 8px;
        }
    </style>
</head>
<body class="bg-gray-100 text-gray-800 flex items-center justify-center min-h-screen p-4">

    <div id="main-container" class="w-full max-w-7xl bg-white rounded-xl shadow-2xl p-6 transition-all duration-500 relative">

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
            <div class="grid grid-cols-3 gap-4 text-center mb-4 p-3 bg-gray-100 rounded-lg">
                <div>คะแนนรวม: <span id="score" class="font-bold text-lg">0</span></div>
                <div class="text-2xl font-bold text-red-500">เวลา: <span id="time">180</span></div>
                <div><span id="player-count" class="font-bold text-lg">0</span> ผู้เล่น</div>
            </div>
            
            <div class="grid grid-cols-12 gap-4">
                <!-- Left column -->
                <div class="col-span-3 space-y-4">
                    <!-- **เป้าหมายและสูตรอาหารรวมกัน** -->
                    <div class="bg-yellow-50 p-3 rounded-lg">
                        <h3 class="font-bold text-lg mb-2 text-center">เป้าหมายของคุณ</h3>
                        <ul id="objectives-list" class="space-y-2"></ul>
                    </div>
                </div>

                <!-- Center column: Workspace -->
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

                <!-- Right column -->
                <div class="col-span-3 flex flex-col space-y-4">
                    <!-- **ปรับปรุง UI แสดงชื่อเพื่อนบ้านบนโซนส่งของ** -->
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
        
        <!-- หน้าจอ Game Over -->
        <div id="game-over-screen" class="hidden text-center p-8">
            <h1 class="text-5xl font-bold text-red-600 mb-4">เกมจบแล้ว!</h1>
            <p id="game-over-message" class="text-xl text-gray-600 mb-4 hidden"></p>
            <p class="text-2xl mb-6">คะแนนรวมของทีมคือ: <span id="final-score" class="font-bold">0</span></p>
            <button id="back-to-lobby-btn" class="bg-blue-500 text-white p-3 rounded-lg font-bold hover:bg-blue-600 transition">กลับไปที่ล็อบบี้</button>
        </div>

    </div>

<script>
    const socket = io();
    let currentRoomId = null;
    let myName = '';
    let mySid = '';
    let isHost = false;
    let draggedData = null; 
    let draggedElement = null;

    // --- UI Elements ---
    const loginScreen = document.getElementById('login-screen');
    const lobbyScreen = document.getElementById('lobby-screen');
    const gameScreen = document.getElementById('game-screen');
    const gameOverScreen = document.getElementById('game-over-screen');
    const playerNameInput = document.getElementById('player-name');
    const roomCodeInput = document.getElementById('room-code-input');
    const createBtn = document.getElementById('create-btn');
    const joinBtn = document.getElementById('join-btn');
    const leaveRoomBtn = document.getElementById('leave-room-btn');
    const roomCodeDisplay = document.getElementById('room-code-display');
    const playerList = document.getElementById('player-list');
    const startGameBtn = document.getElementById('start-game-btn');
    const scoreEl = document.getElementById('score');
    const timeEl = document.getElementById('time');
    const playerCountEl = document.getElementById('player-count');
    const myNameEl = document.getElementById('my-name');
    const objectivesListEl = document.getElementById('objectives-list');
    const conveyorBelt = document.getElementById('conveyor-belt');
    const workspace = document.getElementById('workspace');
    const submitOrderBtn = document.getElementById('submit-order-btn');
    const plateStack = document.getElementById('plate-stack');
    const finalScoreEl = document.getElementById('final-score');
    const backToLobbyBtn = document.getElementById('back-to-lobby-btn');
    const passLeftNameEl = document.getElementById('pass-left-name');
    const passRightNameEl = document.getElementById('pass-right-name');
    const gameOverMessageEl = document.getElementById('game-over-message');

    function showScreen(screenName) {
        ['login', 'lobby', 'game', 'game-over'].forEach(id => {
            document.getElementById(`${id}-screen`).classList.add('hidden');
        });
        if (screenName) {
            document.getElementById(`${screenName}-screen`).classList.remove('hidden');
        }
    }

    // --- Element Creation Functions ---
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
        });
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
        });

        plate.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); plate.classList.add('drag-over'); });
        plate.addEventListener('dragleave', e => { e.stopPropagation(); plate.classList.remove('drag-over'); });
        plate.addEventListener('drop', e => {
            e.preventDefault();
            e.stopPropagation();
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

    // --- Drag & Drop Setup ---
    document.querySelectorAll('.drop-zone').forEach(zone => {
        zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
        zone.addEventListener('dragleave', e => { zone.classList.remove('drag-over'); });
        zone.addEventListener('drop', e => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            if (!draggedElement || !draggedData) return;
            if (draggedElement.contains(e.target)) return;
            
            const targetId = zone.id;
            switch (targetId) {
                case 'pass-left-zone':
                case 'pass-right-zone':
                    socket.emit('player_action', {
                        room_id: currentRoomId, type: 'pass_item',
                        direction: targetId.includes('left') ? 'left' : 'right',
                        item: draggedData
                    });
                    draggedElement.remove();
                    break;
                case 'trash-zone':
                    socket.emit('player_action', { room_id: currentRoomId, type: 'trash_item', item_type: draggedData.type });
                    draggedElement.remove();
                    break;
                case 'workspace':
                    if (draggedData.type === 'plate') {
                         if (workspace.querySelector('.plate')) return;
                         socket.emit('player_action', { room_id: currentRoomId, type: 'take_from_conveyor', item: draggedData });
                         draggedElement.remove();
                    }
                    break;
            }
            draggedElement = null;
            draggedData = null;
        });
    });

    // --- Button Listeners ---
    createBtn.addEventListener('click', () => {
        myName = playerNameInput.value.trim();
        if (!myName) { alert('กรุณาใส่ชื่อของคุณ!'); return; }
        socket.emit('create_room', { name: myName });
    });
    joinBtn.addEventListener('click', () => {
        myName = playerNameInput.value.trim();
        const roomId = roomCodeInput.value.trim().toUpperCase();
        if (!myName || !roomId) { alert('กรุณาใส่ชื่อและรหัสห้อง!'); return; }
        socket.emit('join_room', { name: myName, room_id: roomId });
    });
    leaveRoomBtn.addEventListener('click', () => { location.reload(); });
    roomCodeDisplay.addEventListener('click', () => {
        navigator.clipboard.writeText(currentRoomId).then(() => { alert('คัดลอกรหัสห้องแล้ว!'); });
    });
    startGameBtn.addEventListener('click', () => socket.emit('start_game', { room_id: currentRoomId }));
    submitOrderBtn.addEventListener('click', () => socket.emit('player_action', { room_id: currentRoomId, type: 'submit_order' }));
    
    // **เปลี่ยนปุ่มกลับล็อบบี้ให้เปลี่ยนหน้าจอแทนการโหลดใหม่**
    backToLobbyBtn.addEventListener('click', () => {
        showScreen('lobby');
    });

    plateStack.addEventListener('click', () => {
        if (!workspace.querySelector('.plate')) {
            socket.emit('player_action', { room_id: currentRoomId, type: 'get_empty_plate' });
        } else {
            alert('คุณมีจานบนโต๊ะทำงานแล้ว!');
        }
    });

    // --- SocketIO Handlers ---
    socket.on('connect', () => { mySid = socket.id; showScreen('login'); });
    socket.on('disconnect', () => { alert('การเชื่อมต่อหลุด!'); showScreen('login'); });

    socket.on('room_created', (data) => {
        currentRoomId = data.room_id;
        isHost = data.is_host;
        roomCodeDisplay.textContent = currentRoomId;
        showScreen('lobby');
    });
    socket.on('join_success', (data) => {
        currentRoomId = data.room_id;
        isHost = data.is_host;
        roomCodeDisplay.textContent = currentRoomId;
        showScreen('lobby');
    });
    
    socket.on('update_lobby', (data) => {
        playerList.innerHTML = '';
        data.players.forEach(p => {
            const playerItem = document.createElement('li');
            playerItem.className = 'text-gray-700';
            playerItem.textContent = p.name;
            if (p.sid === data.host_sid) {
                 const hostTag = document.createElement('span');
                 hostTag.className = 'player-tag bg-yellow-400 text-yellow-900';
                 hostTag.textContent = 'Host';
                 playerItem.appendChild(hostTag);
            }
            if (p.sid === mySid) {
                 const youTag = document.createElement('span');
                 youTag.className = 'player-tag bg-blue-400 text-white';
                 youTag.textContent = 'You';
                 playerItem.appendChild(youTag);
            }
            playerList.appendChild(playerItem);
        });
        isHost = (mySid === data.host_sid);
        if (isHost && data.players.length >= 1) { 
            startGameBtn.classList.remove('hidden');
        } else {
            startGameBtn.classList.add('hidden');
        }
    });

    socket.on('new_host', (data) => {
        isHost = (mySid === data.host_sid);
        if (isHost) {
            startGameBtn.classList.remove('hidden');
            alert('คุณได้รับตำแหน่ง Host!');
        }
    });

    socket.on('error_message', (data) => alert(data.message));
    
    socket.on('game_started', (data) => {
        showScreen('game');
        mySid = data.your_sid;
        passLeftNameEl.textContent = data.left_neighbor;
        passRightNameEl.textContent = data.right_neighbor;
        myNameEl.textContent = data.your_name;
        updateGameStateUI(data.initial_state);
    });

    socket.on('update_game_state', (state) => updateGameStateUI(state));

    function updateGameStateUI(state) {
        if (!state) return;
        
        scoreEl.textContent = state.score;
        timeEl.textContent = state.time_left;
        playerCountEl.textContent = state.player_order_sids.length;

        objectivesListEl.innerHTML = '';
        if (state.all_player_objectives) {
            state.all_player_objectives.forEach(obj => {
                const isMyObjective = obj.player_name === myName;
                if (isMyObjective) {
                    const ingredients = obj.ingredients.join(', ');
                    const objectiveHTML = `
                        <li class="bg-green-100 p-2 rounded shadow-sm mb-2 border-l-4 border-green-500">
                            <div class="font-bold text-green-800">เป้าหมาย: <span class="text-gray-800">${obj.objective_name}</span></div>
                            <div class="text-xs text-gray-500">(${obj.points} คะแนน)</div>
                            <div class="text-sm text-gray-600 mt-1">ส่วนผสม: ${ingredients}</div>
                        </li>
                    `;
                    objectivesListEl.innerHTML = objectiveHTML;
                }
            });
        }
        
        const myState = state.players_state[mySid];
        workspace.innerHTML = '<h4 class="font-bold text-gray-400 absolute top-2">โต๊ะทำงาน</h4>';
        if (myState && myState.plate !== null) {
            const myPlate = createPlateElement(myState.plate);
            workspace.appendChild(myPlate);
        }
    }
    
    socket.on('receive_item', (data) => {
        if (conveyorBelt.querySelector('span.text-gray-500')) {
            conveyorBelt.innerHTML = '';
        }
        const itemData = data.item;
        let element;
        if (itemData.type === 'plate') {
            element = createPlateElement(itemData.contents);
        } else if (itemData.type === 'ingredient') {
            element = createItemElement(itemData.name);
        }
        if (element) conveyorBelt.appendChild(element);
    });

    // **เพิ่ม handler สำหรับอัปเดตเพื่อนบ้าน**
    socket.on('update_neighbors', (data) => {
        passLeftNameEl.textContent = data.left_neighbor;
        passRightNameEl.textContent = data.right_neighbor;
    });

    socket.on('action_success', (data) => console.log("Success:", data.message));
    socket.on('action_fail', (data) => alert("ล้มเหลว: " + data.message));

    // **อัปเดต handler ของ game_over ให้แสดงข้อความได้**
    socket.on('game_over', (data) => {
        finalScoreEl.textContent = data.score;
        if (data.message) {
            gameOverMessageEl.textContent = data.message;
            gameOverMessageEl.classList.remove('hidden');
        } else {
            gameOverMessageEl.textContent = '';
            gameOverMessageEl.classList.add('hidden');
        }
        showScreen('game-over');
    });
</script>
</body>
</html>
    """
    with open('templates/index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)

    print("เซิร์ฟเวอร์กำลังจะเริ่มที่ http://127.0.0.1:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
