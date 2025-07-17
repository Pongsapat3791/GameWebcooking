# app.py
#
# --- วิธีการรันโปรแกรม ---
# 1. สร้างโฟลเดอร์ตามโครงสร้าง:
#    - your_project_folder/
#      - app.py
#      - templates/
#        - index.html
#      - static/
#        - css/
#          - style.css
#        - js/
#          - main.js
#
# 2. ติดตั้งไลบรารีที่จำเป็น:
#    pip install Flask Flask-SocketIO eventlet
#
# 3. รันเซิร์ฟเวอร์ด้วยคำสั่ง:
#    python app.py
#
# 4. เปิดเว็บเบราว์เซอร์ไปที่ http://127.0.0.1:5000
# ---

import eventlet
# eventlet.monkey_patch() ต้องถูกเรียกก่อน import โมดูลอื่นเสมอ
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, leave_room, emit
import random
import string
import time
import os

# --- การตั้งค่าพื้นฐาน ---
# บอกให้ Flask หาไฟล์ templates และ static จากโฟลเดอร์ชื่อเดียวกัน
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'a-very-secret-key-for-the-game!'

# --- การตั้งค่า SocketIO ---
# ใช้ eventlet เป็น async mode ซึ่งเป็นวิธีที่แนะนำและทำงานได้ดี
socketio = SocketIO(app, async_mode='eventlet')

# --- ข้อมูลหลักของเกม ---
# การเก็บข้อมูลในตัวแปรแบบนี้จะทำงานได้ดีเมื่อรันเซิร์ฟเวอร์เป็น process เดียว
rooms = {}  # เก็บข้อมูลห้องทั้งหมด { 'room_id': { 'players': {}, 'game_state': {} } }

# --- [แก้ไข] แยกสูตรอาหารปกติออกจากสูตรที่ต้องใช้ความสามารถ ---
RECIPES = {
    'สลัดผัก': {'ingredients': sorted(['🥬', '🍅', '🥕']), 'points': 50, 'time_bonus': 10},
    'สปาเก็ตตี้': {'ingredients': sorted(['🍝', '🥫', '🥩']), 'points': 110, 'time_bonus': 16},
    'ไอศกรีม': {'ingredients': sorted(['🍨', '🍒']), 'points': 35, 'time_bonus': 7},
    'ผลไม้รวม': {'ingredients': sorted(['🍓', '🍌', '🍎']), 'points': 30, 'time_bonus': 5},
}

ABILITIES_CONFIG = {
    'กระทะ': {'verb': 'ทอด', 'transformations': {'🥚': '🍳', '🥩': '🥓'}},
    'หม้อ': {'verb': 'ต้ม', 'transformations': {'🦐': '🦞', '🥔': '🍟'}},
    'เขียง': {'verb': 'หั่น', 'transformations': {'🥬': '🥗', '🥕': '🥒','🐟': '🍣'}}
}

# --- [แก้ไข] ย้ายสูตรที่ต้องแปรรูปวัตถุดิบมารวมกันที่นี่ ---
TRANSFORMED_RECIPES = {
    # หม้อ
    'ซีฟู้ดต้ม': {'ingredients': sorted(['🦞', '🍄', '🌶️']), 'points': 200, 'time_bonus': 22},
    'ไก่ทอด': {'ingredients': sorted(['🍗', '🍟']), 'points': 60, 'time_bonus': 10},
    # กระทะ
    'อาหารเช้าชุดใหญ่': {'ingredients': sorted(['🍳', '🍞', '🍄']), 'points': 170, 'time_bonus': 20},
    'สเต็กแอนด์ฟรายส์': {'ingredients': sorted(['🥓', '🥕', '🍄']), 'points': 210, 'time_bonus': 24},
    #เขียง
    'ซูชิ': {'ingredients': sorted(['🍣', '🥬']), 'points': 130, 'time_bonus': 18},
    'สลัดสุขภาพ': {'ingredients': sorted(['🥗', '🥕', '🍅']), 'points': 160, 'time_bonus': 18},
    'ส้มตำ': {'ingredients': sorted(['🥗', '🌶️', '🍅', '🥜']), 'points': 140, 'time_bonus': 19},
}

# รวมสูตรทั้งหมดเข้าด้วยกัน
RECIPES.update(TRANSFORMED_RECIPES)
ALL_INGREDIENTS = list(set(ing for recipe in RECIPES.values() for ing in recipe['ingredients']))

# จัดหมวดหมู่สูตรอาหารและวัตถุดิบเพื่อการสุ่มที่ถูกต้อง
NORMAL_RECIPES_KEYS = [k for k, v in RECIPES.items() if k not in TRANSFORMED_RECIPES]
ABILITY_TO_RECIPES = {}
for ability, config in ABILITIES_CONFIG.items():
    related_recipes = []
    transformed_ings = list(config['transformations'].values())
    for recipe_name, recipe_data in TRANSFORMED_RECIPES.items():
        if any(ing in recipe_data['ingredients'] for ing in transformed_ings):
            related_recipes.append(recipe_name)
    ABILITY_TO_RECIPES[ability] = related_recipes

TRANSFORMED_TO_BASE_INGREDIENT = {}
for ability_config in ABILITIES_CONFIG.values():
    for base, transformed in ability_config['transformations'].items():
        TRANSFORMED_TO_BASE_INGREDIENT[transformed] = base

# --- [เพิ่ม] สร้าง dict สำหรับค้นหาว่าวัตถุดิบแปรรูปมาจากความสามารถอะไร ---
TRANSFORMED_ING_INFO = {}
for ability, config in ABILITIES_CONFIG.items():
    for transformed_ing in config['transformations'].values():
        TRANSFORMED_ING_INFO[transformed_ing] = ability

# การตั้งค่าด่าน
LEVEL_DEFINITIONS = {
    1: {'target_score': 300, 'time': 120, 'spawn_interval': 4},
    2: {'target_score': 475, 'time': 110, 'spawn_interval': 3},
    3: {'target_score': 750, 'time': 100, 'spawn_interval': 3},
}

# ฟังก์ชันเสริมสำหรับจัดการเป้าหมาย
def assign_new_objective(player_state, game_state):
    active_abilities = {p_state['ability'] for p_state in game_state['players_state'].values() if p_state.get('ability')}
    possible_recipes = list(NORMAL_RECIPES_KEYS)
    for ability in active_abilities:
        if ability in ABILITY_TO_RECIPES:
            possible_recipes.extend(ABILITY_TO_RECIPES[ability])
    if not possible_recipes:
        possible_recipes = list(RECIPES.keys())
    objective_name = random.choice(possible_recipes)
    player_state['objective'] = {'name': objective_name}

# ฟังก์ชันสุ่มความสามารถ
def assign_abilities(game_state):
    player_sids = list(game_state['players_state'].keys())
    abilities_pool = list(ABILITIES_CONFIG.keys())
    assigned_abilities = abilities_pool + [None] * (max(0, len(player_sids) - len(abilities_pool)))
    random.shuffle(assigned_abilities)
    for i, sid in enumerate(player_sids):
        player_ability = assigned_abilities[i] if i < len(assigned_abilities) else None
        if sid in game_state['players_state']:
            game_state['players_state'][sid]['ability'] = player_ability
            game_state['players_state'][sid]['ability_processing'] = None

# หน้าเว็บหลัก
@app.route('/')
def index():
    return render_template('index.html')

# การจัดการการเชื่อมต่อ SocketIO
@socketio.on('connect')
def handle_connect():
    print(f"ผู้เล่นเชื่อมต่อเข้ามา: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"ผู้เล่นตัดการเชื่อมต่อ: {request.sid}")
    room_id_to_update = None
    player_sid_to_remove = request.sid
    for room_id, room_data in list(rooms.items()):
        if player_sid_to_remove in room_data['players']:
            room_id_to_update = room_id
            break
    if not room_id_to_update: return
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
            socketio.emit('game_over', {'total_score': total_final_score, 'message': 'ผู้เล่นไม่พอที่จะเล่นต่อ เกมจบลง'}, room=room_id_to_update)
            room['game_state'] = None
        else:
            player_sids = game_state['player_order_sids']
            for i, sid in enumerate(player_sids):
                left_neighbor_sid = player_sids[i - 1] if len(player_sids) > 1 else sid
                right_neighbor_sid = player_sids[(i + 1) % len(player_sids)] if len(player_sids) > 1 else sid
                socketio.emit('update_neighbors', {'left_neighbor': room['players'][left_neighbor_sid]['name'], 'right_neighbor': room['players'][right_neighbor_sid]['name']}, room=sid)
            ui_state = get_augmented_state_for_ui(room_id_to_update)
            if ui_state:
                socketio.emit('update_game_state', ui_state, room=room_id_to_update)
    if room.get('host_sid') == player_sid_to_remove and room['players']:
        new_host_sid = list(room['players'].keys())[0]
        room['host_sid'] = new_host_sid
        socketio.emit('new_host', {'host_sid': new_host_sid}, room=room_id_to_update)
    socketio.emit('update_lobby', {'players': [{'sid': sid, 'name': p['name']} for sid, p in room['players'].items()], 'host_sid': room.get('host_sid'), 'room_id': room_id_to_update}, room=room_id_to_update)

# ระบบล็อบบี้และห้อง
@socketio.on('create_room')
def handle_create_room(data):
    player_name = data.get('name', 'ผู้เล่นนิรนาม')
    room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    while room_id in rooms:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    rooms[room_id] = {'players': {request.sid: {'name': player_name}}, 'game_state': None, 'host_sid': request.sid}
    join_room(room_id)
    emit('room_created', {'room_id': room_id, 'is_host': True})
    socketio.emit('update_lobby', {'players': [{'sid': sid, 'name': p['name']} for sid, p in rooms[room_id]['players'].items()], 'host_sid': rooms[room_id]['host_sid'], 'room_id': room_id}, room=room_id)

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
    socketio.emit('update_lobby', {'players': [{'sid': sid, 'name': p['name']} for sid, p in rooms[room_id]['players'].items()], 'host_sid': rooms[room_id]['host_sid'], 'room_id': room_id}, room=room_id)

# ฟังก์ชันเสริมสำหรับสร้าง State
def get_augmented_state_for_ui(room_id):
    room = rooms.get(room_id)
    if not room or not room.get('game_state'): return None
    game_state = room['game_state']
    ui_state = game_state.copy()
    all_player_objectives = []
    for sid, p_state in game_state.get('players_state', {}).items():
        player_name = room['players'].get(sid, {}).get('name', '???')
        objective_data = p_state.get('objective')
        if objective_data and 'name' in objective_data:
            recipe_details = RECIPES[objective_data['name']]
            # --- [แก้ไข] เพิ่มข้อมูลเกี่ยวกับวิธีทำวัตถุดิบแปรรูป ---
            ingredients_with_hints = []
            for ing in recipe_details['ingredients']:
                hint = TRANSFORMED_ING_INFO.get(ing)
                base = TRANSFORMED_TO_BASE_INGREDIENT.get(ing)
                ingredients_with_hints.append({'name': ing, 'hint': hint, 'base': base})
            
            all_player_objectives.append({
                'player_name': player_name, 
                'objective_name': objective_data['name'], 
                'ingredients': ingredients_with_hints, # ส่งข้อมูลใหม่
                'points': recipe_details['points']
            })
    ui_state['all_player_objectives'] = all_player_objectives
    return ui_state

# ระบบเริ่มเกมและ Game Loop
def game_loop(room_id):
    last_spawn_time = time.time()
    with app.app_context():
        while True:
            room = rooms.get(room_id)
            if not room or not room.get('game_state'): break
            game_state = room['game_state']
            if not game_state.get('is_active'): break
            current_time = time.time()
            game_state['time_left'] -= 1
            spawn_interval = LEVEL_DEFINITIONS[game_state['level']]['spawn_interval']
            for sid, p_state in game_state['players_state'].items():
                if p_state.get('ability_processing'):
                    proc_info = p_state['ability_processing']
                    if current_time >= proc_info['end_time']:
                        output_item = proc_info['output']
                        socketio.emit('receive_item', {'item': {'type': 'ingredient', 'name': output_item}}, room=sid)
                        p_state['ability_processing'] = None
            
            if current_time - last_spawn_time > spawn_interval:
                all_player_sids = list(game_state['players_state'].keys())
                if all_player_sids:
                    required_ingredients_pool = []
                    for sid in all_player_sids:
                        objective = game_state['players_state'][sid].get('objective')
                        if objective and objective.get('name') in RECIPES:
                            required_ingredients_pool.extend(RECIPES[objective['name']]['ingredients'])
                    
                    if not required_ingredients_pool:
                        required_ingredients_pool = [ing for ing in ALL_INGREDIENTS if ing not in TRANSFORMED_TO_BASE_INGREDIENT]

                    spawnable_ingredients = []
                    for ing in required_ingredients_pool:
                        base_ingredient = TRANSFORMED_TO_BASE_INGREDIENT.get(ing, ing)
                        spawnable_ingredients.append(base_ingredient)

                    spawnable_ingredients = list(set(spawnable_ingredients))

                    if spawnable_ingredients:
                        for sid in all_player_sids:
                            ingredient_to_spawn = random.choice(spawnable_ingredients)
                            socketio.emit('receive_item', {'item': {'type': 'ingredient', 'name': ingredient_to_spawn}}, room=sid)
                last_spawn_time = time.time()

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
    if room_id not in rooms or rooms[room_id]['host_sid'] != request.sid: return
    room = rooms[room_id]
    player_sids = list(room['players'].keys())
    random.shuffle(player_sids)
    players_state = {}
    for sid in player_sids:
        players_state[sid] = {'plate': [], 'objective': None, 'ability': None, 'ability_processing': None}
    start_level = 1
    room['game_state'] = {'is_active': True, 'level': start_level, 'score': 0, 'total_score': 0, 'target_score': LEVEL_DEFINITIONS[start_level]['target_score'], 'time_left': LEVEL_DEFINITIONS[start_level]['time'], 'player_order_sids': player_sids, 'players_state': players_state}
    assign_abilities(room['game_state'])
    for sid in player_sids:
        assign_new_objective(room['game_state']['players_state'][sid], room['game_state'])
    ui_state = get_augmented_state_for_ui(room_id)
    for i, sid in enumerate(player_sids):
        left_neighbor_sid = player_sids[i - 1] if len(player_sids) > 1 else sid
        right_neighbor_sid = player_sids[(i + 1) % len(player_sids)] if len(player_sids) > 1 else sid
        emit('game_started', {'initial_state': ui_state, 'your_sid': sid, 'your_name': room['players'][sid]['name'], 'left_neighbor': room['players'][left_neighbor_sid]['name'], 'right_neighbor': room['players'][right_neighbor_sid]['name']}, room=sid)
    socketio.start_background_task(target=game_loop, room_id=room_id)
    print(f"เกมในห้อง {room_id} เริ่มขึ้นแล้ว!")

# ระบบใช้ความสามารถ
@socketio.on('use_ability')
def handle_use_ability(data):
    room_id = data.get('room_id')
    item_name = data.get('item_name')
    if not room_id or room_id not in rooms or not rooms[room_id].get('game_state'): return
    game_state = rooms[room_id]['game_state']
    if not game_state.get('is_active'): return
    player_sid = request.sid
    player_state = game_state['players_state'].get(player_sid)
    if not player_state: return
    if not player_state.get('ability') or player_state.get('ability_processing'):
        emit('action_fail', {'message': 'ไม่สามารถใช้ความสามารถได้ในขณะนี้', 'sound': 'error'})
        return
    ability = player_state['ability']
    if ability not in ABILITIES_CONFIG or item_name not in ABILITIES_CONFIG[ability]['transformations']:
        emit('action_fail', {'message': 'วัตถุดิบนี้ใช้กับความสามารถของคุณไม่ได้', 'sound': 'error'})
        return
    transformation = ABILITIES_CONFIG[ability]['transformations']
    output_item = transformation[item_name]
    player_state['ability_processing'] = {'input': item_name, 'output': output_item, 'end_time': time.time() + 6}
    ui_state = get_augmented_state_for_ui(room_id)
    if ui_state:
        socketio.emit('update_game_state', ui_state, room=room_id)
    verb = ABILITIES_CONFIG[ability]['verb']
    emit('action_success', {'message': f'กำลัง{verb}{item_name}...', 'sound': 'click'})

# ระบบการกระทำของผู้เล่น
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
        if item_data.get('type') == 'plate':
            emit('action_fail', {'message': 'ไม่สามารถส่งจานได้!', 'sound': 'error'})
            return
        player_index = game_state['player_order_sids'].index(player_sid)
        if len(game_state['player_order_sids']) > 1:
            target_sid = game_state['player_order_sids'][player_index - 1] if direction == 'left' else game_state['player_order_sids'][(player_index + 1) % len(game_state['player_order_sids'])]
        else:
            target_sid = player_sid
        socketio.emit('receive_item', {'item': item_data}, room=target_sid)
    elif action_type == 'add_to_plate':
        if player_state.get('plate') is not None:
             player_state['plate'] = data.get('new_plate_contents', [])
    elif action_type == 'trash_item':
        pass
    elif action_type == 'submit_order':
        if player_state.get('plate') is None:
            emit('action_fail', {'message': 'คุณไม่มีจาน!', 'sound': 'error'})
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
            assign_new_objective(player_state, game_state)
            player_state['plate'] = []
            emit('action_success', {'message': f'ทำ {player_objective_name} สำเร็จ! (+{points_earned} คะแนน)', 'sound': 'success'})
            if game_state['score'] >= game_state['target_score']:
                current_level = game_state['level']
                game_state['total_score'] += game_state['score']
                next_level = current_level + 1
                if next_level in LEVEL_DEFINITIONS:
                    game_state['is_active'] = False
                    socketio.emit('level_complete', {'level': current_level, 'level_score': game_state['score'], 'total_score': game_state['total_score']}, room=room_id)
                    socketio.sleep(5)
                    game_state['level'] = next_level
                    game_state['score'] = 0
                    game_state['target_score'] = LEVEL_DEFINITIONS[next_level]['target_score']
                    game_state['time_left'] = LEVEL_DEFINITIONS[next_level]['time']
                    for sid in game_state['players_state']:
                        game_state['players_state'][sid]['plate'] = []
                    assign_abilities(game_state)
                    for sid in game_state['players_state']:
                        assign_new_objective(game_state['players_state'][sid], game_state)
                    socketio.emit('clear_all_items', {}, room=room_id)
                    game_state['is_active'] = True
                    socketio.emit('start_next_level', get_augmented_state_for_ui(room_id), room=room_id)
                    # --- [แก้ไข] เริ่มต้น Game Loop สำหรับด่านต่อไป ---
                    socketio.start_background_task(target=game_loop, room_id=room_id)
                else:
                    game_state['is_active'] = False
                    total_final_score = game_state.get('total_score', 0)
                    socketio.emit('game_won', {'total_score': total_final_score}, room=room_id)
                    if rooms.get(room_id):
                        rooms[room_id]['game_state'] = None
        else:
            emit('action_fail', {'message': 'สูตรไม่ถูกต้อง! ลองอีกครั้ง', 'sound': 'error'})
    ui_state = get_augmented_state_for_ui(room_id)
    if ui_state:
        socketio.emit('update_game_state', ui_state, room=room_id)

if __name__ == '__main__':
    # สร้างโฟลเดอร์ที่จำเป็นหากยังไม่มี
    if not os.path.exists('templates'):
        os.makedirs('templates')
    if not os.path.exists('static/css'):
        os.makedirs('static/css')
    if not os.path.exists('static/js'):
        os.makedirs('static/js')

    print("เซิร์ฟเวอร์กำลังจะเริ่มที่ http://127.0.0.1:5000")
    # ใช้ debug=True เพื่อให้เซิร์ฟเวอร์รีสตาร์ทเมื่อมีการเปลี่ยนแปลงโค้ด
    # แต่สำหรับ production ควรตั้งเป็น False
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
