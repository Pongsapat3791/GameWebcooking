# app.py (เวอร์ชันปรับปรุงด้วย OOP)
#
# --- ภาพรวมการเปลี่ยนแปลง ---
# 1. ใช้หลักการ OOP: สร้าง Class `Player`, `GameState`, `GameRoom` เพื่อจัดการข้อมูลและตรรกะของเกมให้เป็นสัดส่วน
# 2. ปรับปรุง Game Loop: ใช้ "Master Game Loop" เพียงตัวเดียวในการอัปเดตทุกห้องเกมที่ Active อยู่
#    ซึ่งช่วยลดการใช้ CPU ลงอย่างมากเมื่อเทียบกับการสร้าง Loop แยกสำหรับแต่ละห้อง
# 3. โค้ดที่สะอาดขึ้น: การแยกส่วนการทำงานทำให้โค้ดอ่านง่าย, แก้ไข, และต่อยอดได้สะดวกขึ้น

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, leave_room, emit
import random
import string
import time
import os
from threading import Lock

# --- การตั้งค่าพื้นฐาน ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'a-very-secret-key-for-the-game!'
socketio = SocketIO(app, async_mode='eventlet')

# --- ข้อมูลหลักของเกม (Constants) ---
# การเก็บข้อมูลเหล่านี้ไว้ในระดับ Global ทำให้เข้าถึงได้ง่ายและไม่เปลี่ยนแปลง
RECIPES = {
    'สลัดผัก': {'ingredients': sorted(['🥬', '🍅', '🥕']), 'points': 50, 'time_bonus': 10},
    'สปาเก็ตตี้': {'ingredients': sorted(['🍝', '🥫', '🥩']), 'points': 110, 'time_bonus': 16},
    'ไอศกรีม': {'ingredients': sorted(['🍨', '🍒']), 'points': 35, 'time_bonus': 7},
    'ผลไม้รวม': {'ingredients': sorted(['🍓', '🍌', '🍎']), 'points': 30, 'time_bonus': 5},
    'ซีฟู้ดต้ม': {'ingredients': sorted(['🦞', '🍄', '🌶️']), 'points': 200, 'time_bonus': 22},
    'ไก่ทอด': {'ingredients': sorted(['🍗', '🍟']), 'points': 60, 'time_bonus': 10},
    'อาหารเช้าชุดใหญ่': {'ingredients': sorted(['🍳', '🍞', '🍄']), 'points': 170, 'time_bonus': 20},
    'สเต็กแอนด์ฟรายส์': {'ingredients': sorted(['🥓', '🥕', '🍄']), 'points': 210, 'time_bonus': 24},
    'ซูชิ': {'ingredients': sorted(['🍣', '🥬']), 'points': 130, 'time_bonus': 18},
    'สลัดสุขภาพ': {'ingredients': sorted(['🥗', '🥕', '🍅']), 'points': 160, 'time_bonus': 18},
    'ส้มตำ': {'ingredients': sorted(['🥗', '🌶️', '🍅', '🥜']), 'points': 140, 'time_bonus': 19},
}

ABILITIES_CONFIG = {
    'กระทะ': {'verb': 'ทอด', 'transformations': {'🥚': '🍳', '🥩': '🥓'}},
    'หม้อ': {'verb': 'ต้ม', 'transformations': {'🦐': '🦞', '🥔': '🍟'}},
    'เขียง': {'verb': 'หั่น', 'transformations': {'🥬': '🥗', '🥕': '🥒','🐟': '🍣'}}
}

LEVEL_DEFINITIONS = {
    1: {'target_score': 300, 'time': 130, 'spawn_interval': 3},
    2: {'target_score': 475, 'time': 120, 'spawn_interval': 3},
    3: {'target_score': 750, 'time': 110, 'spawn_interval': 3},
}

# --- สร้างข้อมูลอ้างอิงเพื่อการค้นหาที่รวดเร็ว ---
TRANSFORMED_TO_BASE_INGREDIENT = {transformed: base for ability_config in ABILITIES_CONFIG.values() for base, transformed in ability_config['transformations'].items()}
TRANSFORMED_ING_INFO = {transformed: ability for ability, config in ABILITIES_CONFIG.items() for transformed in config['transformations'].values()}
ALL_INGREDIENTS = list(set(ing for recipe in RECIPES.values() for ing in recipe['ingredients']))
NORMAL_RECIPES_KEYS = [k for k, v in RECIPES.items() if not any(ing in TRANSFORMED_TO_BASE_INGREDIENT for ing in v['ingredients'])]
ABILITY_TO_RECIPES = {
    ability: [
        recipe_name for recipe_name, recipe_data in RECIPES.items()
        if any(ing in recipe_data['ingredients'] for ing in config['transformations'].values())
    ]
    for ability, config in ABILITIES_CONFIG.items()
}

# --- โครงสร้างหลักแบบ OOP ---

class Player:
    """เก็บข้อมูลและสถานะของผู้เล่นแต่ละคน"""
    def __init__(self, sid, name):
        self.sid = sid
        self.name = name
        self.plate = []
        self.objective = None
        self.ability = None
        self.ability_processing = None # {'input': str, 'output': str, 'end_time': float}

    def assign_new_objective(self, possible_recipes):
        """สุ่มเป้าหมายใหม่ให้ผู้เล่น"""
        if not possible_recipes:
            possible_recipes = list(RECIPES.keys())
        objective_name = random.choice(possible_recipes)
        self.objective = {'name': objective_name}

class GameState:
    """จัดการสถานะโดยรวมของเกมในห้องนั้นๆ เช่น ด่าน, คะแนน, เวลา"""
    def __init__(self, player_sids, players_map, level=1):
        self.is_active = True
        self.level = level
        self.score = 0
        self.total_score = 0
        self.target_score = LEVEL_DEFINITIONS[level]['target_score']
        self.time_left = LEVEL_DEFINITIONS[level]['time']
        self.player_order_sids = player_sids
        self.players_map = players_map # {sid: Player object}
        self.last_spawn_time = time.time()

    def tick(self):
        """อัปเดตสถานะเกมในแต่ละวินาที (ถูกเรียกโดย Master Game Loop)"""
        if not self.is_active:
            return
        self.time_left -= 1

    def check_ability_processing(self):
        """ตรวจสอบการแปรรูปวัตถุดิบที่เสร็จสิ้น"""
        finished_players = []
        current_time = time.time()
        for player in self.players_map.values():
            if player.ability_processing and current_time >= player.ability_processing['end_time']:
                finished_players.append(player)
        return finished_players

    def get_spawnable_ingredients(self):
        """รวบรวมวัตถุดิบที่จำเป็นสำหรับผู้เล่นทุกคนเพื่อนำไปสุ่ม"""
        required_pool = set()
        for player in self.players_map.values():
            if player.objective and player.objective.get('name') in RECIPES:
                for ing in RECIPES[player.objective['name']]['ingredients']:
                    base_ingredient = TRANSFORMED_TO_BASE_INGREDIENT.get(ing, ing)
                    required_pool.add(base_ingredient)
        
        if not required_pool: # กรณีไม่มีเป้าหมาย ให้สุ่มจากวัตถุดิบพื้นฐานทั้งหมด
            return [ing for ing in ALL_INGREDIENTS if ing not in TRANSFORMED_TO_BASE_INGREDIENT]
            
        return list(required_pool)

class GameRoom:
    """Class หลักในการจัดการห้องเกม 1 ห้อง"""
    def __init__(self, room_id, host_sid, host_name):
        self.id = room_id
        self.host_sid = host_sid
        self.players = {host_sid: Player(host_sid, host_name)}
        self.game_state = None
        self.lock = Lock() # ป้องกัน Race Condition เมื่อมีการเข้าถึงข้อมูลพร้อมกัน

    def add_player(self, sid, name):
        with self.lock:
            if len(self.players) < 8:
                self.players[sid] = Player(sid, name)
                return True
            return False

    def remove_player(self, sid):
        with self.lock:
            if sid in self.players:
                del self.players[sid]
            if not self.players:
                return 'delete_room' # สัญญาณให้ลบห้องนี้ทิ้ง
            if sid == self.host_sid:
                self.host_sid = list(self.players.keys())[0]
            if self.game_state and self.game_state.is_active:
                if sid in self.game_state.player_order_sids:
                    self.game_state.player_order_sids.remove(sid)
                if sid in self.game_state.players_map:
                    del self.game_state.players_map[sid]
                if len(self.game_state.player_order_sids) < 1:
                    self.game_state.is_active = False
                    return 'game_over_disconnect'
        return 'ok'

    def start_game(self):
        with self.lock:
            player_sids = list(self.players.keys())
            random.shuffle(player_sids)
            self.game_state = GameState(player_sids, self.players)
            self._assign_abilities()
            self._assign_all_objectives()
            
            # ส่งข้อมูลเริ่มต้นเกมให้ผู้เล่นทุกคน
            ui_state = self.get_augmented_state_for_ui()
            for i, sid in enumerate(player_sids):
                left_sid = player_sids[i - 1]
                right_sid = player_sids[(i + 1) % len(player_sids)]
                emit('game_started', {
                    'initial_state': ui_state,
                    'your_sid': sid,
                    'your_name': self.players[sid].name,
                    'left_neighbor': self.players[left_sid].name,
                    'right_neighbor': self.players[right_sid].name
                }, room=sid)
            print(f"เกมในห้อง {self.id} เริ่มขึ้นแล้ว!")

    def _assign_abilities(self):
        """สุ่มความสามารถให้ผู้เล่นในห้อง"""
        abilities_pool = list(ABILITIES_CONFIG.keys())
        random.shuffle(abilities_pool)
        for i, player in enumerate(self.players.values()):
            player.ability = abilities_pool[i] if i < len(abilities_pool) else None
            player.ability_processing = None

    def _assign_all_objectives(self):
        """สุ่มเป้าหมายให้ผู้เล่นทุกคน"""
        active_abilities = {p.ability for p in self.players.values() if p.ability}
        possible_recipes = list(NORMAL_RECIPES_KEYS)
        for ability in active_abilities:
            possible_recipes.extend(ABILITY_TO_RECIPES.get(ability, []))
        
        for player in self.players.values():
            player.assign_new_objective(possible_recipes)

    def update(self):
        """ฟังก์ชันที่ถูกเรียกโดย Master Game Loop ทุกๆ 1 วินาที"""
        with self.lock:
            if not self.game_state or not self.game_state.is_active:
                return

            self.game_state.tick()

            # 1. ตรวจสอบการแปรรูปวัตถุดิบ
            finished_players = self.game_state.check_ability_processing()
            for player in finished_players:
                output_item = player.ability_processing['output']
                socketio.emit('receive_item', {'item': {'type': 'ingredient', 'name': output_item}}, room=player.sid)
                player.ability_processing = None

            # 2. สุ่มวัตถุดิบ
            spawn_interval = LEVEL_DEFINITIONS[self.game_state.level]['spawn_interval']
            if time.time() - self.game_state.last_spawn_time > spawn_interval:
                spawnable_ings = self.game_state.get_spawnable_ingredients()
                if spawnable_ings:
                    for sid in self.game_state.player_order_sids:
                        ingredient = random.choice(spawnable_ings)
                        socketio.emit('receive_item', {'item': {'type': 'ingredient', 'name': ingredient}}, room=sid)
                self.game_state.last_spawn_time = time.time()

            # 3. ตรวจสอบเงื่อนไขจบเกม (หมดเวลา)
            if self.game_state.time_left <= 0:
                self.game_state.is_active = False
                total_final_score = self.game_state.total_score + self.game_state.score
                socketio.emit('game_over', {'total_score': total_final_score, 'message': 'หมดเวลา!'}, room=self.id)
                self.game_state = None # รีเซ็ตสถานะเกม
    
    def get_lobby_info(self):
        """สร้างข้อมูลสำหรับหน้า Lobby"""
        return {
            'players': [{'sid': p.sid, 'name': p.name} for p in self.players.values()],
            'host_sid': self.host_sid,
            'room_id': self.id
        }

    def get_augmented_state_for_ui(self):
        """สร้างข้อมูลเกมทั้งหมดเพื่อส่งไปอัปเดตหน้า UI"""
        if not self.game_state: return None
        
        # สร้างสำเนาข้อมูลพื้นฐาน
        ui_state = {
            'is_active': self.game_state.is_active,
            'level': self.game_state.level,
            'score': self.game_state.score,
            'total_score': self.game_state.total_score,
            'target_score': self.game_state.target_score,
            'time_left': self.game_state.time_left,
            'player_order_sids': self.game_state.player_order_sids,
        }

        # สร้างข้อมูลผู้เล่นและเป้าหมาย
        ui_state['players_state'] = {
            sid: {
                'plate': p.plate,
                'objective': p.objective,
                'ability': p.ability,
                'ability_processing': p.ability_processing
            } for sid, p in self.players.items() if sid in self.game_state.players_map
        }
        
        # สร้างข้อมูลเป้าหมายพร้อมคำใบ้
        all_player_objectives = []
        for player in self.game_state.players_map.values():
            if player.objective and 'name' in player.objective:
                recipe_details = RECIPES[player.objective['name']]
                ingredients_with_hints = [
                    {'name': ing, 'hint': TRANSFORMED_ING_INFO.get(ing), 'base': TRANSFORMED_TO_BASE_INGREDIENT.get(ing)}
                    for ing in recipe_details['ingredients']
                ]
                all_player_objectives.append({
                    'player_name': player.name,
                    'objective_name': player.objective['name'],
                    'ingredients': ingredients_with_hints,
                    'points': recipe_details['points']
                })
        ui_state['all_player_objectives'] = all_player_objectives
        return ui_state

    def handle_player_action(self, sid, data):
        """จัดการ Action ต่างๆ จากผู้เล่น"""
        with self.lock:
            player = self.players.get(sid)
            if not player or not self.game_state or not self.game_state.is_active:
                return

            action_type = data.get('type')
            
            if action_type == 'pass_item':
                item_data = data.get('item')
                if item_data.get('type') == 'plate':
                    emit('action_fail', {'message': 'ไม่สามารถส่งจานได้!', 'sound': 'error'}, room=sid)
                    return
                
                player_sids = self.game_state.player_order_sids
                if len(player_sids) <= 1: return

                player_index = player_sids.index(sid)
                direction = data.get('direction')
                target_sid = player_sids[player_index - 1] if direction == 'left' else player_sids[(player_index + 1) % len(player_sids)]
                socketio.emit('receive_item', {'item': item_data}, room=target_sid)

            elif action_type == 'add_to_plate':
                player.plate = data.get('new_plate_contents', [])

            elif action_type == 'submit_order':
                self._handle_submit_order(player)

            # ส่ง state ล่าสุดให้ทุกคนหลัง action
            ui_state = self.get_augmented_state_for_ui()
            if ui_state:
                socketio.emit('update_game_state', ui_state, room=self.id)

    def _handle_submit_order(self, player):
        """ตรรกะการส่งอาหาร"""
        player_plate = sorted(player.plate)
        objective_name = player.objective.get('name')
        if not objective_name or objective_name not in RECIPES:
            return

        required_ingredients = RECIPES[objective_name]['ingredients']
        if player_plate == required_ingredients:
            # ทำอาหารสำเร็จ
            recipe_data = RECIPES[objective_name]
            self.game_state.score += recipe_data['points']
            self.game_state.time_left = min(self.game_state.time_left + recipe_data['time_bonus'], 999)
            
            player.plate = []
            self._assign_all_objectives() # สุ่มเป้าหมายใหม่ให้ทุกคน
            
            emit('action_success', {'message': f'ทำ {objective_name} สำเร็จ! (+{recipe_data["points"]} คะแนน)', 'sound': 'success'}, room=player.sid)

            # ตรวจสอบเงื่อนไขผ่านด่าน
            if self.game_state.score >= self.game_state.target_score:
                self._level_up()
        else:
            emit('action_fail', {'message': 'สูตรไม่ถูกต้อง! ลองอีกครั้ง', 'sound': 'error'}, room=player.sid)

    def _level_up(self):
        """ตรรกะการเลื่อนขึ้นด่านใหม่"""
        current_level = self.game_state.level
        self.game_state.total_score += self.game_state.score
        next_level = current_level + 1

        if next_level in LEVEL_DEFINITIONS:
            # ไปด่านต่อไป
            self.game_state.is_active = False # หยุดเกมชั่วคราว
            socketio.emit('level_complete', {'level': current_level, 'level_score': self.game_state.score, 'total_score': self.game_state.total_score}, room=self.id)
            socketio.sleep(5) # รอ 5 วินาที

            # รีเซ็ตสำหรับด่านใหม่
            player_sids = list(self.players.keys())
            random.shuffle(player_sids)
            self.game_state = GameState(player_sids, self.players, level=next_level)
            self.game_state.total_score = self.game_state.total_score # ใช้ total_score เดิม
            self._assign_abilities()
            self._assign_all_objectives()
            
            socketio.emit('clear_all_items', {}, room=self.id)
            socketio.emit('start_next_level', self.get_augmented_state_for_ui(), room=self.id)
        else:
            # ชนะเกม
            self.game_state.is_active = False
            socketio.emit('game_won', {'total_score': self.game_state.total_score}, room=self.id)
            self.game_state = None

    def use_ability(self, sid, item_name):
        with self.lock:
            player = self.players.get(sid)
            if not player or not self.game_state or not self.game_state.is_active: return

            if not player.ability or player.ability_processing:
                emit('action_fail', {'message': 'ไม่สามารถใช้ความสามารถได้ในขณะนี้', 'sound': 'error'}, room=sid)
                # [FIX] ส่งวัตถุดิบกลับคืนถ้าใช้ความสามารถไม่ได้
                socketio.emit('receive_item', {'item': {'type': 'ingredient', 'name': item_name}}, room=sid)
                return

            ability_config = ABILITIES_CONFIG.get(player.ability)
            if not ability_config or item_name not in ability_config['transformations']:
                emit('action_fail', {'message': 'วัตถุดิบนี้ใช้กับความสามารถของคุณไม่ได้', 'sound': 'error'}, room=sid)
                # [FIX] ส่งวัตถุดิบกลับคืนถ้าวัตถุดิบไม่ถูกต้อง
                socketio.emit('receive_item', {'item': {'type': 'ingredient', 'name': item_name}}, room=sid)
                return

            output_item = ability_config['transformations'][item_name]
            player.ability_processing = {'input': item_name, 'output': output_item, 'end_time': time.time() + 6}
            
            verb = ability_config['verb']
            emit('action_success', {'message': f'กำลัง{verb}{item_name}...', 'sound': 'click'}, room=sid)
            
            ui_state = self.get_augmented_state_for_ui()
            if ui_state:
                socketio.emit('update_game_state', ui_state, room=self.id)


# --- Global State & Master Loop ---
rooms = {} # {'room_id': GameRoom object}
rooms_lock = Lock()

def master_game_loop():
    """
    Master Loop ที่ทำงานเบื้องหลังเพียง Loop เดียว
    เพื่ออัปเดตสถานะของทุกห้องที่กำลังเล่นอยู่พร้อมกัน
    """
    while True:
        with rooms_lock:
            # สร้าง List ของห้องที่ต้องอัปเดตเพื่อไม่ให้ blockนาน
            active_rooms = [room for room in rooms.values() if room.game_state and room.game_state.is_active]

        if not active_rooms:
            socketio.sleep(1) # ถ้าไม่มีห้องเล่นอยู่ ก็พัก 1 วิ
            continue

        for room in active_rooms:
            room.update() # เรียกใช้ method update ของแต่ละห้อง
            # ส่งข้อมูลอัปเดตให้ผู้เล่นในห้องนั้นๆ ทุกวินาที
            ui_state = room.get_augmented_state_for_ui()
            if ui_state:
                socketio.emit('update_game_state', ui_state, room=room.id)
        
        # หลังจาก update ทุกห้องเสร็จแล้ว ค่อย sleep
        # เพื่อให้การ update เกิดขึ้นใกล้เคียงกันทุก 1 วินาที
        socketio.sleep(1)


# --- SocketIO Event Handlers ---
@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print(f"ผู้เล่นเชื่อมต่อเข้ามา: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"ผู้เล่นตัดการเชื่อมต่อ: {request.sid}")
    room_to_update = None
    with rooms_lock:
        for room in rooms.values():
            if request.sid in room.players:
                room_to_update = room
                break
    
    if not room_to_update: return

    player_name = room_to_update.players.get(request.sid, Player(None, 'Unknown')).name
    result = room_to_update.remove_player(request.sid)
    print(f"ผู้เล่น {player_name} ออกจากห้อง {room_to_update.id}")

    if result == 'delete_room':
        with rooms_lock:
            if room_to_update.id in rooms:
                del rooms[room_to_update.id]
            print(f"ห้อง {room_to_update.id} ว่างเปล่า, ทำการลบห้อง")
        return
    
    if result == 'game_over_disconnect':
        total_final_score = room_to_update.game_state.total_score + room_to_update.game_state.score if room_to_update.game_state else 0
        socketio.emit('game_over', {'total_score': total_final_score, 'message': 'ผู้เล่นไม่พอที่จะเล่นต่อ เกมจบลง'}, room=room_to_update.id)
        room_to_update.game_state = None

    # อัปเดตข้อมูล Lobby และเพื่อนบ้าน
    socketio.emit('update_lobby', room_to_update.get_lobby_info(), room=room_to_update.id)
    if room_to_update.host_sid == request.sid: # ถ้า host เดิมออก
        socketio.emit('new_host', {'host_sid': room_to_update.host_sid}, room=room_to_update.id)

    if room_to_update.game_state and room_to_update.game_state.is_active:
        player_sids = room_to_update.game_state.player_order_sids
        for i, sid in enumerate(player_sids):
            left_sid = player_sids[i - 1]
            right_sid = player_sids[(i + 1) % len(player_sids)]
            socketio.emit('update_neighbors', {
                'left_neighbor': room_to_update.players[left_sid].name,
                'right_neighbor': room_to_update.players[right_sid].name
            }, room=sid)
        ui_state = room_to_update.get_augmented_state_for_ui()
        if ui_state:
            socketio.emit('update_game_state', ui_state, room=room_to_update.id)

@socketio.on('create_room')
def handle_create_room(data):
    player_name = data.get('name', 'ผู้เล่นนิรนาม')
    while True:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        if room_id not in rooms:
            break
    
    room = GameRoom(room_id, request.sid, player_name)
    with rooms_lock:
        rooms[room_id] = room
    
    join_room(room_id)
    emit('room_created', {'room_id': room_id, 'is_host': True})
    socketio.emit('update_lobby', room.get_lobby_info(), room=room_id)

@socketio.on('join_room')
def handle_join_room(data):
    player_name = data.get('name', 'ผู้เล่นนิรนาม')
    room_id = data.get('room_id', '').upper()

    with rooms_lock:
        room = rooms.get(room_id)

    if not room:
        emit('error_message', {'message': 'ไม่พบห้องนี้!'})
        return
    if room.game_state and room.game_state.is_active:
        emit('error_message', {'message': 'เกมในห้องนี้เริ่มไปแล้ว!'})
        return
    
    if not room.add_player(request.sid, player_name):
        emit('error_message', {'message': 'ห้องเต็มแล้ว!'})
        return

    join_room(room_id)
    emit('join_success', {'room_id': room_id, 'is_host': request.sid == room.host_sid})
    socketio.emit('update_lobby', room.get_lobby_info(), room=room_id)

@socketio.on('start_game')
def handle_start_game(data):
    room_id = data.get('room_id')
    with rooms_lock:
        room = rooms.get(room_id)
    if not room or room.host_sid != request.sid:
        return
    room.start_game()

@socketio.on('player_action')
def handle_player_action(data):
    room_id = data.get('room_id')
    with rooms_lock:
        room = rooms.get(room_id)
    if room:
        room.handle_player_action(request.sid, data)

@socketio.on('use_ability')
def handle_use_ability(data):
    room_id = data.get('room_id')
    item_name = data.get('item_name')
    with rooms_lock:
        room = rooms.get(room_id)
    if room:
        room.use_ability(request.sid, item_name)

# --- Main Execution ---
if __name__ == '__main__':
    print("เซิร์ฟเวอร์กำลังจะเริ่มที่ http://127.0.0.1:5000")
    # เริ่ม Master Game Loop ใน Background
    socketio.start_background_task(target=master_game_loop)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
