# app.py
#
# --- วิธีการรันโปรแกรม ---
# 1. ติดตั้งไลบรารีที่จำเป็น:
#    pip install Flask Flask-SocketIO eventlet
#
# 2. รันเซิร์ฟเวอร์ด้วยคำสั่ง:
#    python app.py
#
# 3. เปิดเว็บเบราว์เซอร์ไปที่ http://127.0.0.1:5000
#
# (คำแนะนำ: วิธีการรันนี้สามารถใช้ได้ทั้งสำหรับการทดสอบและใช้งานจริง)
# ---

import eventlet
# eventlet.monkey_patch() ต้องถูกเรียกก่อน import โมดูลอื่นเสมอ
eventlet.monkey_patch()

from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, join_room, leave_room, emit
import random
import string
import time
import os

# --- การตั้งค่าพื้นฐาน ---
app = Flask(__name__)
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
    'เบอร์เกอร์': {'ingredients': sorted(['🍞', '🥩', '🧀']), 'points': 100, 'time_bonus': 15},
    'แซนด์วิช': {'ingredients': sorted(['🍞', '🍖', '🥬']), 'points': 80, 'time_bonus': 12},
    'สเต็ก': {'ingredients': sorted(['🥩', '🥔', '🥕']), 'points': 150, 'time_bonus': 20},
    'ไข่ดาว': {'ingredients': sorted(['🥚', '🥚']), 'points': 40, 'time_bonus': 8},
    'พิซซ่า': {'ingredients': sorted(['🍕', '🍄', '🧀', '🍖']), 'points': 200, 'time_bonus': 25},
    'ต้มยำกุ้ง': {'ingredients': sorted(['🦐', '🍄', '🌶️']), 'points': 170, 'time_bonus': 22},
    'ผัดไทย': {'ingredients': sorted(['🍜', '🦐', '🥜']), 'points': 160, 'time_bonus': 21},
    'ข้าวผัด': {'ingredients': sorted(['🍚', '🥚', '🥕']), 'points': 90, 'time_bonus': 13},
    'แกงเขียวหวาน': {'ingredients': sorted(['🍗', '🍆', '🥥']), 'points': 190, 'time_bonus': 24},
    'ซูชิ': {'ingredients': sorted(['🍣', '🍚', '🐟']), 'points': 130, 'time_bonus': 18},
    'สปาเก็ตตี้': {'ingredients': sorted(['🍝', '🥫', '🥩']), 'points': 110, 'time_bonus': 16},
    'ไอศกรีม': {'ingredients': sorted(['🍨', '🍒']), 'points': 35, 'time_bonus': 7},
    'ผลไม้รวม': {'ingredients': sorted(['🍓', '🍌', '🍎']), 'points': 30, 'time_bonus': 5},
}

ABILITIES_CONFIG = {
    'กระทะ': {'verb': 'ทอด', 'transformations': {'🥚': '🍳', '🥩': '🥓'}},
    'หม้อ': {'verb': 'ต้ม', 'transformations': {'🦐': '🦞', '🥔': '🍟'}},
    'เขียง': {'verb': 'หั่น', 'transformations': {'🥬': '🥗', '🥕': '🥒'}}
}

# --- [แก้ไข] ย้ายสูตรที่ต้องแปรรูปวัตถุดิบมารวมกันที่นี่ ---
TRANSFORMED_RECIPES = {
    'อาหารเช้าชุดใหญ่': {'ingredients': sorted(['🍳', '🥓', '🍞']), 'points': 180, 'time_bonus': 20},
    'สเต็กแอนด์ฟรายส์': {'ingredients': sorted(['🥓', '🍟', '🥗']), 'points': 220, 'time_bonus': 25},
    'ซีฟู้ดต้ม': {'ingredients': sorted(['🦞', '🍄', '🌶️']), 'points': 200, 'time_bonus': 22},
    'สลัดสุขภาพ': {'ingredients': sorted(['🥗', '🥒', '🍅']), 'points': 160, 'time_bonus': 18},
    'ไก่ทอด': {'ingredients': sorted(['🍗', '🍟']), 'points': 60, 'time_bonus': 10},
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
    1: {'target_score': 300, 'time': 180, 'spawn_interval': 4},
    2: {'target_score': 500, 'time': 180, 'spawn_interval': 3},
    3: {'target_score': 800, 'time': 180, 'spawn_interval': 3},
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
    return render_template_string(open('templates/index.html', encoding='utf-8').read())

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
    if not os.path.exists('templates'):
        os.makedirs('templates')

    html_content = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>ครัวอลหม่าน</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/tone/14.7.77/Tone.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Kanit:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #f9fafb; --bg-secondary: #ffffff; --bg-tertiary: #f3f4f6; --bg-interactive: #e5e7eb;
            --text-primary: #111827; --text-secondary: #6b7280; --border-color: #d1d5db; --accent-color: #f97316;
            --accent-text-color: #ffffff;
        }
        html.dark {
            --bg-primary: #1f2937; --bg-secondary: #374151; --bg-tertiary: #4b5563; --bg-interactive: #505a68;
            --text-primary: #f3f4f6; --text-secondary: #9ca3af; --border-color: #4b5563; --accent-color: #fb923c;
            --accent-text-color: #111827;
        }
        body { 
            font-family: 'Kanit', sans-serif; touch-action: none; overflow: hidden;
            overscroll-behavior: none; background-color: var(--bg-primary); color: var(--text-primary);
            transition: background-color 0.3s, color 0.3s;
        }
        .item, .plate {
            cursor: grab; user-select: none; touch-action: none;
            transition: transform 0.2s ease-in-out, opacity 0.2s ease-in-out, box-shadow 0.2s ease-in-out;
        }
        .item:active { cursor: grabbing; }
        .ghost-drag {
            position: fixed; pointer-events: none; z-index: 1000; opacity: 0.8;
            transform: scale(1.1) rotate(5deg); transition: none;
        }
        .dragging { opacity: 0.4; transform: scale(0.95); }
        .drop-zone { border: 2px dashed var(--border-color); transition: all 0.2s; }
        .drop-zone.drag-over { 
            border-color: #4ade80; background-color: #f0fdf4; transform: scale(1.02); 
            box-shadow: 0 0 15px rgba(74, 222, 128, 0.5);
        }
        html.dark .drop-zone.drag-over { background-color: #166534; }
        #ability-station.processing {
             border-style: solid; border-color: #818cf8; animation: pulse-border 2s infinite;
        }
        @keyframes pulse-border {
            0% { box-shadow: 0 0 0 0 rgba(129, 140, 248, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(129, 140, 248, 0); }
            100% { box-shadow: 0 0 0 0 rgba(129, 140, 248, 0); }
        }
        .plate-items-container { min-height: 40px; }
        .item {
            font-size: 2rem; line-height: 1; width: 50px; height: 50px; display: flex;
            align-items: center; justify-content: center; padding: 0; border-radius: 9999px; flex-shrink: 0;
        }
        .item-in-plate {
            background-color: #dcfce7; color: #166534; font-size: 1.25rem;
            line-height: 1; padding: 4px; border-radius: 8px;
        }
        html.dark .item-in-plate { background-color: #15803d; color: #dcfce7; }
        .plate { cursor: default; }
        .player-tag { padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem; font-weight: bold; margin-left: 8px; }
        .screen-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0; background-color: rgba(0, 0, 0, 0.75);
            display: flex; align-items: center; justify-content: center; z-index: 50; transition: opacity 0.3s ease;
        }
        .popup-box {
            background-color: var(--bg-secondary); color: var(--text-primary);
            transform: scale(0.7); opacity: 0;
        }
        .screen-overlay:not(.hidden) .popup-box {
            opacity: 1; animation: popup-bounce-in 0.4s cubic-bezier(0.68, -0.55, 0.27, 1.55) forwards;
        }
        @keyframes popup-bounce-in { 0% { transform: scale(0.7); opacity: 0; } 70% { transform: scale(1.05); } 100% { transform: scale(1); opacity: 1; } }
        .toast { animation: toast-in 0.5s forwards, toast-out 0.5s 4s forwards; pointer-events: none; }
        @keyframes toast-in { from { transform: translateX(120%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        @keyframes toast-out { from { transform: translateX(0); opacity: 1; } to { transform: translateX(120%); opacity: 0; } }
    </style>
</head>
<body class="flex items-center justify-center min-h-dvh p-2 sm:p-4">

    <div id="main-container" class="w-full h-full max-w-screen-2xl bg-[var(--bg-secondary)] rounded-xl shadow-2xl p-4 sm:p-6 transition-all duration-500 relative overflow-hidden flex flex-col">
        
        <div class="absolute top-4 right-4 z-10">
            <button id="theme-toggle" class="p-2 rounded-full bg-[var(--bg-interactive)] text-[var(--text-primary)]">
                <svg id="theme-icon-sun" class="h-6 w-6 hidden" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" /></svg>
                <svg id="theme-icon-moon" class="h-6 w-6 hidden" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" /></svg>
            </button>
        </div>

        <div id="login-screen" class="flex-grow flex flex-col justify-center">
            <h1 class="text-4xl font-bold text-center text-[var(--accent-color)] mb-6">ครัวอลหม่าน</h1>
            <div class="max-w-sm mx-auto w-full">
                <input id="player-name" type="text" placeholder="ใส่ชื่อของคุณ" class="w-full p-3 border rounded-lg mb-4 focus:ring-2 focus:outline-none bg-[var(--bg-primary)] border-[var(--border-color)] focus:ring-[var(--accent-color)]">
                <input id="room-code-input" type="text" placeholder="ใส่รหัสห้อง (ถ้ามี)" class="w-full p-3 border rounded-lg mb-4 focus:ring-2 focus:outline-none uppercase bg-[var(--bg-primary)] border-[var(--border-color)] focus:ring-[var(--accent-color)]">
                <div class="flex space-x-4">
                    <button id="join-btn" class="w-full bg-blue-500 text-white p-3 rounded-lg font-bold hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-700 transition">เข้าร่วมห้อง</button>
                    <button id="create-btn" class="w-full bg-green-500 text-white p-3 rounded-lg font-bold hover:bg-green-600 dark:bg-green-600 dark:hover:bg-green-700 transition">สร้างห้องใหม่</button>
                </div>
            </div>
        </div>

        <div id="lobby-screen" class="hidden flex-grow flex flex-col justify-center">
            <h2 class="text-3xl font-bold text-center mb-2">ห้องรอเล่น</h2>
            <p class="text-center text-[var(--text-secondary)] mb-4">รหัสห้อง: <span id="room-code-display" class="font-bold text-2xl text-red-500 dark:text-red-400 bg-[var(--bg-tertiary)] px-3 py-1 rounded-md cursor-pointer" title="คลิกเพื่อคัดลอก"></span></p>
            <div class="bg-[var(--bg-tertiary)] p-4 rounded-lg min-h-[200px] max-w-md mx-auto w-full">
                <h3 class="font-bold mb-2">ผู้เล่นในห้อง:</h3>
                <ul id="player-list" class="list-disc list-inside space-y-2"></ul>
            </div>
            <div class="max-w-md mx-auto w-full">
                <button id="start-game-btn" class="hidden w-full mt-6 bg-[var(--accent-color)] text-[var(--accent-text-color)] p-4 rounded-lg font-bold text-xl hover:opacity-90 transition">เริ่มเกม!</button>
                <button id="leave-room-btn" class="w-full mt-2 bg-red-500 text-white p-2 rounded-lg font-bold hover:bg-red-600 dark:bg-red-600 dark:hover:bg-red-700 transition">ออกจากห้อง</button>
            </div>
        </div>

        <div id="game-screen" class="hidden flex flex-col h-full">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-2 md:gap-4 text-center mb-4 p-2 md:p-3 bg-[var(--bg-tertiary)] rounded-lg text-xs sm:text-sm md:text-base flex-shrink-0">
                <div>ด่าน: <span id="level" class="font-bold text-lg">1</span></div>
                <div>คะแนน: <span id="score" class="font-bold text-lg">0</span> / <span id="target-score" class="font-bold text-lg">0</span></div>
                <div class="text-2xl font-bold text-red-500 dark:text-red-400">เวลา: <span id="time">180</span></div>
                <div><span id="player-count" class="font-bold text-lg">0</span> ผู้เล่น</div>
            </div>

            <div id="game-layout-container" class="grid grid-cols-1 lg:grid-cols-12 gap-4 flex-grow overflow-y-auto lg:overflow-hidden" style="min-height: 0;">
                <div class="lg:col-span-2 flex flex-col">
                    <div id="pass-left-zone" class="drop-zone p-2 md:p-4 rounded-lg text-center bg-blue-100 dark:bg-blue-900/50 flex-grow flex flex-col items-center justify-center min-h-[100px] lg:min-h-0">
                        <h4 class="text-xs md:text-sm font-bold text-blue-800 dark:text-blue-200">ส่งให้ (ซ้าย)</h4>
                        <p id="pass-left-name" class="font-bold text-lg md:text-xl text-blue-900 dark:text-blue-100 truncate"></p>
                    </div>
                </div>

                <div class="lg:col-span-3 space-y-4 flex flex-col">
                    <div class="bg-yellow-50 dark:bg-yellow-900/50 p-3 rounded-lg flex-grow flex flex-col min-h-[200px] lg:min-h-0" style="min-height: 0;">
                        <h3 class="font-bold text-lg mb-2 text-center flex-shrink-0">เป้าหมาย</h3>
                        <ul id="objectives-list" class="space-y-2 overflow-y-auto"></ul>
                    </div>
                     <div id="trash-zone" class="drop-zone p-4 rounded-lg text-center bg-red-100 dark:bg-red-900/50 flex-shrink-0 h-24 flex items-center justify-center">
                        <h4 class="font-bold text-red-800 dark:text-red-200">ถังขยะ</h4>
                    </div>
                </div>

                <div class="lg:col-span-5 flex flex-col space-y-2">
                    <div class="text-center font-bold text-lg">พื้นที่ของ <span id="my-name" class="text-purple-600 dark:text-purple-400"></span></div>
                    
                    <div id="ability-station" class="p-3 rounded-lg text-center bg-indigo-100 dark:bg-indigo-900/50 min-h-[100px] flex flex-col items-center justify-center transition-all">
                    </div>

                    <div id="cooking-area" class="flex-grow p-2 bg-blue-50 dark:bg-blue-900/20 rounded-lg flex flex-col items-center relative min-h-[150px]">
                        <h4 class="font-bold text-gray-400 dark:text-gray-500 absolute top-2">พื้นที่ทำอาหาร</h4>
                        <div id="plate-container" class="w-full h-full flex items-center justify-center">
                        </div>
                    </div>
                    <div id="conveyor-belt" class="min-h-[80px] p-2 bg-[var(--bg-tertiary)] rounded-lg flex items-center flex-nowrap gap-2 overflow-x-auto">
                        <span class="text-[var(--text-secondary)] flex-shrink-0">วัตถุดิบที่ได้รับ...</span>
                    </div>
                    <button id="submit-order-btn" class="w-full bg-green-500 text-white p-3 rounded-lg font-bold hover:bg-green-600 dark:bg-green-600 dark:hover:bg-green-700 transition">ส่งอาหาร</button>
                </div>

                <div class="lg:col-span-2 flex flex-col">
                     <div id="pass-right-zone" class="drop-zone p-2 md:p-4 rounded-lg text-center bg-green-100 dark:bg-green-900/50 flex-grow flex flex-col items-center justify-center min-h-[100px] lg:min-h-0">
                        <h4 class="text-xs md:text-sm font-bold text-green-800 dark:text-green-200">ส่งให้ (ขวา)</h4>
                        <p id="pass-right-name" class="font-bold text-lg md:text-xl text-green-900 dark:text-green-100 truncate"></p>
                    </div>
                </div>
            </div>
        </div>

        <div id="level-complete-screen" class="hidden screen-overlay"><div class="p-8 rounded-xl shadow-2xl text-center popup-box"><h1 id="level-complete-title" class="text-4xl font-bold text-green-500 dark:text-green-400 mb-4">ผ่านด่าน!</h1><p id="level-complete-message" class="text-xl mb-2"></p><p id="total-score-message" class="text-2xl mb-6"></p><p class="text-[var(--text-secondary)]">เตรียมตัวสำหรับด่านต่อไป...</p></div></div>
        <div id="game-over-screen" class="hidden screen-overlay"><div class="p-8 rounded-xl shadow-2xl text-center popup-box"><h1 class="text-5xl font-bold text-red-600 dark:text-red-500 mb-4">เกมจบแล้ว!</h1><p id="game-over-message" class="text-xl text-[var(--text-secondary)] mb-4"></p><p class="text-2xl mb-6">คะแนนรวมทั้งหมด: <span id="final-total-score" class="font-bold">0</span></p><button id="back-to-lobby-btn" class="bg-blue-500 text-white p-3 rounded-lg font-bold hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-700 transition">กลับไปที่ล็อบบี้</button></div></div>
        <div id="game-won-screen" class="hidden screen-overlay"><div class="p-8 rounded-xl shadow-2xl text-center popup-box"><h1 class="text-5xl font-bold text-yellow-500 dark:text-yellow-400 mb-4">คุณชนะ!</h1><p class="text-xl text-[var(--text-secondary)] mb-4">สุดยอดไปเลย! คุณผ่านทุกด่านแล้ว</p><p class="text-2xl mb-6">คะแนนรวมทั้งหมด: <span id="final-won-score" class="font-bold">0</span></p><button id="won-back-to-lobby-btn" class="bg-blue-500 text-white p-3 rounded-lg font-bold hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-700 transition">กลับไปที่ล็อบบี้</button></div></div>
    </div>

    <div id="popup-overlay" class="hidden screen-overlay" style="z-index: 100;"><div class="popup-box p-6 rounded-xl shadow-2xl text-center w-full max-w-sm mx-4"><p id="popup-message" class="text-lg mb-6"></p><button id="popup-close-btn" class="w-full bg-blue-500 text-white px-6 py-2 rounded-lg font-bold hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-700 transition focus:outline-none focus:ring-2 focus:ring-blue-400">ตกลง</button></div></div>
    <div id="toast-container" class="fixed top-5 right-5 z-[100] w-full max-w-xs space-y-3"></div>


<script>
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
        'เขียง': {'verb': 'หั่น', 'transformations': {'🥬': '🥗', '🥕': '🥒'}}
    };

    let audioInitialized = false;
    const sounds = {};
    function initAudio() {
        if (audioInitialized) return;
        Tone.start();
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

    createBtn.addEventListener('click', () => { initAudio(); playSound('click'); myName = playerNameInput.value.trim(); if (!myName) { showPopup('กรุณาใส่ชื่อของคุณ!'); return; } socket.emit('create_room', { name: myName }); });
    joinBtn.addEventListener('click', () => { initAudio(); playSound('click'); myName = playerNameInput.value.trim(); const roomId = roomCodeInput.value.trim().toUpperCase(); if (!myName || !roomId) { showPopup('กรุณาใส่ชื่อและรหัสห้อง!'); return; } socket.emit('join_room', { name: myName, room_id: roomId }); });
    leaveRoomBtn.addEventListener('click', () => { playSound('click'); location.reload(); });
    roomCodeDisplay.addEventListener('click', () => { if(currentRoomId) navigator.clipboard.writeText(currentRoomId).then(() => { showToast('คัดลอกรหัสห้องแล้ว!', 'success'); playSound('click'); }); });
    startGameBtn.addEventListener('click', () => { playSound('levelUp'); socket.emit('start_game', { room_id: currentRoomId }); });
    submitOrderBtn.addEventListener('click', () => { playSound('click'); socket.emit('player_action', { room_id: currentRoomId, type: 'submit_order' }); });
    backToLobbyBtn.addEventListener('click', () => { playSound('click'); showScreen('lobby'); });
    wonBackToLobbyBtn.addEventListener('click', () => { playSound('click'); showScreen('lobby'); });

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
            
            // --- [แก้ไข] แสดงข้อมูลว่าวัตถุดิบแปรรูปมาจากไหน ---
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
    
    const themeToggleBtn = document.getElementById('theme-toggle');
    const sunIcon = document.getElementById('theme-icon-sun');
    const moonIcon = document.getElementById('theme-icon-moon');
    function applyTheme(theme) { if (theme === 'dark') { document.documentElement.classList.add('dark'); sunIcon.classList.remove('hidden'); moonIcon.classList.add('hidden'); localStorage.setItem('theme', 'dark'); } else { document.documentElement.classList.remove('dark'); sunIcon.classList.add('hidden'); moonIcon.classList.remove('hidden'); localStorage.setItem('theme', 'light'); } }
    themeToggleBtn.addEventListener('click', () => { const currentTheme = localStorage.getItem('theme') || 'light'; applyTheme(currentTheme === 'light' ? 'dark' : 'light'); });
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (savedTheme) { applyTheme(savedTheme); } else { applyTheme(prefersDark ? 'dark' : 'light'); }

</script>
</body>
</html>
    """
    with open('templates/index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)

    print("เซิร์ฟเวอร์กำลังจะเริ่มที่ http://127.0.0.1:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
